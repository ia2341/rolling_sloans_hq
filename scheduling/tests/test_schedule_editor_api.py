"""`/api/schedule/editor/` and its Preview/Save: the rehearsal editor's read+write surface over HTTP (issue #337, ADR 0008)."""

import json
from datetime import time, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from scheduling.factories import (
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.models import Rehearsal, RehearsalSong
from scheduling.tests.api_test_helpers import (
    admin_client,
    member_client,
    select,
)
from scheduling.tests.preview_helpers import assert_preview_writes_nothing

TOMORROW = timezone.localdate() + timedelta(days=1)
NEXT_WEEK = timezone.localdate() + timedelta(days=7)
YESTERDAY = timezone.localdate() - timedelta(days=1)


def _editor_url():
    """Return the schedule-editor read `/api/` endpoint's URL."""
    return reverse('api-schedule-editor')


def _preview_url():
    """Return the schedule-editor Preview `/api/` endpoint's URL."""
    return reverse('api-schedule-editor-preview')


def _save_url():
    """Return the schedule-editor Save `/api/` endpoint's URL."""
    return reverse('api-schedule-editor-save')


def _post_json(test_case, url, body):
    """POST `body` (a dict) as a JSON request body and return `(response, parsed envelope)`."""
    response = test_case.client.post(url, data=json.dumps(body), content_type='application/json')
    return response, json.loads(response.content)


def _row(rehearsal=None, *, row_key='row-1', date=None, start_time='18:00', end_time=None,
         is_full_setlist=False, running_order=()):
    """Build one well-formed Rehearsal edit row, defaulting from an existing `rehearsal` when given."""
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
    """Build a well-formed `/api/schedule/editor/{preview,save}/` request body for `semester`."""
    return {
        'semester_id': semester.pk,
        'semester_updated_at': semester.updated_at.isoformat(),
        'rows': list(rows),
        'deleted_rehearsal_ids': list(deleted_rehearsal_ids),
    }


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessControlTests(TestCase):
    """Every route here gates identically to every other `AdminApiView`/`AdminPreviewApiView`."""

    def setUp(self):
        """Build a Semester so a request has something to resolve against."""
        self.semester = SemesterFactory()

    def test_anonymous_get_editor_is_401(self):
        """An anonymous GET to the editor read answers the documented JSON 401, never a redirect."""
        response = self.client.get(_editor_url())

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

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

    def test_non_admin_get_editor_is_403(self):
        """A logged-in non-admin's GET to the editor read is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.get(_editor_url())

        self.assertEqual(response.status_code, 403)

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

    def test_editor_post_is_not_allowed(self):
        """A POST to the editor read is rejected -- it is GET-only."""
        admin_client(self)

        response = self.client.post(_editor_url())

        self.assertEqual(response.status_code, 405)


@override_settings(SECURE_SSL_REDIRECT=False)
class ReadShapeTests(TestCase):
    """`GET /api/schedule/editor/` carries every future Rehearsal, its Running Order, and the past-Rehearsal disclosure."""

    def setUp(self):
        """Log in a synthetic admin viewing a Semester with one future and one past Rehearsal."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester, position=1, title='Anthem')
        self.future_rehearsal = RehearsalFactory(semester=self.semester, date=TOMORROW)
        self.rehearsal_song = RehearsalSongFactory(rehearsal=self.future_rehearsal, song=self.song, order=1)
        self.past_rehearsal = RehearsalFactory(semester=self.semester, date=YESTERDAY)

    def test_future_rehearsal_carries_its_running_order(self):
        """The future Rehearsal's row carries its Running Order, with the Song's title and derived slot times."""
        response = self.client.get(_editor_url())
        envelope = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        rehearsal_payload = next(r for r in envelope['data']['rehearsals'] if r['id'] == self.future_rehearsal.pk)
        self.assertEqual(len(rehearsal_payload['running_order']), 1)
        row = rehearsal_payload['running_order'][0]
        self.assertEqual(row['song_title'], 'Anthem')
        self.assertEqual(row['rehearsal_song_id'], self.rehearsal_song.pk)
        self.assertFalse(row['is_pinned'])
        self.assertEqual(row['pinned_reasons'], [])

    def test_past_rehearsal_appears_only_in_the_read_only_list(self):
        """The past Rehearsal appears in `past_rehearsals`, never in the editable `rehearsals` list."""
        response = self.client.get(_editor_url())
        envelope = json.loads(response.content)

        editable_ids = [r['id'] for r in envelope['data']['rehearsals']]
        past_ids = [r['id'] for r in envelope['data']['past_rehearsals']]
        self.assertNotIn(self.past_rehearsal.pk, editable_ids)
        self.assertIn(self.past_rehearsal.pk, past_ids)

    def test_a_recording_bearing_row_is_pinned_with_its_reason(self):
        """A Running Order row carrying a Recording reports `is_pinned: true` with `recording` among its reasons."""
        RecordingFactory(rehearsal_song=self.rehearsal_song)

        response = self.client.get(_editor_url())
        envelope = json.loads(response.content)

        rehearsal_payload = next(r for r in envelope['data']['rehearsals'] if r['id'] == self.future_rehearsal.pk)
        row = rehearsal_payload['running_order'][0]
        self.assertTrue(row['is_pinned'])
        self.assertIn('recording', row['pinned_reasons'])

    def test_a_hand_raised_slot_count_row_is_pinned_with_its_reason(self):
        """A Running Order row with `slot_count > 1` reports `is_pinned: true` with `manual_slot_count` among its reasons."""
        self.rehearsal_song.slot_count = 2
        self.rehearsal_song.save()

        response = self.client.get(_editor_url())
        envelope = json.loads(response.content)

        rehearsal_payload = next(r for r in envelope['data']['rehearsals'] if r['id'] == self.future_rehearsal.pk)
        row = rehearsal_payload['running_order'][0]
        self.assertTrue(row['is_pinned'])
        self.assertIn('manual_slot_count', row['pinned_reasons'])

    def test_setlist_songs_and_semester_defaults_are_carried(self):
        """The payload carries the Semester's own setlist (for the picker) and its timing/slot defaults."""
        response = self.client.get(_editor_url())
        envelope = json.loads(response.content)

        self.assertEqual([s['title'] for s in envelope['data']['setlist_songs']], ['Anthem'])
        self.assertEqual(envelope['data']['semester_defaults']['default_song_slot_count'], 5)

    def test_no_semester_returns_the_empty_shape(self):
        """`serialize_schedule_editor(None)` returns its documented empty shape rather than erroring.

        Exercised at the serializer level rather than through the view:
        an admin viewing this route always resolves *some* Semester once
        one exists (ADR 0010's "show the newest-created" admin fallback),
        so reaching a genuinely `None` viewing Semester through a live
        request needs zero Semesters to ever have been created at all —
        harder to arrange through the HTTP seam than through the
        serializer directly.
        """
        from scheduling.serializers import serialize_schedule_editor

        data = serialize_schedule_editor(None)

        self.assertEqual(data, {
            'semester_name': None, 'rehearsals': [], 'past_rehearsals': [],
            'setlist_songs': [], 'semester_defaults': None, 'pattern': None,
        })


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewValidBufferTests(TestCase):
    """A valid mixed Buffer (creation, mutation, and deletion) previews `ok: true` and writes nothing."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with two future Rehearsals (one to edit, one to delete)."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester, position=1)
        self.kept_rehearsal = RehearsalFactory(semester=self.semester, date=TOMORROW, start_time=time(18, 0))
        self.doomed_rehearsal = RehearsalFactory(semester=self.semester, date=NEXT_WEEK)

    def test_mixed_buffer_previews_ok_with_fallout_and_echoed_values_and_writes_nothing(self):
        """A Buffer that re-times one Rehearsal, adds a brand-new one, and deletes a third previews cleanly and writes nothing."""
        body = _body(
            self.semester,
            rows=[
                _row(self.kept_rehearsal, start_time='19:00'),
                _row(None, row_key='new-row', date=self.kept_rehearsal.date + timedelta(days=1)),
            ],
            deleted_rehearsal_ids=[self.doomed_rehearsal.pk],
        )

        response = assert_preview_writes_nothing(
            self, _preview_url(),
            models_to_check=[Rehearsal, RehearsalSong], semester=self.semester, json_body=body,
        )
        envelope = json.loads(response.content)

        self.assertTrue(envelope['ok'])
        self.assertIn('context', envelope)
        self.assertIsNotNone(envelope['fallout'])
        self.assertFalse(envelope['fallout']['is_blocked'])
        self.assertIsNotNone(envelope['values'])
        self.assertEqual(len(envelope['values']['rows']), 2)
        self.assertEqual(envelope['values']['deleted_rehearsal_ids'], [self.doomed_rehearsal.pk])
        self.assertEqual(envelope['errors'], {})

    def test_a_deleted_rehearsal_carrying_recordings_previews_a_doomed_group(self):
        """A Buffer deleting a Rehearsal with Recordings previews a `doomed_recording_groups` entry naming no Conflict, name or reason."""
        rehearsal_song = RehearsalSongFactory(rehearsal=self.doomed_rehearsal, song=self.song, order=1)
        RecordingFactory(rehearsal_song=rehearsal_song)
        body = _body(
            self.semester, rows=[_row(self.kept_rehearsal)], deleted_rehearsal_ids=[self.doomed_rehearsal.pk],
        )

        _response, envelope = _post_json(self, _preview_url(), body)

        self.assertTrue(envelope['ok'])
        groups = envelope['fallout']['doomed_recording_groups']
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['recording_count'], 1)
        self.assertEqual(set(groups[0].keys()), {'label', 'recording_count', 'uploader_count'})


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewInvalidBufferTests(TestCase):
    """A malformed Buffer previews `ok: false` with per-row errors, and still echoes every submitted value."""

    def setUp(self):
        """Log in a synthetic admin against a Semester."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)

    def test_missing_date_previews_ok_false_with_a_row_error(self):
        """A row missing `date` previews `ok: false` with a `date` field error keyed by `row_key`."""
        body = _body(self.semester, rows=[
            {
                'row_key': 'bad-row', 'rehearsal_id': None, 'date': '', 'start_time': '18:00', 'end_time': None,
                'is_full_setlist': False, 'setup_grace_minutes': None, 'teardown_grace_minutes': None,
                'arrival_buffer_minutes': None, 'departure_buffer_minutes': None, 'running_order': [],
            },
        ])

        response, envelope = _post_json(self, _preview_url(), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertIn('date', envelope['errors']['bad-row'])
        self.assertIsNotNone(envelope['values'])


@override_settings(SECURE_SSL_REDIRECT=False)
class WrongSemesterTests(TestCase):
    """A `semester_id` that doesn't match the viewing Semester hard-fails on both endpoints (issue #337, mirrors #334)."""

    def setUp(self):
        """Log in a synthetic admin viewing one Semester, with a second Semester the Buffer will wrongly claim."""
        admin_client(self)
        self.viewing_semester = SemesterFactory()
        self.other_semester = SemesterFactory()
        select(self, self.viewing_semester)

    def test_wrong_semester_id_previews_a_4xx(self):
        """Preview answers a wrong `semester_id` with a 4xx, not a 200 Validation Error."""
        response, envelope = _post_json(self, _preview_url(), _body(self.other_semester))

        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.assertEqual(envelope['error'], 'wrong_semester')

    def test_wrong_semester_id_save_writes_nothing(self):
        """A wrong-`semester_id` Save leaves the other Semester's Rehearsal count untouched."""
        rehearsal = RehearsalFactory(semester=self.other_semester, date=TOMORROW, start_time=time(18, 0))
        count_before = Rehearsal.objects.filter(semester=self.other_semester).count()
        body = _body(self.other_semester, rows=[_row(rehearsal, start_time='20:00')])

        self.client.post(_save_url(), data=json.dumps(body), content_type='application/json')

        self.assertEqual(Rehearsal.objects.filter(semester=self.other_semester).count(), count_before)


@override_settings(SECURE_SSL_REDIRECT=False)
class StaleSemesterTests(TestCase):
    """A stale `semester_updated_at` is reported, never refused (ADR 0008), differently on Preview vs. Save."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one Rehearsal, and build a stamp a year behind reality."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(semester=self.semester, date=TOMORROW, start_time=time(18, 0))
        self.stale_stamp = self.semester.updated_at.replace(year=self.semester.updated_at.year - 1)

    def _stale_body(self):
        """Build a well-formed Buffer body whose `semester_updated_at` is the stale (year-behind) stamp."""
        body = _body(self.semester, rows=[_row(self.rehearsal, start_time='20:00')])
        body['semester_updated_at'] = self.stale_stamp.isoformat()
        return body

    def test_stale_preview_reports_is_stale_true_with_fallout_still_computed(self):
        """Preview against a stale stamp still computes Fallout and reports `is_stale: true`, `ok: true`."""
        response, envelope = _post_json(self, _preview_url(), self._stale_body())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertTrue(envelope['fallout']['is_stale'])

    def test_stale_save_is_refused_without_corrupting_data(self):
        """Save against a stale stamp reports `ok: false` (not a hard 4xx) and leaves the Rehearsal unchanged."""
        response, envelope = _post_json(self, _save_url(), self._stale_body())

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        self.rehearsal.refresh_from_db()
        self.assertEqual(str(self.rehearsal.start_time), '18:00:00')


@override_settings(SECURE_SSL_REDIRECT=False)
class NamedRefusalTests(TestCase):
    """The named backend cases this ticket owns (issue #337's Testing Decisions section)."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one future Rehearsal and one Song."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester, position=1)
        self.rehearsal = RehearsalFactory(semester=self.semester, date=TOMORROW, start_time=time(18, 0))

    def test_a_past_dated_row_is_refused_as_a_validation_error_and_writes_nothing(self):
        """A row dated in the past is refused (`ok: false`) on Save, and the Rehearsal table is untouched."""
        count_before = Rehearsal.objects.count()
        body = _body(self.semester, rows=[_row(self.rehearsal, date=YESTERDAY)])

        _response, envelope = _post_json(self, _save_url(), body)

        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        self.assertEqual(Rehearsal.objects.count(), count_before)

    def test_a_running_order_on_a_dress_flagged_row_is_refused(self):
        """A Running Order attached to a row flagged Dress is refused (ADR 0003)."""
        body = _body(self.semester, rows=[
            _row(
                self.rehearsal, is_full_setlist=True,
                running_order=[{'rehearsal_song_id': None, 'song_id': self.song.pk, 'slot_count': 1}],
            ),
        ])

        _response, envelope = _post_json(self, _save_url(), body)

        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        self.assertFalse(RehearsalSong.objects.filter(rehearsal=self.rehearsal).exists())

    def test_slot_counts_over_the_semester_budget_are_refused(self):
        """A Running Order whose slot_counts sum past `default_song_slot_count` (5) is refused."""
        songs = [SongFactory(semester=self.semester, position=n) for n in range(2, 4)]
        body = _body(self.semester, rows=[
            _row(self.rehearsal, running_order=[
                {'rehearsal_song_id': None, 'song_id': self.song.pk, 'slot_count': 3},
                {'rehearsal_song_id': None, 'song_id': songs[0].pk, 'slot_count': 3},
            ]),
        ])

        _response, envelope = _post_json(self, _save_url(), body)

        self.assertFalse(envelope['ok'])
        self.assertFalse(RehearsalSong.objects.filter(rehearsal=self.rehearsal).exists())

    def test_a_rehearsal_left_with_no_songs_is_fallout_not_a_refusal(self):
        """A non-Dress Rehearsal saved with an empty Running Order previews as quiet Fallout, not a block."""
        rehearsal_song = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song, order=1)
        body = _body(self.semester, rows=[_row(self.rehearsal, running_order=[])])

        _response, envelope = _post_json(self, _preview_url(), body)

        self.assertTrue(envelope['ok'])
        self.assertFalse(envelope['fallout']['is_blocked'])
        self.assertTrue(any('no songs' in line for line in envelope['fallout']['quiet']))
        # Sanity: the row existed with a song before this Preview (which writes nothing).
        self.assertTrue(RehearsalSong.objects.filter(pk=rehearsal_song.pk).exists())

    def test_nothing_pending_valid_save_actually_commits(self):
        """A valid Save actually re-times the Rehearsal in the database."""
        body = _body(self.semester, rows=[_row(self.rehearsal, start_time='20:00')])

        _response, envelope = _post_json(self, _save_url(), body)

        self.assertTrue(envelope['ok'])
        self.assertIsNone(envelope['values'])
        self.rehearsal.refresh_from_db()
        self.assertEqual(str(self.rehearsal.start_time), '20:00:00')
