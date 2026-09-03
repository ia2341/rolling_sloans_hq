"""RehearsalPattern, RehearsalTime and SkipDate: the schema rehearsal generation needs (issue #214)."""

from datetime import date, time

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from scheduling.factories import (
    RehearsalPatternFactory,
    RehearsalTimeFactory,
    SemesterFactory,
    SkipDateFactory,
)
from scheduling.models import RehearsalPattern, RehearsalTime, SkipDate


class RehearsalPatternTests(TestCase):
    def test_created_with_semester_and_range(self):
        """A RehearsalPattern is created with its Semester and generation range."""
        semester = SemesterFactory()

        pattern = RehearsalPatternFactory(semester=semester, start_date=date(2026, 9, 1), end_date=date(2026, 12, 15))

        reloaded = RehearsalPattern.objects.get(pk=pattern.pk)
        self.assertEqual(reloaded.semester, semester)
        self.assertEqual(reloaded.start_date, date(2026, 9, 1))
        self.assertEqual(reloaded.end_date, date(2026, 12, 15))

    def test_one_per_semester(self):
        """A second RehearsalPattern for the same Semester is rejected at the database level."""
        semester = SemesterFactory()
        RehearsalPatternFactory(semester=semester)

        with self.assertRaises(IntegrityError):
            RehearsalPattern.objects.create(semester=semester, start_date=date(2026, 9, 1), end_date=date(2026, 12, 15))

    def test_reversed_range_is_rejected_by_full_clean(self):
        """A Pattern whose end_date falls before start_date fails validation."""
        pattern = RehearsalPatternFactory.build(start_date=date(2026, 12, 15), end_date=date(2026, 9, 1))

        with self.assertRaises(ValidationError):
            pattern.full_clean()

    def test_save_rejects_a_reversed_range_even_without_full_clean(self):
        """save() enforces the ordering check directly, so a caller that skips full_clean() can't bypass it."""
        semester = SemesterFactory()

        with self.assertRaises(ValueError):
            RehearsalPattern.objects.create(
                semester=semester, start_date=date(2026, 12, 15), end_date=date(2026, 9, 1),
            )

    def test_equal_start_and_end_date_is_valid(self):
        """A one-day generation range (start_date == end_date) is valid."""
        semester = SemesterFactory()
        pattern = RehearsalPattern(semester=semester, start_date=date(2026, 9, 1), end_date=date(2026, 9, 1))

        pattern.full_clean(exclude=['id'])


class RehearsalTimeTests(TestCase):
    def test_created_with_day_and_times(self):
        """A RehearsalTime is created with its Pattern, day of week, and start/end times."""
        pattern = RehearsalPatternFactory()

        rehearsal_time = RehearsalTimeFactory(
            pattern=pattern, day_of_week=RehearsalTime.WEDNESDAY, start_time=time(19, 0), end_time=time(23, 0),
        )

        reloaded = RehearsalTime.objects.get(pk=rehearsal_time.pk)
        self.assertEqual(reloaded.pattern, pattern)
        self.assertEqual(reloaded.day_of_week, RehearsalTime.WEDNESDAY)
        self.assertEqual(reloaded.start_time, time(19, 0))
        self.assertEqual(reloaded.end_time, time(23, 0))

    def test_a_pattern_can_carry_multiple_rehearsal_times(self):
        """A Pattern can hold more than one RehearsalTime, e.g. Wednesdays and Sundays."""
        pattern = RehearsalPatternFactory()

        wednesday = RehearsalTimeFactory(pattern=pattern, day_of_week=RehearsalTime.WEDNESDAY)
        sunday = RehearsalTimeFactory(
            pattern=pattern, day_of_week=RehearsalTime.SUNDAY, start_time=time(11, 0), end_time=time(15, 0),
        )

        times = RehearsalTime.objects.filter(pattern=pattern)
        self.assertEqual(times.count(), 2)
        self.assertIn(wednesday, times)
        self.assertIn(sunday, times)


class SkipDateTests(TestCase):
    def test_a_single_date_leaves_end_date_blank(self):
        """A holiday Skip Date is expressed with end_date left null."""
        skip = SkipDateFactory(start_date=date(2026, 11, 26), end_date=None)

        reloaded = SkipDate.objects.get(pk=skip.pk)
        self.assertEqual(reloaded.start_date, date(2026, 11, 26))
        self.assertIsNone(reloaded.end_date)

    def test_an_inclusive_range_sets_both_dates(self):
        """A break Skip Date (e.g. spring break) is expressed with both start_date and end_date set."""
        skip = SkipDateFactory(start_date=date(2027, 3, 9), end_date=date(2027, 3, 15))

        reloaded = SkipDate.objects.get(pk=skip.pk)
        self.assertEqual(reloaded.start_date, date(2027, 3, 9))
        self.assertEqual(reloaded.end_date, date(2027, 3, 15))

    def test_reversed_range_is_rejected_by_full_clean(self):
        """A Skip Date whose end_date falls before start_date fails validation."""
        skip = SkipDateFactory.build(start_date=date(2027, 3, 15), end_date=date(2027, 3, 9))

        with self.assertRaises(ValidationError):
            skip.full_clean()

    def test_save_rejects_a_reversed_range_even_without_full_clean(self):
        """save() enforces the ordering check directly, so a caller that skips full_clean() can't bypass it."""
        pattern = RehearsalPatternFactory()

        with self.assertRaises(ValueError):
            SkipDate.objects.create(pattern=pattern, start_date=date(2027, 3, 15), end_date=date(2027, 3, 9))

    def test_a_pattern_can_carry_multiple_skip_dates(self):
        """A Pattern can hold more than one Skip Date, e.g. a holiday and a break."""
        pattern = RehearsalPatternFactory()

        holiday = SkipDateFactory(pattern=pattern, start_date=date(2026, 11, 26), end_date=None)
        break_ = SkipDateFactory(pattern=pattern, start_date=date(2027, 3, 9), end_date=date(2027, 3, 15))

        skip_dates = SkipDate.objects.filter(pattern=pattern)
        self.assertEqual(skip_dates.count(), 2)
        self.assertIn(holiday, skip_dates)
        self.assertIn(break_, skip_dates)
