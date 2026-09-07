"""SongRoleAssignment + role-mismatch flag (issue #35, repointed to PersonRole by issue #377)."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    PersonRoleFactory,
    RoleFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import SongRoleAssignment, SongRoleRequirement


class SongRoleAssignmentMismatchTests(TestCase):
    def test_assignment_without_declared_role_is_flagged_mismatched(self):
        """Assigning a Person to a Role they haven't declared sets is_role_mismatch=True."""
        role = RoleFactory()
        song = SongFactory()
        person = PersonFactory()
        MembershipFactory(person=person, semester=song.semester)  # no PersonRole declared

        assignment = SongRoleAssignmentFactory(song=song, role=role, person=person)

        self.assertTrue(assignment.is_role_mismatch)

    def test_assignment_with_declared_role_is_not_flagged(self):
        """Assigning a Person to a Role they've declared (person-level, per ADR-0014) is not flagged."""
        role = RoleFactory()
        song = SongFactory()
        person = PersonFactory()
        MembershipFactory(person=person, semester=song.semester)
        PersonRoleFactory(person=person, role=role)

        assignment = SongRoleAssignmentFactory(song=song, role=role, person=person)

        self.assertFalse(assignment.is_role_mismatch)

    def test_mismatch_clears_when_matching_role_is_later_declared(self):
        """Declaring the matching PersonRole after the fact clears an existing mismatch flag."""
        role = RoleFactory()
        song = SongFactory()
        person = PersonFactory()
        MembershipFactory(person=person, semester=song.semester)
        assignment = SongRoleAssignmentFactory(song=song, role=role, person=person)
        self.assertTrue(assignment.is_role_mismatch)

        PersonRoleFactory(person=person, role=role)

        reloaded = SongRoleAssignment.objects.get(pk=assignment.pk)
        self.assertFalse(reloaded.is_role_mismatch)

    def test_mismatch_reappears_when_declared_role_is_removed(self):
        """Removing the matching PersonRole re-flags an existing assignment as mismatched."""
        role = RoleFactory()
        song = SongFactory()
        person = PersonFactory()
        MembershipFactory(person=person, semester=song.semester)
        person_role = PersonRoleFactory(person=person, role=role)
        assignment = SongRoleAssignmentFactory(song=song, role=role, person=person)
        self.assertFalse(assignment.is_role_mismatch)

        person_role.delete()

        reloaded = SongRoleAssignment.objects.get(pk=assignment.pk)
        self.assertTrue(reloaded.is_role_mismatch)

    def test_unrelated_person_role_change_does_not_affect_other_assignments(self):
        """A PersonRole change for one Person/Role doesn't touch another Person's assignment."""
        role = RoleFactory()
        song = SongFactory()
        watched_person = PersonFactory()
        other_person = PersonFactory()
        MembershipFactory(person=watched_person, semester=song.semester)
        MembershipFactory(person=other_person, semester=song.semester)
        assignment = SongRoleAssignmentFactory(song=song, role=role, person=watched_person)
        self.assertTrue(assignment.is_role_mismatch)

        PersonRoleFactory(person=other_person, role=role)

        reloaded = SongRoleAssignment.objects.get(pk=assignment.pk)
        self.assertTrue(reloaded.is_role_mismatch)

    def test_person_role_declared_with_no_membership_at_all_still_clears_mismatch(self):
        """PersonRole carries no Semester dimension (ADR-0014), so declaring it needs no Membership to clear a mismatch."""
        role = RoleFactory()
        song = SongFactory()
        person = PersonFactory()  # no Membership at all
        assignment = SongRoleAssignmentFactory(song=song, role=role, person=person)
        self.assertTrue(assignment.is_role_mismatch)

        PersonRoleFactory(person=person, role=role)

        reloaded = SongRoleAssignment.objects.get(pk=assignment.pk)
        self.assertFalse(reloaded.is_role_mismatch)


class SongRoleAssignmentUniquenessTests(TestCase):
    def test_duplicate_song_role_person_is_rejected(self):
        """A second assignment for the same (song, role, person) triple raises IntegrityError."""
        song = SongFactory()
        role = RoleFactory()
        person = PersonFactory()
        SongRoleAssignmentFactory(song=song, role=role, person=person)

        with self.assertRaises(IntegrityError), transaction.atomic():
            SongRoleAssignmentFactory(song=song, role=role, person=person)


class SongRoleAssignmentMultipleAssignmentsTests(TestCase):
    def test_same_person_can_hold_multiple_assignments_across_songs_and_roles(self):
        """The same Person can hold assignments for multiple roles, and on multiple songs."""
        person = PersonFactory()
        singer = RoleFactory(name='Singer')
        guitarist = RoleFactory(name='Guitarist')
        song_one = SongFactory()
        song_two = SongFactory()

        SongRoleAssignmentFactory(song=song_one, role=singer, person=person)
        SongRoleAssignmentFactory(song=song_one, role=guitarist, person=person)
        SongRoleAssignmentFactory(song=song_two, role=singer, person=person)

        self.assertEqual(SongRoleAssignment.objects.filter(person=person).count(), 3)


class SongRoleAssignmentRequirementGateTests(TestCase):
    def test_save_rejects_a_role_with_no_matching_requirement(self):
        """Saving a SongRoleAssignment for a (song, role) with no SongRoleRequirement raises ValueError (issue #439)."""
        song = SongFactory()
        role = RoleFactory()
        person = PersonFactory()

        with self.assertRaises(ValueError):
            SongRoleAssignment.objects.create(song=song, role=role, person=person)

    def test_clean_rejects_a_role_with_no_matching_requirement(self):
        """full_clean() surfaces the same rule as a ValidationError, for form/admin callers (issue #439)."""
        song = SongFactory()
        role = RoleFactory()
        person = PersonFactory()
        assignment = SongRoleAssignment(song=song, role=role, person=person)

        with self.assertRaises(ValidationError):
            assignment.clean()

    def test_save_succeeds_once_a_matching_requirement_exists(self):
        """A (song, role) pair with a SongRoleRequirement can be assigned regardless of its count (issue #439)."""
        song = SongFactory()
        role = RoleFactory()
        person = PersonFactory()
        SongRoleRequirementFactory(song=song, role=role, count=1)

        assignment = SongRoleAssignment.objects.create(song=song, role=role, person=person)

        self.assertEqual(SongRoleAssignment.objects.get(pk=assignment.pk).role, role)

    def test_multiple_assignments_allowed_regardless_of_requirement_count(self):
        """A Requirement's count is a display target only -- more people can be assigned than count (issue #439)."""
        song = SongFactory()
        role = RoleFactory()
        SongRoleRequirementFactory(song=song, role=role, count=1)
        first = PersonFactory()
        second = PersonFactory()

        SongRoleAssignment.objects.create(song=song, role=role, person=first)
        SongRoleAssignment.objects.create(song=song, role=role, person=second)

        self.assertEqual(SongRoleAssignment.objects.filter(song=song, role=role).count(), 2)

    def test_deleting_the_requirement_directly_cascades_to_its_assignments(self):
        """A direct .delete() on a SongRoleRequirement removes every SongRoleAssignment sharing its (song, role) (issue #439)."""
        song = SongFactory()
        role = RoleFactory()
        requirement = SongRoleRequirementFactory(song=song, role=role, count=1)
        assignment = SongRoleAssignmentFactory(song=song, role=role)

        requirement.delete()

        self.assertFalse(SongRoleAssignment.objects.filter(pk=assignment.pk).exists())

    def test_deleting_the_requirement_via_a_queryset_still_cascades(self):
        """A bulk queryset .delete() on SongRoleRequirement still dispatches the cascade signal per row (issue #439)."""
        song = SongFactory()
        role = RoleFactory()
        SongRoleRequirementFactory(song=song, role=role, count=1)
        assignment = SongRoleAssignmentFactory(song=song, role=role)

        SongRoleRequirement.objects.filter(song=song, role=role).delete()

        self.assertFalse(SongRoleAssignment.objects.filter(pk=assignment.pk).exists())

    def test_deleting_one_requirement_leaves_other_song_role_pairs_assignments_untouched(self):
        """Deleting one Requirement doesn't cascade to an assignment for a different (song, role) pair (issue #439)."""
        song = SongFactory()
        role = RoleFactory()
        requirement = SongRoleRequirementFactory(song=song, role=role, count=1)
        other_role = RoleFactory()
        SongRoleRequirementFactory(song=song, role=other_role, count=1)
        other_assignment = SongRoleAssignmentFactory(song=song, role=other_role)

        requirement.delete()

        self.assertTrue(SongRoleAssignment.objects.filter(pk=other_assignment.pk).exists())


class SongRoleAssignmentFieldTests(TestCase):
    def test_created_with_all_fields(self):
        """A SongRoleAssignment is created with its Song, Role, and Person."""
        song = SongFactory()
        role = RoleFactory()
        person = PersonFactory()

        assignment = SongRoleAssignmentFactory(song=song, role=role, person=person)

        reloaded = SongRoleAssignment.objects.get(pk=assignment.pk)
        self.assertEqual(reloaded.song, song)
        self.assertEqual(reloaded.role, role)
        self.assertEqual(reloaded.person, person)
