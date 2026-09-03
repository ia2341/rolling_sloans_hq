"""Backup: rehearsal-scoped substitution model (ADR-0007, issue #174)."""

from django.db import IntegrityError, transaction
from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import (
    BackupFactory,
    ConflictFactory,
    MembershipFactory,
    RehearsalSongFactory,
    RoleFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Backup, Conflict, MembershipRole, SongRoleAssignment


class BackupUniquenessTests(TestCase):
    def test_duplicate_slot_role_person_is_rejected(self):
        """A second Backup for the same (rehearsal_song, role, person) triple raises IntegrityError."""
        rehearsal_song = RehearsalSongFactory()
        role = RoleFactory()
        person = PersonFactory()
        BackupFactory(rehearsal_song=rehearsal_song, role=role, person=person)

        with self.assertRaises(IntegrityError), transaction.atomic():
            BackupFactory(rehearsal_song=rehearsal_song, role=role, person=person)

    def test_different_people_can_back_up_the_same_slot_and_role(self):
        """Several different people can each hold a Backup for the same (rehearsal_song, role)."""
        rehearsal_song = RehearsalSongFactory()
        role = RoleFactory()

        BackupFactory(rehearsal_song=rehearsal_song, role=role)
        BackupFactory(rehearsal_song=rehearsal_song, role=role)

        self.assertEqual(Backup.objects.filter(rehearsal_song=rehearsal_song, role=role).count(), 2)

    def test_person_cannot_cover_for_themselves(self):
        """Setting covering_for equal to person is refused by a database constraint."""
        person = PersonFactory()

        with self.assertRaises(IntegrityError), transaction.atomic():
            BackupFactory(person=person, covering_for=person)


class BackupCoveringForTests(TestCase):
    def test_covering_for_none_saves_happily(self):
        """A Backup with no standing assignee (covering_for=None) is a legal, unremarkable record."""
        backup = BackupFactory(covering_for=None)

        self.assertIsNone(backup.covering_for)


class BackupMismatchTests(TestCase):
    def test_backup_without_declared_role_is_flagged_mismatched(self):
        """Recording a Backup for a Role the Person hasn't declared sets is_role_mismatch=True."""
        role = RoleFactory()
        rehearsal_song = RehearsalSongFactory()
        person = PersonFactory()
        MembershipFactory(person=person, semester=rehearsal_song.rehearsal.semester)

        backup = BackupFactory(rehearsal_song=rehearsal_song, role=role, person=person)

        self.assertTrue(backup.is_role_mismatch)

    def test_backup_with_declared_role_is_not_flagged(self):
        """Recording a Backup for a Role the Person has declared on their current Membership is not flagged."""
        role = RoleFactory()
        rehearsal_song = RehearsalSongFactory()
        person = PersonFactory()
        membership = MembershipFactory(person=person, semester=rehearsal_song.rehearsal.semester)
        MembershipRole.objects.create(membership=membership, role=role)

        backup = BackupFactory(rehearsal_song=rehearsal_song, role=role, person=person)

        self.assertFalse(backup.is_role_mismatch)

    def test_backup_with_no_membership_at_all_is_flagged(self):
        """A Backup for a Person with no Membership in the Semester at all is flagged mismatched."""
        role = RoleFactory()
        rehearsal_song = RehearsalSongFactory()
        person = PersonFactory()  # no Membership at all

        backup = BackupFactory(rehearsal_song=rehearsal_song, role=role, person=person)

        self.assertTrue(backup.is_role_mismatch)

    def test_mismatch_clears_when_matching_role_is_later_declared(self):
        """Declaring the matching MembershipRole after the fact clears an existing mismatch flag."""
        role = RoleFactory()
        rehearsal_song = RehearsalSongFactory()
        person = PersonFactory()
        membership = MembershipFactory(person=person, semester=rehearsal_song.rehearsal.semester)
        backup = BackupFactory(rehearsal_song=rehearsal_song, role=role, person=person)
        self.assertTrue(backup.is_role_mismatch)

        MembershipRole.objects.create(membership=membership, role=role)

        reloaded = Backup.objects.get(pk=backup.pk)
        self.assertFalse(reloaded.is_role_mismatch)

    def test_mismatch_reappears_when_declared_role_is_removed(self):
        """Removing the matching MembershipRole re-flags an existing Backup as mismatched."""
        role = RoleFactory()
        rehearsal_song = RehearsalSongFactory()
        person = PersonFactory()
        membership = MembershipFactory(person=person, semester=rehearsal_song.rehearsal.semester)
        membership_role = MembershipRole.objects.create(membership=membership, role=role)
        backup = BackupFactory(rehearsal_song=rehearsal_song, role=role, person=person)
        self.assertFalse(backup.is_role_mismatch)

        membership_role.delete()

        reloaded = Backup.objects.get(pk=backup.pk)
        self.assertTrue(reloaded.is_role_mismatch)

    def test_song_role_assignment_reevaluation_still_works_alongside_backup_sweep(self):
        """Generalising the sweep to cover Backups leaves SongRoleAssignment re-evaluation working unmodified."""
        role = RoleFactory()
        song = SongFactory()
        person = PersonFactory()
        membership = MembershipFactory(person=person, semester=song.semester)
        assignment = SongRoleAssignmentFactory(song=song, role=role, person=person)
        self.assertTrue(assignment.is_role_mismatch)

        MembershipRole.objects.create(membership=membership, role=role)

        reloaded = SongRoleAssignment.objects.get(pk=assignment.pk)
        self.assertFalse(reloaded.is_role_mismatch)


class BackupLifecycleTests(TestCase):
    def test_deleting_rehearsal_song_removes_backup(self):
        """Deleting the RehearsalSong (e.g. pulling the Song from the Running Order) cascades to the Backup."""
        rehearsal_song = RehearsalSongFactory()
        backup = BackupFactory(rehearsal_song=rehearsal_song)

        rehearsal_song.delete()

        self.assertFalse(Backup.objects.filter(pk=backup.pk).exists())

    def test_deleting_person_removes_backup(self):
        """Deleting the covering Person removes their Backup."""
        person = PersonFactory()
        backup = BackupFactory(person=person)

        person.delete()

        self.assertFalse(Backup.objects.filter(pk=backup.pk).exists())

    def test_deleting_covered_person_leaves_backup_standing_with_null_covering_for(self):
        """Deleting the covered Person leaves the Backup row standing with covering_for cleared."""
        covered = PersonFactory()
        backup = BackupFactory(covering_for=covered)

        covered.delete()

        reloaded = Backup.objects.get(pk=backup.pk)
        self.assertIsNone(reloaded.covering_for)


class BackupStalenessTests(TestCase):
    def test_is_stale_false_with_matching_conflict_present(self):
        """is_stale() reads False while the covered Person still has a Conflict on this Rehearsal."""
        rehearsal_song = RehearsalSongFactory()
        covered = PersonFactory()
        ConflictFactory(person=covered, rehearsal=rehearsal_song.rehearsal, type=Conflict.FULL_CONFLICT)
        backup = BackupFactory(rehearsal_song=rehearsal_song, covering_for=covered)

        self.assertFalse(backup.is_stale())

    def test_is_stale_true_once_conflict_is_withdrawn_and_backup_still_exists(self):
        """Withdrawing the covered Person's Conflict flips is_stale() true but leaves the Backup standing (ADR-0007 §3)."""
        rehearsal_song = RehearsalSongFactory()
        covered = PersonFactory()
        conflict = ConflictFactory(person=covered, rehearsal=rehearsal_song.rehearsal, type=Conflict.FULL_CONFLICT)
        backup = BackupFactory(rehearsal_song=rehearsal_song, covering_for=covered)

        conflict.delete()

        reloaded = Backup.objects.get(pk=backup.pk)
        self.assertTrue(reloaded.is_stale())
        self.assertTrue(Backup.objects.filter(pk=backup.pk).exists())

    def test_is_stale_false_when_covering_for_is_none(self):
        """is_stale() is always False for a Backup with no standing assignee."""
        backup = BackupFactory(covering_for=None)

        self.assertFalse(backup.is_stale())


class BackupFieldTests(TestCase):
    def test_created_with_all_fields(self):
        """A Backup is created with its RehearsalSong, Role, Person, and covering_for."""
        rehearsal_song = RehearsalSongFactory()
        role = RoleFactory()
        person = PersonFactory()
        covered = PersonFactory()

        backup = BackupFactory(
            rehearsal_song=rehearsal_song, role=role, person=person, covering_for=covered,
        )

        reloaded = Backup.objects.get(pk=backup.pk)
        self.assertEqual(reloaded.rehearsal_song, rehearsal_song)
        self.assertEqual(reloaded.role, role)
        self.assertEqual(reloaded.person, person)
        self.assertEqual(reloaded.covering_for, covered)
