"""apply_song_role_assignments(): the semester-wide removal/add write and the two staleness checks (issues #210, #211)."""

from datetime import timedelta

from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
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

    def _buffer(self, removed_assignment_ids=(), added_entries=(), semester=None, updated_at=None):
        """Build an AssignmentEditBuffer against self.semester unless overridden."""
        semester = semester or self.semester
        return AssignmentEditBuffer(
            semester_id=semester.pk,
            semester_updated_at=updated_at if updated_at is not None else semester.updated_at,
            removed_assignment_ids=frozenset(removed_assignment_ids),
            added_entries=frozenset(added_entries),
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

    def test_added_entry_creates_a_new_assignment_for_a_rostered_person(self):
        """An added (song, role, person) triple for a rostered Person creates a new SongRoleAssignment (issue #211)."""
        membership = MembershipFactory(semester=self.semester)
        buffer = self._buffer(added_entries=[(self.song.pk, self.role.pk, membership.person.pk)])

        apply_song_role_assignments(buffer, viewing_semester=self.semester)

        self.assertTrue(
            SongRoleAssignment.objects.filter(song=self.song, role=self.role, person=membership.person).exists()
        )

    def test_added_entry_is_semester_wide_across_every_rehearsal_and_the_concert(self):
        """A picked person appears on the Song for every Rehearsal's grid, since SongRoleAssignment carries no rehearsal FK."""
        RehearsalFactory(semester=self.semester)  # a second Rehearsal, to prove the created row isn't scoped to one
        membership = MembershipFactory(semester=self.semester)
        buffer = self._buffer(added_entries=[(self.song.pk, self.role.pk, membership.person.pk)])

        apply_song_role_assignments(buffer, viewing_semester=self.semester)

        self.assertEqual(
            SongRoleAssignment.objects.filter(
                song=self.song, role=self.role, person=membership.person,
            ).count(),
            1,
        )

    def test_added_entry_for_a_person_who_has_not_declared_the_role_is_flagged_not_blocked(self):
        """Picking a mismatched Person is allowed with no block; the saved row carries the mismatch flag (ADR-0002)."""
        membership = MembershipFactory(semester=self.semester)  # no MembershipRole for self.role
        buffer = self._buffer(added_entries=[(self.song.pk, self.role.pk, membership.person.pk)])

        apply_song_role_assignments(buffer, viewing_semester=self.semester)

        created = SongRoleAssignment.objects.get(song=self.song, role=self.role, person=membership.person)
        self.assertTrue(created.is_role_mismatch)

    def test_added_entry_for_a_non_rostered_person_is_silently_skipped(self):
        """A tampered add naming a Person with no Membership in the Semester is skipped, not created (issue #211)."""
        outsider = PersonFactory()
        buffer = self._buffer(added_entries=[(self.song.pk, self.role.pk, outsider.pk)])

        apply_song_role_assignments(buffer, viewing_semester=self.semester)

        self.assertFalse(SongRoleAssignment.objects.filter(song=self.song, role=self.role, person=outsider).exists())

    def test_added_entry_for_a_foreign_semesters_song_is_silently_skipped(self):
        """A tampered add naming another Semester's Song is skipped, not created."""
        other_semester = SemesterFactory()
        other_song = SongFactory(semester=other_semester)
        membership = MembershipFactory(semester=self.semester)
        buffer = self._buffer(added_entries=[(other_song.pk, self.role.pk, membership.person.pk)])

        apply_song_role_assignments(buffer, viewing_semester=self.semester)

        self.assertFalse(
            SongRoleAssignment.objects.filter(song=other_song, role=self.role, person=membership.person).exists()
        )

    def test_added_entry_duplicating_an_existing_assignment_is_a_no_op(self):
        """Re-adding an already-assigned (song, role, person) triple is a no-op, not an IntegrityError."""
        buffer = self._buffer(added_entries=[(self.song.pk, self.role.pk, self.assignment.person.pk)])

        apply_song_role_assignments(buffer, viewing_semester=self.semester)

        self.assertEqual(
            SongRoleAssignment.objects.filter(song=self.song, role=self.role, person=self.assignment.person).count(),
            1,
        )

    def test_mixed_removal_and_add_buffer_produces_exactly_the_intended_rows_in_one_save(self):
        """A Buffer mixing a removal and an add commits both atomically (issue #211 acceptance)."""
        membership = MembershipFactory(semester=self.semester)
        buffer = self._buffer(
            removed_assignment_ids=[self.assignment.pk],
            added_entries=[(self.song.pk, self.role.pk, membership.person.pk)],
        )

        apply_song_role_assignments(buffer, viewing_semester=self.semester)

        self.assertFalse(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())
        self.assertTrue(
            SongRoleAssignment.objects.filter(song=self.song, role=self.role, person=membership.person).exists()
        )

    def test_add_rejected_when_semester_stamp_is_stale(self):
        """An add is rejected, writing nothing, when the Semester's stamp has moved since the grid was rendered."""
        membership = MembershipFactory(semester=self.semester)
        stale_stamp = self.semester.updated_at - timedelta(days=1)
        buffer = self._buffer(
            added_entries=[(self.song.pk, self.role.pk, membership.person.pk)], updated_at=stale_stamp,
        )

        with self.assertRaises(StaleAssignmentSemesterError):
            apply_song_role_assignments(buffer, viewing_semester=self.semester)

        self.assertFalse(
            SongRoleAssignment.objects.filter(song=self.song, role=self.role, person=membership.person).exists()
        )
