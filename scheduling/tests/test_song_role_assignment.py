"""SongRoleAssignment + role-mismatch flag (issue #35)."""

from django.db import IntegrityError, transaction
from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    RoleFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import MembershipRole, SongRoleAssignment


class SongRoleAssignmentMismatchTests(TestCase):
    def test_assignment_without_declared_role_is_flagged_mismatched(self):
        """Assigning a Person to a Role they haven't declared sets is_role_mismatch=True."""
        role = RoleFactory()
        song = SongFactory()
        person = PersonFactory()
        MembershipFactory(person=person, semester=song.semester)  # no MembershipRole declared

        assignment = SongRoleAssignmentFactory(song=song, role=role, person=person)

        self.assertTrue(assignment.is_role_mismatch)

    def test_assignment_with_declared_role_is_not_flagged(self):
        """Assigning a Person to a Role they've declared on their current Membership is not flagged."""
        role = RoleFactory()
        song = SongFactory()
        person = PersonFactory()
        membership = MembershipFactory(person=person, semester=song.semester)
        MembershipRole.objects.create(membership=membership, role=role)

        assignment = SongRoleAssignmentFactory(song=song, role=role, person=person)

        self.assertFalse(assignment.is_role_mismatch)

    def test_mismatch_clears_when_matching_role_is_later_declared(self):
        """Declaring the matching MembershipRole after the fact clears an existing mismatch flag."""
        role = RoleFactory()
        song = SongFactory()
        person = PersonFactory()
        membership = MembershipFactory(person=person, semester=song.semester)
        assignment = SongRoleAssignmentFactory(song=song, role=role, person=person)
        self.assertTrue(assignment.is_role_mismatch)

        MembershipRole.objects.create(membership=membership, role=role)

        reloaded = SongRoleAssignment.objects.get(pk=assignment.pk)
        self.assertFalse(reloaded.is_role_mismatch)

    def test_mismatch_reappears_when_declared_role_is_removed(self):
        """Removing the matching MembershipRole re-flags an existing assignment as mismatched."""
        role = RoleFactory()
        song = SongFactory()
        person = PersonFactory()
        membership = MembershipFactory(person=person, semester=song.semester)
        membership_role = MembershipRole.objects.create(membership=membership, role=role)
        assignment = SongRoleAssignmentFactory(song=song, role=role, person=person)
        self.assertFalse(assignment.is_role_mismatch)

        membership_role.delete()

        reloaded = SongRoleAssignment.objects.get(pk=assignment.pk)
        self.assertTrue(reloaded.is_role_mismatch)

    def test_unrelated_membership_role_change_does_not_affect_other_assignments(self):
        """A MembershipRole change for one Person/Role doesn't touch another Person's assignment."""
        role = RoleFactory()
        song = SongFactory()
        watched_person = PersonFactory()
        other_person = PersonFactory()
        MembershipFactory(person=watched_person, semester=song.semester)
        other_membership = MembershipFactory(person=other_person, semester=song.semester)
        assignment = SongRoleAssignmentFactory(song=song, role=role, person=watched_person)
        self.assertTrue(assignment.is_role_mismatch)

        MembershipRole.objects.create(membership=other_membership, role=role)

        reloaded = SongRoleAssignment.objects.get(pk=assignment.pk)
        self.assertTrue(reloaded.is_role_mismatch)


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
