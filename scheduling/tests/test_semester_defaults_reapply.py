"""apply_semester_defaults_reapply()/preview_semester_defaults_reapply(): the bulk defaults-push action (issue #291)."""

from datetime import time, timedelta

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from scheduling.factories import (
    ConflictFactory,
    ConflictWindowFactory,
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    SemesterFactory,
)
from scheduling.models import Conflict, RehearsalSong
from scheduling.services import (
    SemesterDefaultsReapplyBlockedError,
    SemesterDefaultsReapplyBuffer,
    StaleSemesterDefaultsError,
    apply_semester_defaults_reapply,
    preview_semester_defaults_reapply,
)

YESTERDAY = timezone.localdate() - timedelta(days=1)
TOMORROW = timezone.localdate() + timedelta(days=1)
NEXT_WEEK = timezone.localdate() + timedelta(days=7)


class ApplySemesterDefaultsReapplyTests(TestCase):
    def _buffer(self, semester):
        """Return a Buffer naming `semester` at its current stamp."""
        return SemesterDefaultsReapplyBuffer(semester_id=semester.pk, semester_updated_at=semester.updated_at)

    def test_overwrites_grace_and_buffer_fields_on_an_upcoming_rehearsal(self):
        """An upcoming Rehearsal's already-concrete grace/buffer fields are replaced with the Semester's current defaults."""
        semester = SemesterFactory(default_setup_grace_minutes=20, default_teardown_grace_minutes=10)
        rehearsal = RehearsalFactory(
            semester=semester, date=TOMORROW, setup_grace_minutes=1, teardown_grace_minutes=1,
        )

        apply_semester_defaults_reapply(self._buffer(semester))

        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.setup_grace_minutes, 20)
        self.assertEqual(rehearsal.teardown_grace_minutes, 10)

    def test_recomputes_end_time_from_the_current_default_duration(self):
        """end_time is re-derived from start_time against the Semester's current default_rehearsal_duration_minutes."""
        semester = SemesterFactory(default_rehearsal_duration_minutes=60)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(21, 0))

        apply_semester_defaults_reapply(self._buffer(semester))

        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.end_time, time(19, 0))

    def test_excludes_past_rehearsals(self):
        """A Rehearsal dated before today is left completely untouched."""
        semester = SemesterFactory(default_setup_grace_minutes=20)
        past = RehearsalFactory(semester=semester, date=YESTERDAY, setup_grace_minutes=1)

        apply_semester_defaults_reapply(self._buffer(semester))

        past.refresh_from_db()
        self.assertEqual(past.setup_grace_minutes, 1)

    def test_recomputes_rehearsal_song_slot_times_against_the_new_window(self):
        """Shrinking the Semester's default duration re-times a surviving RehearsalSong's slot."""
        semester = SemesterFactory(default_rehearsal_duration_minutes=60, default_song_slot_count=2)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(21, 0))
        song = RehearsalSongFactory(rehearsal=rehearsal, order=1, slot_count=1)

        apply_semester_defaults_reapply(self._buffer(semester))

        song.refresh_from_db()
        self.assertEqual((song.start_time, song.end_time), (time(18, 0), time(18, 30)))

    def test_bumps_the_semester_stamp(self):
        """A successful reapply strictly advances the Semester's updated_at."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=TOMORROW)
        stamp_before = semester.updated_at

        apply_semester_defaults_reapply(self._buffer(semester))

        semester.refresh_from_db()
        self.assertGreater(semester.updated_at, stamp_before)

    def test_stale_semester_stamp_rejects_and_writes_nothing(self):
        """A Buffer built against a stale updated_at is rejected without touching any Rehearsal."""
        semester = SemesterFactory(default_setup_grace_minutes=20)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, setup_grace_minutes=1)
        buffer = self._buffer(semester)
        semester.updated_at = timezone.now()
        semester.save(update_fields=['updated_at'])

        with self.assertRaises(StaleSemesterDefaultsError):
            apply_semester_defaults_reapply(buffer)

        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.setup_grace_minutes, 1)

    def test_a_shrunk_slot_count_that_overruns_blocks_the_whole_reapply(self):
        """A RehearsalSong that no longer fits the (shrunk) default_song_slot_count blocks the batch, writing nothing."""
        semester = SemesterFactory(default_song_slot_count=5)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, setup_grace_minutes=1)
        RehearsalSongFactory(rehearsal=rehearsal, order=1, slot_count=5)
        semester.default_song_slot_count = 1
        semester.save(update_fields=['default_song_slot_count'])
        buffer = SemesterDefaultsReapplyBuffer(semester_id=semester.pk, semester_updated_at=semester.updated_at)

        with self.assertRaises(SemesterDefaultsReapplyBlockedError):
            apply_semester_defaults_reapply(buffer)

        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.setup_grace_minutes, 1)

    def test_midnight_wraparound_blocks_the_whole_reapply(self):
        """A start_time whose new default duration would wrap past midnight blocks the batch, writing nothing."""
        semester = SemesterFactory(default_rehearsal_duration_minutes=60, default_setup_grace_minutes=20)
        rehearsal = RehearsalFactory(
            semester=semester, date=TOMORROW, start_time=time(23, 30), end_time=time(23, 59),
            setup_grace_minutes=1,
        )

        with self.assertRaises(SemesterDefaultsReapplyBlockedError):
            apply_semester_defaults_reapply(self._buffer(semester))

        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.setup_grace_minutes, 1)

    def test_a_second_future_rehearsal_does_not_collide_on_unique_order_per_rehearsal(self):
        """Recomputing two Rehearsals' RehearsalSongs in one batch doesn't trip unique_order_per_rehearsal."""
        semester = SemesterFactory(default_rehearsal_duration_minutes=60, default_song_slot_count=2)
        first = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(21, 0))
        second = RehearsalFactory(semester=semester, date=NEXT_WEEK, start_time=time(18, 0), end_time=time(21, 0))
        RehearsalSongFactory(rehearsal=first, order=1, slot_count=1)
        RehearsalSongFactory(rehearsal=second, order=1, slot_count=1)

        apply_semester_defaults_reapply(self._buffer(semester))

        self.assertEqual(RehearsalSong.objects.filter(rehearsal=first).count(), 1)
        self.assertEqual(RehearsalSong.objects.filter(rehearsal=second).count(), 1)


class PreviewSemesterDefaultsReapplyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Semester with one upcoming Rehearsal."""
        cls.semester = SemesterFactory(default_rehearsal_duration_minutes=90)
        cls.rehearsal = RehearsalFactory(semester=cls.semester, date=TOMORROW, start_time=time(18, 0))

    def _buffer(self):
        """Return a Buffer naming the fixture Semester at its current stamp."""
        return SemesterDefaultsReapplyBuffer(semester_id=self.semester.pk, semester_updated_at=self.semester.updated_at)

    def _preview(self, buffer):
        """Call preview_semester_defaults_reapply() inside a transaction the test itself rolls back, per its docstring."""
        with transaction.atomic():
            fallout = preview_semester_defaults_reapply(buffer)
            transaction.set_rollback(True)
        return fallout

    def test_writes_nothing(self):
        """A preview leaves the Rehearsal and the Semester stamp untouched."""
        stamp_before = self.semester.updated_at
        self.rehearsal.setup_grace_minutes = 1
        self.rehearsal.save(update_fields=['setup_grace_minutes'])

        self._preview(self._buffer())

        self.rehearsal.refresh_from_db()
        self.assertEqual(self.rehearsal.setup_grace_minutes, 1)
        self.semester.refresh_from_db()
        self.assertEqual(self.semester.updated_at, stamp_before)

    def test_reports_the_changed_rehearsal_count(self):
        """The Fallout counts every upcoming Rehearsal this reapply would touch."""
        RehearsalFactory(semester=self.semester, date=NEXT_WEEK)

        fallout = self._preview(self._buffer())

        self.assertFalse(fallout.is_blocked)
        self.assertEqual(fallout.changed_rehearsal_count, 2)

    def test_a_blocked_reapply_reports_is_blocked_with_no_fallout(self):
        """A slot overrun surfaces as is_blocked, with empty loud/quiet lists."""
        RehearsalSongFactory(rehearsal=self.rehearsal, order=1, slot_count=self.semester.default_song_slot_count)
        self.semester.default_song_slot_count = 1
        self.semester.save(update_fields=['default_song_slot_count'])

        fallout = self._preview(SemesterDefaultsReapplyBuffer(
            semester_id=self.semester.pk, semester_updated_at=self.semester.updated_at,
        ))

        self.assertTrue(fallout.is_blocked)
        self.assertEqual(fallout.loud, [])
        self.assertEqual(fallout.quiet, [])

    def test_a_recorded_rehearsal_song_re_time_is_reported_loud(self):
        """A Recording whose RehearsalSong slot moves after the reapply is a loud Fallout line."""
        self.semester.default_rehearsal_duration_minutes = 60
        self.semester.save(update_fields=['default_rehearsal_duration_minutes'])
        self.rehearsal.end_time = time(21, 0)
        self.rehearsal.save(update_fields=['end_time'])
        song = RehearsalSongFactory(rehearsal=self.rehearsal, order=1, slot_count=1)
        RecordingFactory(rehearsal_song=song)

        fallout = self._preview(self._buffer())

        self.assertFalse(fallout.is_blocked)
        self.assertEqual(len(fallout.loud), 1)

    def test_a_conflict_window_losing_overlap_is_reported_quiet(self):
        """A declared Conflict Window that no longer overlaps the re-timed Rehearsal is a quiet Fallout line."""
        self.semester.default_rehearsal_duration_minutes = 30
        self.semester.save(update_fields=['default_rehearsal_duration_minutes'])
        conflict = ConflictFactory(rehearsal=self.rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(19, 0), unavailable_end=time(19, 15))

        fallout = self._preview(self._buffer())

        self.assertFalse(fallout.is_blocked)
        self.assertEqual(len(fallout.quiet), 1)
