"""Spotify playlist import service: fetch, filter and map, never persist (issue #183)."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import requests
from django.test import TestCase, override_settings

from scheduling.spotify import (
    ImportedSong,
    SpotifyImportError,
    SpotifyImportUnavailable,
    import_playlist,
)

VALID_URL = 'https://open.spotify.com/playlist/37i9dQZF1E8KcRnHXtvNli'


def _track_item(name='Synth Serenade', artists=('Faux Static',), duration_ms=225_000):
    """Build a raw Spotify playlist-item payload for a usable track."""
    return {
        'item': {
            'type': 'track',
            'is_local': False,
            'name': name,
            'artists': [{'name': artist} for artist in artists],
            'duration_ms': duration_ms,
        }
    }


def _episode_item():
    """Build a raw playlist-item payload for a podcast episode."""
    return {'item': {'type': 'episode', 'is_local': False, 'name': 'A Podcast Episode'}}


def _local_file_item():
    """Build a raw playlist-item payload for a local file (null/minimal track object)."""
    return {'item': {'is_local': True}}


def _page(items, next_url=None):
    """Build one page of the playlists/{id}/items response shape."""
    return {'items': items, 'next': next_url}


def _response(status_code=200, json_data=None, headers=None):
    """Build a fake `requests.Response`-shaped object for a mocked session call."""
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.json.return_value = json_data or {}
    response.headers = headers or {}
    return response


@override_settings(SPOTIFY_CLIENT_ID='client-id', SPOTIFY_CLIENT_SECRET='client-secret')
class ImportPlaylistTests(TestCase):
    """`import_playlist()` against a mocked `requests.Session` — no live Spotify call."""

    def _mock_session(self, mock_session_cls, get_responses, token_response=None):
        """Wire a mocked Session whose post() returns a token and get() cycles through pages."""
        session = mock_session_cls.return_value.__enter__.return_value
        session.post.return_value = token_response or _response(
            json_data={'access_token': 'token-123'}
        )
        session.get.side_effect = get_responses
        return session

    @patch('scheduling.spotify.requests.Session')
    def test_maps_a_single_page_of_tracks_into_rows(self, mock_session_cls):
        """A track's name, joined artists and truncated-to-second duration land on the row."""
        items = [_track_item(name='One', artists=('Solo Artist',), duration_ms=185_499)]
        self._mock_session(mock_session_cls, [_response(json_data=_page(items))])

        result = import_playlist(VALID_URL)

        self.assertEqual(
            result.songs,
            [ImportedSong(title='One', artist='Solo Artist', length=timedelta(seconds=185), position=1)],
        )
        self.assertEqual(result.skipped_count, 0)

    @patch('scheduling.spotify.requests.Session')
    def test_multiple_artists_are_joined(self, mock_session_cls):
        """A collaboration's artist names are joined, not dropped or truncated."""
        items = [_track_item(artists=('Artist A', 'Artist B', 'Artist C'))]
        self._mock_session(mock_session_cls, [_response(json_data=_page(items))])

        result = import_playlist(VALID_URL)

        self.assertEqual(result.songs[0].artist, 'Artist A, Artist B, Artist C')

    @patch('scheduling.spotify.requests.Session')
    def test_notes_are_always_blank(self, mock_session_cls):
        """An imported row always has a blank notes field; Spotify has no equivalent."""
        self._mock_session(mock_session_cls, [_response(json_data=_page([_track_item()]))])

        result = import_playlist(VALID_URL)

        self.assertEqual(result.songs[0].notes, '')

    @patch('scheduling.spotify.requests.Session')
    def test_follows_pagination_past_the_page_cap(self, mock_session_cls):
        """A playlist longer than one page arrives in full, across two `get` calls."""
        page_one = _page([_track_item(name='Track 1')], next_url='https://api.spotify.com/v1/next-page')
        page_two = _page([_track_item(name='Track 2')])
        self._mock_session(mock_session_cls, [_response(json_data=page_one), _response(json_data=page_two)])

        result = import_playlist(VALID_URL)

        self.assertEqual([song.title for song in result.songs], ['Track 1', 'Track 2'])
        self.assertEqual([song.position for song in result.songs], [1, 2])

    @patch('scheduling.spotify.requests.Session')
    def test_podcast_episodes_and_local_files_are_skipped_with_contiguous_positions(
        self, mock_session_cls
    ):
        """Skipped items leave no gaps: survivors are renumbered 1..N, and the caller learns why."""
        items = [
            _track_item(name='First'),
            _episode_item(),
            _local_file_item(),
            _track_item(name='Second'),
        ]
        self._mock_session(mock_session_cls, [_response(json_data=_page(items))])

        result = import_playlist(VALID_URL)

        self.assertEqual([song.title for song in result.songs], ['First', 'Second'])
        self.assertEqual([song.position for song in result.songs], [1, 2])
        self.assertEqual(result.skipped_count, 2)
        self.assertEqual(result.skipped_reasons, {'podcast episode': 1, 'local file': 1})

    def test_malformed_link_fails_before_any_request(self):
        """A non-Spotify or malformed link is rejected without touching the network."""
        with patch('scheduling.spotify.requests.Session') as mock_session_cls:
            with self.assertRaises(SpotifyImportError):
                import_playlist('https://example.com/not-spotify')
            mock_session_cls.assert_not_called()

    def test_link_with_a_path_suffix_after_the_id_is_rejected(self):
        """A trailing path segment past the playlist ID is malformed, not extra routing."""
        with patch('scheduling.spotify.requests.Session') as mock_session_cls:
            with self.assertRaises(SpotifyImportError):
                import_playlist(f'{VALID_URL}/extra')
            mock_session_cls.assert_not_called()

    @patch('scheduling.spotify.requests.Session')
    def test_link_with_a_query_string_is_still_accepted(self, mock_session_cls):
        """A share link's tracking query string (?si=...) doesn't make the link malformed."""
        self._mock_session(mock_session_cls, [_response(json_data=_page([_track_item()]))])

        result = import_playlist(f'{VALID_URL}?si=abc123')

        self.assertEqual(len(result.songs), 1)

    @patch('scheduling.spotify.requests.Session')
    def test_playlist_not_found_produces_a_readable_error(self, mock_session_cls):
        """A private, deleted or non-existent playlist raises a readable message, no rows."""
        self._mock_session(mock_session_cls, [_response(status_code=404)])

        with self.assertRaises(SpotifyImportError):
            import_playlist(VALID_URL)

    @patch('scheduling.spotify.requests.Session')
    def test_auth_failure_on_token_exchange_produces_a_readable_error(self, mock_session_cls):
        """A rejected client-credentials exchange raises a readable message, no rows."""
        self._mock_session(mock_session_cls, [], token_response=_response(status_code=401))

        with self.assertRaises(SpotifyImportError):
            import_playlist(VALID_URL)

    @patch('scheduling.spotify.requests.Session')
    def test_rate_limited_response_produces_a_readable_error_with_retry_hint(self, mock_session_cls):
        """A 429 raises a readable message that carries Spotify's Retry-After hint."""
        self._mock_session(
            mock_session_cls, [_response(status_code=429, headers={'Retry-After': '30'})]
        )

        with self.assertRaises(SpotifyImportError) as ctx:
            import_playlist(VALID_URL)
        self.assertIn('30', str(ctx.exception))

    @patch('scheduling.spotify.requests.Session')
    def test_transport_error_produces_a_readable_error(self, mock_session_cls):
        """A network-level failure raises a readable message, no rows."""
        session = mock_session_cls.return_value.__enter__.return_value
        session.post.side_effect = requests.ConnectionError('boom')

        with self.assertRaises(SpotifyImportError):
            import_playlist(VALID_URL)

    @override_settings(SPOTIFY_CLIENT_ID=None, SPOTIFY_CLIENT_SECRET=None)
    def test_missing_credentials_is_unavailable_not_a_crash(self):
        """With no Spotify credentials configured, the import reports unavailable, not a raw error."""
        with patch('scheduling.spotify.requests.Session') as mock_session_cls:
            with self.assertRaises(SpotifyImportUnavailable):
                import_playlist(VALID_URL)
            mock_session_cls.assert_not_called()

    @patch('scheduling.spotify.requests.Session')
    def test_persists_nothing(self, mock_session_cls):
        """A successful import creates no `Song` rows — it only returns row data."""
        from scheduling.models import Song

        self._mock_session(mock_session_cls, [_response(json_data=_page([_track_item()]))])

        import_playlist(VALID_URL)

        self.assertEqual(Song.objects.count(), 0)
