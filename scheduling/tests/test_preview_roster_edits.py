"""preview_roster_edits(): Fallout tiering computed by running the real apply and rolling it back (issue #228, ADR 0008)."""

from django.db import transaction
from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import (
    ConflictFactory,
    MembershipFactory,
    MembershipRoleFactory,
    RehearsalFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import (
    Conflict,
    Membership,
    MembershipRole,
    SongRoleAssignment,
)
from scheduling.services import (
    RosterEditBuffer,
    RosterEditEntry,
    preview_roster_edits,
)


class PreviewRosterEditsTests(TestCase):
    def setUp(self):
        """Build a Semester with one Role and one admin Person to submit Buffers as."""
        self.semester = SemesterFactory()
        self.role = RoleFactory()
        self.admin = PersonFactory(is_admin=True)

    def _buffer(self, entries=(), removed_person_ids=(), semester=None, updated_at=None):
        """Build a RosterEditBuffer against self.semester unless overridden."""
        semester = semester or self.semester
        return RosterEditBuffer(
            semester_id=semester.pk,
            semester_updated_at=updated_at if updated_at is not None else semester.updated_at,
            entries=list(entries),
            removed_person_ids=frozenset(removed_person_ids),
        )

    def _preview(self, buffer, requesting_admin=None):
        """Call preview_roster_edits() inside a transaction the test itself rolls back, per its docstring's requirement."""
        requesting_admin = requesting_admin or self.admin
        with transaction.atomic():
            fallout = preview_roster_edits(buffer, viewing_semester=self.semester, requesting_admin=requesting_admin)
            transaction.set_rollback(True)
        return fallout

    def _assert_nothing_moved(self, membership_count, role_count, assignment_count, conflict_count, stamp):
        """Assert the row counts and Semester stamp given are exactly what the DB holds now."""
        self.assertEqual(Membership.objects.count(), membership_count)
        self.assertEqual(MembershipRole.objects.count(), role_count)
        self.assertEqual(SongRoleAssignment.objects.count(), assignment_count)
        self.assertEqual(Conflict.objects.count(), conflict_count)
        self.semester.refresh_from_db()
        self.assertEqual(self.semester.updated_at, stamp)

    def test_writes_nothing(self):
        """A preview of an add+mutation+removal batch leaves every row count and the Semester stamp untouched."""
        added = PersonFactory()
        kept = PersonFactory(name='Kept Person')
        MembershipFactory(person=kept, semester=self.semester)
        removed = PersonFactory()
        MembershipFactory(person=removed, semester=self.semester)
        counts_before = (
            Membership.objects.count(), MembershipRole.objects.count(),
            SongRoleAssignment.objects.count(), Conflict.objects.count(),
        )
        stamp_before = self.semester.updated_at
        buffer = self._buffer(
            entries=[
                RosterEditEntry(person=added, name=added.name, role_ids=frozenset()),
                RosterEditEntry(person=kept, name='Changed Name', role_ids=frozenset({self.role.pk})),
            ],
            removed_person_ids=[removed.pk],
        )

        self._preview(buffer)

        self._assert_nothing_moved(*counts_before, stamp_before)

    def test_pending_adds_lists_a_new_person(self):
        """A Buffer entry with no existing Membership shows up in pending_adds."""
        added = PersonFactory(name='Brand New')
        buffer = self._buffer(entries=[RosterEditEntry(person=added, name=added.name, role_ids=frozenset())])

        fallout = self._preview(buffer)

        self.assertIn('Brand New', fallout.pending_adds)
        self.assertFalse(fallout.is_blocked)

    def test_pending_name_edit_and_role_change_are_reported(self):
        """A mutation to an existing Membership shows up in pending_name_edits and pending_role_changes."""
        person = PersonFactory(name='Old Name')
        membership = MembershipFactory(person=person, semester=self.semester)
        other_role = RoleFactory()
        MembershipRoleFactory(membership=membership, role=other_role)
        buffer = self._buffer(entries=[
            RosterEditEntry(person=person, name='New Name', role_ids=frozenset({self.role.pk})),
        ])

        fallout = self._preview(buffer)

        self.assertTrue(any('New Name' in line for line in fallout.pending_name_edits))
        self.assertTrue(any('New Name' in line for line in fallout.pending_role_changes))

    def test_pending_removals_carries_name_and_email(self):
        """A Buffer removal shows up in pending_removals with the removed Person's name and email."""
        removed = PersonFactory(name='Gone Person')
        MembershipFactory(person=removed, semester=self.semester)
        buffer = self._buffer(removed_person_ids=[removed.pk])

        fallout = self._preview(buffer)

        self.assertEqual(len(fallout.pending_removals), 1)
        removal = fallout.pending_removals[0]
        self.assertEqual(removal.name, 'Gone Person')
        self.assertEqual(removal.email, removed.email)

    def test_loud_fallout_counts_destroyed_assignments_and_conflicts(self):
        """A removal's loud Fallout names the count of Role Assignments destroyed and Conflicts deleted, plural-correct."""
        removed = PersonFactory(name='Multi Removal')
        MembershipFactory(person=removed, semester=self.semester)
        song_a = SongFactory(semester=self.semester)
        song_b = SongFactory(semester=self.semester)
        SongRoleAssignmentFactory(song=song_a, person=removed)
        SongRoleAssignmentFactory(song=song_b, person=removed)
        rehearsal_a = RehearsalFactory(semester=self.semester)
        rehearsal_b = RehearsalFactory(semester=self.semester)
        ConflictFactory(person=removed, rehearsal=rehearsal_a)
        ConflictFactory(person=removed, rehearsal=rehearsal_b)
        buffer = self._buffer(removed_person_ids=[removed.pk])

        fallout = self._preview(buffer)

        self.assertTrue(any('2 Role Assignment' in line and '2 Conflict' in line for line in fallout.loud))

    def test_loud_fallout_names_a_song_left_unfillable(self):
        """A removal that drops a Song's only Role Assignment for a Requirement names that Song and Role as unfillable."""
        removed = PersonFactory()
        MembershipFactory(person=removed, semester=self.semester)
        song = SongFactory(semester=self.semester, title='Only Song')
        SongRoleRequirementFactory(song=song, role=self.role, count=1)
        SongRoleAssignmentFactory(song=song, role=self.role, person=removed)
        buffer = self._buffer(removed_person_ids=[removed.pk])

        fallout = self._preview(buffer)

        self.assertTrue(any('Only Song' in line and self.role.name in line for line in fallout.loud))

    def test_quiet_fallout_flags_a_person_with_no_declared_roles(self):
        """A Role change leaving a Person's Membership with zero declared Roles reports quiet Fallout."""
        person = PersonFactory(name='No Roles Left')
        membership = MembershipFactory(person=person, semester=self.semester)
        MembershipRoleFactory(membership=membership, role=self.role)
        buffer = self._buffer(entries=[RosterEditEntry(person=person, name=person.name, role_ids=frozenset())])

        fallout = self._preview(buffer)

        self.assertTrue(any('No Roles Left' in line for line in fallout.quiet))

    def test_quiet_fallout_flags_a_newly_mismatched_assignment(self):
        """Dropping a declared Role that an existing SongRoleAssignment relies on reports quiet Fallout."""
        person = PersonFactory(name='Mismatch Person')
        membership = MembershipFactory(person=person, semester=self.semester)
        MembershipRoleFactory(membership=membership, role=self.role)
        song = SongFactory(semester=self.semester, title='Mismatch Song')
        assignment = SongRoleAssignmentFactory(song=song, role=self.role, person=person)
        self.assertFalse(assignment.is_role_mismatch)
        buffer = self._buffer(entries=[RosterEditEntry(person=person, name=person.name, role_ids=frozenset())])

        fallout = self._preview(buffer)

        self.assertTrue(any('Mismatch Person' in line and 'Mismatch Song' in line for line in fallout.quiet))
        assignment.refresh_from_db()
        self.assertFalse(assignment.is_role_mismatch)

    def test_wrong_viewing_semester_is_blocked_not_fallout(self):
        """A Buffer whose semester_id doesn't match the viewing Semester is reported as blocked, with no Fallout computed."""
        other_semester = SemesterFactory()
        buffer = self._buffer(semester=other_semester)

        fallout = self._preview(buffer)

        self.assertTrue(fallout.is_blocked)
        self.assertIn("doesn't match", fallout.block_message)
        self.assertEqual(fallout.loud, [])
        self.assertEqual(fallout.quiet, [])

    def test_self_removal_is_blocked_not_fallout(self):
        """A Buffer removing the requesting admin's own Person is reported as blocked, with no Fallout computed."""
        MembershipFactory(person=self.admin, semester=self.semester)
        buffer = self._buffer(removed_person_ids=[self.admin.pk])

        fallout = self._preview(buffer)

        self.assertTrue(fallout.is_blocked)
        self.assertIn('cannot remove their own', fallout.block_message)

    def test_is_stale_true_when_semester_updated_at_moved(self):
        """A Buffer built against a stale Semester.updated_at reports is_stale True, without blocking."""
        stale_stamp = self.semester.updated_at.replace(year=self.semester.updated_at.year - 1)
        buffer = self._buffer(updated_at=stale_stamp)

        fallout = self._preview(buffer)

        self.assertTrue(fallout.is_stale)
        self.assertFalse(fallout.is_blocked)

    def test_is_stale_false_when_semester_updated_at_matches(self):
        """A Buffer built against the current Semester.updated_at reports is_stale False."""
        buffer = self._buffer()

        fallout = self._preview(buffer)

        self.assertFalse(fallout.is_stale)

    def test_preview_does_not_advance_the_semester_stamp(self):
        """Even though the real apply runs, rolling back the caller's transaction leaves Semester.updated_at untouched."""
        original_stamp = self.semester.updated_at
        buffer = self._buffer()

        self._preview(buffer)

        self.semester.refresh_from_db()
        self.assertEqual(self.semester.updated_at, original_stamp)
