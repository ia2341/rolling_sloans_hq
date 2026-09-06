"""The mandatory invariant: preview and save can never construct a Rehearsal edit Buffer differently (issue #337, ADR 0008).

Mirrors `scheduling/tests/test_preview_save_buffer_identity.py`'s shape
for the Setlist surface: `build_rehearsal_buffer_from_request()` is the
ONE place a submitted JSON body becomes a `RehearsalEditBuffer`.
"""

import json
from datetime import timedelta

from django.http import HttpRequest
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from scheduling.api_builders import (
    RehearsalBufferValidationError,
    build_rehearsal_buffer_from_request,
)
from scheduling.factories import RehearsalFactory, SemesterFactory
from scheduling.tests.api_test_helpers import admin_client, select

TOMORROW = timezone.localdate() + timedelta(days=1)


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
    """Calling `build_rehearsal_buffer_from_request()` twice on the identical body always yields the identical result."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one future Rehearsal."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(semester=self.semester, date=TOMORROW)

    def _valid_body(self):
        """Return a well-formed request body for `self.semester`."""
        return {
            'semester_id': self.semester.pk,
            'semester_updated_at': self.semester.updated_at.isoformat(),
            'rows': [
                {
                    'row_key': 'r1', 'rehearsal_id': self.rehearsal.pk, 'date': self.rehearsal.date.isoformat(),
                    'start_time': '19:00', 'end_time': None, 'is_full_setlist': False,
                    'setup_grace_minutes': None, 'teardown_grace_minutes': None,
                    'arrival_buffer_minutes': None, 'departure_buffer_minutes': None, 'running_order': [],
                },
            ],
            'deleted_rehearsal_ids': [],
        }

    def test_valid_body_builds_an_identical_buffer_every_time(self):
        """A well-formed body builds byte-for-byte identical (frozen-dataclass-equal) Buffers on repeated calls."""
        body = self._valid_body()

        first = build_rehearsal_buffer_from_request(_fake_request(body), viewing_semester=self.semester)
        second = build_rehearsal_buffer_from_request(_fake_request(body), viewing_semester=self.semester)

        self.assertEqual(first, second)

    def test_per_field_validation_failure_raises_the_same_shape_every_time(self):
        """A body with a per-field failure (missing date) raises the identical row_errors/non_field_errors every time."""
        body = self._valid_body()
        body['rows'][0]['date'] = ''

        with self.assertRaises(RehearsalBufferValidationError) as first_capture:
            build_rehearsal_buffer_from_request(_fake_request(body), viewing_semester=self.semester)
        with self.assertRaises(RehearsalBufferValidationError) as second_capture:
            build_rehearsal_buffer_from_request(_fake_request(body), viewing_semester=self.semester)

        self.assertEqual(first_capture.exception.row_errors, second_capture.exception.row_errors)
        self.assertEqual(first_capture.exception.non_field_errors, second_capture.exception.non_field_errors)

    def test_wrong_semester_id_builds_the_identical_buffer_both_times(self):
        """A body naming a `semester_id` that doesn't match `viewing_semester` still builds identically both times."""
        other_semester = SemesterFactory()
        body = self._valid_body()
        body['semester_id'] = other_semester.pk

        first = build_rehearsal_buffer_from_request(_fake_request(body), viewing_semester=self.semester)
        second = build_rehearsal_buffer_from_request(_fake_request(body), viewing_semester=self.semester)

        self.assertEqual(first, second)
        self.assertNotEqual(first.semester_id, self.semester.pk)

    def test_stale_semester_updated_at_builds_the_identical_buffer_both_times(self):
        """A body whose `semester_updated_at` is stale still builds identically both times (staleness is `apply_*`'s job)."""
        body = self._valid_body()
        body['semester_updated_at'] = self.semester.updated_at.replace(year=self.semester.updated_at.year - 1).isoformat()

        first = build_rehearsal_buffer_from_request(_fake_request(body), viewing_semester=self.semester)
        second = build_rehearsal_buffer_from_request(_fake_request(body), viewing_semester=self.semester)

        self.assertEqual(first, second)


@override_settings(SECURE_SSL_REDIRECT=False)
class LiveEndpointsDelegateToTheSameBuilderTests(TestCase):
    """Driving the two live HTTP endpoints with the identical body proves neither reimplements construction."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one future Rehearsal."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(semester=self.semester, date=TOMORROW)

    def test_valid_body_previews_and_saves_agree_on_the_persisted_result(self):
        """Preview's echoed `values` for a valid body match exactly what Save then actually persists."""
        body = {
            'semester_id': self.semester.pk,
            'semester_updated_at': self.semester.updated_at.isoformat(),
            'rows': [
                {
                    'row_key': 'r1', 'rehearsal_id': self.rehearsal.pk, 'date': self.rehearsal.date.isoformat(),
                    'start_time': '20:00', 'end_time': None, 'is_full_setlist': False,
                    'setup_grace_minutes': None, 'teardown_grace_minutes': None,
                    'arrival_buffer_minutes': None, 'departure_buffer_minutes': None, 'running_order': [],
                },
            ],
            'deleted_rehearsal_ids': [],
        }

        preview_response, preview_envelope = _post_json(self, reverse('api-schedule-editor-preview'), body)
        self.assertEqual(preview_response.status_code, 200)
        self.assertTrue(preview_envelope['ok'])
        echoed_start_time = preview_envelope['values']['rows'][0]['start_time']

        save_response, save_envelope = _post_json(self, reverse('api-schedule-editor-save'), body)
        self.assertEqual(save_response.status_code, 200)
        self.assertTrue(save_envelope['ok'])

        self.rehearsal.refresh_from_db()
        self.assertEqual(self.rehearsal.start_time.isoformat(), echoed_start_time)

    def test_invalid_body_fails_both_endpoints_with_the_identical_row_errors(self):
        """An invalid body (missing date) fails Preview and Save with the identical `errors` shape."""
        body = {
            'semester_id': self.semester.pk,
            'semester_updated_at': self.semester.updated_at.isoformat(),
            'rows': [
                {
                    'row_key': 'r1', 'rehearsal_id': self.rehearsal.pk, 'date': '', 'start_time': '20:00',
                    'end_time': None, 'is_full_setlist': False, 'setup_grace_minutes': None,
                    'teardown_grace_minutes': None, 'arrival_buffer_minutes': None,
                    'departure_buffer_minutes': None, 'running_order': [],
                },
            ],
            'deleted_rehearsal_ids': [],
        }

        preview_response, preview_envelope = _post_json(self, reverse('api-schedule-editor-preview'), body)
        save_response, save_envelope = _post_json(self, reverse('api-schedule-editor-save'), body)

        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(save_response.status_code, 200)
        self.assertFalse(preview_envelope['ok'])
        self.assertFalse(save_envelope['ok'])
        self.assertEqual(preview_envelope['errors'], save_envelope['errors'])
