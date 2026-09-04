"""The "Generate rehearsal dates" staging modal's views: the Pattern editor, its Save, and the diff Preview (issue #222)."""

from datetime import date, time, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    RehearsalPatternFactory,
    RehearsalTimeFactory,
    SemesterFactory,
    SkipDateFactory,
)
from scheduling.models import Rehearsal, RehearsalPattern, RehearsalTime, SkipDate
from scheduling.tests.preview_helpers import assert_preview_writes_nothing

PASSWORD = 'a-strong-test-password-123'
TOMORROW = timezone.localdate() + timedelta(days=1)


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


def pattern_form_data(
    start_date=TOMORROW, end_date=None, rehearsal_times=(), skip_dates=(),
    narrow_start_date='', narrow_end_date='',
):
    """Build POST data for the Pattern editor's three forms/formsets, prefixed exactly like the modal template."""
    end_date = end_date or (start_date + timedelta(days=90))
    data = {
        'range-start_date': start_date.isoformat(),
        'range-end_date': end_date.isoformat(),
        'rehearsal-time-TOTAL_FORMS': str(len(rehearsal_times)),
        'rehearsal-time-INITIAL_FORMS': '0',
        'rehearsal-time-MIN_NUM_FORMS': '0',
        'rehearsal-time-MAX_NUM_FORMS': '1000',
        'skip-date-TOTAL_FORMS': str(len(skip_dates)),
        'skip-date-INITIAL_FORMS': '0',
        'skip-date-MIN_NUM_FORMS': '0',
        'skip-date-MAX_NUM_FORMS': '1000',
        'narrow-start_date': narrow_start_date,
        'narrow-end_date': narrow_end_date,
    }
    for index, rehearsal_time in enumerate(rehearsal_times):
        data[f'rehearsal-time-{index}-day_of_week'] = str(rehearsal_time['day_of_week'])
        data[f'rehearsal-time-{index}-start_time'] = rehearsal_time['start_time']
        data[f'rehearsal-time-{index}-end_time'] = rehearsal_time['end_time']
    for index, skip_date in enumerate(skip_dates):
        data[f'skip-date-{index}-start_date'] = skip_date['start_date']
        data[f'skip-date-{index}-end_date'] = skip_date.get('end_date', '')
    return data


@override_settings(SECURE_SSL_REDIRECT=False)
class RehearsalPatternModalViewTests(TestCase):
    def test_get_redirects_anonymous_users_to_login(self):
        """An anonymous GET to the modal endpoint redirects to the login page."""
        SemesterFactory()
        url = reverse('scheduling:schedule-edit-generate')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_get_is_forbidden_for_a_non_admin(self):
        """A logged-in non-admin's GET to the modal endpoint returns 403."""
        SemesterFactory()
        member_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit-generate'))

        self.assertEqual(response.status_code, 403)

    def test_get_renders_blank_editor_with_no_saved_pattern(self):
        """An admin opening the modal on a Semester with no saved Pattern sees an empty editor, not an error."""
        SemesterFactory()
        admin_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit-generate'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="rehearsal-pattern-editor"')

    def test_get_prefills_from_an_existing_pattern(self):
        """An admin opening the modal on a Semester with a saved Pattern sees its Rehearsal Times and Skip Dates prefilled."""
        semester = SemesterFactory()
        pattern = RehearsalPatternFactory(semester=semester, start_date=date(2026, 9, 1), end_date=date(2026, 12, 15))
        RehearsalTimeFactory(pattern=pattern, day_of_week=RehearsalTime.WEDNESDAY, start_time=time(19, 0), end_time=time(23, 0))
        SkipDateFactory(pattern=pattern, start_date=date(2026, 11, 26))
        admin_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit-generate'))

        self.assertContains(response, 'value="2026-09-01"')
        self.assertContains(response, 'value="19:00:00"')


@override_settings(SECURE_SSL_REDIRECT=False)
class RehearsalPatternSaveViewTests(TestCase):
    def test_get_is_forbidden_for_a_non_admin(self):
        """A logged-in non-admin's POST to the save endpoint returns 403 and changes nothing."""
        SemesterFactory()
        member_client(self)

        response = self.client.post(reverse('scheduling:schedule-edit-generate-save'), pattern_form_data())

        self.assertEqual(response.status_code, 403)
        self.assertEqual(RehearsalPattern.objects.count(), 0)

    def test_valid_post_persists_the_pattern(self):
        """A valid submission persists a RehearsalPattern with its Rehearsal Times and Skip Dates."""
        SemesterFactory()
        admin_client(self)
        data = pattern_form_data(
            rehearsal_times=[{'day_of_week': RehearsalTime.WEDNESDAY, 'start_time': '19:00', 'end_time': '23:00'}],
            skip_dates=[{'start_date': '2026-11-26'}],
        )

        response = self.client.post(reverse('scheduling:schedule-edit-generate-save'), data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(RehearsalPattern.objects.count(), 1)
        self.assertEqual(RehearsalTime.objects.count(), 1)
        self.assertEqual(SkipDate.objects.count(), 1)

    def test_colliding_rehearsal_times_are_rejected_and_write_nothing(self):
        """Two Rehearsal Times sharing a day-of-week are rejected with an error and persist no Pattern."""
        SemesterFactory()
        admin_client(self)
        data = pattern_form_data(rehearsal_times=[
            {'day_of_week': RehearsalTime.WEDNESDAY, 'start_time': '19:00', 'end_time': '21:00'},
            {'day_of_week': RehearsalTime.WEDNESDAY, 'start_time': '21:00', 'end_time': '23:00'},
        ])

        response = self.client.post(reverse('scheduling:schedule-edit-generate-save'), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="rehearsal-pattern-save-error"')
        self.assertEqual(RehearsalPattern.objects.count(), 0)


@override_settings(SECURE_SSL_REDIRECT=False)
class RehearsalGenerationPreviewViewTests(TestCase):
    def test_get_is_forbidden_for_a_non_admin(self):
        """A logged-in non-admin's POST to the preview endpoint returns 403."""
        SemesterFactory()
        member_client(self)

        response = self.client.post(reverse('scheduling:schedule-edit-generate-preview'), pattern_form_data())

        self.assertEqual(response.status_code, 403)

    def test_preview_writes_nothing(self):
        """A Preview POST renders the diff and leaves every Rehearsal/Pattern row and the Semester stamp untouched."""
        semester = SemesterFactory()
        admin_client(self)
        data = pattern_form_data(rehearsal_times=[
            {'day_of_week': RehearsalTime.WEDNESDAY, 'start_time': '19:00', 'end_time': '23:00'},
        ])

        response = assert_preview_writes_nothing(
            self, reverse('scheduling:schedule-edit-generate-preview'), data,
            models_to_check=[Rehearsal, RehearsalPattern, RehearsalTime, SkipDate],
            semester=semester,
        )

        self.assertContains(response, 'id="rehearsal-generation-diff"', status_code=200)

    def test_preview_renders_the_four_bucket_diff(self):
        """A valid Preview renders at least one Create item for a fresh Semester with no Rehearsals."""
        SemesterFactory()
        admin_client(self)
        data = pattern_form_data(rehearsal_times=[
            {'day_of_week': RehearsalTime.WEDNESDAY, 'start_time': '19:00', 'end_time': '23:00'},
        ])

        response = self.client.post(reverse('scheduling:schedule-edit-generate-preview'), data)

        self.assertContains(response, 'rs-generation-create-item')

    def test_colliding_rehearsal_times_render_an_error_not_a_diff(self):
        """A Pattern-level collision renders a Validation Error, never a diff."""
        SemesterFactory()
        admin_client(self)
        data = pattern_form_data(rehearsal_times=[
            {'day_of_week': RehearsalTime.WEDNESDAY, 'start_time': '19:00', 'end_time': '21:00'},
            {'day_of_week': RehearsalTime.WEDNESDAY, 'start_time': '21:00', 'end_time': '23:00'},
        ])

        response = self.client.post(reverse('scheduling:schedule-edit-generate-preview'), data)

        self.assertContains(response, 'id="rehearsal-generation-errors"')
        self.assertNotContains(response, 'rs-generation-create-item')
