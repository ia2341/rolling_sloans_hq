"""apply_rehearsal_edits(): the rehearsal editor's single write, its staleness checks, and the past-row hard failure (issue #219)."""

from datetime import time, timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from scheduling.factories import ConflictFactory, RehearsalFactory, SemesterFactory
from scheduling.models import Rehearsal
from scheduling.services import (
    PastRehearsalEditError,
    RehearsalEditBuffer,
    RehearsalEditRow,
    StaleRehearsalSemesterError,
    WrongViewingSemesterError,
    apply_rehearsal_edits,
)

TOMORROW = timezone.localdate() + timedelta(days=1)
NEXT_WEEK = timezone.localdate() + timedelta(days=7)
YESTERDAY = timezone.localdate() - timedelta(days=1)


class ApplyRehearsalEditsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Semester and one existing future Rehearsal to edit."""
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, date=TOMORROW, start_time=time(18, 0))

    def _row(self, **overrides):
        """Build a RehearsalEditRow for a brand-new row unless `rehearsal_id` is overridden."""
        defaults = {
            'rehearsal_id': None,
            'date': NEXT_WEEK,
            'start_time': time(19, 0),
            'end_time': time(21, 0),
            'is_full_setlist': False,
            'setup_grace_minutes': None,
            'teardown_grace_minutes': None,
            'arrival_buffer_minutes': None,
            'departure_buffer_minutes': None,
        }
        defaults.update(overrides)
        return RehearsalEditRow(**defaults)

    def _buffer(self, rows, semester=None, updated_at=None):
        """Build a RehearsalEditBuffer against self.semester unless overridden."""
        semester = semester or self.semester
        return RehearsalEditBuffer(
            semester_id=semester.pk,
            semester_updated_at=updated_at if updated_at is not None else semester.updated_at,
            rows=list(rows),
        )

    def test_creates_a_new_row(self):
        """A row with no rehearsal_id creates a new Rehearsal on the Semester."""
        buffer = self._buffer([self._row(date=NEXT_WEEK)])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        created = Rehearsal.objects.get(semester=self.semester, date=NEXT_WEEK)
        self.assertEqual(created.start_time, time(19, 0))
        self.assertEqual(created.end_time, time(21, 0))

    def test_edits_an_existing_row(self):
        """A row naming an existing Rehearsal's pk edits that row in place, rather than creating a new one."""
        buffer = self._buffer([self._row(rehearsal_id=self.rehearsal.pk, date=TOMORROW, start_time=time(20, 0), end_time=time(22, 0))])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.rehearsal.refresh_from_db()
        self.assertEqual(self.rehearsal.start_time, time(20, 0))
        self.assertEqual(self.rehearsal.end_time, time(22, 0))
        self.assertEqual(Rehearsal.objects.filter(semester=self.semester).count(), 1)

    def test_a_new_and_an_edited_row_together_write_both(self):
        """A Buffer mixing a creation and a mutation applies both in the same call."""
        buffer = self._buffer([
            self._row(date=NEXT_WEEK),
            self._row(rehearsal_id=self.rehearsal.pk, date=TOMORROW, start_time=time(17, 0), end_time=time(19, 0)),
        ])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.assertEqual(Rehearsal.objects.filter(semester=self.semester).count(), 2)
        self.rehearsal.refresh_from_db()
        self.assertEqual(self.rehearsal.start_time, time(17, 0))

    def test_bumps_the_semester_stamp(self):
        """A successful apply bumps the Semester's updated_at."""
        stamp_before = self.semester.updated_at
        buffer = self._buffer([self._row(date=NEXT_WEEK)])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.semester.refresh_from_db()
        self.assertGreater(self.semester.updated_at, stamp_before)

    def test_a_blank_override_on_a_new_row_resolves_to_the_semester_default(self):
        """Leaving setup_grace_minutes blank on a new row saves the Semester's current default, not null."""
        buffer = self._buffer([self._row(date=NEXT_WEEK, setup_grace_minutes=None)])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        created = Rehearsal.objects.get(semester=self.semester, date=NEXT_WEEK)
        self.assertEqual(created.setup_grace_minutes, self.semester.default_setup_grace_minutes)

    def test_a_blank_override_on_an_existing_row_resolves_to_the_semester_default(self):
        """Blanking out an existing row's override reverts it to the Semester's current default, not null."""
        self.rehearsal.arrival_buffer_minutes = 5
        self.rehearsal.save(update_fields=['arrival_buffer_minutes'])
        buffer = self._buffer([self._row(
            rehearsal_id=self.rehearsal.pk, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0),
            arrival_buffer_minutes=None,
        )])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.rehearsal.refresh_from_db()
        self.assertEqual(self.rehearsal.arrival_buffer_minutes, self.semester.default_arrival_buffer_minutes)

    def test_a_new_row_left_blank_derives_its_end_time_from_the_semester_default(self):
        """A new row with end_time=None derives it from the Semester's default duration, same as a hand-created Rehearsal."""
        buffer = self._buffer([self._row(date=NEXT_WEEK, start_time=time(18, 0), end_time=None)])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        created = Rehearsal.objects.get(semester=self.semester, date=NEXT_WEEK)
        expected_minutes = self.semester.default_rehearsal_duration_minutes
        self.assertEqual(
            created.end_time,
            (timezone.datetime.combine(NEXT_WEEK, time(18, 0)) + timedelta(minutes=expected_minutes)).time(),
        )

    def test_an_existing_rows_end_time_is_never_re_derived(self):
        """Saving an existing row with its literal submitted end_time never re-derives it from the Semester default."""
        buffer = self._buffer([self._row(
            rehearsal_id=self.rehearsal.pk, date=TOMORROW, start_time=time(18, 0), end_time=time(18, 30),
        )])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.rehearsal.refresh_from_db()
        self.assertEqual(self.rehearsal.end_time, time(18, 30))

    def test_wrong_viewing_semester_hard_fails_and_writes_nothing(self):
        """A Buffer whose semester_id doesn't match the viewing Semester raises and writes nothing."""
        other_semester = SemesterFactory()
        buffer = self._buffer([self._row(date=NEXT_WEEK)], semester=other_semester)
        count_before = Rehearsal.objects.count()

        with self.assertRaises(WrongViewingSemesterError):
            apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.assertEqual(Rehearsal.objects.count(), count_before)

    def test_stale_semester_stamp_rejects_and_writes_nothing(self):
        """A Buffer carrying a stale semester_updated_at raises and writes nothing."""
        buffer = self._buffer([self._row(date=NEXT_WEEK)], updated_at=self.semester.updated_at - timedelta(seconds=1))
        count_before = Rehearsal.objects.count()

        with self.assertRaises(StaleRehearsalSemesterError):
            apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.assertEqual(Rehearsal.objects.count(), count_before)
        self.semester.refresh_from_db()

    def test_a_row_whose_current_stored_date_is_already_past_hard_fails_and_writes_nothing(self):
        """A row naming an existing Rehearsal whose current DB date has slipped into the past is a hard failure, not a normal save."""
        self.rehearsal.date = YESTERDAY
        Rehearsal.objects.filter(pk=self.rehearsal.pk).update(date=YESTERDAY)
        buffer = self._buffer([
            self._row(rehearsal_id=self.rehearsal.pk, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0)),
        ])
        stamp_before = self.semester.updated_at

        with self.assertRaises(PastRehearsalEditError):
            apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.rehearsal.refresh_from_db()
        self.assertEqual(self.rehearsal.date, YESTERDAY)
        self.semester.refresh_from_db()
        self.assertEqual(self.semester.updated_at, stamp_before)

    def test_a_same_day_race_across_midnight_hard_fails_and_writes_nothing(self):
        """A row for a Rehearsal dated exactly 'today' at buffer-build time, saved after the day rolls over, is a hard failure."""
        today_rehearsal = RehearsalFactory(semester=self.semester, date=timezone.localdate(), start_time=time(20, 0))
        buffer = self._buffer([
            self._row(rehearsal_id=today_rehearsal.pk, date=timezone.localdate(), start_time=time(20, 30), end_time=time(22, 0)),
        ])

        with (
            mock.patch('django.utils.timezone.localdate', return_value=timezone.localdate() + timedelta(days=1)),
            self.assertRaises(PastRehearsalEditError),
        ):
            apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        today_rehearsal.refresh_from_db()
        self.assertEqual(today_rehearsal.start_time, time(20, 0))

    def test_a_mixed_batch_with_one_hard_failure_writes_nothing_at_all(self):
        """A Buffer mixing a valid new row with a past-slipped existing row writes neither."""
        self.rehearsal.date = YESTERDAY
        Rehearsal.objects.filter(pk=self.rehearsal.pk).update(date=YESTERDAY)
        buffer = self._buffer([
            self._row(date=NEXT_WEEK),
            self._row(rehearsal_id=self.rehearsal.pk, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0)),
        ])
        count_before = Rehearsal.objects.count()

        with self.assertRaises(PastRehearsalEditError):
            apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.assertEqual(Rehearsal.objects.count(), count_before)

    def test_a_new_rows_submitted_past_date_hard_fails_and_writes_nothing(self):
        """A brand-new row (no rehearsal_id) submitting a past date is a hard failure, not just an existing-row concern."""
        buffer = self._buffer([self._row(date=YESTERDAY)])
        count_before = Rehearsal.objects.count()

        with self.assertRaises(PastRehearsalEditError):
            apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.assertEqual(Rehearsal.objects.count(), count_before)

    def test_an_existing_rows_submitted_past_date_hard_fails_even_though_its_stored_date_is_future(self):
        """An existing row whose *submitted* date is past hard-fails, even though its current stored date is still future."""
        buffer = self._buffer([
            self._row(rehearsal_id=self.rehearsal.pk, date=YESTERDAY, start_time=time(18, 0), end_time=time(20, 0)),
        ])

        with self.assertRaises(PastRehearsalEditError):
            apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.rehearsal.refresh_from_db()
        self.assertEqual(self.rehearsal.date, TOMORROW)

    def test_swapping_dates_between_two_existing_rows_does_not_hit_the_unique_constraint(self):
        """Two existing rows exchanging dates in one Buffer must not collide mid-batch on unique_rehearsal_date_per_semester."""
        other = RehearsalFactory(semester=self.semester, date=NEXT_WEEK, start_time=time(19, 0))
        buffer = self._buffer([
            self._row(rehearsal_id=self.rehearsal.pk, date=NEXT_WEEK, start_time=time(18, 0), end_time=time(20, 0)),
            self._row(rehearsal_id=other.pk, date=TOMORROW, start_time=time(19, 0), end_time=time(21, 0)),
        ])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.rehearsal.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.rehearsal.date, NEXT_WEEK)
        self.assertEqual(other.date, TOMORROW)

    def test_flipping_to_dress_with_existing_conflicts_still_refuses_per_adr_0006(self):
        """ADR-0006's flip-block still applies through this surface: a Rehearsal with Conflicts can't become the Dress Rehearsal."""
        ConflictFactory(rehearsal=self.rehearsal)
        buffer = self._buffer([
            self._row(rehearsal_id=self.rehearsal.pk, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0), is_full_setlist=True),
        ])

        with self.assertRaises(ValueError):
            apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.rehearsal.refresh_from_db()
        self.assertFalse(self.rehearsal.is_full_setlist)
