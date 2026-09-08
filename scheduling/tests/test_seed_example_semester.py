"""Tests for the `seed_example_semester` management command (production demo Semester seeder)."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from identity.models import Person
from scheduling import services
from scheduling.management.commands.seed_example_semester import (
    EXAMPLE_ROLE_NAMES,
    EXAMPLE_SEMESTER_NAME,
)
from scheduling.models import (
    Membership,
    PersonRole,
    Rehearsal,
    Role,
    Semester,
    Song,
    SongRoleAssignment,
    SongRoleRequirement,
)


class SeedExampleSemesterTests(TestCase):
    """Verifies the confirm guard and the shape of the data `seed_example_semester` produces."""

    def test_refuses_without_confirm(self):
        """The command must raise CommandError, and write nothing, without --confirm."""
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command('seed_example_semester', stdout=StringIO())
        self.assertEqual(Semester.objects.count(), 0)

    def test_seeds_a_complete_semester_with_full_roster(self):
        """The seeded Example Semester has a populated roster, person-level Roles, and matched castings."""
        out = StringIO()
        call_command('seed_example_semester', '--confirm', stdout=out)

        semester = Semester.objects.get(name=EXAMPLE_SEMESTER_NAME)
        self.assertIsNotNone(semester.published_at)

        memberships = Membership.objects.filter(semester=semester)
        self.assertGreater(memberships.count(), 0)

        # Every seeded Person on the roster has at least one declared, person-level Role.
        for membership in memberships:
            self.assertTrue(
                PersonRole.objects.filter(person=membership.person).exists(),
                f'{membership.person} has no declared PersonRole',
            )

        self.assertGreater(Song.objects.filter(semester=semester).count(), 0)
        self.assertGreater(Rehearsal.objects.filter(semester=semester).count(), 0)

        assignments = SongRoleAssignment.objects.filter(song__semester=semester)
        self.assertGreater(assignments.count(), 0)
        self.assertFalse(assignments.filter(is_role_mismatch=True).exists())

        # Every seeded SongRoleAssignment has a matching SongRoleRequirement
        # (issue #439's gate) -- a no-op check today since seed_example_semester
        # already pairs every assignment with a requirement per (song, role),
        # but a regression here would mean the seeder can no longer run.
        requirement_pairs = set(SongRoleRequirement.objects.values_list('song_id', 'role_id'))
        for assignment in assignments:
            self.assertIn(
                (assignment.song_id, assignment.role_id),
                requirement_pairs,
                f'{assignment} has no matching SongRoleRequirement',
            )

        # Every seeded Person has a usable password hash (so the demo roster
        # reads as 'accepted' rather than badging every row "not yet
        # invited" on the Band page and Roster editor), but it's a random,
        # never-surfaced value nobody can log in with.
        for membership in memberships:
            self.assertTrue(membership.person.has_usable_password())
            self.assertFalse(membership.person.check_password('password'))

        # The full roster actually appears through the Band page's own query
        # (issue #455: every Membership is included regardless of invite
        # state, so this is really just confirming the seeder produced real
        # Membership rows -- but it's kept as a guard against a future
        # reintroduction of a password-gated roster filter).
        self.assertEqual(
            services.roster_for(memberships).count(), memberships.count(),
        )

        # No admin account is created.
        self.assertFalse(Person.objects.filter(is_admin=True).exists())

    def test_seeds_the_full_role_catalog(self):
        """Every Role named in EXAMPLE_ROLE_NAMES exists after seeding."""
        call_command('seed_example_semester', '--confirm', stdout=StringIO())
        for name in EXAMPLE_ROLE_NAMES:
            self.assertTrue(Role.objects.filter(name=name).exists(), f'Role "{name}" was not seeded')

    def test_running_twice_rewrites_in_place(self):
        """Running the command a second time replaces the existing Example Semester rather than refusing or duplicating it."""
        call_command('seed_example_semester', '--confirm', stdout=StringIO())
        first_semester_pk = Semester.objects.get(name=EXAMPLE_SEMESTER_NAME).pk
        first_person_ids = set(Person.objects.values_list('pk', flat=True))

        call_command('seed_example_semester', '--confirm', stdout=StringIO())

        self.assertEqual(Semester.objects.filter(name=EXAMPLE_SEMESTER_NAME).count(), 1)
        second_semester = Semester.objects.get(name=EXAMPLE_SEMESTER_NAME)
        self.assertNotEqual(second_semester.pk, first_semester_pk)

        # The old demo People are gone, not left behind as orphans.
        second_person_ids = set(Person.objects.values_list('pk', flat=True))
        self.assertFalse(first_person_ids & second_person_ids)

        memberships = Membership.objects.filter(semester=second_semester)
        self.assertGreater(memberships.count(), 0)
        for membership in memberships:
            self.assertTrue(PersonRole.objects.filter(person=membership.person).exists())
