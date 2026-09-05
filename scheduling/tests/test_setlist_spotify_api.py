"""`/api/setlist/spotify/`: the + Add sheet's Spotify fetch, write-nothing (issue #335)."""

import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from scheduling.factories import SemesterFactory, SongFactory
from scheduling.models import Song
from scheduling.spotify import (
    ImportedSong,
    PlaylistImportResult,
    SpotifyImportError,
    SpotifyImportUnavailable,
)
from scheduling.tests.test_setlist_reorder_add_delete import (
    admin_client,
    member_client,
    select,
)

VALID_URL = 'https://open.spotify.com/playlist/37i9dQZF1E8KcRnHXtvNli'


def _url():
    """Return the Spotify-fetch `/api/` endpoint's URL."""
    return reverse('api-setlist-spotify')


def _post_json(test_case, body):
    """POST `body` (a dict) as a JSON request body to the Spotify-fetch endpoint and return the parsed response envelope."""
    response = test_case.client.post(_url(), data=json.dumps(body), content_type='application/json')
    return response, json.loads(response.content)


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessControlTests(TestCase):
    """Gates identically to every other `AdminApiView`."""

    def test_anonymous_post_is_401(self):
        """An anonymous POST answers the documented JSON 401, never a redirect."""
        response = self.client.post(_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_non_admin_post_is_403(self):
        """A logged-in non-admin's POST is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.post(_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def test_get_is_not_allowed(self):
        """A GET is rejected -- it is POST-only."""
        admin_client(self)

        response = self.client.get(_url())

        self.assertEqual(response.status_code, 405)


@override_settings(SECURE_SSL_REDIRECT=False)
class SpotifyImportApiTests(TestCase):
    """A successful fetch flags duplicates server-side and writes nothing; every failure degrades to a message."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one existing Song, viewed by the session."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.existing_song = SongFactory(semester=self.semester, title='Already Here', position=1)

    def test_blank_url_returns_a_readable_message_and_no_songs(self):
        """A missing/blank `url` degrades to the invalid-link message rather than a non-2xx status."""
        response, envelope = _post_json(self, {'url': ''})

        self.assertEqual(response.status_code, 200)
        self.assertIn('context', envelope)
        self.assertEqual(envelope['data']['songs'], [])
        self.assertTrue(envelope['data']['message'])

    @patch('scheduling.api_views.spotify.import_playlist')
    def test_spotify_import_error_degrades_to_a_message(self, mock_import):
        """A `SpotifyImportError` (bad link, not found, rate limit, ...) degrades to a 200 with a readable message."""
        mock_import.side_effect = SpotifyImportError('Bad link.')

        response, envelope = _post_json(self, {'url': VALID_URL})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(envelope['data']['message'], 'Bad link.')
        self.assertEqual(envelope['data']['songs'], [])

    @patch('scheduling.api_views.spotify.import_playlist')
    def test_unconfigured_credentials_degrade_to_a_message(self, mock_import):
        """A missing Spotify credential (`SpotifyImportUnavailable`) degrades to a message, not an error page."""
        mock_import.side_effect = SpotifyImportUnavailable('Spotify import is not configured.')

        response, envelope = _post_json(self, {'url': VALID_URL})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(envelope['data']['message'], 'Spotify import is not configured.')

    @patch('scheduling.api_views.spotify.import_playlist')
    def test_successful_fetch_flags_the_duplicate_title_case_insensitively(self, mock_import):
        """A candidate whose title matches an existing Song's (case-insensitively) is flagged, others are not."""
        mock_import.return_value = PlaylistImportResult(
            songs=[
                ImportedSong(title='already here', artist='Someone Else', length=timedelta(minutes=3, seconds=10), position=1),
                ImportedSong(title='Brand New Track', artist='Faux Static', length=timedelta(minutes=4), position=2),
            ],
            skipped_count=2,
            skipped_reasons={'local file': 1, 'podcast episode': 1},
        )

        response, envelope = _post_json(self, {'url': VALID_URL})

        self.assertEqual(response.status_code, 200)
        songs = envelope['data']['songs']
        self.assertEqual(envelope['data']['message'], '')
        self.assertEqual(envelope['data']['skipped_count'], 2)
        self.assertEqual(envelope['data']['skipped_reasons'], {'local file': 1, 'podcast episode': 1})
        self.assertTrue(songs[0]['already_in_setlist'])
        self.assertEqual(songs[0]['length'], '3:10')
        self.assertFalse(songs[1]['already_in_setlist'])

    @patch('scheduling.api_views.spotify.import_playlist')
    def test_a_successful_fetch_writes_no_song(self, mock_import):
        """A successful fetch never creates a `Song` -- it only returns candidate rows for the client's own Buffer."""
        mock_import.return_value = PlaylistImportResult(
            songs=[ImportedSong(title='Brand New Track', artist='Faux Static', length=timedelta(minutes=4), position=1)],
        )
        count_before = Song.objects.count()

        self._post_json_and_discard()

        self.assertEqual(Song.objects.count(), count_before)

    def _post_json_and_discard(self):
        """POST a valid fetch request and discard the response."""
        _post_json(self, {'url': VALID_URL})
