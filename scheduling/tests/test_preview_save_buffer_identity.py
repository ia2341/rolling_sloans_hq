"""The mandatory invariant: preview and save can never construct a Setlist Buffer differently (issue #334, ADR 0008).

`build_setlist_buffer_from_request()` is the ONE place a submitted JSON
body becomes a `SetlistEditBuffer`. This test's whole point is to fail the
moment someone forks that construction function into two, so it calls
`build_setlist_buffer_from_request()` directly (never a view) for the
buffer-equality half of each case, and separately drives both live HTTP
endpoints with the identical body to prove neither one reimplements
anything of its own.
"""

import json

from django.http import HttpRequest
from django.test import TestCase, override_settings
from django.urls import reverse

from scheduling.api_builders import (
    SetlistBufferValidationError,
    build_setlist_buffer_from_request,
)
from scheduling.factories import SemesterFactory, SongFactory
from scheduling.tests.test_setlist_reorder_add_delete import admin_client, select

PASSWORD = 'a-strong-test-password-123'


def _fake_request(body: dict) -> HttpRequest:
    """Build a bare `HttpRequest` carrying `body` as its JSON-encoded `.body`, for calling the builder directly."""
    request = HttpRequest()
    request._body = json.dumps(body).encode('utf-8')
    return request


def _post_json(test_case, url, body):
    """POST `body` as JSON to `url` and return the parsed response envelope."""
    response = test_case.client.post(url, data=json.dumps(body), content_type='application/json')
    return response, json.loads(response.content)


@override_settings(SECURE_SSL_REDIRECT=False)
class BuilderIsTheOneConstructionPathTests(TestCase):
    """Calling `build_setlist_buffer_from_request()` twice on the identical body always yields the identical result."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one Song."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester, position=1, title='Original', artist='Artist A')

    def _valid_body(self):
        """Return a well-formed request body for `self.semester`."""
        return {
            'semester_id': self.semester.pk,
            'semester_updated_at': self.semester.updated_at.isoformat(),
            'rows': [
                {'row_key': 'r1', 'song_id': self.song.pk, 'title': 'Edited', 'artist': 'Artist A', 'length': '3:30', 'notes': ''},
                {'row_key': 'r2', 'song_id': None, 'title': 'New Song', 'artist': 'New Artist', 'length': '2:15', 'notes': ''},
            ],
            'deleted_song_ids': [],
        }

    def test_valid_body_builds_an_identical_buffer_every_time(self):
        """A well-formed body builds byte-for-byte identical (frozen-dataclass-equal) Buffers on repeated calls."""
        body = self._valid_body()

        first = build_setlist_buffer_from_request(_fake_request(body), viewing_semester=self.semester)
        second = build_setlist_buffer_from_request(_fake_request(body), viewing_semester=self.semester)

        self.assertEqual(first, second)

    def test_per_field_validation_failure_raises_the_same_shape_every_time(self):
        """A body with a per-field failure (missing title) raises the identical row_errors/non_field_errors every time."""
        body = self._valid_body()
        body['rows'][0]['title'] = ''

        with self.assertRaises(SetlistBufferValidationError) as first_capture:
            build_setlist_buffer_from_request(_fake_request(body), viewing_semester=self.semester)
        with self.assertRaises(SetlistBufferValidationError) as second_capture:
            build_setlist_buffer_from_request(_fake_request(body), viewing_semester=self.semester)

        self.assertEqual(first_capture.exception.row_errors, second_capture.exception.row_errors)
        self.assertEqual(first_capture.exception.non_field_errors, second_capture.exception.non_field_errors)

    def test_malformed_length_string_raises_the_same_shape_every_time(self):
        """A body with an unparseable `length` string raises the identical failure shape every time."""
        body = self._valid_body()
        body['rows'][0]['length'] = 'garbage'

        with self.assertRaises(SetlistBufferValidationError) as first_capture:
            build_setlist_buffer_from_request(_fake_request(body), viewing_semester=self.semester)
        with self.assertRaises(SetlistBufferValidationError) as second_capture:
            build_setlist_buffer_from_request(_fake_request(body), viewing_semester=self.semester)

        self.assertEqual(first_capture.exception.row_errors, second_capture.exception.row_errors)

    def test_wrong_semester_id_builds_the_identical_buffer_both_times(self):
        """A body naming a `semester_id` that doesn't match `viewing_semester` still builds identically both times.

        `build_setlist_buffer_from_request()` doesn't itself check
        `semester_id` against `viewing_semester` (that's the caller's
        `WrongViewingSemesterError` territory) — so this case still
        exercises the "one construction path" invariant the same way the
        valid-body case does, just with a Buffer whose `semester_id`
        happens not to match.
        """
        other_semester = SemesterFactory()
        body = self._valid_body()
        body['semester_id'] = other_semester.pk

        first = build_setlist_buffer_from_request(_fake_request(body), viewing_semester=self.semester)
        second = build_setlist_buffer_from_request(_fake_request(body), viewing_semester=self.semester)

        self.assertEqual(first, second)
        self.assertNotEqual(first.semester_id, self.semester.pk)

    def test_stale_semester_updated_at_builds_the_identical_buffer_both_times(self):
        """A body whose `semester_updated_at` is stale still builds identically both times (staleness is `apply_*`'s job)."""
        body = self._valid_body()
        body['semester_updated_at'] = self.semester.updated_at.replace(year=self.semester.updated_at.year - 1).isoformat()

        first = build_setlist_buffer_from_request(_fake_request(body), viewing_semester=self.semester)
        second = build_setlist_buffer_from_request(_fake_request(body), viewing_semester=self.semester)

        self.assertEqual(first, second)


@override_settings(SECURE_SSL_REDIRECT=False)
class LiveEndpointsDelegateToTheSameBuilderTests(TestCase):
    """Driving the two live HTTP endpoints with the identical body proves neither reimplements construction."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one Song."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester, position=1, title='Original', artist='Artist A')

    def test_valid_body_previews_and_saves_agree_on_the_persisted_result(self):
        """Preview's echoed `values` for a valid body match exactly what Save then actually persists."""
        body = {
            'semester_id': self.semester.pk,
            'semester_updated_at': self.semester.updated_at.isoformat(),
            'rows': [
                {'row_key': 'r1', 'song_id': self.song.pk, 'title': 'Renamed', 'artist': 'Artist A', 'length': '4:00', 'notes': 'n'},
            ],
            'deleted_song_ids': [],
        }

        preview_response, preview_envelope = _post_json(self, reverse('api-setlist-preview'), body)
        self.assertEqual(preview_response.status_code, 200)
        self.assertTrue(preview_envelope['ok'])
        echoed_title = preview_envelope['values']['rows'][0]['title']
        echoed_length = preview_envelope['values']['rows'][0]['length']

        save_response, save_envelope = _post_json(self, reverse('api-setlist-save'), body)
        self.assertEqual(save_response.status_code, 200)
        self.assertTrue(save_envelope['ok'])

        self.song.refresh_from_db()
        self.assertEqual(self.song.title, echoed_title)
        from scheduling.fields import format_song_length
        self.assertEqual(format_song_length(self.song.length), echoed_length)

    def test_invalid_body_fails_both_endpoints_with_the_identical_row_errors(self):
        """An invalid body (bad length) fails Preview and Save with the identical `errors` shape."""
        body = {
            'semester_id': self.semester.pk,
            'semester_updated_at': self.semester.updated_at.isoformat(),
            'rows': [
                {'row_key': 'r1', 'song_id': self.song.pk, 'title': 'X', 'artist': 'A', 'length': 'nonsense', 'notes': ''},
            ],
            'deleted_song_ids': [],
        }

        preview_response, preview_envelope = _post_json(self, reverse('api-setlist-preview'), body)
        save_response, save_envelope = _post_json(self, reverse('api-setlist-save'), body)

        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(save_response.status_code, 200)
        self.assertFalse(preview_envelope['ok'])
        self.assertFalse(save_envelope['ok'])
        self.assertEqual(preview_envelope['errors'], save_envelope['errors'])
