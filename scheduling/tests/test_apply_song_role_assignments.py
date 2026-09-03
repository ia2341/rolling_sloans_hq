"""apply_song_role_assignments(): the semester-wide removal write and the two staleness checks (issue #210)."""

from datetime import timedelta

from django.test import TestCase

from scheduling.factories import (
    RehearsalFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import SongRoleAssignment
from scheduling.services import (
    AssignmentEditBuffer,
    StaleAssignmentSemesterError,
    WrongViewingSemesterError,
    apply_song_role_assignments,
)


class ApplySongRoleAssignmentsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Semester with one Song, one Role and one existing SongRoleAssignment."""
        cls.semester = SemesterFactory()
        cls.role = RoleFactory()
        cls.song = SongFactory(semester=cls.semester)
        cls.assignment = SongRoleAssignmentFactory(song=cls.song, role=cls.role)

    def _buffer(self, removed_assignment_ids=(), semester=None, updated_at=None):
        """Build an AssignmentEditBuffer against self.semester unless overridden."""
        semester = semester or self.semester
        return AssignmentEditBuffer(
            semester_id=semester.pk,
            semester_updated_at=updated_at if updated_at is not None else semester.updated_at,
            removed_assignment_ids=frozenset(removed_assignment_ids),
        )

    def test_removes_the_buffered_assignment(self):
        """A Buffer naming an existing SongRoleAssignment's pk deletes that row."""
        buffer = self._buffer(removed_assignment_ids=[self.assignment.pk])

        apply_song_role_assignments(buffer, viewing_semester=self.semester)

        self.assertFalse(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())

    def test_removal_is_semester_wide_across_every_rehearsal_and_the_concert(self):
        """Removing an assignment through one Rehearsal's grid deletes the Song-level row entirely, not a per-rehearsal copy.

        SongRoleAssignment carries no rehearsal FK (ADR-0009), so the same
        removed pk is simply gone from every Rehearsal's grid and the
        concert setlist for that Song — there is no other row to check.
        """
        RehearsalFactory(semester=self.semester)
        RehearsalFactory(semester=self.semester)
        buffer = self._buffer(removed_assignment_ids=[self.assignment.pk])

        apply_song_role_assignments(buffer, viewing_semester=self.semester)

        self.assertEqual(SongRoleAssignment.objects.filter(song=self.song, role=self.role).count(), 0)

    def test_untouched_assignment_survives(self):
        """An assignment whose pk isn't in the Buffer is left alone."""
        survivor = SongRoleAssignmentFactory(song=self.song, role=self.role)
        buffer = self._buffer(removed_assignment_ids=[self.assignment.pk])

        apply_song_role_assignments(buffer, viewing_semester=self.semester)

        self.assertTrue(SongRoleAssignment.objects.filter(pk=survivor.pk).exists())

    def test_empty_removal_set_writes_nothing_but_still_bumps_the_stamp(self):
        """An empty Buffer is a legal no-op save: nothing is deleted, but the Semester's stamp still advances."""
        old_updated_at = self.semester.updated_at
        buffer = self._buffer(removed_assignment_ids=[])

        apply_song_role_assignments(buffer, viewing_semester=self.semester)

        self.assertTrue(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())
        self.semester.refresh_from_db()
        self.assertGreater(self.semester.updated_at, old_updated_at)

    def test_removal_scoped_to_the_semester_ignores_a_foreign_assignment_id(self):
        """An assignment id belonging to a different Semester's Song is never deleted, even if named in the Buffer."""
        other_semester = SemesterFactory()
        other_song = SongFactory(semester=other_semester)
        foreign_assignment = SongRoleAssignmentFactory(song=other_song, role=self.role)
        buffer = self._buffer(removed_assignment_ids=[foreign_assignment.pk])

        apply_song_role_assignments(buffer, viewing_semester=self.semester)

        self.assertTrue(SongRoleAssignment.objects.filter(pk=foreign_assignment.pk).exists())

    def test_no_semester_row_lock_is_taken(self):
        """Nothing here renumbers positions, so it never calls select_for_update — asserted via a plain successful save."""
        buffer = self._buffer(removed_assignment_ids=[self.assignment.pk])

        apply_song_role_assignments(buffer, viewing_semester=self.semester)

        self.semester.refresh_from_db()

    def test_stale_semester_stamp_rejects_and_writes_nothing(self):
        """A Buffer stamped against an old Semester.updated_at is rejected before anything is deleted."""
        stale_stamp = self.semester.updated_at - timedelta(days=1)
        buffer = self._buffer(removed_assignment_ids=[self.assignment.pk], updated_at=stale_stamp)

        with self.assertRaises(StaleAssignmentSemesterError):
            apply_song_role_assignments(buffer, viewing_semester=self.semester)

        self.assertTrue(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())

    def test_stale_semester_stamp_names_what_happened(self):
        """A stale-stamp rejection carries a message describing the problem, not a bare exception."""
        stale_stamp = self.semester.updated_at - timedelta(days=1)
        buffer = self._buffer(updated_at=stale_stamp)

        with self.assertRaisesMessage(StaleAssignmentSemesterError, 'changed while you were editing'):
            apply_song_role_assignments(buffer, viewing_semester=self.semester)

    def test_wrong_viewing_semester_hard_fails_and_writes_nothing(self):
        """A Buffer whose semester_id doesn't match the session-scoped viewing Semester is rejected before any write."""
        other_semester = SemesterFactory()
        buffer = self._buffer(semester=other_semester, removed_assignment_ids=[self.assignment.pk])

        with self.assertRaises(WrongViewingSemesterError):
            apply_song_role_assignments(buffer, viewing_semester=self.semester)

        self.assertTrue(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())

    def test_none_viewing_semester_hard_fails(self):
        """A None viewing Semester (nothing published, no admin selection) rejects any Buffer outright."""
        buffer = self._buffer(removed_assignment_ids=[self.assignment.pk])

        with self.assertRaises(WrongViewingSemesterError):
            apply_song_role_assignments(buffer, viewing_semester=None)
