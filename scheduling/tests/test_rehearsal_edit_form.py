"""RehearsalEditRowForm/RehearsalEditFormSet: per-row validation and the cross-row duplicate-date check (issue #219)."""

from datetime import time, timedelta

from django.test import TestCase
from django.utils import timezone

from scheduling.factories import RehearsalFactory, SemesterFactory
from scheduling.forms import RehearsalEditFormSet, RehearsalEditRowForm
from scheduling.models import Rehearsal

TOMORROW = timezone.localdate() + timedelta(days=1)
NEXT_WEEK = timezone.localdate() + timedelta(days=7)
YESTERDAY = timezone.localdate() - timedelta(days=1)


def _row_form(semester, **overrides):
    """Build a bound, unsaved RehearsalEditRowForm from `overrides`, defaulting to a plausible valid row."""
    data = {
        'date': TOMORROW.isoformat(), 'start_time': '18:00', 'end_time': '20:00', 'is_full_setlist': False,
    }
    data.update(overrides)
    return RehearsalEditRowForm(data, semester=semester)


class RehearsalEditRowFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Semester with a 90-minute default rehearsal duration."""
        cls.semester = SemesterFactory(default_rehearsal_duration_minutes=90)

    def test_a_plausible_row_is_valid(self):
        """A row with a future date and end after start is valid."""
        form = _row_form(self.semester)

        self.assertTrue(form.is_valid())

    def test_end_time_at_or_before_start_time_is_invalid(self):
        """An end time equal to or before the start time is rejected on the end_time field."""
        form = _row_form(self.semester, start_time='20:00', end_time='20:00')

        self.assertFalse(form.is_valid())
        self.assertIn('end_time', form.errors)

    def test_a_date_before_today_is_invalid_and_names_the_django_admin(self):
        """A row dated before today is rejected, naming the Django admin as where that job lives."""
        form = _row_form(self.semester, date=YESTERDAY.isoformat())

        self.assertFalse(form.is_valid())
        self.assertIn('Django admin', form.errors['date'][0])

    def test_a_date_of_today_is_valid(self):
        """A row dated exactly today is accepted — today counts as future, not past."""
        form = _row_form(self.semester, date=timezone.localdate().isoformat())

        self.assertTrue(form.is_valid())

    def test_a_blank_end_time_on_a_new_row_is_valid_and_left_out_of_cleaned_data(self):
        """A new row may leave end_time blank; cleaned_data carries None so apply_* can derive it."""
        form = _row_form(self.semester, end_time='')

        self.assertTrue(form.is_valid())
        self.assertIsNone(form.cleaned_data['end_time'])

    def test_a_blank_end_time_deriving_past_midnight_is_invalid(self):
        """Leaving end_time blank on a new row is rejected when the Semester's default duration would cross midnight."""
        form = _row_form(self.semester, start_time='23:30', end_time='')

        self.assertFalse(form.is_valid())
        self.assertIn('end_time', form.errors)

    def test_a_blank_end_time_on_an_existing_row_is_invalid(self):
        """An existing row cannot leave end_time blank — only a new row may."""
        rehearsal = RehearsalFactory(semester=self.semester, date=TOMORROW, start_time=time(18, 0))
        form = RehearsalEditRowForm(
            {'date': TOMORROW.isoformat(), 'start_time': '18:00', 'end_time': '', 'is_full_setlist': False},
            instance=rehearsal, semester=self.semester,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('end_time', form.errors)

    def test_blank_overrides_are_optional_and_left_out_of_cleaned_data(self):
        """The four grace/buffer override fields are optional; leaving them blank cleans to None."""
        form = _row_form(self.semester)

        self.assertTrue(form.is_valid())
        self.assertIsNone(form.cleaned_data['setup_grace_minutes'])
        self.assertIsNone(form.cleaned_data['teardown_grace_minutes'])
        self.assertIsNone(form.cleaned_data['arrival_buffer_minutes'])
        self.assertIsNone(form.cleaned_data['departure_buffer_minutes'])

    def test_override_placeholders_show_the_semester_defaults(self):
        """Each override field's placeholder attribute is the Semester's current default."""
        semester = SemesterFactory(
            default_setup_grace_minutes=11, default_teardown_grace_minutes=12,
            default_arrival_buffer_minutes=13, default_departure_buffer_minutes=14,
        )
        form = _row_form(semester)

        self.assertEqual(form.fields['setup_grace_minutes'].widget.attrs['placeholder'], '11')
        self.assertEqual(form.fields['teardown_grace_minutes'].widget.attrs['placeholder'], '12')
        self.assertEqual(form.fields['arrival_buffer_minutes'].widget.attrs['placeholder'], '13')
        self.assertEqual(form.fields['departure_buffer_minutes'].widget.attrs['placeholder'], '14')


def _formset_data(rows):
    """Build POST-shaped data for RehearsalEditFormSet from a list of row dicts."""
    data = {
        'rehearsal-TOTAL_FORMS': str(len(rows)),
        'rehearsal-INITIAL_FORMS': '0',
        'rehearsal-MIN_NUM_FORMS': '0',
        'rehearsal-MAX_NUM_FORMS': '1000',
    }
    for index, row in enumerate(rows):
        for field, value in row.items():
            data[f'rehearsal-{index}-{field}'] = value
    return data


class RehearsalEditFormSetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a plain Semester for formset-level Buffers."""
        cls.semester = SemesterFactory()

    def test_two_new_rows_sharing_a_date_are_both_flagged(self):
        """Two pending rows dated the same day both carry a date error, and no plain save would go through."""
        row = {'date': TOMORROW.isoformat(), 'start_time': '18:00', 'end_time': '20:00', 'is_full_setlist': False}
        other_row = {'date': TOMORROW.isoformat(), 'start_time': '21:00', 'end_time': '22:00', 'is_full_setlist': False}
        formset = RehearsalEditFormSet(
            _formset_data([row, other_row]), queryset=Rehearsal.objects.none(),
            prefix='rehearsal', form_kwargs={'semester': self.semester},
        )

        self.assertFalse(formset.is_valid())
        self.assertIn('date', formset.forms[0].errors)
        self.assertIn('date', formset.forms[1].errors)

    def test_two_rows_on_different_dates_are_both_valid(self):
        """Two pending rows on distinct dates raise no duplicate-date error."""
        row = {'date': TOMORROW.isoformat(), 'start_time': '18:00', 'end_time': '20:00', 'is_full_setlist': False}
        other_row = {'date': NEXT_WEEK.isoformat(), 'start_time': '18:00', 'end_time': '20:00', 'is_full_setlist': False}
        formset = RehearsalEditFormSet(
            _formset_data([row, other_row]), queryset=Rehearsal.objects.none(),
            prefix='rehearsal', form_kwargs={'semester': self.semester},
        )

        self.assertTrue(formset.is_valid())
