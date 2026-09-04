"""`/schedule/edit/`: the admin-only "Edit rehearsals" mode — the toggle, the buffer, and the past-date lock (issue #219)."""

from datetime import time, timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.models import Recording, Rehearsal, RehearsalSong
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY
from scheduling.tests.preview_helpers import assert_preview_writes_nothing

PASSWORD = 'a-strong-test-password-123'
TOMORROW = timezone.localdate() + timedelta(days=1)
NEXT_WEEK = timezone.localdate() + timedelta(days=7)
YESTERDAY = timezone.localdate() - timedelta(days=1)


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


def formset_data(
    rehearsals, edits=None, extra_rows=(), semester_id=None, stamp=None, running_order=(),
    deleted_rehearsal_ids=(),
):
    """Build POST data for `RehearsalEditFormSet` (plus `RunningOrderFormSet`), one row per existing Rehearsal plus any `extra_rows`.

    Every existing row starts from the Rehearsal's current values so a
    test only has to spell out the fields it means to change, keyed by
    pk in `edits`. `extra_rows` are plain dicts appended past
    `INITIAL_FORMS`, for a brand-new row. `semester_id`/`stamp` default to
    the first Rehearsal's Semester; both are required even with zero
    Rehearsals, so a caller building a from-empty Buffer must pass them.
    `running_order` (issue #220) is a list of dicts for `RunningOrderFormSet`'s
    rows (each needs `rehearsal_row_key`, `song_id`, `slot_count`, and
    optionally `rehearsal_song_id`/`DELETE`) — empty by default, so a test
    that doesn't touch the sub-grid still submits a valid (empty) buffer for it.
    `deleted_rehearsal_ids` (issue #221) checks that row's own `DELETE` field.
    """
    edits = edits or {}
    data = {
        'rehearsal-TOTAL_FORMS': str(len(rehearsals) + len(extra_rows)),
        'rehearsal-INITIAL_FORMS': str(len(rehearsals)),
        'rehearsal-MIN_NUM_FORMS': '0',
        'rehearsal-MAX_NUM_FORMS': '1000',
        'songs-TOTAL_FORMS': str(len(running_order)),
        'songs-INITIAL_FORMS': '0',
        'songs-MIN_NUM_FORMS': '0',
        'songs-MAX_NUM_FORMS': '1000',
    }
    song_order_tokens = []
    for index, row in enumerate(running_order):
        prefix = f'songs-{index}'
        song_order_tokens.append(prefix)
        data[f'{prefix}-rehearsal_row_key'] = row['rehearsal_row_key']
        data[f'{prefix}-song_id'] = str(row['song_id'])
        data[f'{prefix}-slot_count'] = str(row['slot_count'])
        if row.get('rehearsal_song_id') is not None:
            data[f'{prefix}-rehearsal_song_id'] = str(row['rehearsal_song_id'])
        if row.get('DELETE'):
            data[f'{prefix}-DELETE'] = 'on'
    if song_order_tokens:
        data['song_slot_order'] = song_order_tokens
    for index, rehearsal in enumerate(rehearsals):
        row = {
            'date': rehearsal.date.isoformat(),
            'start_time': rehearsal.start_time.isoformat(),
            'end_time': rehearsal.end_time.isoformat() if rehearsal.end_time else '',
            'is_full_setlist': rehearsal.is_full_setlist,
            'setup_grace_minutes': rehearsal.setup_grace_minutes,
            'teardown_grace_minutes': rehearsal.teardown_grace_minutes,
            'arrival_buffer_minutes': rehearsal.arrival_buffer_minutes,
            'departure_buffer_minutes': rehearsal.departure_buffer_minutes,
        }
        row.update(edits.get(rehearsal.pk, {}))
        data[f'rehearsal-{index}-id'] = str(rehearsal.pk)
        for field, value in row.items():
            if value is None:
                continue
            data[f'rehearsal-{index}-{field}'] = value
        if rehearsal.pk in deleted_rehearsal_ids:
            data[f'rehearsal-{index}-DELETE'] = 'on'
    for offset, extra_row in enumerate(extra_rows):
        index = len(rehearsals) + offset
        for field, value in extra_row.items():
            if value is None:
                continue
            data[f'rehearsal-{index}-{field}'] = value
    if semester_id is None and rehearsals:
        semester_id = rehearsals[0].semester.pk
    if stamp is None and rehearsals:
        stamp = rehearsals[0].semester.updated_at.isoformat()
    data['schedule_semester_id'] = str(semester_id) if semester_id is not None else ''
    data['schedule_semester_updated_at'] = stamp or ''
    return data


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleEditButtonTests(TestCase):
    def test_edit_button_renders_for_an_admin(self):
        """The read-mode /schedule/?view=all page renders the 'Edit rehearsals' button for a logged-in admin."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=TOMORROW)
        admin_client(self)

        response = self.client.get(f"{reverse('scheduling:schedule')}?view=all")

        self.assertContains(response, 'id="edit-rehearsals-button"')

    def test_edit_button_is_absent_for_a_member(self):
        """A member sees no edit affordance on the All-Rehearsals list."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=TOMORROW)
        member_client(self)

        response = self.client.get(f"{reverse('scheduling:schedule')}?view=all")

        self.assertNotContains(response, 'id="edit-rehearsals-button"')
        self.assertNotContains(response, 'schedule-edit-form')

    def test_edit_button_renders_on_a_semester_with_zero_rehearsals(self):
        """A brand-new Semester with no Rehearsals still shows the button, so it isn't a dead end."""
        SemesterFactory()
        admin_client(self)

        response = self.client.get(f"{reverse('scheduling:schedule')}?view=all")

        self.assertContains(response, 'id="edit-rehearsals-button"')


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleEditAccessTests(TestCase):
    def test_get_redirects_anonymous_users_to_login(self):
        """An anonymous GET to /schedule/edit/ redirects to the login page."""
        url = reverse('scheduling:schedule-edit')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_post_redirects_anonymous_users_to_login(self):
        """An anonymous POST to /schedule/edit/ redirects to login and changes nothing."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        url = reverse('scheduling:schedule-edit')

        response = self.client.post(url, formset_data([rehearsal], edits={rehearsal.pk: {'start_time': '19:00'}}))

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.start_time, time(18, 0))

    def test_get_is_forbidden_for_a_non_admin(self):
        """A logged-in non-admin's GET to /schedule/edit/ returns 403."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=TOMORROW)
        member_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit'))

        self.assertEqual(response.status_code, 403)

    def test_post_is_forbidden_for_a_non_admin_and_changes_nothing(self):
        """A logged-in non-admin's POST to /schedule/edit/ returns 403 and changes nothing."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        member_client(self)

        response = self.client.post(
            reverse('scheduling:schedule-edit'), formset_data([rehearsal], edits={rehearsal.pk: {'start_time': '19:00'}}),
        )

        self.assertEqual(response.status_code, 403)
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.start_time, time(18, 0))


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleEditGetTests(TestCase):
    def test_full_page_get_renders_the_grid_and_the_banner(self):
        """A direct (non-htmx) GET renders the full page, including the non-live Semester banner."""
        draft = SemesterFactory(draft=True)
        RehearsalFactory(semester=draft, date=TOMORROW)
        admin_client(self)
        select(self, draft)

        response = self.client.get(reverse('scheduling:schedule-edit'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="semester-banner"')
        self.assertContains(response, 'id="schedule-edit-form"')

    def test_htmx_get_returns_a_bare_fragment(self):
        """An `HX-Request` GET returns just the grid fragment, not the full page shell."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=TOMORROW)
        admin_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit'), HTTP_HX_REQUEST='true')

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<html')
        self.assertContains(response, 'id="schedule-edit-form"')

    def test_a_past_rehearsal_renders_with_no_inputs(self):
        """A past-dated Rehearsal renders in the collapsed past section with no editable inputs anywhere in the grid."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=YESTERDAY, start_time=time(18, 0))
        RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(19, 0))
        admin_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit'))
        content = response.content.decode()

        self.assertIn('id="schedule-edit-past"', content)
        # One editable row (the future Rehearsal) plus the inert "+ Add rehearsal" <template> row
        # (issue #221, never live DOM) — the past Rehearsal contributes neither.
        self.assertEqual(content.count('class="schedule-edit-row"'), 2)

    def test_a_today_dated_rehearsal_is_still_editable(self):
        """A Rehearsal dated exactly today renders as an editable row, not a locked one."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=timezone.localdate(), start_time=time(18, 0))
        admin_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit'))

        self.assertContains(response, 'name="rehearsal-0-date"')

    def test_zero_rehearsals_still_renders_one_blank_row(self):
        """A Semester with no Rehearsals renders one blank row rather than an empty grid."""
        SemesterFactory()
        admin_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit'))

        self.assertContains(response, 'name="rehearsal-0-date"')

    def test_a_blank_new_rows_override_renders_as_placeholder_not_a_value(self):
        """A brand-new row's override field renders the Semester default as placeholder text, never a filled-in value.

        An *existing* Rehearsal is never a fair test of this: `Rehearsal.save()`
        already concretizes a blank override into a real value at creation
        time (an existing, documented invariant this ticket doesn't change —
        see `apply_rehearsal_edits()`'s docstring), so only a never-yet-saved
        row can still be blank when the grid renders it.
        """
        SemesterFactory(default_setup_grace_minutes=12)
        admin_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit'))
        content = response.content.decode()

        self.assertIn('placeholder="12"', content)
        row_start = content.index('name="rehearsal-0-setup_grace_minutes"')
        row_end = content.index('>', row_start)
        self.assertNotIn('value="12"', content[row_start:row_end])


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleEditSaveTests(TestCase):
    def test_valid_save_commits_and_redirects_to_the_all_rehearsals_list(self):
        """A valid Save Changes commits the edited field and returns to the All-Rehearsals list."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        admin_client(self)
        data = formset_data([rehearsal], edits={rehearsal.pk: {'start_time': '17:00'}})

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertRedirects(response, f"{reverse('scheduling:schedule')}?view=all")
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.start_time, time(17, 0))

    @mock.patch('scheduling.services._recording_storage')
    def test_a_deleted_row_is_hard_deleted_on_save(self, recording_storage):
        """Checking a row's Remove control and saving hard-deletes that Rehearsal (issue #221)."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        admin_client(self)
        data = formset_data([rehearsal], deleted_rehearsal_ids=[rehearsal.pk])

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertRedirects(response, f"{reverse('scheduling:schedule')}?view=all")
        self.assertFalse(Rehearsal.objects.filter(pk=rehearsal.pk).exists())

    def test_a_new_row_is_created_on_save(self):
        """A blank extra row filled in and saved creates a new Rehearsal."""
        semester = SemesterFactory()
        admin_client(self)
        data = formset_data([], semester_id=semester.pk, stamp=semester.updated_at.isoformat(), extra_rows=[{
            'date': NEXT_WEEK.isoformat(), 'start_time': '18:00', 'end_time': '20:00', 'is_full_setlist': False,
        }])

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertRedirects(response, f"{reverse('scheduling:schedule')}?view=all")
        self.assertTrue(Rehearsal.objects.filter(semester=semester, date=NEXT_WEEK).exists())

    def test_two_pending_rows_sharing_a_date_block_the_save(self):
        """Two rows dated the same day block the save entirely; the database is unchanged afterwards."""
        semester = SemesterFactory()
        first = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        admin_client(self)
        data = formset_data([first], extra_rows=[{
            'date': first.date.isoformat(), 'start_time': '20:00', 'end_time': '21:00', 'is_full_setlist': False,
        }])

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Rehearsal.objects.filter(semester=semester).count(), 1)
        first.refresh_from_db()
        self.assertEqual(first.start_time, time(18, 0))

    def test_an_end_time_before_start_time_blocks_the_save(self):
        """An end time before the start time blocks the save; the database is unchanged afterwards."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        admin_client(self)
        data = formset_data([rehearsal], edits={rehearsal.pk: {'start_time': '20:00', 'end_time': '19:00'}})

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.start_time, time(18, 0))

    def test_an_invalid_override_field_reopens_its_advanced_timing_details(self):
        """A row with a bad override value re-renders with that row's <details> open, so the error is actually visible."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        admin_client(self)
        data = formset_data([rehearsal], edits={rehearsal.pk: {'setup_grace_minutes': '-5'}})

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        details_start = content.index('schedule-edit-overrides-expander')
        details_tag_end = content.index('>', details_start)
        self.assertIn('open', content[details_start:details_tag_end])

    def test_a_new_row_dated_in_the_past_is_a_blocking_validation_error_naming_the_django_admin(self):
        """A new row dated before today is a blocking Validation Error, naming the Django admin, and writes nothing."""
        semester = SemesterFactory()
        admin_client(self)
        data = formset_data([], semester_id=semester.pk, stamp=semester.updated_at.isoformat(), extra_rows=[{
            'date': YESTERDAY.isoformat(), 'start_time': '18:00', 'end_time': '20:00', 'is_full_setlist': False,
        }])

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Django admin')
        self.assertFalse(Rehearsal.objects.filter(semester=semester, date=YESTERDAY).exists())

    def test_backdating_a_future_row_to_the_past_is_blocked_the_same_way(self):
        """Editing an existing future row's date to a past one is blocked exactly like a new past row."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        admin_client(self)
        data = formset_data([rehearsal], edits={rehearsal.pk: {'date': YESTERDAY.isoformat()}})

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Django admin')
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.date, TOMORROW)

    def test_a_blocked_save_preserves_every_submitted_value(self):
        """A validation failure re-renders the grid with the submitted (unsaved) values still present."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        admin_client(self)
        data = formset_data([rehearsal], edits={rehearsal.pk: {'start_time': '20:00', 'end_time': '19:00'}})

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertContains(response, 'value="20:00"')

    def test_a_stale_stamp_is_rejected_wholesale_and_writes_nothing(self):
        """A save carrying an older Semester stamp than the current one is rejected, writing nothing."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        stale_stamp = semester.updated_at.isoformat()
        semester.updated_at = timezone.now() + timedelta(seconds=1)
        semester.save(update_fields=['updated_at'])
        admin_client(self)
        data = formset_data([rehearsal], edits={rehearsal.pk: {'start_time': '19:00'}}, stamp=stale_stamp)

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.start_time, time(18, 0))
        self.assertContains(response, 'reload and reapply')
        self.assertContains(response, f'value="{stale_stamp}"')

        second_response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(second_response.status_code, 200)
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.start_time, time(18, 0))
        self.assertContains(second_response, 'reload and reapply')

    def test_a_wrong_semester_id_is_rejected_and_writes_nothing(self):
        """A hidden Semester id that no longer matches the session's viewed Semester is rejected wholesale."""
        semester = SemesterFactory()
        other = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        admin_client(self)
        select(self, semester)
        data = formset_data([rehearsal], edits={rehearsal.pk: {'start_time': '19:00'}}, semester_id=other.pk)

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.start_time, time(18, 0))

    def test_a_past_dated_rehearsal_is_excluded_from_the_editable_queryset_so_it_cannot_be_targeted_by_pk(self):
        """A row naming a past-dated Rehearsal's pk can't edit it: the queryset excludes it, so Django binds a new instance instead.

        `apply_rehearsal_edits()`'s own hard failure for a genuinely
        forged/raced past row is covered at the service layer
        (`test_apply_rehearsal_edits.py`) — Django's own ModelFormSet
        instance matching, scoped to this view's future-only queryset,
        already prevents an out-of-queryset pk from reaching an edit of
        the real row through this surface.
        """
        semester = SemesterFactory()
        past_rehearsal = RehearsalFactory(semester=semester, date=YESTERDAY, start_time=time(18, 0))
        admin_client(self)
        data = {
            'rehearsal-TOTAL_FORMS': '1',
            'rehearsal-INITIAL_FORMS': '1',
            'rehearsal-MIN_NUM_FORMS': '0',
            'rehearsal-MAX_NUM_FORMS': '1000',
            'rehearsal-0-id': str(past_rehearsal.pk),
            'rehearsal-0-date': NEXT_WEEK.isoformat(),
            'rehearsal-0-start_time': '18:00',
            'rehearsal-0-end_time': '20:00',
            'schedule_semester_id': str(semester.pk),
            'schedule_semester_updated_at': semester.updated_at.isoformat(),
        }

        self.client.post(reverse('scheduling:schedule-edit'), data)

        past_rehearsal.refresh_from_db()
        self.assertEqual(past_rehearsal.date, YESTERDAY)
        self.assertEqual(past_rehearsal.start_time, time(18, 0))


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleEditRunningOrderGetTests(TestCase):
    def test_renders_a_collapsed_details_element_with_the_songs_inputs_present(self):
        """The Running Order sub-grid renders inside a collapsed <details>, but its inputs are still in the DOM."""
        semester = SemesterFactory(default_song_slot_count=5)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        song = SongFactory(semester=semester, position=1)
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1, slot_count=1)
        admin_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit'))
        content = response.content.decode()

        self.assertIn('class="running-order-expander"', content)
        self.assertNotIn('class="running-order-expander" open', content)
        self.assertIn(f'name="songs-0-song_id" value="{song.pk}"', content)
        self.assertIn(f'data-rehearsal-song-id="{rehearsal_song.pk}"', content)

    def test_the_song_title_is_read_only_text_not_an_editable_input(self):
        """A scheduled Song's title renders as plain text in the sub-grid, never a free-text input."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        song = SongFactory(semester=semester, position=1, title='Song A')
        RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        admin_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit'))

        self.assertContains(response, '<span class="running-order-song-title">Song A</span>')
        self.assertNotContains(response, 'name="songs-0-title"')

    def test_add_song_options_exclude_songs_already_scheduled_in_that_rehearsal(self):
        """The '+ Add song' <select> lists a not-yet-scheduled Song as a normal option and a scheduled one hidden."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        scheduled = SongFactory(semester=semester, position=1, title='Song A')
        unscheduled = SongFactory(semester=semester, position=2, title='Song B')
        RehearsalSongFactory(rehearsal=rehearsal, song=scheduled, order=1)
        admin_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit'))
        content = response.content.decode()

        self.assertIn(f'value="{unscheduled.pk}" data-title="Song B">Song B</option>', content)
        self.assertIn(f'value="{scheduled.pk}" data-title="Song A">Song A</option>', content)

    def test_a_past_rehearsal_renders_no_running_order_sub_grid_at_all(self):
        """A past-dated Rehearsal contributes no Running Order sub-grid — only the future Rehearsal's own sub-grid renders."""
        semester = SemesterFactory()
        past = RehearsalFactory(semester=semester, date=YESTERDAY, start_time=time(18, 0))
        RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(19, 0))
        song = SongFactory(semester=semester, position=1)
        past_rehearsal_song = RehearsalSongFactory(rehearsal=past, song=song, order=1)
        admin_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit'))
        content = response.content.decode()

        # One live sub-grid (the future Rehearsal) plus the inert "+ Add rehearsal" <template>'s own
        # (issue #221, never live DOM) — the past Rehearsal contributes neither.
        self.assertEqual(content.count('class="running-order-sub-grid"'), 2)
        self.assertNotIn(f'data-rehearsal-song-id="{past_rehearsal_song.pk}"', content)


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleEditRunningOrderSaveTests(TestCase):
    def test_adding_a_new_song_creates_a_rehearsal_song(self):
        """A '+ Add song' row submitted with a real Song id creates a RehearsalSong on Save."""
        semester = SemesterFactory(default_song_slot_count=5)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        song = SongFactory(semester=semester, position=1)
        admin_client(self)
        data = formset_data([rehearsal], running_order=[
            {'rehearsal_row_key': 'rehearsal-0', 'song_id': song.pk, 'slot_count': 1},
        ])

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertRedirects(response, f"{reverse('scheduling:schedule')}?view=all")
        self.assertTrue(RehearsalSong.objects.filter(rehearsal=rehearsal, song=song).exists())

    def test_reordering_two_existing_rows_renumbers_them(self):
        """Submitting two existing rows in swapped order renumbers them to match on Save."""
        semester = SemesterFactory(default_song_slot_count=5)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        song_a = SongFactory(semester=semester, position=1)
        song_b = SongFactory(semester=semester, position=2)
        first = RehearsalSongFactory(rehearsal=rehearsal, song=song_a, order=1)
        second = RehearsalSongFactory(rehearsal=rehearsal, song=song_b, order=2)
        admin_client(self)
        data = formset_data([rehearsal], running_order=[
            {'rehearsal_row_key': 'rehearsal-0', 'song_id': song_b.pk, 'slot_count': 1, 'rehearsal_song_id': second.pk},
            {'rehearsal_row_key': 'rehearsal-0', 'song_id': song_a.pk, 'slot_count': 1, 'rehearsal_song_id': first.pk},
        ])

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertRedirects(response, f"{reverse('scheduling:schedule')}?view=all")
        second.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(second.order, 1)
        self.assertEqual(first.order, 2)

    def test_removing_a_row_by_omitting_it_deletes_it_on_save(self):
        """A row left off the submitted running_order (never marked DELETE, just absent) is removed on Save."""
        semester = SemesterFactory(default_song_slot_count=5)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        song = SongFactory(semester=semester, position=1)
        doomed = RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        admin_client(self)
        data = formset_data([rehearsal], running_order=[])

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertRedirects(response, f"{reverse('scheduling:schedule')}?view=all")
        self.assertFalse(RehearsalSong.objects.filter(pk=doomed.pk).exists())

    def test_slot_counts_exceeding_the_semesters_default_block_the_save(self):
        """A Running Order whose slot counts exceed the Semester's default_song_slot_count blocks the save; the database is unchanged."""
        semester = SemesterFactory(default_song_slot_count=2)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        song_a = SongFactory(semester=semester, position=1)
        song_b = SongFactory(semester=semester, position=2)
        admin_client(self)
        data = formset_data([rehearsal], running_order=[
            {'rehearsal_row_key': 'rehearsal-0', 'song_id': song_a.pk, 'slot_count': 2},
            {'rehearsal_row_key': 'rehearsal-0', 'song_id': song_b.pk, 'slot_count': 2},
        ])

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(RehearsalSong.objects.filter(rehearsal=rehearsal).count(), 0)

    def test_a_running_order_on_a_row_flipped_to_dress_blocks_the_save(self):
        """Flipping a row to Dress Rehearsal while its Running Order still names songs blocks the save; the database is unchanged."""
        semester = SemesterFactory(default_song_slot_count=5)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        song = SongFactory(semester=semester, position=1)
        admin_client(self)
        data = formset_data(
            [rehearsal], edits={rehearsal.pk: {'is_full_setlist': True}},
            running_order=[{'rehearsal_row_key': 'rehearsal-0', 'song_id': song.pk, 'slot_count': 1}],
        )

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(RehearsalSong.objects.filter(rehearsal=rehearsal).count(), 0)

    def test_a_malformed_song_slot_order_blocks_the_save(self):
        """A song_slot_order token set that doesn't match the songs formset's own prefixes is rejected wholesale."""
        semester = SemesterFactory(default_song_slot_count=5)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        song = SongFactory(semester=semester, position=1)
        admin_client(self)
        data = formset_data([rehearsal], running_order=[
            {'rehearsal_row_key': 'rehearsal-0', 'song_id': song.pk, 'slot_count': 1},
        ])
        data['song_slot_order'] = ['songs-nonexistent']

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(RehearsalSong.objects.filter(rehearsal=rehearsal).count(), 0)

    def test_removing_a_recorded_row_by_hand_is_allowed_with_confirmation(self):
        """A Running Order row carrying Recordings can still be removed by hand -- the asymmetry with the bulk generator."""
        semester = SemesterFactory(default_song_slot_count=5)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        song = SongFactory(semester=semester, position=1)
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        RecordingFactory(rehearsal_song=rehearsal_song)
        admin_client(self)
        data = formset_data([rehearsal], running_order=[])

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertRedirects(response, f"{reverse('scheduling:schedule')}?view=all")
        self.assertFalse(RehearsalSong.objects.filter(pk=rehearsal_song.pk).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleEditDestroyConfirmViewTests(TestCase):
    """The one destructive-save confirmation, enumerating doomed Recordings across all three causes (issue #221)."""

    @mock.patch('scheduling.services._recording_storage')
    def test_names_a_doomed_rows_recording_and_uploader_count_when_a_song_is_removed(self, recording_storage):
        """Removing a recorded Running Order row renders its Rehearsal's doomed-Recording group."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        song = SongFactory(semester=semester, position=1, title='Song A')
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        RecordingFactory(rehearsal_song=rehearsal_song)
        admin_client(self)
        data = formset_data([rehearsal], running_order=[
            {'rehearsal_row_key': 'rehearsal-0', 'song_id': song.pk, 'slot_count': 1,
             'rehearsal_song_id': rehearsal_song.pk, 'DELETE': True},
        ])

        response = self.client.post(reverse('scheduling:schedule-edit-confirm-destroy'), data)

        self.assertContains(response, '1 recording')
        self.assertContains(response, str(rehearsal.date))

    @mock.patch('scheduling.services._recording_storage')
    def test_names_a_doomed_group_when_a_rehearsal_is_deleted(self, recording_storage):
        """Deleting a whole Rehearsal with Recordings renders its doomed-Recording group too."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        song = SongFactory(semester=semester, position=1)
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        RecordingFactory(rehearsal_song=rehearsal_song)
        admin_client(self)
        data = formset_data([rehearsal], deleted_rehearsal_ids=[rehearsal.pk])

        response = self.client.post(reverse('scheduling:schedule-edit-confirm-destroy'), data)

        self.assertContains(response, str(rehearsal.date))

    def test_no_content_when_nothing_would_be_destroyed(self):
        """A buffer that destroys no Recording renders 204, so the dialog never fires needlessly."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        admin_client(self)
        data = formset_data([rehearsal])

        response = self.client.post(reverse('scheduling:schedule-edit-confirm-destroy'), data)

        self.assertEqual(response.status_code, 204)

    def test_is_forbidden_for_a_non_admin(self):
        """A logged-in non-admin's POST to the confirm-destroy endpoint returns 403."""
        member_client(self)

        response = self.client.post(reverse('scheduling:schedule-edit-confirm-destroy'), {})

        self.assertEqual(response.status_code, 403)

    def test_redirects_anonymous_users_to_login(self):
        """An anonymous POST to the confirm-destroy endpoint redirects to login."""
        url = reverse('scheduling:schedule-edit-confirm-destroy')

        response = self.client.post(url, {})

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleEditPreviewViewTests(TestCase):
    def test_preview_writes_nothing_for_a_buffer_mixing_creations_reorders_and_removals(self):
        """Preview runs the real save and rolls it back for a buffer that adds, reorders and removes Running Order rows together."""
        semester = SemesterFactory(default_song_slot_count=5)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        song_a = SongFactory(semester=semester, position=1)
        song_b = SongFactory(semester=semester, position=2)
        song_c = SongFactory(semester=semester, position=3)
        kept = RehearsalSongFactory(rehearsal=rehearsal, song=song_a, order=1)
        doomed = RehearsalSongFactory(rehearsal=rehearsal, song=song_b, order=2)
        admin_client(self)
        data = formset_data([rehearsal], running_order=[
            {'rehearsal_row_key': 'rehearsal-0', 'song_id': song_c.pk, 'slot_count': 1},
            {'rehearsal_row_key': 'rehearsal-0', 'song_id': song_a.pk, 'slot_count': 1, 'rehearsal_song_id': kept.pk},
        ])

        assert_preview_writes_nothing(
            self, reverse('scheduling:schedule-edit-preview'), data,
            models_to_check=[Rehearsal, RehearsalSong], semester=semester,
        )
        self.assertTrue(RehearsalSong.objects.filter(pk=doomed.pk).exists())

    def test_previewing_a_rehearsal_deletion_with_recordings_touches_no_storage_object(self):
        """A Preview of a buffer that would delete a Rehearsal with Recordings never calls the storage backend at all (issue #221)."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        song = SongFactory(semester=semester, position=1)
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        RecordingFactory(rehearsal_song=rehearsal_song)
        admin_client(self)
        data = formset_data([rehearsal], deleted_rehearsal_ids=[rehearsal.pk])

        assert_preview_writes_nothing(
            self, reverse('scheduling:schedule-edit-preview'), data,
            models_to_check=[Rehearsal, Recording], semester=semester,
        )

    def test_is_forbidden_for_a_non_admin(self):
        """A logged-in non-admin's POST to the preview endpoint returns 403."""
        member_client(self)

        response = self.client.post(reverse('scheduling:schedule-edit-preview'), {})

        self.assertEqual(response.status_code, 403)

    def test_redirects_anonymous_users_to_login(self):
        """An anonymous POST to the preview endpoint redirects to login."""
        url = reverse('scheduling:schedule-edit-preview')

        response = self.client.post(url, {})

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")
