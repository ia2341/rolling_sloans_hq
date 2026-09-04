"""apply_rehearsal_edits()'s Running Order sub-grid buffer: adds, reorders, removals and the two new blocking Validation Errors (issue #220)."""

from datetime import time, timedelta

from django.test import TestCase
from django.utils import timezone

from scheduling.factories import (
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.models import Recording, RehearsalSong
from scheduling.services import (
    RehearsalEditBuffer,
    RehearsalEditRow,
    RunningOrderRow,
    RunningOrderValidationError,
    apply_rehearsal_edits,
)

TOMORROW = timezone.localdate() + timedelta(days=1)


class ApplyRunningOrderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Semester (slot_count=5) with one future Rehearsal and three setlist Songs."""
        cls.semester = SemesterFactory(default_song_slot_count=5)
        cls.rehearsal = RehearsalFactory(semester=cls.semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        cls.song_a = SongFactory(semester=cls.semester, position=1)
        cls.song_b = SongFactory(semester=cls.semester, position=2)
        cls.song_c = SongFactory(semester=cls.semester, position=3)

    def _row(self, running_order, **overrides):
        """Build a RehearsalEditRow editing self.rehearsal in place, carrying `running_order`."""
        defaults = {
            'rehearsal_id': self.rehearsal.pk,
            'date': self.rehearsal.date,
            'start_time': self.rehearsal.start_time,
            'end_time': self.rehearsal.end_time,
            'is_full_setlist': False,
            'setup_grace_minutes': None,
            'teardown_grace_minutes': None,
            'arrival_buffer_minutes': None,
            'departure_buffer_minutes': None,
        }
        defaults.update(overrides)
        return RehearsalEditRow(running_order=list(running_order), **defaults)

    def _buffer(self, rows):
        return RehearsalEditBuffer(
            semester_id=self.semester.pk, semester_updated_at=self.semester.updated_at, rows=list(rows),
        )

    def test_adds_new_running_order_rows_in_submitted_order(self):
        """A Buffer naming two brand-new Songs (no rehearsal_song_id) creates them at contiguous positions 1..N."""
        buffer = self._buffer([self._row([
            RunningOrderRow(rehearsal_song_id=None, song_id=self.song_a.pk, slot_count=1),
            RunningOrderRow(rehearsal_song_id=None, song_id=self.song_b.pk, slot_count=2),
        ])])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        rehearsal_songs = list(RehearsalSong.objects.filter(rehearsal=self.rehearsal).order_by('order'))
        self.assertEqual([rs.song_id for rs in rehearsal_songs], [self.song_a.pk, self.song_b.pk])
        self.assertEqual([rs.order for rs in rehearsal_songs], [1, 2])

    def test_derives_start_and_end_times_from_slot_count(self):
        """A newly-created row's start_time/end_time are derived from the Rehearsal window and slot_count, never from Song.length."""
        buffer = self._buffer([self._row([RunningOrderRow(rehearsal_song_id=None, song_id=self.song_a.pk, slot_count=2)])])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        rehearsal_song = RehearsalSong.objects.get(rehearsal=self.rehearsal, song=self.song_a)
        # Rehearsal window is 18:00-20:00 (120 min) over 5 slots => 24 min/slot; 2 slots => 48 min.
        self.assertEqual(rehearsal_song.start_time, time(18, 0))
        self.assertEqual(rehearsal_song.end_time, time(18, 48))

    def test_reorders_existing_rows_and_re_derives_their_times(self):
        """Submitting existing rows in a new order renumbers them contiguously and recomputes every affected row's times."""
        first = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song_a, order=1, slot_count=1)
        second = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song_b, order=2, slot_count=1)
        buffer = self._buffer([self._row([
            RunningOrderRow(rehearsal_song_id=second.pk, song_id=self.song_b.pk, slot_count=1),
            RunningOrderRow(rehearsal_song_id=first.pk, song_id=self.song_a.pk, slot_count=1),
        ])])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        second.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(second.order, 1)
        self.assertEqual(first.order, 2)
        self.assertEqual(second.start_time, time(18, 0))
        self.assertEqual(first.start_time, time(18, 24))

    def test_removes_a_row_not_named_in_the_buffer(self):
        """An existing RehearsalSong the Buffer no longer names is deleted."""
        doomed = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song_a, order=1)
        buffer = self._buffer([self._row([])])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.assertFalse(RehearsalSong.objects.filter(pk=doomed.pk).exists())

    def test_removing_a_recorded_row_deletes_its_recordings_too(self):
        """Removing a RehearsalSong row that carries Recordings deletes them along with it (hand-editing allows this, unlike the generator)."""
        doomed = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song_a, order=1)
        recording = RecordingFactory(rehearsal_song=doomed)
        buffer = self._buffer([self._row([])])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.assertFalse(RehearsalSong.objects.filter(pk=doomed.pk).exists())
        self.assertFalse(Recording.objects.filter(pk=recording.pk).exists())

    def test_a_rehearsal_left_with_no_songs_is_accepted(self):
        """A Buffer with an empty running_order for a Rehearsal that already has no songs saves cleanly."""
        buffer = self._buffer([self._row([])])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.assertEqual(RehearsalSong.objects.filter(rehearsal=self.rehearsal).count(), 0)

    def test_slot_counts_exceeding_the_semester_default_block_the_save(self):
        """Slot counts summing past the Semester's default_song_slot_count is a blocking Validation Error; nothing is written."""
        buffer = self._buffer([self._row([
            RunningOrderRow(rehearsal_song_id=None, song_id=self.song_a.pk, slot_count=3),
            RunningOrderRow(rehearsal_song_id=None, song_id=self.song_b.pk, slot_count=3),
        ])])

        with self.assertRaises(RunningOrderValidationError):
            apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.assertEqual(RehearsalSong.objects.filter(rehearsal=self.rehearsal).count(), 0)

    def test_a_running_order_on_a_row_flagged_dress_blocks_the_save(self):
        """A Running Order attached to a row flagged is_full_setlist=True is a blocking Validation Error; nothing is written."""
        buffer = self._buffer([self._row(
            [RunningOrderRow(rehearsal_song_id=None, song_id=self.song_a.pk, slot_count=1)],
            is_full_setlist=True,
        )])

        with self.assertRaises(RunningOrderValidationError):
            apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.assertEqual(RehearsalSong.objects.filter(rehearsal=self.rehearsal).count(), 0)
        self.rehearsal.refresh_from_db()
        self.assertFalse(self.rehearsal.is_full_setlist)

    def test_a_song_outside_the_semesters_setlist_blocks_the_save(self):
        """A Running Order row naming a Song from a different Semester is a blocking Validation Error; nothing is written."""
        other_semester_song = SongFactory(semester=SemesterFactory(), position=1)
        buffer = self._buffer([self._row([
            RunningOrderRow(rehearsal_song_id=None, song_id=other_semester_song.pk, slot_count=1),
        ])])

        with self.assertRaises(RunningOrderValidationError):
            apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.assertEqual(RehearsalSong.objects.filter(rehearsal=self.rehearsal).count(), 0)

    def test_a_mixed_buffer_of_adds_reorders_and_removals_applies_together(self):
        """One Buffer mixing a removal, a reorder and a brand-new add lands all three in a single call."""
        keep = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song_a, order=1, slot_count=1)
        doomed = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song_b, order=2, slot_count=1)
        buffer = self._buffer([self._row([
            RunningOrderRow(rehearsal_song_id=None, song_id=self.song_c.pk, slot_count=1),
            RunningOrderRow(rehearsal_song_id=keep.pk, song_id=self.song_a.pk, slot_count=1),
        ])])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.assertFalse(RehearsalSong.objects.filter(pk=doomed.pk).exists())
        rehearsal_songs = list(RehearsalSong.objects.filter(rehearsal=self.rehearsal).order_by('order'))
        self.assertEqual([rs.song_id for rs in rehearsal_songs], [self.song_c.pk, self.song_a.pk])
        self.assertEqual([rs.order for rs in rehearsal_songs], [1, 2])

    def test_two_rehearsals_running_orders_are_independent(self):
        """A Buffer touching two Rehearsals applies each one's Running Order independently."""
        other_rehearsal = RehearsalFactory(
            semester=self.semester, date=TOMORROW + timedelta(days=1), start_time=time(18, 0), end_time=time(20, 0),
        )
        buffer = self._buffer([
            self._row([RunningOrderRow(rehearsal_song_id=None, song_id=self.song_a.pk, slot_count=1)]),
            self._row(
                [RunningOrderRow(rehearsal_song_id=None, song_id=self.song_b.pk, slot_count=1)],
                rehearsal_id=other_rehearsal.pk, date=other_rehearsal.date,
                start_time=other_rehearsal.start_time, end_time=other_rehearsal.end_time,
            ),
        ])

        apply_rehearsal_edits(buffer, viewing_semester=self.semester)

        self.assertEqual(RehearsalSong.objects.get(rehearsal=self.rehearsal).song_id, self.song_a.pk)
        self.assertEqual(RehearsalSong.objects.get(rehearsal=other_rehearsal).song_id, self.song_b.pk)
