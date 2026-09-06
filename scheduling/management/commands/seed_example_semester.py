"""Management command that seeds a demo "Example Semester", published live, on production.

Unlike `seed_dev_data` (DEBUG-only, and deliberately never safe to run
against production because it gives every seeded Person the same
publicly-documented password), this command is meant to run against a
real production database. It reuses `seed_dev_data`'s Semester/Role/Song/
Rehearsal builders for realistic demo content, but every demo Person here
gets an **unusable** password (`set_unusable_password`), never a known one
— they exist to make the demo Semester look populated to a logged-in
member, not to be logged into themselves. This command creates no admin
account and touches no existing Person — it only adds a new, published
Semester and its own fresh demo roster.

Requires `--confirm` so it can't run by accident, and refuses to run twice
(an existing "Example Semester" is a strong signal this has already been
done once).
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from faker import Faker

from identity.factories import PersonFactory
from scheduling.factories import SemesterFactory
from scheduling.management.commands.seed_dev_data import (
    _build_memberships,
    _build_rehearsal_schedule,
    _build_song_requirements_and_assignments,
    _build_songs,
    _deal_running_order,
    _get_or_create_roles,
)
from scheduling.models import Semester

EXAMPLE_SEMESTER_NAME = 'Example Semester'

fake = Faker()


class Command(BaseCommand):
    """`manage.py seed_example_semester --confirm`: seed one published demo Semester for non-admin viewing."""

    help = (
        'Seed a demo "Example Semester" (fake Roles/People/Songs/Rehearsals, all with '
        'unusable passwords), published live so any logged-in member sees it. Creates no '
        'admin account and touches no existing Person. Safe to run once against production.'
    )

    def add_arguments(self, parser):
        """
        Declare this command's CLI arguments.

        Parameters:
            parser (argparse.ArgumentParser): The argument parser to add arguments to.
        """
        parser.add_argument(
            '--confirm', action='store_true',
            help='Required. Confirms you intend to run this against the currently configured database.',
        )

    def handle(self, *args, **options):
        """Seed the demo Semester, published live, once.

        Raises:
            CommandError: if `--confirm` was not passed, or an "Example
                Semester" already exists (this command is not meant to be
                re-run).
        """
        if not options['confirm']:
            raise CommandError('Refusing to run without --confirm.')

        if Semester.objects.filter(name=EXAMPLE_SEMESTER_NAME).exists():
            raise CommandError(
                f'A Semester named "{EXAMPLE_SEMESTER_NAME}" already exists — refusing to seed a second one.'
            )

        # One transaction for the whole command: a failure partway through
        # (a bad Faker value, a DB hiccup, whatever) must leave nothing
        # behind, or the "Example Semester already exists" guard above would
        # block ever retrying a failed run.
        with transaction.atomic():
            semester = SemesterFactory(name=EXAMPLE_SEMESTER_NAME, published_at=timezone.now())
            roles = _get_or_create_roles()
            people = _build_demo_people()
            memberships = _build_memberships(semester, people, roles)
            songs = _build_songs(semester)
            _build_song_requirements_and_assignments(songs, roles, memberships)
            rehearsals = _build_rehearsal_schedule(semester)
            _deal_running_order(semester)

        self.stdout.write(self.style.SUCCESS(
            f'Seeded Semester "{semester.name}" (published_at={semester.published_at}, live): '
            f'{len(people)} People (all with unusable passwords), {len(songs)} Songs, '
            f'{len(rehearsals)} Rehearsals. No admin account was created or modified.'
        ))


def _build_demo_people(count=12):
    """Build `count` demo People with unusable passwords (none of them are ever loggable-in).

    The production analogue of `seed_dev_data._build_people`, minus the
    known shared dev password and minus the first-person-is-admin carve-out
    — these exist to populate the demo Semester's roster, not to be signed
    into, and this command must never create or touch an admin account.
    """
    return [PersonFactory(email=fake.unique.safe_email(), is_admin=False) for _ in range(count)]
