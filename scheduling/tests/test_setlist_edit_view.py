"""The setlist's admin-only edit mode: the toggle, the buffer, and the atomic/optimistic-concurrency save (issue #178)."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import SemesterFactory, SongFactory
from scheduling.fields import format_song_length
from scheduling.models import Semester, Song
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY

PASSWORD = 'a-strong-test-password-123'


def admin_client(test_case):
    """Log a synthetic admin Person into `test_case`'s client and return that Person."""
    person = PersonFactory(password=PASSWORD, is_admin=True)
    test_case.client.login(username=person.email, password=PASSWORD)
    return person


def member_client(test_case):
    """Log a synthetic non-admin Person into `test_case`'s client and return that Person."""
    person = PersonFactory(password=PASSWORD)
    test_case.client.login(username=person.email, password=PASSWORD)
    return person


def select(test_case, semester):
    """Record `semester` as the client's session selection, mirroring `services.set_viewing_semester`."""
    session = test_case.client.session
    session[VIEWING_SEMESTER_SESSION_KEY] = semester.pk
    session.save()


def formset_data(songs, edits=None, stamp=None):
    """Build POST data for `SetlistEditFormSet`, in position order, with any per-song `edits` (by pk) applied.

    Every row starts from the Song's current values so a test only has to
    spell out the fields it means to change. `stamp` defaults to each
    Song's Semester's current `updated_at`; pass an explicit value to
    exercise the optimistic-concurrency check. `song_order` (issue #179)
    mirrors the grid's JS, which submits it in the buffer's visual order —
    here that's just the same position order the rows were built in.
    """
    edits = edits or {}
    data = {
        'song-TOTAL_FORMS': str(len(songs)),
        'song-INITIAL_FORMS': str(len(songs)),
        'song-MIN_NUM_FORMS': '0',
        'song-MAX_NUM_FORMS': '1000',
    }
    for index, song in enumerate(songs):
        row = {
            'title': song.title,
            'artist': song.artist,
            'length': format_song_length(song.length),
            'notes': song.notes,
        }
        row.update(edits.get(song.pk, {}))
        data[f'song-{index}-id'] = str(song.pk)
        for field, value in row.items():
            data[f'song-{index}-{field}'] = value
    data['song_order'] = [f'song-{index}' for index in range(len(songs))]
    if stamp is None and songs:
        stamp = songs[0].semester.updated_at.isoformat()
    data['semester_updated_at'] = stamp or ''
    return data


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistEditButtonTests(TestCase):
    def test_edit_button_renders_for_an_admin(self):
        """The read-mode /setlist/ page renders the 'Edit setlist' button for a logged-in admin."""
        semester = SemesterFactory()
        SongFactory(semester=semester)
        admin_client(self)

        response = self.client.get(reverse('scheduling:setlist'))

        self.assertContains(response, 'id="edit-setlist-button"')

    def test_edit_button_is_absent_for_a_member(self):
        """A member sees no edit affordance anywhere on the setlist page."""
        semester = SemesterFactory()
        SongFactory(semester=semester)
        member_client(self)

        response = self.client.get(reverse('scheduling:setlist'))

        self.assertNotContains(response, 'id="edit-setlist-button"')
        self.assertNotContains(response, 'setlist-edit-form')

    def test_edit_button_is_absent_with_no_semester_to_view(self):
        """With nothing to view, the button doesn't render even for an admin."""
        admin_client(self)

        response = self.client.get(reverse('scheduling:setlist'))

        self.assertNotContains(response, 'id="edit-setlist-button"')


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistEditAccessTests(TestCase):
    def test_get_redirects_anonymous_users_to_login(self):
        """An anonymous GET to /setlist/edit/ redirects to the login page."""
        url = reverse('scheduling:setlist-edit')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_post_redirects_anonymous_users_to_login(self):
        """An anonymous POST to /setlist/edit/ redirects to the login page and changes nothing."""
        song = SongFactory(title='Original Title', position=1)
        url = reverse('scheduling:setlist-edit')

        response = self.client.post(url, formset_data([song], edits={song.pk: {'title': 'New Title'}}))

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")
        self.assertEqual(Song.objects.get(pk=song.pk).title, 'Original Title')

    def test_get_is_forbidden_for_a_non_admin(self):
        """A logged-in non-admin's GET to /setlist/edit/ returns 403."""
        SongFactory()
        member_client(self)

        response = self.client.get(reverse('scheduling:setlist-edit'))

        self.assertEqual(response.status_code, 403)

    def test_post_is_forbidden_for_a_non_admin_and_changes_nothing(self):
        """A logged-in non-admin's POST to /setlist/edit/ returns 403 and changes nothing."""
        song = SongFactory(title='Original Title', position=1)
        member_client(self)

        response = self.client.post(
            reverse('scheduling:setlist-edit'), formset_data([song], edits={song.pk: {'title': 'New Title'}}),
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Song.objects.get(pk=song.pk).title, 'Original Title')


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistEditGetTests(TestCase):
    def test_full_page_get_renders_the_grid_in_position_order_and_the_banner(self):
        """A direct (non-htmx) GET renders the full page: the grid in position order, and the non-live banner."""
        draft = SemesterFactory(draft=True)
        second = SongFactory(semester=draft, position=2, title='Second Song')
        first = SongFactory(semester=draft, position=1, title='First Song')
        admin_client(self)
        select(self, draft)

        response = self.client.get(reverse('scheduling:setlist-edit'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="semester-banner"')
        first_index = response.content.decode().index(first.title)
        second_index = response.content.decode().index(second.title)
        self.assertLess(first_index, second_index)

    def test_htmx_get_returns_a_bare_fragment(self):
        """An `HX-Request` GET returns just the grid fragment, not the full page shell (no nav, no <html>)."""
        semester = SemesterFactory()
        SongFactory(semester=semester)
        admin_client(self)

        response = self.client.get(reverse('scheduling:setlist-edit'), HTTP_HX_REQUEST='true')

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<html')
        self.assertContains(response, 'id="setlist-edit-form"')

    def test_edit_grid_omits_derived_columns_and_sort_toggles(self):
        """Edit mode drops performers/rehearsals-remaining/recordings and the sort-toggle buttons."""
        semester = SemesterFactory()
        SongFactory(semester=semester)
        admin_client(self)

        response = self.client.get(reverse('scheduling:setlist-edit'))

        self.assertNotContains(response, 'Performers')
        self.assertNotContains(response, 'Rehearsals remaining')
        self.assertNotContains(response, 'Recordings')
        self.assertNotContains(response, 'id="sort-by-position"')
        self.assertNotContains(response, 'id="sort-by-title"')

    def test_length_renders_through_the_mm_ss_field(self):
        """A Song's length renders into the grid as M:SS, not Django's default duration format."""
        semester = SemesterFactory()
        SongFactory(semester=semester, length=timedelta(minutes=4, seconds=5))
        admin_client(self)

        response = self.client.get(reverse('scheduling:setlist-edit'))

        self.assertContains(response, 'value="4:05"')


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistEditSaveTests(TestCase):
    def test_valid_save_commits_every_row_atomically_and_redirects_to_the_setlist(self):
        """A valid Save Changes commits every edited field in one pass and returns to the read-mode setlist."""
        semester = SemesterFactory()
        first = SongFactory(semester=semester, position=1, title='Old First', artist='Old Artist A')
        second = SongFactory(semester=semester, position=2, title='Old Second', artist='Old Artist B')
        admin_client(self)
        data = formset_data(
            [first, second],
            edits={
                first.pk: {'title': 'New First', 'artist': 'New Artist A'},
                second.pk: {'title': 'New Second'},
            },
        )

        response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertRedirects(response, reverse('scheduling:setlist'))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.title, 'New First')
        self.assertEqual(first.artist, 'New Artist A')
        self.assertEqual(second.title, 'New Second')
        self.assertEqual(second.artist, 'Old Artist B')

    def test_valid_save_persists_a_note_entered_behind_the_per_row_expander(self):
        """A Song's notes edit lands through the same Save Changes as title/artist/length."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester, notes='')
        admin_client(self)
        data = formset_data([song], edits={song.pk: {'notes': 'Watch the bridge tempo.'}})

        self.client.post(reverse('scheduling:setlist-edit'), data)

        song.refresh_from_db()
        self.assertEqual(song.notes, 'Watch the bridge tempo.')

    def test_a_validation_failure_writes_nothing_and_preserves_every_submitted_value(self):
        """An invalid length on one row re-renders the whole grid with per-field errors and nothing saved."""
        semester = SemesterFactory()
        first = SongFactory(semester=semester, position=1, title='Old First')
        second = SongFactory(semester=semester, position=2, title='Old Second')
        admin_client(self)
        data = formset_data(
            [first, second],
            edits={
                first.pk: {'title': 'New First', 'length': 'not-a-length'},
                second.pk: {'title': 'New Second'},
            },
        )

        response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertEqual(response.status_code, 200)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.title, 'Old First')
        self.assertEqual(second.title, 'Old Second')
        self.assertContains(response, 'value="New First"')
        self.assertContains(response, 'value="New Second"')
        self.assertContains(response, 'Enter a length as M:SS')

    def test_a_stale_stamp_is_rejected_wholesale_and_writes_nothing(self):
        """A save carrying an older Semester stamp than the current one is rejected, writing nothing."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester, title='Old Title')
        stale_stamp = semester.updated_at.isoformat()
        semester.updated_at = timezone.now() + timedelta(seconds=1)
        semester.save(update_fields=['updated_at'])
        admin_client(self)
        data = formset_data([song], edits={song.pk: {'title': 'New Title'}}, stamp=stale_stamp)

        response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertEqual(response.status_code, 200)
        song.refresh_from_db()
        self.assertEqual(song.title, 'Old Title')
        self.assertContains(response, 'reload and reapply')

    def test_a_successful_save_advances_the_stamp_so_a_subsequent_stale_save_is_rejected(self):
        """After one Save Changes succeeds, a second save still carrying the original stamp is rejected."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester, title='Original')
        original_stamp = semester.updated_at.isoformat()
        admin_client(self)

        first_response = self.client.post(
            reverse('scheduling:setlist-edit'),
            formset_data([song], edits={song.pk: {'title': 'First Edit'}}, stamp=original_stamp),
        )
        self.assertRedirects(first_response, reverse('scheduling:setlist'))
        song.refresh_from_db()
        self.assertEqual(song.title, 'First Edit')

        second_response = self.client.post(
            reverse('scheduling:setlist-edit'),
            formset_data([song], edits={song.pk: {'title': 'Second Edit'}}, stamp=original_stamp),
        )

        self.assertEqual(second_response.status_code, 200)
        self.assertContains(second_response, 'reload and reapply')
        song.refresh_from_db()
        self.assertEqual(song.title, 'First Edit')

    def test_the_non_live_banner_is_present_on_a_stale_stamp_rejection(self):
        """The non-live-Semester banner still renders when a draft save is rejected for a stale stamp."""
        draft = SemesterFactory(draft=True)
        song = SongFactory(semester=draft, title='Old Title')
        stale_stamp = draft.updated_at.isoformat()
        draft.updated_at = timezone.now() + timedelta(seconds=1)
        draft.save(update_fields=['updated_at'])
        admin_client(self)
        select(self, draft)
        data = formset_data([song], edits={song.pk: {'title': 'New Title'}}, stamp=stale_stamp)

        response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="semester-banner"')

    def test_saving_into_a_draft_semester_leaves_the_live_semester_untouched(self):
        """An admin viewing a draft edits and saves into that draft; the Live Semester's Songs are unaffected."""
        live = SemesterFactory()
        live_song = SongFactory(semester=live, title='Live Title')
        draft = SemesterFactory(draft=True)
        draft_song = SongFactory(semester=draft, title='Draft Title')
        admin_client(self)
        select(self, draft)
        data = formset_data([draft_song], edits={draft_song.pk: {'title': 'Edited Draft Title'}})

        response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertRedirects(response, reverse('scheduling:setlist'))
        draft_song.refresh_from_db()
        live_song.refresh_from_db()
        self.assertEqual(draft_song.title, 'Edited Draft Title')
        self.assertEqual(live_song.title, 'Live Title')
        self.assertEqual(Semester.objects.get(pk=live.pk).updated_at, live.updated_at)

    def test_a_song_order_missing_a_surviving_prefix_is_rejected_and_writes_nothing(self):
        """A `song_order` that drops an existing row's prefix is rejected wholesale, not silently applied."""
        semester = SemesterFactory()
        first = SongFactory(semester=semester, position=1, title='First')
        second = SongFactory(semester=semester, position=2, title='Second')
        admin_client(self)
        data = formset_data([first, second], edits={second.pk: {'title': 'New Second'}})
        data['song_order'] = ['song-0']

        response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertEqual(response.status_code, 200)
        second.refresh_from_db()
        self.assertEqual(second.title, 'Second')
        self.assertContains(response, 'reload and reapply')

    def test_a_song_order_with_a_duplicated_prefix_is_rejected_and_writes_nothing(self):
        """A `song_order` naming one prefix twice (and another not at all) is rejected wholesale."""
        semester = SemesterFactory()
        first = SongFactory(semester=semester, position=1, title='First')
        second = SongFactory(semester=semester, position=2, title='Second')
        admin_client(self)
        data = formset_data([first, second])
        data['song_order'] = ['song-0', 'song-0']

        response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertEqual(response.status_code, 200)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.position, 1)
        self.assertEqual(second.position, 2)
        self.assertContains(response, 'reload and reapply')

    def test_a_song_order_naming_an_unknown_prefix_is_rejected_and_writes_nothing(self):
        """A `song_order` token that names no formset prefix at all is rejected wholesale."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester, position=1, title='Original')
        admin_client(self)
        data = formset_data([song])
        data['song_order'] = ['song-99']

        response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertEqual(response.status_code, 200)
        song.refresh_from_db()
        self.assertEqual(song.title, 'Original')
        self.assertContains(response, 'reload and reapply')

    def test_cancel_link_returns_to_the_read_mode_setlist(self):
        """The Cancel affordance is a plain link back to the read-mode /setlist/ page."""
        semester = SemesterFactory()
        SongFactory(semester=semester)
        admin_client(self)

        response = self.client.get(reverse('scheduling:setlist-edit'))

        self.assertContains(response, f'href="{reverse("scheduling:setlist")}"')


@override_settings(SECURE_SSL_REDIRECT=False)
class EmptySetlistTests(TestCase):
    """The empty setlist as a way in, not a dead end (issue #180)."""

    def test_edit_button_renders_for_an_admin_with_zero_songs(self):
        """The 'Edit setlist' button renders for an admin even when the setlist has no Songs."""
        SemesterFactory()
        admin_client(self)

        response = self.client.get(reverse('scheduling:setlist'))

        self.assertContains(response, 'id="edit-setlist-button"')

    def test_an_admins_empty_setlist_shows_a_call_to_action_wired_to_edit_mode(self):
        """An admin's empty setlist offers a call to action that opens the same edit mode as the button."""
        SemesterFactory()
        admin_client(self)

        response = self.client.get(reverse('scheduling:setlist'))

        self.assertContains(response, 'id="add-first-song-button"')
        self.assertContains(response, f'hx-get="{reverse("scheduling:setlist-edit")}"')

    def test_a_members_empty_setlist_is_the_unchanged_flat_sentence(self):
        """A member's empty setlist stays the plain sentence, with no button and no call to action."""
        SemesterFactory()
        member_client(self)

        response = self.client.get(reverse('scheduling:setlist'))

        self.assertContains(response, 'No songs on the setlist yet.')
        self.assertNotContains(response, 'id="edit-setlist-button"')
        self.assertNotContains(response, 'id="add-first-song-button"')

    def test_edit_mode_on_an_empty_setlist_opens_with_one_blank_row(self):
        """Edit mode on an empty setlist renders exactly one blank row, not zero, so typing can start immediately."""
        SemesterFactory()
        admin_client(self)

        response = self.client.get(reverse('scheduling:setlist-edit'))

        self.assertContains(response, 'name="song-TOTAL_FORMS" value="1"')
        rows_html = response.content.decode().split('id="setlist-empty-form-template"')[0]
        self.assertEqual(rows_html.count('class="setlist-edit-row-group"'), 1)

    def test_saving_from_an_empty_setlist_creates_the_typed_song_at_position_one(self):
        """Saving the one blank row typed into an empty setlist creates that Song at position 1."""
        semester = SemesterFactory()
        admin_client(self)
        data = {
            'song-TOTAL_FORMS': '1',
            'song-INITIAL_FORMS': '0',
            'song-MIN_NUM_FORMS': '0',
            'song-MAX_NUM_FORMS': '1000',
            'song-0-id': '',
            'song-0-title': 'Brand New Song',
            'song-0-artist': 'Brand New Artist',
            'song-0-length': '3:45',
            'song-0-notes': '',
            'song_order': ['song-0'],
            'semester_updated_at': semester.updated_at.isoformat(),
        }

        response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertRedirects(response, reverse('scheduling:setlist'))
        [song] = Song.objects.filter(semester=semester)
        self.assertEqual(song.title, 'Brand New Song')
        self.assertEqual(song.position, 1)
