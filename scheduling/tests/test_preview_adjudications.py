"""`preview_adjudications()`: the Fallout for a candidate Adjudication Buffer, writing nothing (issue #194)."""

from datetime import time

from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import (
    ConflictFactory,
    ConflictWindowFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Conflict
from scheduling.services import (
    AdjudicationBuffer,
    AdjudicationEntry,
    preview_adjudications,
)


class PreviewAdjudicationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Semester/Rehearsal with two Songs and one partial Conflict whose person is assigned to both."""
        cls.semester = SemesterFactory(default_song_slot_count=2)
        cls.rehearsal = RehearsalFactory(
            semester=cls.semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(19, 0),
        )
        cls.song_a = SongFactory(semester=cls.semester)
        cls.song_b = SongFactory(semester=cls.semester)
        RehearsalSongFactory(rehearsal=cls.rehearsal, song=cls.song_a, order=1, slot_count=1)
        RehearsalSongFactory(rehearsal=cls.rehearsal, song=cls.song_b, order=2, slot_count=1)
        cls.person = PersonFactory()
        SongRoleAssignmentFactory(song=cls.song_a, person=cls.person)
        SongRoleAssignmentFactory(song=cls.song_b, person=cls.person)
        cls.conflict = ConflictFactory(person=cls.person, rehearsal=cls.rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=cls.conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))

    def _buffer(self, entries, semester=None, semester_updated_at=None):
        """Build an AdjudicationBuffer for `self.rehearsal`, defaulting to the current Semester stamp."""
        semester = semester or self.semester
        return AdjudicationBuffer(
            rehearsal_id=self.rehearsal.pk,
            semester_id=semester.pk,
            semester_updated_at=semester_updated_at or semester.updated_at,
            entries=entries,
        )

    def test_approving_an_infeasible_conflict_reports_loud_fallout(self):
        """Approving a Conflict no ordering resolves reports loud Fallout naming the person."""
        buffer = self._buffer([AdjudicationEntry(conflict_id=self.conflict.pk, status=Conflict.APPROVED, note='')])

        fallout = preview_adjudications(buffer, rehearsal=self.rehearsal, viewing_semester=self.semester)

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(any(self.person.name in line for line in fallout.loud))

    def test_pending_conflict_reports_no_fallout(self):
        """Leaving the Conflict pending reports no loud or quiet Fallout -- it isn't in the approved set."""
        buffer = self._buffer([AdjudicationEntry(conflict_id=self.conflict.pk, status=Conflict.PENDING, note='')])

        fallout = preview_adjudications(buffer, rehearsal=self.rehearsal, viewing_semester=self.semester)

        self.assertEqual(fallout.loud, [])
        self.assertEqual(fallout.quiet, [])

    def test_writes_nothing_to_the_conflict_row(self):
        """A Preview call never persists the candidate status onto the Conflict row."""
        buffer = self._buffer([AdjudicationEntry(conflict_id=self.conflict.pk, status=Conflict.APPROVED, note='changed')])

        preview_adjudications(buffer, rehearsal=self.rehearsal, viewing_semester=self.semester)

        self.conflict.refresh_from_db()
        self.assertEqual(self.conflict.status, Conflict.PENDING)
        self.assertEqual(self.conflict.adjudication_note, '')

    def test_wrong_semester_id_is_blocked(self):
        """A Buffer whose semester_id doesn't match the viewing Semester is blocked, with no Fallout computed."""
        other_semester = SemesterFactory()
        buffer = self._buffer(
            [AdjudicationEntry(conflict_id=self.conflict.pk, status=Conflict.APPROVED, note='')],
            semester=other_semester,
        )

        fallout = preview_adjudications(buffer, rehearsal=self.rehearsal, viewing_semester=self.semester)

        self.assertTrue(fallout.is_blocked)
        self.assertEqual(fallout.loud, [])

    def test_unknown_conflict_id_is_blocked(self):
        """A Buffer naming a Conflict id that doesn't belong to the Rehearsal is blocked."""
        other_conflict = ConflictFactory()
        buffer = self._buffer([AdjudicationEntry(conflict_id=other_conflict.pk, status=Conflict.APPROVED, note='')])

        fallout = preview_adjudications(buffer, rehearsal=self.rehearsal, viewing_semester=self.semester)

        self.assertTrue(fallout.is_blocked)

    def test_stale_stamp_reports_is_stale_without_blocking(self):
        """A stale semester_updated_at reports is_stale True, but still computes Fallout rather than blocking."""
        stale_stamp = self.semester.updated_at.replace(year=self.semester.updated_at.year - 1)
        buffer = self._buffer(
            [AdjudicationEntry(conflict_id=self.conflict.pk, status=Conflict.APPROVED, note='')],
            semester_updated_at=stale_stamp,
        )

        fallout = preview_adjudications(buffer, rehearsal=self.rehearsal, viewing_semester=self.semester)

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(fallout.is_stale)
        self.assertTrue(any(self.person.name in line for line in fallout.loud))

    def test_no_viewing_semester_is_blocked(self):
        """A None viewing_semester is blocked rather than raising."""
        buffer = self._buffer([AdjudicationEntry(conflict_id=self.conflict.pk, status=Conflict.APPROVED, note='')])

        fallout = preview_adjudications(buffer, rehearsal=self.rehearsal, viewing_semester=None)

        self.assertTrue(fallout.is_blocked)
