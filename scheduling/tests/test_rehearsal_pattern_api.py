"""`/api/schedule/editor/pattern/save/` and `/api/schedule/editor/generate/diff/` over HTTP (issue #337, #222)."""

import json
from datetime import timedelta

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
from scheduling.models import RehearsalPattern, RehearsalTime
from scheduling.tests.api_test_helpers import (
    admin_client,
    member_client,
    select,
)

TOMORROW = timezone.localdate() + timedelta(days=1)


def _pattern_save_url():
    """Return the Pattern-save `/api/` endpoint's URL."""
    return reverse('api-schedule-editor-pattern-save')


def _diff_url():
    """Return the generation-diff `/api/` endpoint's URL."""
    return reverse('api-schedule-editor-generate-diff')


def _post_json(test_case, url, body):
    """POST `body` (a dict) as a JSON request body and return `(response, parsed envelope)`."""
    response = test_case.client.post(url, data=json.dumps(body), content_type='application/json')
    return response, json.loads(response.content)


def _pattern_body(start_date, end_date, rehearsal_times=(), skip_dates=()):
    """Build a well-formed Pattern-editor request body."""
    return {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'rehearsal_times': list(rehearsal_times),
        'skip_dates': list(skip_dates),
    }


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessControlTests(TestCase):
    """Both routes gate identically to every other `AdminApiView`."""

    def setUp(self):
        """Build a Semester so a request has something to resolve against."""
        self.semester = SemesterFactory()

    def test_anonymous_pattern_save_is_401(self):
        """An anonymous POST to Pattern-save answers the documented JSON 401, never a redirect."""
        response = self.client.post(_pattern_save_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_anonymous_diff_is_401(self):
        """An anonymous POST to the generation diff answers the documented JSON 401, never a redirect."""
        response = self.client.post(_diff_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_non_admin_pattern_save_is_403(self):
        """A logged-in non-admin's POST to Pattern-save is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.post(_pattern_save_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def test_non_admin_diff_is_403(self):
        """A logged-in non-admin's POST to the generation diff is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.post(_diff_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
class PatternSaveTests(TestCase):
    """`RehearsalPatternSaveApiView` persists the submitted Pattern wholesale, or reports a collision."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with no saved Pattern yet."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)

    def test_valid_pattern_saves_rehearsal_times_and_skip_dates(self):
        """A well-formed Pattern persists its Rehearsal Times and Skip Dates onto the Semester's one RehearsalPattern."""
        body = _pattern_body(
            TOMORROW, TOMORROW + timedelta(days=90),
            rehearsal_times=[{'day_of_week': 2, 'start_time': '19:00', 'end_time': '21:00'}],
            skip_dates=[{'start_date': (TOMORROW + timedelta(days=10)).isoformat(), 'end_date': None}],
        )

        response, envelope = _post_json(self, _pattern_save_url(), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        pattern = RehearsalPattern.objects.get(semester=self.semester)
        self.assertEqual(pattern.rehearsal_times.count(), 1)
        self.assertEqual(pattern.skip_dates.count(), 1)

    def test_two_rehearsal_times_on_the_same_weekday_are_refused_naming_the_day(self):
        """Two Rehearsal Times sharing a day-of-week are refused, naming the colliding day (issue #222 user story 28)."""
        body = _pattern_body(
            TOMORROW, TOMORROW + timedelta(days=90),
            rehearsal_times=[
                {'day_of_week': 2, 'start_time': '19:00', 'end_time': '21:00'},
                {'day_of_week': 2, 'start_time': '10:00', 'end_time': '12:00'},
            ],
        )

        _response, envelope = _post_json(self, _pattern_save_url(), body)

        self.assertFalse(envelope['ok'])
        self.assertTrue(any('Wednesday' in message for message in envelope['non_field_errors']))
        self.assertFalse(RehearsalPattern.objects.filter(semester=self.semester).exists())

    def test_re_saving_replaces_rehearsal_times_wholesale(self):
        """Saving a Pattern a second time with different Rehearsal Times replaces the first set entirely."""
        first = _pattern_body(
            TOMORROW, TOMORROW + timedelta(days=90),
            rehearsal_times=[{'day_of_week': 2, 'start_time': '19:00', 'end_time': '21:00'}],
        )
        _post_json(self, _pattern_save_url(), first)
        second = _pattern_body(
            TOMORROW, TOMORROW + timedelta(days=90),
            rehearsal_times=[{'day_of_week': 3, 'start_time': '19:00', 'end_time': '21:00'}],
        )

        _post_json(self, _pattern_save_url(), second)

        pattern = RehearsalPattern.objects.get(semester=self.semester)
        self.assertEqual(list(pattern.rehearsal_times.values_list('day_of_week', flat=True)), [RehearsalTime.THURSDAY])

    def test_pattern_save_writes_no_rehearsal(self):
        """Saving a Pattern writes no Rehearsal at all — it is input history with no downstream authority."""
        from scheduling.models import Rehearsal

        body = _pattern_body(
            TOMORROW, TOMORROW + timedelta(days=90),
            rehearsal_times=[{'day_of_week': 2, 'start_time': '19:00', 'end_time': '21:00'}],
        )

        _post_json(self, _pattern_save_url(), body)

        self.assertEqual(Rehearsal.objects.filter(semester=self.semester).count(), 0)


@override_settings(SECURE_SSL_REDIRECT=False)
class GenerationDiffTests(TestCase):
    """`RehearsalGenerationDiffApiView` computes the four-bucket diff without writing anything."""

    def setUp(self):
        """Log in a synthetic admin against an otherwise-empty Semester."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)

    def test_first_run_produces_only_creates(self):
        """A first-ever run on a Semester with no Rehearsals lands every produced date in `creates`."""
        body = _pattern_body(
            TOMORROW, TOMORROW + timedelta(days=13),
            rehearsal_times=[{'day_of_week': TOMORROW.weekday(), 'start_time': '19:00', 'end_time': '21:00'}],
        )

        response, envelope = _post_json(self, _diff_url(), body)

        self.assertEqual(response.status_code, 200)
        self.assertIn('context', envelope)
        self.assertGreater(len(envelope['data']['creates']), 0)
        self.assertEqual(envelope['data']['keeps'], [])
        self.assertEqual(envelope['data']['retimes'], [])
        self.assertEqual(envelope['data']['orphans'], [])

    def test_the_diff_never_produces_a_bucket_item_dated_before_today(self):
        """Even a Pattern whose stored start_date is in the past clamps every bucket to today or later."""
        yesterday = timezone.localdate() - timedelta(days=1)
        body = _pattern_body(
            yesterday, TOMORROW + timedelta(days=13),
            rehearsal_times=[{'day_of_week': TOMORROW.weekday(), 'start_time': '19:00', 'end_time': '21:00'}],
        )

        _response, envelope = _post_json(self, _diff_url(), body)

        for create in envelope['data']['creates']:
            self.assertGreaterEqual(create['date'], timezone.localdate().isoformat())

    def test_an_orphan_carrying_recordings_comes_back_with_its_tick_disabled(self):
        """An existing Rehearsal the Pattern no longer produces, carrying a Recording, reports `delete_disabled: true`."""
        song = SongFactory(semester=self.semester, position=1)
        orphan_date = TOMORROW + timedelta(days=2)
        rehearsal = RehearsalFactory(semester=self.semester, date=orphan_date)
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        RecordingFactory(rehearsal_song=rehearsal_song)
        # A Pattern whose only Rehearsal Time falls on a different weekday than `orphan_date`,
        # so the existing Rehearsal is produced by nothing and becomes an Orphan.
        other_weekday = (orphan_date.weekday() + 1) % 7
        body = _pattern_body(
            TOMORROW, TOMORROW + timedelta(days=13),
            rehearsal_times=[{'day_of_week': other_weekday, 'start_time': '19:00', 'end_time': '21:00'}],
        )

        _response, envelope = _post_json(self, _diff_url(), body)

        orphans = envelope['data']['orphans']
        matching = [o for o in orphans if o['rehearsal_id'] == rehearsal.pk]
        self.assertEqual(len(matching), 1)
        self.assertTrue(matching[0]['delete_disabled'])
        self.assertEqual(matching[0]['recording_count'], 1)

    def test_a_weekday_collision_in_the_diff_body_is_refused(self):
        """The generation-diff endpoint shares the Pattern-save endpoint's day-of-week collision check."""
        body = _pattern_body(
            TOMORROW, TOMORROW + timedelta(days=90),
            rehearsal_times=[
                {'day_of_week': 2, 'start_time': '19:00', 'end_time': '21:00'},
                {'day_of_week': 2, 'start_time': '10:00', 'end_time': '12:00'},
            ],
        )

        response = self.client.post(_diff_url(), data=json.dumps(body), content_type='application/json')

        self.assertEqual(response.status_code, 400)

    def test_diff_writes_no_rehearsal(self):
        """The generation diff is a pure read — it writes no Rehearsal, Pattern, or anything else."""
        from scheduling.models import Rehearsal

        body = _pattern_body(
            TOMORROW, TOMORROW + timedelta(days=13),
            rehearsal_times=[{'day_of_week': TOMORROW.weekday(), 'start_time': '19:00', 'end_time': '21:00'}],
        )

        _post_json(self, _diff_url(), body)

        self.assertEqual(Rehearsal.objects.filter(semester=self.semester).count(), 0)
        self.assertFalse(RehearsalPattern.objects.filter(semester=self.semester).exists())

    def test_date_range_narrows_the_run_without_touching_the_stored_pattern(self):
        """A `date_range` override narrows a single run's bucket dates without persisting anything (this endpoint saves no Pattern at all)."""
        narrow_end = TOMORROW + timedelta(days=1)
        body = _pattern_body(
            TOMORROW, TOMORROW + timedelta(days=90),
            rehearsal_times=[{'day_of_week': TOMORROW.weekday(), 'start_time': '19:00', 'end_time': '21:00'}],
        )
        body['date_range'] = {'start_date': TOMORROW.isoformat(), 'end_date': narrow_end.isoformat()}

        _response, envelope = _post_json(self, _diff_url(), body)

        for create in envelope['data']['creates']:
            self.assertLessEqual(create['date'], narrow_end.isoformat())
