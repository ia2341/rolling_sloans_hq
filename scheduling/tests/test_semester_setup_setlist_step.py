"""Semester setup step 4: importing the setlist from a Spotify playlist link (issue #202)."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import SemesterFactory, SongFactory
from scheduling.models import Song
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY
from scheduling.spotify import ImportedSong, PlaylistImportResult
from scheduling.tests.test_setlist_reorder_add_delete import build_post_data

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


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistStepAuthTests(TestCase):
    def test_anonymous_get_redirects_to_login(self):
        """An anonymous GET to the setlist step redirects to login."""
        semester = SemesterFactory(draft=True)

        response = self.client.get(reverse('scheduling:manage-semester-setup-setlist', args=[semester.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('identity:login'), response.url)

    def test_member_get_is_forbidden(self):
        """A logged-in non-admin gets a 403 for the setlist step."""
        semester = SemesterFactory(draft=True)
        member_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-setlist', args=[semester.pk]))

        self.assertEqual(response.status_code, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistStepGetTests(TestCase):
    def test_renders_an_empty_row_for_a_bare_draft(self):
        """A freshly created draft with no Songs opens the grid with one blank row, mirroring the Setlist tab."""
        semester = SemesterFactory(draft=True)
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-setlist', args=[semester.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="setlist-import"')
        self.assertContains(response, 'id="id_playlist_url"')

    def test_switches_the_session_viewing_semester_to_the_draft(self):
        """Visiting the step directly (not just via the create redirect) still scopes reads/writes to this draft."""
        other = SemesterFactory()
        semester = SemesterFactory(draft=True)
        admin_client(self)
        session = self.client.session
        session[VIEWING_SEMESTER_SESSION_KEY] = other.pk
        session.save()

        self.client.get(reverse('scheduling:manage-semester-setup-setlist', args=[semester.pk]))

        self.assertEqual(self.client.session[VIEWING_SEMESTER_SESSION_KEY], semester.pk)

    def test_offers_a_skip_link_to_the_finish_screen(self):
        """The step offers a Skip link straight to the finish screen, writing nothing."""
        semester = SemesterFactory(draft=True)
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-setlist', args=[semester.pk]))

        self.assertContains(response, reverse('scheduling:manage-semester-setup-finish', args=[semester.pk]))
        self.assertEqual(Song.objects.count(), 0)

    def test_existing_songs_are_shown_for_review(self):
        """A draft that already has Songs (e.g. revisited after a partial import) shows them in the grid."""
        semester = SemesterFactory(draft=True)
        song = SongFactory(semester=semester, title='Existing Song')
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-setlist', args=[semester.pk]))

        self.assertContains(response, song.title)


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistStepImportAndSaveTests(TestCase):
    """The step's import box and grid post to the Setlist tab's own endpoints, unchanged (issue #184, #179)."""

    def test_pasting_a_playlist_link_previews_rows_through_the_existing_import_endpoint(self):
        """The step's import box calls the same `import_playlist()`-backed endpoint the Setlist tab uses."""
        semester = SemesterFactory(draft=True)
        admin_client(self)
        self.client.get(reverse('scheduling:manage-semester-setup-setlist', args=[semester.pk]))
        result = PlaylistImportResult(songs=[
            ImportedSong(
                title='Synth Wave', artist='Fictional Artist',
                length=timedelta(minutes=3, seconds=30), position=1,
            ),
        ])

        with patch('scheduling.views.import_playlist', return_value=result) as mock_import:
            response = self.client.post(reverse('scheduling:setlist-edit-import'), {
                'playlist_url': 'https://open.spotify.com/playlist/37i9dQZF1E8KcRnHXtvNli',
                'next_index': '0',
            })

        mock_import.assert_called_once()
        self.assertContains(response, 'Synth Wave')
        self.assertContains(response, 'Fictional Artist')
        self.assertEqual(Song.objects.count(), 0)

    def test_saving_the_grid_writes_songs_for_this_draft_and_redirects_to_the_setlist_tab(self):
        """Saving the wizard step's grid uses the real `setlist-edit` save path — no second implementation."""
        semester = SemesterFactory(draft=True)
        admin_client(self)
        self.client.get(reverse('scheduling:manage-semester-setup-setlist', args=[semester.pk]))
        data = build_post_data(semester, rows=[
            {'title': 'Imported Track', 'artist': 'Imported Artist', 'length': '3:30', 'notes': ''},
        ])

        response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertRedirects(response, reverse('scheduling:setlist'))
        song = Song.objects.get(semester=semester)
        self.assertEqual(song.title, 'Imported Track')
        self.assertEqual(song.notes, '')

    def test_the_prior_semesters_songs_are_unchanged_and_unmoved(self):
        """Importing into the new draft never touches another Semester's Songs."""
        prior = SemesterFactory()
        prior_song = SongFactory(semester=prior, position=1)
        semester = SemesterFactory(draft=True)
        admin_client(self)
        self.client.get(reverse('scheduling:manage-semester-setup-setlist', args=[semester.pk]))
        data = build_post_data(semester, rows=[
            {'title': 'Imported Track', 'artist': 'Imported Artist', 'length': '3:30', 'notes': ''},
        ])

        self.client.post(reverse('scheduling:setlist-edit'), data)

        prior_song.refresh_from_db()
        self.assertEqual(prior_song.position, 1)
        self.assertEqual(Song.objects.filter(semester=prior).count(), 1)
