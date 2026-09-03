"""The setlist edit grid's Spotify playlist import: fetch-and-append, never a second write path (issue #184)."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import SemesterFactory, SongFactory
from scheduling.models import Song
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY
from scheduling.spotify import (
    ImportedSong,
    PlaylistImportResult,
    SpotifyImportError,
    SpotifyImportUnavailable,
)
from scheduling.tests.test_setlist_reorder_add_delete import build_post_data

PASSWORD = 'a-strong-test-password-123'
VALID_URL = 'https://open.spotify.com/playlist/37i9dQZF1E8KcRnHXtvNli'


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


def import_result(**overrides):
    """Build a `PlaylistImportResult` of two synthesized tracks, overridable per test."""
    songs = overrides.pop('songs', [
        ImportedSong(title='Synth Serenade', artist='Faux Static', length=timedelta(minutes=3, seconds=45), position=1),
        ImportedSong(title='Borrowed Chorus', artist='Nomad Echo', length=timedelta(minutes=4, seconds=5), position=2),
    ])
    return PlaylistImportResult(songs=songs, **overrides)


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistImportAccessTests(TestCase):
    def test_redirects_anonymous_users_to_login(self):
        """An anonymous POST to the import endpoint redirects to the login page."""
        url = reverse('scheduling:setlist-edit-import')

        response = self.client.post(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_is_forbidden_for_a_non_admin(self):
        """A logged-in non-admin's POST to the import endpoint returns 403."""
        member_client(self)

        response = self.client.post(reverse('scheduling:setlist-edit-import'))

        self.assertEqual(response.status_code, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistImportViewTests(TestCase):
    @patch('scheduling.views.import_playlist')
    def test_a_successful_import_renders_filled_rows_at_the_requested_slots(self, mock_import):
        """A successful import renders each track's title, artist and length at consecutive song-N slots."""
        mock_import.return_value = import_result()
        semester = SemesterFactory()
        admin_client(self)
        select(self, semester)

        response = self.client.post(
            reverse('scheduling:setlist-edit-import'),
            {'playlist_url': VALID_URL, 'next_index': '0'},
        )

        mock_import.assert_called_once_with(VALID_URL)
        self.assertContains(response, 'song-0-title')
        self.assertContains(response, 'song-1-title')
        self.assertContains(response, 'Synth Serenade')
        self.assertContains(response, 'Faux Static')
        self.assertContains(response, '3:45')
        self.assertContains(response, 'Borrowed Chorus')
        self.assertContains(response, '4:05')
        self.assertContains(response, 'data-added-count="2"')

    @patch('scheduling.views.import_playlist')
    def test_imported_rows_land_at_the_submitted_next_index_not_zero(self, mock_import):
        """Rows are slotted starting at the client's reported next_index, so they append after existing rows."""
        mock_import.return_value = import_result(songs=[
            ImportedSong(title='Only Track', artist='Solo Act', length=timedelta(minutes=2), position=1),
        ])
        semester = SemesterFactory()
        admin_client(self)
        select(self, semester)

        response = self.client.post(
            reverse('scheduling:setlist-edit-import'),
            {'playlist_url': VALID_URL, 'next_index': '5'},
        )

        self.assertContains(response, 'song-5-title')
        self.assertNotContains(response, 'song-0-title')

    @patch('scheduling.views.import_playlist')
    def test_imported_rows_carry_blank_notes_even_if_the_import_result_did_not(self, mock_import):
        """An imported row's notes field renders blank, distinguishing it from an admin-typed row.

        Deliberately feeds a non-blank `notes` on the `ImportedSong` (which
        the service never actually produces) to prove the view itself
        forces the field blank, rather than merely passing through
        whatever happened to already be empty.
        """
        mock_import.return_value = import_result(songs=[
            ImportedSong(
                title='Track', artist='Artist', length=timedelta(minutes=2), position=1,
                notes='should never reach the rendered field',
            ),
        ])
        semester = SemesterFactory()
        admin_client(self)
        select(self, semester)

        response = self.client.post(
            reverse('scheduling:setlist-edit-import'),
            {'playlist_url': VALID_URL, 'next_index': '0'},
        )

        self.assertContains(response, '<textarea name="song-0-notes" cols="40" rows="10" id="id_song-0-notes">\n</textarea>', html=True)
        self.assertNotContains(response, 'should never reach the rendered field')

    @patch('scheduling.views.import_playlist')
    def test_a_successful_import_writes_no_songs(self, mock_import):
        """The import persists nothing: no Song row exists until a subsequent Save Changes."""
        mock_import.return_value = import_result()
        semester = SemesterFactory()
        admin_client(self)
        select(self, semester)

        self.client.post(
            reverse('scheduling:setlist-edit-import'),
            {'playlist_url': VALID_URL, 'next_index': '0'},
        )

        self.assertEqual(Song.objects.count(), 0)

    @patch('scheduling.views.import_playlist')
    def test_reports_how_many_items_were_skipped_and_why(self, mock_import):
        """The rendered fragment names the skip count and reason, so a short import isn't a mystery."""
        mock_import.return_value = import_result(skipped_count=3, skipped_reasons={'podcast episode': 3})
        semester = SemesterFactory()
        admin_client(self)
        select(self, semester)

        response = self.client.post(
            reverse('scheduling:setlist-edit-import'),
            {'playlist_url': VALID_URL, 'next_index': '0'},
        )

        self.assertContains(response, 'Skipped 3 items')
        self.assertContains(response, 'podcast episode')

    def test_a_malformed_link_is_a_field_error_and_never_calls_the_import_service(self):
        """A malformed/non-Spotify link fails validation before any import is attempted."""
        semester = SemesterFactory()
        admin_client(self)
        select(self, semester)

        with patch('scheduling.views.import_playlist') as mock_import:
            response = self.client.post(
                reverse('scheduling:setlist-edit-import'),
                {'playlist_url': 'https://example.com/not-spotify', 'next_index': '0'},
            )

        mock_import.assert_not_called()
        self.assertContains(response, 'id="setlist-import-error"')
        self.assertEqual(Song.objects.count(), 0)

    @patch('scheduling.views.import_playlist')
    def test_a_private_or_missing_playlist_renders_a_readable_error_not_a_stack_trace(self, mock_import):
        """A `SpotifyImportError` from the service renders as a readable message, not an exception page."""
        mock_import.side_effect = SpotifyImportError("Spotify couldn't find that playlist. Make sure it's public, not deleted.")
        semester = SemesterFactory()
        admin_client(self)
        select(self, semester)

        response = self.client.post(
            reverse('scheduling:setlist-edit-import'),
            {'playlist_url': VALID_URL, 'next_index': '0'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "couldn&#x27;t find that playlist")
        self.assertNotContains(response, 'setlist-import-rows')

    @patch('scheduling.views.import_playlist')
    def test_missing_credentials_renders_unavailable_without_raising(self, mock_import):
        """A credential-less environment renders the unavailable message rather than a 500."""
        mock_import.side_effect = SpotifyImportUnavailable('Spotify import is not configured.')
        semester = SemesterFactory()
        admin_client(self)
        select(self, semester)

        response = self.client.post(
            reverse('scheduling:setlist-edit-import'),
            {'playlist_url': VALID_URL, 'next_index': '0'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not configured')

    @patch('scheduling.views.import_playlist')
    def test_a_rate_limited_import_leaves_no_songs_written(self, mock_import):
        """A rate-limited import renders its message and writes nothing, per the buffer-untouched guarantee."""
        mock_import.side_effect = SpotifyImportError('Spotify is rate-limiting this import; try again in 30 seconds.')
        semester = SemesterFactory()
        SongFactory(semester=semester, title='Already Typed')
        admin_client(self)
        select(self, semester)

        response = self.client.post(
            reverse('scheduling:setlist-edit-import'),
            {'playlist_url': VALID_URL, 'next_index': '1'},
        )

        self.assertContains(response, 'rate-limiting')
        self.assertEqual(Song.objects.count(), 1)
        self.assertEqual(Song.objects.get().title, 'Already Typed')


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistImportedRowsSaveTests(TestCase):
    """Once appended, imported rows are ordinary buffer rows: Save Changes governs them exactly like a typed one."""

    def test_saving_a_buffer_of_an_existing_song_plus_imported_rows_renumbers_contiguously(self):
        """A pre-existing Song plus two never-before-saved imported-style rows save as a contiguous 1..3."""
        semester = SemesterFactory()
        existing = SongFactory(semester=semester, position=1, title='Already Typed')
        admin_client(self)
        data = build_post_data(semester, [
            {'song': existing},
            {'title': 'Synth Serenade', 'artist': 'Faux Static', 'length': '3:45'},
            {'title': 'Borrowed Chorus', 'artist': 'Nomad Echo', 'length': '4:05'},
        ])

        response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertRedirects(response, reverse('scheduling:setlist'))
        songs = list(Song.objects.filter(semester=semester).order_by('position'))
        self.assertEqual([song.position for song in songs], [1, 2, 3])
        self.assertEqual([song.title for song in songs], ['Already Typed', 'Synth Serenade', 'Borrowed Chorus'])

    def test_importing_into_a_non_empty_setlist_appends_and_never_replaces_existing_rows(self):
        """Existing rows and their positions survive a save that also carries newly-imported rows."""
        semester = SemesterFactory()
        first = SongFactory(semester=semester, position=1, title='First')
        second = SongFactory(semester=semester, position=2, title='Second')
        admin_client(self)
        data = build_post_data(semester, [
            {'song': first},
            {'song': second},
            {'title': 'Imported Track', 'artist': 'Imported Artist', 'length': '2:30'},
        ])

        self.client.post(reverse('scheduling:setlist-edit'), data)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.position, 1)
        self.assertEqual(second.position, 2)
        self.assertEqual(Song.objects.get(title='Imported Track').position, 3)
