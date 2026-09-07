"""Tests for the `seed_dev_data` management command (local-dev-only Semester seeder)."""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from identity.models import Person
from scheduling.models import (
    Membership,
    PersonRole,
    Rehearsal,
    Semester,
    Song,
    SongRoleAssignment,
    SongRoleRequirement,
)


class SeedDevDataTests(TestCase):
    """Verifies the DEBUG-only guard and the shape of the data `seed_dev_data` produces."""

    @override_settings(DEBUG=False)
    def test_refuses_to_run_outside_debug(self):
        """`seed_dev_data` must raise CommandError, and write nothing, when settings.DEBUG is False."""
        with self.assertRaises(CommandError):
            call_command('seed_dev_data', stdout=StringIO())
        self.assertEqual(Semester.objects.count(), 0)
        self.assertEqual(Person.objects.count(), 0)

    @override_settings(DEBUG=True)
    def test_seeds_a_complete_semester(self):
        """Under DEBUG=True, the command builds one Semester with non-zero People, Memberships, Songs, Rehearsals, and Assignments."""
        out = StringIO()
        call_command('seed_dev_data', stdout=out)

        self.assertEqual(Semester.objects.count(), 1)
        semester = Semester.objects.get()
        self.assertIsNotNone(semester.published_at)

        self.assertGreater(Person.objects.count(), 0)
        self.assertGreater(Membership.objects.filter(semester=semester).count(), 0)
        self.assertGreater(Song.objects.filter(semester=semester).count(), 0)
        self.assertGreater(Rehearsal.objects.filter(semester=semester).count(), 0)
        self.assertGreater(SongRoleAssignment.objects.filter(song__semester=semester).count(), 0)

        # Every seeded, rostered Person has at least one declared, person-level
        # Role (regression: this command used to write the retired
        # MembershipRole instead of PersonRole, which roster_for() no longer reads).
        for membership in Membership.objects.filter(semester=semester):
            self.assertTrue(
                PersonRole.objects.filter(person=membership.person).exists(),
                f'{membership.person} has no declared PersonRole',
            )

        # At least one seeded Person should be able to log in locally.
        person = Person.objects.first()
        self.assertTrue(person.has_usable_password())

        # Every seeded SongRoleAssignment has a matching SongRoleRequirement
        # (issue #439's gate) -- a no-op check today since seed_dev_data
        # already pairs every assignment with a requirement per (song, role),
        # but a regression here would mean the seeder can no longer run.
        requirement_pairs = set(SongRoleRequirement.objects.values_list('song_id', 'role_id'))
        for assignment in SongRoleAssignment.objects.filter(song__semester=semester):
            self.assertIn(
                (assignment.song_id, assignment.role_id),
                requirement_pairs,
                f'{assignment} has no matching SongRoleRequirement',
            )

        # Every seeded SongRoleAssignment casts a Person who actually
        # declared the assigned Role (regression: this command used to
        # deliberately cast a mismatched Person on every third Song to
        # exercise is_role_mismatch, which made a "logical" seed roster
        # impossible to rely on).
        for assignment in SongRoleAssignment.objects.filter(song__semester=semester):
            self.assertFalse(
                assignment.is_role_mismatch,
                f'{assignment} is role-mismatched: {assignment.person} has not declared {assignment.role}',
            )

        output = out.getvalue()
        self.assertIn(semester.name, output)

    @override_settings(DEBUG=True)
    def test_running_twice_does_not_crash(self):
        """Running the command a second time must not raise, even though Role names are globally unique."""
        call_command('seed_dev_data', stdout=StringIO())
        call_command('seed_dev_data', stdout=StringIO())
        self.assertEqual(Semester.objects.count(), 2)
