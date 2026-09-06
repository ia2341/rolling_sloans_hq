"""`/api/schedule/editor/stats/`: the "Randomize Rehearsal Plan" stats panel, recomputed live off an unsaved Buffer (ADR 0008)."""

import json
from datetime import time, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from scheduling.factories import (
    ConflictFactory,
    MembershipFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Rehearsal, RehearsalSong
from scheduling.tests.api_test_helpers import admin_client, member_client, select
from scheduling.tests.preview_helpers import assert_preview_writes_nothing

TOMORROW = timezone.localdate() + timedelta(days=1)
NEXT_WEEK = timezone.localdate() + timedelta(days=7)


def _stats_url():
    """Return the schedule-editor stats `/api/` endpoint's URL."""
    return reverse('api-schedule-editor-stats')


def _post_json(test_case, url, body):
    """POST `body` (a dict) as a JSON request body and return `(response, parsed envelope)`."""
    response = test_case.client.post(url, data=json.dumps(body), content_type='application/json')
    return response, json.loads(response.content)


def _row(rehearsal=None, *, row_key='row-1', date=None, start_time='18:00', end_time=None,
         is_full_setlist=False, running_order=()):
    """Build one well-formed Rehearsal edit row, defaulting from an existing `rehearsal` when given (mirrors `test_schedule_editor_api.py`'s helper)."""
    return {
        'row_key': row_key,
        'rehearsal_id': rehearsal.pk if rehearsal is not None else None,
        'date': (date or (rehearsal.date if rehearsal is not None else TOMORROW)).isoformat(),
        'start_time': start_time,
        'end_time': end_time,
        'is_full_setlist': is_full_setlist,
        'setup_grace_minutes': None,
        'teardown_grace_minutes': None,
        'arrival_buffer_minutes': None,
        'departure_buffer_minutes': None,
        'running_order': list(running_order),
    }


def _body(semester, rows=(), deleted_rehearsal_ids=()):
    """Build a well-formed `/api/schedule/editor/stats/` request body for `semester`."""
    return {
        'semester_id': semester.pk,
        'semester_updated_at': semester.updated_at.isoformat(),
        'rows': list(rows),
        'deleted_rehearsal_ids': list(deleted_rehearsal_ids),
    }


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessControlTests(TestCase):
    """Gates identically to every other `AdminPreviewApiView` (mirrors `test_schedule_editor_api.py`'s own suite)."""

    def setUp(self):
        """Build a Semester so a request has something to resolve against."""
        self.semester = SemesterFactory()

    def test_anonymous_post_is_401(self):
        """An anonymous POST answers the documented JSON 401, never a redirect."""
        response = self.client.post(_stats_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_non_admin_post_is_403(self):
        """A logged-in non-admin's POST is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.post(_stats_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def test_get_is_not_allowed(self):
        """A GET is rejected -- this endpoint is POST-only, like every other Preview surface."""
        admin_client(self)

        response = self.client.get(_stats_url())

        self.assertEqual(response.status_code, 405)


@override_settings(SECURE_SSL_REDIRECT=False)
class StatsShapeTests(TestCase):
    """A valid Buffer previews `ok: true` with the stats panel's whole shape, and writes nothing (ADR 0008)."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one future Rehearsal and two Songs."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(semester=self.semester, date=TOMORROW, start_time=time(18, 0))
        self.busy_song = SongFactory(semester=self.semester, position=1, title='Busy')
        # Alphabetically last among the zero-appearance Songs this test adds, so it's guaranteed
        # to land on the "lowest" side of `_song_slot_totals()`'s title tie-break rather than the
        # "highest" one (both sides here have `total_slot_count == 0`).
        self.quiet_song = SongFactory(semester=self.semester, position=2, title='Zzz Quiet')
        self.rehearsal_song = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.busy_song, order=1)

    def test_a_valid_buffer_reports_the_full_stats_shape_and_writes_nothing(self):
        """A Buffer re-timing the Rehearsal previews live stats and leaves the database untouched."""
        body = _body(self.semester, rows=[_row(self.rehearsal, start_time='19:00')])

        response = assert_preview_writes_nothing(
            self, _stats_url(), models_to_check=[Rehearsal, RehearsalSong], semester=self.semester, json_body=body,
        )
        envelope = json.loads(response.content)

        self.assertTrue(envelope['ok'])
        data = envelope['data']
        self.assertIn('unresolved_conflict_count', data)
        self.assertIn('old_max_wait_minutes', data)
        self.assertIn('new_max_wait_minutes', data)
        self.assertIsInstance(data['highest_slot_songs'], list)
        self.assertIsInstance(data['lowest_slot_songs'], list)
        self.rehearsal.refresh_from_db()
        self.assertEqual(str(self.rehearsal.start_time), '18:00:00')

    def test_song_slot_totals_are_ranked_and_disjoint(self):
        """The busiest Song (with a Running Order row) outranks Songs with none, and the two lists never share a Song.

        Needs more than 3 Songs total: with 3 or fewer, `highest_slot_songs`
        alone already covers every Song, per `compute_schedule_editor_live_stats()`'s
        disjointness rule, leaving nothing distinct for `lowest_slot_songs`
        to report.
        """
        for position in range(3, 6):
            SongFactory(semester=self.semester, position=position, title=f'Silent {position}')
        body = _body(self.semester, rows=[_row(
            self.rehearsal, end_time=self.rehearsal.end_time.isoformat(timespec='minutes'),
            running_order=[{'rehearsal_song_id': self.rehearsal_song.pk, 'song_id': self.busy_song.pk, 'slot_count': 1}],
        )])

        _response, envelope = _post_json(self, _stats_url(), body)

        data = envelope['data']
        highest_ids = {entry['song_id'] for entry in data['highest_slot_songs']}
        lowest_ids = {entry['song_id'] for entry in data['lowest_slot_songs']}
        self.assertIn(self.busy_song.pk, highest_ids)
        self.assertIn(self.quiet_song.pk, lowest_ids)
        self.assertEqual(highest_ids & lowest_ids, set())

    def test_an_unresolved_conflict_overlapping_the_running_order_is_counted(self):
        """A Person assigned to the Song, with a full Conflict against the Rehearsal, counts toward `unresolved_conflict_count`."""
        role = RoleFactory()
        membership = MembershipFactory(semester=self.semester)
        SongRoleAssignmentFactory(song=self.busy_song, role=role, person=membership.person)
        ConflictFactory(rehearsal=self.rehearsal, person=membership.person, type='full_conflict')
        body = _body(self.semester, rows=[_row(
            self.rehearsal, end_time=self.rehearsal.end_time.isoformat(timespec='minutes'),
            running_order=[{'rehearsal_song_id': self.rehearsal_song.pk, 'song_id': self.busy_song.pk, 'slot_count': 1}],
        )])

        _response, envelope = _post_json(self, _stats_url(), body)

        self.assertGreaterEqual(envelope['data']['unresolved_conflict_count'], 1)


@override_settings(SECURE_SSL_REDIRECT=False)
class WrongSemesterTests(TestCase):
    """A `semester_id` that doesn't match the viewing Semester hard-fails, mirroring the Preview/Save endpoints."""

    def setUp(self):
        """Log in a synthetic admin viewing one Semester, with a second Semester the Buffer will wrongly claim."""
        admin_client(self)
        self.viewing_semester = SemesterFactory()
        self.other_semester = SemesterFactory()
        select(self, self.viewing_semester)

    def test_wrong_semester_id_is_a_4xx(self):
        """Stats answers a wrong `semester_id` with a 4xx, not a 200 Validation Error."""
        response, envelope = _post_json(self, _stats_url(), _body(self.other_semester))

        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.assertEqual(envelope['error'], 'wrong_semester')


@override_settings(SECURE_SSL_REDIRECT=False)
class NamedRefusalTests(TestCase):
    """A row that `apply_rehearsal_edits()` itself refuses is reported `ok: false`, never a stats payload."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one future Rehearsal."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(semester=self.semester, date=TOMORROW, start_time=time(18, 0))

    def test_a_past_dated_row_is_refused_and_writes_nothing(self):
        """A row dated in the past is refused (`ok: false`) rather than crashing or silently computing stale stats."""
        yesterday = timezone.localdate() - timedelta(days=1)
        body = _body(self.semester, rows=[_row(self.rehearsal, date=yesterday)])

        _response, envelope = _post_json(self, _stats_url(), body)

        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
