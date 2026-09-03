"""apply_roster_edits(): the batch write, the semester-scoped purge, and the two staleness checks (issue #226)."""

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
)
from scheduling.models import Conflict, Membership, MembershipRole, SongRoleAssignment
from scheduling.services import (
    RosterEditBuffer,
    RosterEditEntry,
    SelfRemovalError,
    StaleRosterSemesterError,
    WrongViewingSemesterError,
    apply_roster_edits,
)


class ApplyRosterEditsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Semester with one Role and one admin Person to submit Buffers as."""
        cls.semester = SemesterFactory()
        cls.role = RoleFactory()
        cls.admin = PersonFactory(is_admin=True)

    def _buffer(self, entries=(), removed_person_ids=(), semester=None, updated_at=None):
        """Build a RosterEditBuffer against self.semester unless overridden."""
        semester = semester or self.semester
        return RosterEditBuffer(
            semester_id=semester.pk,
            semester_updated_at=updated_at if updated_at is not None else semester.updated_at,
            entries=list(entries),
            removed_person_ids=frozenset(removed_person_ids),
        )

    def test_adds_a_new_person_with_declared_roles(self):
        """A Buffer entry for a Person with no existing Membership creates one, with the declared Role set."""
        person = PersonFactory()
        buffer = self._buffer(entries=[RosterEditEntry(person=person, name=person.name, role_ids=frozenset({self.role.pk}))])

        apply_roster_edits(buffer, viewing_semester=self.semester, requesting_admin=self.admin)

        membership = Membership.objects.get(person=person, semester=self.semester)
        self.assertEqual(
            set(MembershipRole.objects.filter(membership=membership).values_list('role_id', flat=True)),
            {self.role.pk},
        )

    def test_name_edit_saves_onto_the_person(self):
        """A Buffer entry carrying a different name updates the Person row."""
        person = PersonFactory(name='Old Name')
        MembershipFactory(person=person, semester=self.semester)
        buffer = self._buffer(entries=[RosterEditEntry(person=person, name='New Name', role_ids=frozenset())])

        apply_roster_edits(buffer, viewing_semester=self.semester, requesting_admin=self.admin)

        person.refresh_from_db()
        self.assertEqual(person.name, 'New Name')

    def test_role_set_change_adds_and_removes_membership_roles(self):
        """A Buffer entry's role_ids fully replaces the Membership's declared Roles: additions and removals both apply."""
        keep_role = RoleFactory()
        drop_role = RoleFactory()
        add_role = RoleFactory()
        person = PersonFactory()
        membership = MembershipFactory(person=person, semester=self.semester)
        MembershipRoleFactory(membership=membership, role=keep_role)
        MembershipRoleFactory(membership=membership, role=drop_role)
        buffer = self._buffer(entries=[
            RosterEditEntry(person=person, name=person.name, role_ids=frozenset({keep_role.pk, add_role.pk})),
        ])

        apply_roster_edits(buffer, viewing_semester=self.semester, requesting_admin=self.admin)

        self.assertEqual(
            set(MembershipRole.objects.filter(membership=membership).values_list('role_id', flat=True)),
            {keep_role.pk, add_role.pk},
        )

    def test_role_removal_reevaluates_is_role_mismatch_through_the_model(self):
        """Dropping a declared Role flips is_role_mismatch on that Person's existing SongRoleAssignment for it, via the model's own signal."""
        person = PersonFactory()
        membership = MembershipFactory(person=person, semester=self.semester)
        MembershipRoleFactory(membership=membership, role=self.role)
        song = SongFactory(semester=self.semester)
        assignment = SongRoleAssignmentFactory(song=song, role=self.role, person=person)
        self.assertFalse(assignment.is_role_mismatch)
        buffer = self._buffer(entries=[RosterEditEntry(person=person, name=person.name, role_ids=frozenset())])

        apply_roster_edits(buffer, viewing_semester=self.semester, requesting_admin=self.admin)

        assignment.refresh_from_db()
        self.assertTrue(assignment.is_role_mismatch)

    def test_removal_purges_membership_roles_assignments_and_conflicts_for_that_semester(self):
        """Removing a Person deletes their Membership, declared Roles, Role Assignments and Conflicts scoped to the Semester, with non-trivial counts."""
        person = PersonFactory()
        membership = MembershipFactory(person=person, semester=self.semester)
        MembershipRoleFactory(membership=membership, role=self.role)
        song_a = SongFactory(semester=self.semester)
        song_b = SongFactory(semester=self.semester)
        SongRoleAssignmentFactory(song=song_a, person=person)
        SongRoleAssignmentFactory(song=song_b, person=person)
        rehearsal_a = RehearsalFactory(semester=self.semester)
        rehearsal_b = RehearsalFactory(semester=self.semester)
        ConflictFactory(person=person, rehearsal=rehearsal_a)
        ConflictFactory(person=person, rehearsal=rehearsal_b)
        buffer = self._buffer(removed_person_ids=[person.pk])

        apply_roster_edits(buffer, viewing_semester=self.semester, requesting_admin=self.admin)

        self.assertFalse(Membership.objects.filter(person=person, semester=self.semester).exists())
        self.assertFalse(MembershipRole.objects.filter(membership__person=person).exists())
        self.assertEqual(SongRoleAssignment.objects.filter(person=person, song__semester=self.semester).count(), 0)
        self.assertEqual(Conflict.objects.filter(person=person, rehearsal__semester=self.semester).count(), 0)

    def test_removal_succeeds_despite_existing_role_assignments(self):
        """A removal is never blocked by standing Role Assignments — it deletes them instead."""
        person = PersonFactory()
        MembershipFactory(person=person, semester=self.semester)
        song = SongFactory(semester=self.semester)
        SongRoleAssignmentFactory(song=song, person=person)
        buffer = self._buffer(removed_person_ids=[person.pk])

        apply_roster_edits(buffer, viewing_semester=self.semester, requesting_admin=self.admin)

        self.assertFalse(Membership.objects.filter(person=person, semester=self.semester).exists())

    def test_removal_leaves_a_prior_semesters_rows_for_the_same_person_untouched(self):
        """Purging a Person from the viewing Semester leaves their prior Semester's Membership, Roles, Assignments and Conflicts standing."""
        person = PersonFactory()
        prior_semester = SemesterFactory()
        prior_membership = MembershipFactory(person=person, semester=prior_semester)
        MembershipRoleFactory(membership=prior_membership, role=self.role)
        prior_song = SongFactory(semester=prior_semester)
        prior_assignment = SongRoleAssignmentFactory(song=prior_song, person=person)
        prior_rehearsal = RehearsalFactory(semester=prior_semester)
        prior_conflict = ConflictFactory(person=person, rehearsal=prior_rehearsal)
        MembershipFactory(person=person, semester=self.semester)
        buffer = self._buffer(removed_person_ids=[person.pk])

        apply_roster_edits(buffer, viewing_semester=self.semester, requesting_admin=self.admin)

        self.assertTrue(Membership.objects.filter(pk=prior_membership.pk).exists())
        self.assertTrue(MembershipRole.objects.filter(membership=prior_membership, role=self.role).exists())
        self.assertTrue(SongRoleAssignment.objects.filter(pk=prior_assignment.pk).exists())
        self.assertTrue(Conflict.objects.filter(pk=prior_conflict.pk).exists())

    def test_a_failure_mid_batch_applies_nothing(self):
        """A stale stamp fails the whole Buffer: no add, removal, Role change or name edit lands, even ones ordered before it in the diff."""
        added_person = PersonFactory()
        kept_person = PersonFactory(name='Original Name')
        MembershipFactory(person=kept_person, semester=self.semester)
        removed_person = PersonFactory()
        MembershipFactory(person=removed_person, semester=self.semester)
        buffer = self._buffer(
            entries=[
                RosterEditEntry(person=added_person, name=added_person.name, role_ids=frozenset()),
                RosterEditEntry(person=kept_person, name='Changed Name', role_ids=frozenset({self.role.pk})),
            ],
            removed_person_ids=[removed_person.pk],
            updated_at=self.semester.updated_at.replace(year=self.semester.updated_at.year - 1),
        )

        with self.assertRaises(StaleRosterSemesterError):
            apply_roster_edits(buffer, viewing_semester=self.semester, requesting_admin=self.admin)

        self.assertFalse(Membership.objects.filter(person=added_person, semester=self.semester).exists())
        kept_person.refresh_from_db()
        self.assertEqual(kept_person.name, 'Original Name')
        self.assertFalse(MembershipRole.objects.filter(membership__person=kept_person).exists())
        self.assertTrue(Membership.objects.filter(person=removed_person, semester=self.semester).exists())

    def test_stale_semester_stamp_names_what_happened(self):
        """A stale-stamp rejection carries a message describing the problem, not a bare exception."""
        stale_stamp = self.semester.updated_at.replace(year=self.semester.updated_at.year - 1)
        buffer = self._buffer(updated_at=stale_stamp)

        with self.assertRaisesMessage(StaleRosterSemesterError, 'changed while you were editing'):
            apply_roster_edits(buffer, viewing_semester=self.semester, requesting_admin=self.admin)

    def test_wrong_viewing_semester_hard_fails(self):
        """A Buffer whose semester_id doesn't match the session-scoped viewing Semester is rejected before any write."""
        other_semester = SemesterFactory()
        buffer = self._buffer(semester=other_semester)

        with self.assertRaises(WrongViewingSemesterError):
            apply_roster_edits(buffer, viewing_semester=self.semester, requesting_admin=self.admin)

    def test_admin_cannot_remove_their_own_person(self):
        """A Buffer removing the requesting admin's own Person is rejected and writes nothing."""
        MembershipFactory(person=self.admin, semester=self.semester)
        buffer = self._buffer(removed_person_ids=[self.admin.pk])

        with self.assertRaises(SelfRemovalError):
            apply_roster_edits(buffer, viewing_semester=self.semester, requesting_admin=self.admin)

        self.assertTrue(Membership.objects.filter(person=self.admin, semester=self.semester).exists())

    def test_bumps_the_semester_stamp_on_a_successful_save(self):
        """A successful apply advances the Semester's updated_at, so a second Buffer built from the old stamp is now stale."""
        original_stamp = self.semester.updated_at
        buffer = self._buffer()

        apply_roster_edits(buffer, viewing_semester=self.semester, requesting_admin=self.admin)

        self.semester.refresh_from_db()
        self.assertGreater(self.semester.updated_at, original_stamp)
