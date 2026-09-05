"""`/api/setlist/preview/` and `/api/setlist/save/`: the Setlist edit surface over HTTP (issue #334, ADR 0008)."""

import json

from django.test import TestCase, override_settings
from django.urls import reverse

from scheduling.factories import SemesterFactory, SongFactory
from scheduling.models import Song
from scheduling.tests.preview_helpers import assert_preview_writes_nothing
from scheduling.tests.test_setlist_reorder_add_delete import (
    admin_client,
    member_client,
    select,
)

PASSWORD = 'a-strong-test-password-123'


def _preview_url():
    """Return the Setlist Preview `/api/` endpoint's URL."""
    return reverse('api-setlist-preview')


def _save_url():
    """Return the Setlist Save `/api/` endpoint's URL."""
    return reverse('api-setlist-save')


def _post_json(test_case, url, body):
    """POST `body` (a dict) as a JSON request body and return the parsed response envelope."""
    response = test_case.client.post(url, data=json.dumps(body), content_type='application/json')
    return response, json.loads(response.content)


def _valid_body(semester, rows=None, deleted_song_ids=None):
    """Build a well-formed `/api/setlist/{preview,save}/` request body for `semester`."""
    return {
        'semester_id': semester.pk,
        'semester_updated_at': semester.updated_at.isoformat(),
        'rows': rows if rows is not None else [],
        'deleted_song_ids': deleted_song_ids or [],
    }


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessControlTests(TestCase):
    """Both endpoints gate identically to every other `AdminApiView`/`AdminPreviewApiView`."""

    def setUp(self):
        """Build a Semester so a POST has something to resolve against."""
        self.semester = SemesterFactory()

    def test_anonymous_preview_post_is_401(self):
        """An anonymous POST to Preview answers the documented JSON 401, never a redirect."""
        response = self.client.post(_preview_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_anonymous_save_post_is_401(self):
        """An anonymous POST to Save answers the documented JSON 401, never a redirect."""
        response = self.client.post(_save_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_non_admin_preview_post_is_403(self):
        """A logged-in non-admin's POST to Preview is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.post(_preview_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def test_non_admin_save_post_is_403(self):
        """A logged-in non-admin's POST to Save is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.post(_save_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def test_preview_get_is_not_allowed(self):
        """A GET to Preview is rejected -- it is POST-only."""
        admin_client(self)

        response = self.client.get(_preview_url())

        self.assertEqual(response.status_code, 405)

    def test_save_get_is_not_allowed(self):
        """A GET to Save is rejected -- it is POST-only."""
        admin_client(self)

        response = self.client.get(_save_url())

        self.assertEqual(response.status_code, 405)


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewValidBufferTests(TestCase):
    """A valid Buffer's Preview renders Fallout, echoes `values`, and writes nothing."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with two Songs (one to edit, one to delete)."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester, position=1, title='Original', artist='Artist A')
        self.doomed_song = SongFactory(semester=self.semester, position=2, title='Doomed', artist='Artist B')

    def test_valid_buffer_previews_ok_with_fallout_and_echoed_values_and_writes_nothing(self):
        """A mixed add+edit+delete Buffer (issue #228's acceptance criteria) previews `ok: true` and writes nothing.

        Exercises `assert_preview_writes_nothing()`'s new `json_body=` mode
        with a Buffer containing a creation, a mutation *and* a deletion
        together — per issue #228, a helper exercised only against
        additions proves nothing about the rollback of a delete.
        """
        body = _valid_body(
            self.semester,
            rows=[
                {'row_key': 'r1', 'song_id': self.song.pk, 'title': 'Edited', 'artist': 'Artist A', 'length': '3:30', 'notes': ''},
                {'row_key': 'r2', 'song_id': None, 'title': 'New Song', 'artist': 'New Artist', 'length': '2:15', 'notes': 'fresh'},
            ],
            deleted_song_ids=[self.doomed_song.pk],
        )
        response = assert_preview_writes_nothing(
            self, _preview_url(), models_to_check=[Song], semester=self.semester, json_body=body,
        )
        envelope = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertIn('context', envelope)
        self.assertIsNotNone(envelope['fallout'])
        self.assertEqual(envelope['fallout']['pending_adds'], ['New Song'])
        self.assertEqual(len(envelope['fallout']['pending_deletions']), 1)
        self.assertEqual(envelope['fallout']['pending_deletions'][0]['title'], 'Doomed')
        self.assertIsNotNone(envelope['values'])
        self.assertEqual(envelope['values']['rows'][0]['title'], 'Edited')
        self.assertEqual(envelope['values']['rows'][1]['title'], 'New Song')
        self.assertEqual(envelope['values']['deleted_song_ids'], [self.doomed_song.pk])
        self.assertEqual(envelope['errors'], {})
        self.assertEqual(envelope['non_field_errors'], [])


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewInvalidBufferTests(TestCase):
    """A malformed Buffer previews `ok: false` with per-row errors, and still echoes every submitted value."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one Song."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester, position=1)

    def test_malformed_length_previews_ok_false_with_row_errors_and_still_echoes_values(self):
        """A row with an unparseable `length` string previews HTTP 200, `ok: false`, and echoes the raw submitted rows."""
        body = _valid_body(self.semester, rows=[
            {'row_key': 'bad-row', 'song_id': self.song.pk, 'title': 'T', 'artist': 'A', 'length': 'not-a-length', 'notes': ''},
        ])

        response, envelope = _post_json(self, _preview_url(), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertIn('context', envelope)
        self.assertIsNone(envelope['fallout'])
        self.assertIn('bad-row', envelope['errors'])
        self.assertIn('length', envelope['errors']['bad-row'])
        self.assertIsNotNone(envelope['values'])
        self.assertEqual(envelope['values']['rows'][0]['length'], 'not-a-length')

    def test_missing_title_previews_ok_false_with_a_row_error(self):
        """A row missing `title` previews `ok: false` with a `title` field error keyed by `row_key`."""
        body = _valid_body(self.semester, rows=[
            {'row_key': 'row-x', 'song_id': None, 'title': '', 'artist': 'A', 'length': '3:00', 'notes': ''},
        ])

        response, envelope = _post_json(self, _preview_url(), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertIn('title', envelope['errors']['row-x'])


@override_settings(SECURE_SSL_REDIRECT=False)
class WrongSemesterTests(TestCase):
    """A `semester_id` that doesn't match the viewing Semester hard-fails on both endpoints."""

    def setUp(self):
        """Log in a synthetic admin viewing one Semester, with a second Semester the Buffer will wrongly claim."""
        admin_client(self)
        self.viewing_semester = SemesterFactory()
        self.other_semester = SemesterFactory()
        select(self, self.viewing_semester)

    def test_wrong_semester_id_previews_a_4xx(self):
        """Preview answers a wrong `semester_id` with a 4xx, not a 200 Validation Error."""
        body = _valid_body(self.other_semester)

        response, envelope = _post_json(self, _preview_url(), body)

        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.assertEqual(envelope['error'], 'wrong_semester')

    def test_wrong_semester_id_save_is_a_4xx(self):
        """Save answers a wrong `semester_id` with a 4xx, not a 200 Validation Error."""
        body = _valid_body(self.other_semester)

        response, envelope = _post_json(self, _save_url(), body)

        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.assertEqual(envelope['error'], 'wrong_semester')

    def test_wrong_semester_id_save_writes_nothing(self):
        """A wrong-`semester_id` Save leaves the other Semester's Song count untouched."""
        song = SongFactory(semester=self.other_semester)
        body = _valid_body(self.other_semester, rows=[
            {'row_key': 'r1', 'song_id': song.pk, 'title': 'Changed', 'artist': song.artist, 'length': '3:30', 'notes': ''},
        ])

        self._post_json_and_check_song_unchanged(song, body)

    def _post_json_and_check_song_unchanged(self, song, body):
        """POST `body` to Save and assert `song`'s title didn't change."""
        self.client.post(_save_url(), data=json.dumps(body), content_type='application/json')
        song.refresh_from_db()
        self.assertNotEqual(song.title, 'Changed')


@override_settings(SECURE_SSL_REDIRECT=False)
class StaleSemesterTests(TestCase):
    """A stale `semester_updated_at` is reported, never refused (ADR 0008), differently on Preview vs. Save."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one Song, and build a stamp a year behind reality."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester, position=1)
        self.stale_stamp = self.semester.updated_at.replace(year=self.semester.updated_at.year - 1)

    def _stale_body(self):
        """Build a well-formed Buffer body whose `semester_updated_at` is the stale (year-behind) stamp."""
        return {
            'semester_id': self.semester.pk,
            'semester_updated_at': self.stale_stamp.isoformat(),
            'rows': [
                {'row_key': 'r1', 'song_id': self.song.pk, 'title': 'Edited', 'artist': self.song.artist, 'length': '3:30', 'notes': ''},
            ],
            'deleted_song_ids': [],
        }

    def test_stale_preview_reports_is_stale_true_with_fallout_still_computed(self):
        """Preview against a stale stamp still computes Fallout and reports `is_stale: true`, `ok: true`."""
        response, envelope = _post_json(self, _preview_url(), self._stale_body())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertIsNotNone(envelope['fallout'])
        self.assertTrue(envelope['fallout']['is_stale'])

    def test_stale_save_is_refused_without_corrupting_data(self):
        """Save against a stale stamp reports `ok: false` (not a hard 4xx) and leaves the Song unchanged."""
        response, envelope = _post_json(self, _save_url(), self._stale_body())

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        self.song.refresh_from_db()
        self.assertNotEqual(self.song.title, 'Edited')


@override_settings(SECURE_SSL_REDIRECT=False)
class SaveCommitsTests(TestCase):
    """A valid Save actually persists the Buffer, and never echoes `values`."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one Song."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester, position=1, title='Original')

    def test_valid_save_persists_rows_and_does_not_echo_values(self):
        """A valid Save actually renames the Song in the database and answers with `values: null`."""
        body = _valid_body(self.semester, rows=[
            {'row_key': 'r1', 'song_id': self.song.pk, 'title': 'Renamed', 'artist': self.song.artist, 'length': '3:30', 'notes': ''},
        ])

        response, envelope = _post_json(self, _save_url(), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertIsNone(envelope['values'])
        self.assertIn('context', envelope)
        self.song.refresh_from_db()
        self.assertEqual(self.song.title, 'Renamed')

    def test_invalid_save_does_not_echo_values(self):
        """An invalid Save's failure response also omits `values` (unlike Preview, which echoes on failure)."""
        body = _valid_body(self.semester, rows=[
            {'row_key': 'bad', 'song_id': self.song.pk, 'title': self.song.title, 'artist': self.song.artist, 'length': 'nope', 'notes': ''},
        ])

        response, envelope = _post_json(self, _save_url(), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertIsNone(envelope['values'])
