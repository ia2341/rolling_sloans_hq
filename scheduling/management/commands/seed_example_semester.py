"""Management command that seeds a demo "Example Semester", published live, on production.

Unlike `seed_dev_data` (DEBUG-only, and deliberately never safe to run
against production because it gives every seeded Person the same
publicly-documented password), this command is meant to run against a
real production database. It reuses `seed_dev_data`'s Song/Rehearsal
builders for realistic demo content, but every demo Person here gets a
**random, discarded** password, never a known one — they exist to make
the demo Semester look populated to a logged-in member, not to be logged
into themselves. Deliberately not `set_unusable_password()`: an unusable
password reads to `services.active_roster_for()` as an invited-but-not-
yet-active member and hides the Person from the Band page entirely,
which would defeat the point of this command. This command creates no
admin account and touches no existing Person outside its own demo
roster.

Requires `--confirm` so it can't run by accident. Running it again rewrites
the existing "Example Semester" in place (issue #396): the old demo
Semester and its own demo People are deleted and a fresh one is built,
rather than refusing to run or leaving a second Semester behind.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string
from faker import Faker

from identity.factories import PersonFactory
from identity.models import Person
from scheduling import services
from scheduling.factories import (
    MembershipFactory,
    PersonRoleFactory,
    SemesterFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.management.commands.seed_dev_data import (
    _build_rehearsal_schedule,
    _build_songs,
    _deal_running_order,
    _get_or_create_roles,
)
from scheduling.models import Membership, Recording, Semester

EXAMPLE_SEMESTER_NAME = 'Example Semester'

# The full Role catalog issue #396 asks this command to ensure exists,
# person-level playable Roles included — deliberately a superset of
# seed_dev_data's placeholder ROLE_NAMES, since a production-facing demo
# should show the real instrumentation a member would recognize.
EXAMPLE_ROLE_NAMES = (
    'Male Lead Vocalist', 'Male Backing Vocalist', 'Female Lead Vocalist', 'Female Backing Vocalist',
    'Lead Electric Guitar', 'Rhythm Electric Guitar', 'Lead Acoustic Guitar', 'Lead Rhythm Guitar',
    'Bass', 'Drums', 'Percussion', 'Violin', 'Saxophone', 'Flute', 'Keyboard',
)

fake = Faker()


class Command(BaseCommand):
    """`manage.py seed_example_semester --confirm`: seed (or re-seed in place) one published demo Semester."""

    help = (
        'Seed a demo "Example Semester" (fake Roles/People/Songs/Rehearsals, all with '
        'random, discarded passwords), published live so any logged-in member sees it. Creates '
        'no admin account and touches no existing Person outside its own demo roster. '
        'Re-running this command rewrites the existing "Example Semester" in place.'
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
        """Seed the demo Semester, published live, rewriting a prior run's Example Semester in place.

        Raises:
            CommandError: if `--confirm` was not passed.
        """
        if not options['confirm']:
            raise CommandError('Refusing to run without --confirm.')

        # One transaction for the whole command: a failure partway through
        # (a bad Faker value, a DB hiccup, whatever) must leave nothing
        # behind, including any in-progress deletion of a prior run.
        with transaction.atomic():
            existing = Semester.objects.filter(name=EXAMPLE_SEMESTER_NAME).first()
            if existing is not None:
                _delete_existing_example_semester(existing)

            semester = SemesterFactory(name=EXAMPLE_SEMESTER_NAME, published_at=timezone.now())
            roles = _get_or_create_roles(EXAMPLE_ROLE_NAMES)
            people = _build_demo_people()
            _build_memberships(semester, people)
            people_by_role = _assign_person_roles(people, roles)
            songs = _build_songs(semester)
            _build_song_requirements_and_assignments(songs, roles, people_by_role)
            rehearsals = _build_rehearsal_schedule(semester)
            _deal_running_order(semester)

        self.stdout.write(self.style.SUCCESS(
            f'Seeded Semester "{semester.name}" (published_at={semester.published_at}, live): '
            f'{len(people)} People (all with random, discarded passwords), {len(songs)} Songs, '
            f'{len(rehearsals)} Rehearsals. No admin account was created or modified.'
        ))


def _delete_existing_example_semester(semester):
    """Hard-delete a prior run's "Example Semester" and its own demo People, so re-seeding starts clean.

    Mirrors `services.delete_semester()`'s cascade and best-effort R2
    cleanup, but doesn't call it: that function refuses the Live Semester
    (ADR-0011), and the Example Semester is deliberately published live —
    issue #396 needs this command able to overwrite it anyway. The demo
    People this command created are deleted too (CASCADE takes their
    Memberships, PersonRoles and SongRoleAssignments with them), so a
    second run doesn't accumulate orphaned demo accounts with no Membership.
    """
    demo_person_ids = list(Membership.objects.filter(semester=semester).values_list('person_id', flat=True))
    object_keys = list(
        Recording.objects.filter(rehearsal_song__rehearsal__semester=semester).values_list('file', flat=True)
    )
    semester.delete()
    if object_keys:
        transaction.on_commit(lambda: services._delete_recording_objects(object_keys))
    Person.objects.filter(pk__in=demo_person_ids).delete()


def _build_demo_people(count=12):
    """Build `count` demo People, each with a random, discarded password (none of them are ever loggable-in).

    The production analogue of `seed_dev_data._build_people`, minus the
    known shared dev password and minus the first-person-is-admin carve-out
    — these exist to populate the demo Semester's roster, not to be signed
    into, and this command must never create or touch an admin account.

    Deliberately a random `set_password()`, not `set_unusable_password()`:
    `services.active_roster_for()` (issue #333) hides any Person whose
    password is unusable from the Band page, treating them as an
    invited-but-not-yet-active member — exactly the wrong read for a demo
    roster that issue #396 needs to render as populated. A random,
    never-surfaced password satisfies `has_usable_password()` without
    making the account actually loggable-in by anyone.
    """
    return [
        PersonFactory(email=fake.unique.safe_email(), is_admin=False, password=get_random_string(32))
        for _ in range(count)
    ]


def _build_memberships(semester, people):
    """Build one Membership per Person for `semester`; return the list of created Memberships.

    Unlike `seed_dev_data._build_memberships`, this doesn't also declare
    `MembershipRole` rows: playable Roles are a person-level fact
    (`PersonRole`, ADR-0014), not a per-Membership one, so `_assign_person_
    roles()` is the only place this command declares Roles.
    """
    return [MembershipFactory(person=person, semester=semester) for person in people]


def _assign_person_roles(people, roles):
    """Declare each Person's playable Roles as `PersonRole` rows; return {role_id: [Person, ...]}.

    Round-robins the full Role catalog across People as each Person's
    primary declared Role, then tops up early People with a second,
    leftover Role so every catalog Role ends up with at least one Person
    who can play it, even though there are more Roles (15) than demo People
    (12). Returns the person-by-role mapping so the caller can cast a
    Person onto only the Roles they actually declared (issue #396: a demo
    Semester's castings shouldn't read as role-mismatched).
    """
    people_by_role = {role.pk: [] for role in roles}
    for i, person in enumerate(people):
        primary_role = roles[i % len(roles)]
        PersonRoleFactory(person=person, role=primary_role)
        people_by_role[primary_role.pk].append(person)

    leftover_roles = roles[len(people):]
    for i, role in enumerate(leftover_roles):
        person = people[i % len(people)]
        PersonRoleFactory(person=person, role=role)
        people_by_role[role.pk].append(person)

    return people_by_role


def _build_song_requirements_and_assignments(songs, roles, people_by_role):
    """Build one SongRoleRequirement per catalog Role with a declared Person, casting a Person who declared it.

    Every cast Person actually declared the Role they're assigned — issue
    #396 asks a demo Semester's roster to read as fully matched, with no
    `is_role_mismatch` flags to explain away. (`seed_dev_data` now casts
    the same way for the same reason.)
    """
    castable_roles = [role for role in roles if people_by_role.get(role.pk)]
    for song in songs:
        for role in castable_roles:
            requirement = SongRoleRequirementFactory(song=song, role=role, count=1)
            person = fake.random_element(people_by_role[role.pk])
            SongRoleAssignmentFactory(song=requirement.song, role=role, person=person)
