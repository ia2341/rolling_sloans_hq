"""preview_rehearsal_edits(): the ADR-0008 real-write-then-rollback wrapper, and the Fallout it computes (issues #219, #221)."""

from datetime import time, timedelta
from unittest import mock

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from scheduling.factories import (
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.models import Rehearsal
from scheduling.services import (
    RehearsalEditBuffer,
    RehearsalEditRow,
    RunningOrderRow,
    preview_rehearsal_edits,
)

TOMORROW = timezone.localdate() + timedelta(days=1)
NEXT_WEEK = timezone.localdate() + timedelta(days=7)


class PreviewRehearsalEditsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Semester with one existing future Rehearsal."""
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, date=TOMORROW, start_time=time(18, 0))

    def _preview(self, buffer):
        """Call preview_rehearsal_edits() inside a transaction the test itself rolls back, per its docstring's requirement."""
        with transaction.atomic():
            fallout = preview_rehearsal_edits(buffer, viewing_semester=self.semester)
            transaction.set_rollback(True)
        return fallout

    def test_writes_nothing_for_a_buffer_with_a_creation_and_a_mutation_together(self):
        """A preview of a new row plus an edited existing row leaves every Rehearsal row and the Semester stamp untouched."""
        count_before = Rehearsal.objects.count()
        stamp_before = self.semester.updated_at
        buffer = RehearsalEditBuffer(
            semester_id=self.semester.pk,
            semester_updated_at=self.semester.updated_at,
            rows=[
                RehearsalEditRow(
                    rehearsal_id=None, date=NEXT_WEEK, start_time=time(19, 0), end_time=time(21, 0),
                    is_full_setlist=False, setup_grace_minutes=None, teardown_grace_minutes=None,
                    arrival_buffer_minutes=None, departure_buffer_minutes=None,
                ),
                RehearsalEditRow(
                    rehearsal_id=self.rehearsal.pk, date=TOMORROW, start_time=time(20, 0), end_time=time(22, 0),
                    is_full_setlist=False, setup_grace_minutes=None, teardown_grace_minutes=None,
                    arrival_buffer_minutes=None, departure_buffer_minutes=None,
                ),
            ],
        )

        self._preview(buffer)

        self.assertEqual(Rehearsal.objects.count(), count_before)
        self.rehearsal.refresh_from_db()
        self.assertEqual(self.rehearsal.start_time, time(18, 0))
        self.semester.refresh_from_db()
        self.assertEqual(self.semester.updated_at, stamp_before)


class RehearsalEditFalloutTests(TestCase):
    """The loud/quiet Fallout tiers `preview_rehearsal_edits()` computes, and the doomed-Recording groups it surfaces (issue #221)."""

    @classmethod
    def setUpTestData(cls):
        """Build a Semester with one existing future Rehearsal."""
        cls.semester = SemesterFactory(default_song_slot_count=5)
        cls.rehearsal = RehearsalFactory(semester=cls.semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))

    def _preview(self, buffer):
        """Call preview_rehearsal_edits() inside a transaction the test itself rolls back, per its docstring's requirement."""
        with transaction.atomic():
            fallout = preview_rehearsal_edits(buffer, viewing_semester=self.semester)
            transaction.set_rollback(True)
        return fallout

    def _buffer(self, rows=(), deleted_rehearsal_ids=()):
        """Build a RehearsalEditBuffer against self.semester."""
        return RehearsalEditBuffer(
            semester_id=self.semester.pk, semester_updated_at=self.semester.updated_at,
            rows=list(rows), deleted_rehearsal_ids=list(deleted_rehearsal_ids),
        )

    def _unchanged_row(self, **overrides):
        """Build a RehearsalEditRow that resaves self.rehearsal unchanged unless overridden."""
        defaults = {
            'rehearsal_id': self.rehearsal.pk, 'date': self.rehearsal.date,
            'start_time': self.rehearsal.start_time, 'end_time': self.rehearsal.end_time,
            'is_full_setlist': False, 'setup_grace_minutes': None, 'teardown_grace_minutes': None,
            'arrival_buffer_minutes': None, 'departure_buffer_minutes': None, 'running_order': [],
        }
        defaults.update(overrides)
        return RehearsalEditRow(**defaults)

    @mock.patch('scheduling.services._recording_storage')
    def test_deleting_a_rehearsal_with_recordings_reports_a_doomed_group(self, recording_storage):
        """Deleting a Rehearsal with Recordings surfaces a DoomedRecordingGroup naming its date and counts."""
        song = SongFactory(semester=self.semester)
        rehearsal_song = RehearsalSongFactory(rehearsal=self.rehearsal, song=song, order=1)
        RecordingFactory(rehearsal_song=rehearsal_song)
        RecordingFactory(rehearsal_song=rehearsal_song)
        buffer = self._buffer(deleted_rehearsal_ids=[self.rehearsal.pk])

        fallout = self._preview(buffer)

        self.assertFalse(fallout.is_blocked)
        self.assertEqual(len(fallout.doomed_recording_groups), 1)
        group = fallout.doomed_recording_groups[0]
        self.assertEqual(group.recording_count, 2)
        self.assertEqual(str(self.rehearsal.date), group.label)
        self.assertTrue(any('will be destroyed' in line for line in fallout.loud))

    @mock.patch('scheduling.services._recording_storage')
    def test_deleting_a_rehearsal_with_no_recordings_reports_no_doomed_group(self, recording_storage):
        """Deleting a Rehearsal with no Recordings is Fallout-silent on the destructive-save front."""
        buffer = self._buffer(deleted_rehearsal_ids=[self.rehearsal.pk])

        fallout = self._preview(buffer)

        self.assertEqual(fallout.doomed_recording_groups, [])

    @mock.patch('scheduling.services._recording_storage')
    def test_flipping_a_rehearsal_to_dress_reports_its_recordings_as_doomed(self, recording_storage):
        """A row flipped to is_full_setlist=True (with an empty Running Order) destroys its RehearsalSongs' Recordings (ADR 0003)."""
        song = SongFactory(semester=self.semester)
        rehearsal_song = RehearsalSongFactory(rehearsal=self.rehearsal, song=song, order=1)
        RecordingFactory(rehearsal_song=rehearsal_song)
        buffer = self._buffer(rows=[self._unchanged_row(is_full_setlist=True, running_order=[])])

        fallout = self._preview(buffer)

        self.assertEqual(len(fallout.doomed_recording_groups), 1)
        self.assertEqual(fallout.doomed_recording_groups[0].recording_count, 1)

    @mock.patch('scheduling.services._recording_storage')
    def test_a_retimed_rehearsal_names_the_old_and_new_slot_for_its_recordings(self, recording_storage):
        """Re-timing a Rehearsal (without removing the song) reports a loud line naming the old and new slot."""
        song = SongFactory(semester=self.semester, title='Song A')
        rehearsal_song = RehearsalSongFactory(rehearsal=self.rehearsal, song=song, order=1, slot_count=1)
        RecordingFactory(rehearsal_song=rehearsal_song)
        buffer = self._buffer(rows=[self._unchanged_row(
            start_time=time(19, 0), end_time=time(21, 0),
            running_order=[RunningOrderRow(rehearsal_song_id=rehearsal_song.pk, song_id=song.pk, slot_count=1)],
        )])

        fallout = self._preview(buffer)

        self.assertFalse(fallout.doomed_recording_groups)
        self.assertTrue(any('1 recording on Song A was made against' in line and 'now' in line for line in fallout.loud))

    @mock.patch('scheduling.services._recording_storage')
    def test_a_non_dress_rehearsal_left_with_zero_songs_is_quiet_fallout(self, recording_storage):
        """A non-Dress Rehearsal whose Running Order buffer is empty is flagged quiet, not loud."""
        buffer = self._buffer(rows=[self._unchanged_row(running_order=[])])

        fallout = self._preview(buffer)

        self.assertTrue(any('no songs scheduled' in line for line in fallout.quiet))

    def test_a_blocked_buffer_reports_no_fallout_at_all(self):
        """A Buffer that apply_rehearsal_edits() would hard-reject is reported as is_blocked with empty Fallout lists."""
        Rehearsal.objects.filter(pk=self.rehearsal.pk).update(date=timezone.localdate() - timedelta(days=1))
        buffer = self._buffer(rows=[self._unchanged_row(date=timezone.localdate() - timedelta(days=1))])

        fallout = self._preview(buffer)

        self.assertTrue(fallout.is_blocked)
        self.assertEqual(fallout.loud, [])
        self.assertEqual(fallout.quiet, [])
        self.assertEqual(fallout.doomed_recording_groups, [])
