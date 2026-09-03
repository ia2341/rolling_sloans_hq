"""Spotify playlist import: turns a public playlist link into setlist rows (issue #183).

Read-only against Spotify and **write-nothing** against this app: the
service returns row data for the caller (the setlist edit buffer, per spec
#172) to append and save. It authenticates via the Client Credentials Flow
(server-to-server, app-only token) since a public playlist needs no
per-admin OAuth. See ADR-free rationale in the issue: playlist order *is*
concert position, per the owner's correction over the original research.
"""

import re
from dataclasses import dataclass, field
from datetime import timedelta

import requests
from django.conf import settings

TOKEN_URL = 'https://accounts.spotify.com/api/token'
API_BASE_URL = 'https://api.spotify.com/v1'
PLAYLIST_ITEMS_PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 10

#: A Spotify playlist link, e.g. https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=...
_PLAYLIST_URL_PATTERN = re.compile(
    r'^https://open\.spotify\.com/playlist/(?P<playlist_id>[A-Za-z0-9]+)(?:/)?(?:[?#].*)?$'
)

UNAVAILABLE_MESSAGE = (
    'Spotify import is not configured. Set SPOTIFY_CLIENT_ID and '
    'SPOTIFY_CLIENT_SECRET to enable it.'
)
INVALID_LINK_MESSAGE = (
    'Enter a public Spotify playlist link, e.g. '
    'https://open.spotify.com/playlist/<id>.'
)
NOT_FOUND_MESSAGE = (
    "Spotify couldn't find that playlist. Make sure it's public, not deleted."
)
AUTH_FAILED_MESSAGE = 'Spotify rejected the import credentials.'
RATE_LIMITED_MESSAGE = 'Spotify is rate-limiting this import; try again in {retry_after} seconds.'
TRANSPORT_ERROR_MESSAGE = "Couldn't reach Spotify; the import was not completed."


class SpotifyImportError(Exception):
    """A readable, caller-facing import failure. Never leaves the buffer touched."""


class SpotifyImportUnavailable(SpotifyImportError):
    """Raised when SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET are not configured."""


@dataclass(frozen=True)
class ImportedSong:
    """One playlist track, shaped like the fields `Song` needs — nothing is persisted here."""

    title: str
    artist: str
    length: timedelta
    position: int
    notes: str = ''


@dataclass(frozen=True)
class PlaylistImportResult:
    """The rows an import produced, plus how many items were skipped and why."""

    songs: list[ImportedSong] = field(default_factory=list)
    skipped_count: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)


def import_playlist(url: str) -> PlaylistImportResult:
    """Fetch a public Spotify playlist by its share link and return it as setlist rows.

    Writes nothing to this app or to Spotify. Raises `SpotifyImportUnavailable`
    if no Spotify credentials are configured, or `SpotifyImportError` for a
    malformed link, a private/missing playlist, an auth failure, a
    rate-limited response, or a transport error — every case a readable
    message and no rows.
    """
    playlist_id = extract_playlist_id(url)
    client_id = getattr(settings, 'SPOTIFY_CLIENT_ID', None)
    client_secret = getattr(settings, 'SPOTIFY_CLIENT_SECRET', None)
    if not client_id or not client_secret:
        raise SpotifyImportUnavailable(UNAVAILABLE_MESSAGE)

    with requests.Session() as session:
        access_token = _fetch_access_token(session, client_id, client_secret)
        items = _fetch_all_playlist_items(session, access_token, playlist_id)
    return _rows_from_items(items)


def extract_playlist_id(url: str) -> str:
    """Return the playlist ID from a Spotify playlist link, before any network call.

    Raises `SpotifyImportError` on anything that isn't a well-formed
    `open.spotify.com/playlist/<id>` link, so a typo never reaches the
    network. Public so the setlist edit surface (issue #184) can run the
    identical check as a form field error before this module is asked to
    do anything else.
    """
    match = _PLAYLIST_URL_PATTERN.match((url or '').strip())
    if not match:
        raise SpotifyImportError(INVALID_LINK_MESSAGE)
    return match.group('playlist_id')


def _fetch_access_token(session, client_id, client_secret) -> str:
    """Exchange app credentials for an app-only access token via Client Credentials Flow."""
    try:
        response = session.post(
            TOKEN_URL,
            data={'grant_type': 'client_credentials'},
            auth=(client_id, client_secret),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise SpotifyImportError(TRANSPORT_ERROR_MESSAGE) from error

    if response.status_code == 401:
        raise SpotifyImportError(AUTH_FAILED_MESSAGE)
    _raise_for_rate_limit(response)
    if not response.ok:
        raise SpotifyImportError(AUTH_FAILED_MESSAGE)
    return response.json()['access_token']


def _fetch_all_playlist_items(session, access_token, playlist_id) -> list[dict]:
    """Fetch every playlist item, following pagination past the 100-item page cap."""
    headers = {'Authorization': f'Bearer {access_token}'}
    url = f'{API_BASE_URL}/playlists/{playlist_id}/items'
    params = {'limit': PLAYLIST_ITEMS_PAGE_SIZE}
    items = []
    while url:
        try:
            response = session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as error:
            raise SpotifyImportError(TRANSPORT_ERROR_MESSAGE) from error

        if response.status_code in (401, 403):
            raise SpotifyImportError(AUTH_FAILED_MESSAGE)
        if response.status_code == 404:
            raise SpotifyImportError(NOT_FOUND_MESSAGE)
        _raise_for_rate_limit(response)
        if not response.ok:
            raise SpotifyImportError(NOT_FOUND_MESSAGE)

        payload = response.json()
        items.extend(payload.get('items', []))
        url = payload.get('next')
        params = None  # `next` is a fully-formed URL; no params to re-append.
    return items


def _raise_for_rate_limit(response) -> None:
    """Raise `SpotifyImportError` with a retry hint on a 429, else return."""
    if response.status_code != 429:
        return
    retry_after = response.headers.get('Retry-After', '60')
    raise SpotifyImportError(RATE_LIMITED_MESSAGE.format(retry_after=retry_after))


def _rows_from_items(items: list[dict]) -> PlaylistImportResult:
    """Filter and map raw playlist items into `ImportedSong` rows, renumbered contiguously.

    Podcast episodes and local files are skipped (they carry no usable
    track metadata); positions are assigned 1..N over the survivors only,
    never the raw Spotify indices.
    """
    songs = []
    skipped_reasons: dict[str, int] = {}

    for item in items:
        track = item.get('item')
        skip_reason = _skip_reason_for(track)
        if skip_reason:
            skipped_reasons[skip_reason] = skipped_reasons.get(skip_reason, 0) + 1
            continue
        songs.append(
            ImportedSong(
                title=track['name'],
                artist=', '.join(artist['name'] for artist in track['artists']),
                length=timedelta(seconds=track['duration_ms'] // 1000),
                position=len(songs) + 1,
            )
        )

    return PlaylistImportResult(
        songs=songs,
        skipped_count=sum(skipped_reasons.values()),
        skipped_reasons=skipped_reasons,
    )


def _skip_reason_for(track: dict | None) -> str | None:
    """Return why a playlist item should be skipped, or `None` if it's a usable track."""
    if not track or track.get('is_local'):
        return 'local file'
    if track.get('type') != 'track':
        return 'podcast episode'
    return None
