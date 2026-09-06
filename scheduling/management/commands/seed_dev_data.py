"""Management command that seeds a realistic, internally-consistent Semester for local development.

DEBUG-only by construction (see `Command.handle()`) — it exists so a
developer can `python manage.py runserver` against an empty local database
and immediately have something to click through: a published (Live)
Semester, a roster of loggable-in People, a setlist with Role requirements
and Assignments, a generated Rehearsal schedule, and a dealt Running Order.
Every name/email/note here is synthesized via `factory_boy`/`Faker` at
run-time, per CONTRIBUTING.md's privacy constraint — nothing here may ever
resemble a real band member.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from faker import Faker

from identity.factories import PersonFactory
from scheduling import services
from scheduling.factories import (
    MembershipFactory,
    RehearsalFactory,
    RehearsalPatternFactory,
    RehearsalSongFactory,
    RehearsalTimeFactory,
    SemesterFactory,
    SkipDateFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import MembershipRole, Rehearsal, RehearsalTime, Role, Song

fake = Faker()

# A fixed, recognizable roster of Role names — deliberately not band-specific
# real instrumentation, just plausible enough to exercise the Role/
# Requirement/Assignment machinery. Role.name is globally unique (Role is a
# semester-independent catalog per CONTEXT.md), so this command fetches or
# creates each by name rather than blindly inserting, keeping repeat runs
# from crashing on a second seed.
ROLE_NAMES = ('Vocals', 'Guitar', 'Bass', 'Drums', 'Keys')

DEV_PASSWORD = 'devpassword123!'  # a fixed, obviously-fake local dev password, never used in prod (DEBUG-only guard above)


class Command(BaseCommand):
    """`manage.py seed_dev_data`: build one realistic Semester end-to-end for local development only."""

    help = (
        'Seed a realistic, internally-consistent Semester (People, Roles, Songs, Assignments, '
        'a generated Rehearsal schedule, and a dealt Running Order) for local development. '
        'Refuses to run unless settings.DEBUG is True.'
    )

    def handle(self, *args, **options):
        """Refuse outside DEBUG, then build one Semester end-to-end and print a summary.

        Raises:
            CommandError: if `settings.DEBUG` is falsy — this command must
                never be reachable against a production database, since it
                creates People with real, known, usable passwords.
        """
        if not settings.DEBUG:
            raise CommandError(
                'seed_dev_data refuses to run unless settings.DEBUG is True. '
                'This command creates People with a known, usable password and is for local '
                'development only — it must never be run against a production database.'
            )

        semester = _build_semester()
        roles = _get_or_create_roles()
        people = _build_people()
        memberships = _build_memberships(semester, people, roles)
        songs = _build_songs(semester)
        _build_song_requirements_and_assignments(songs, roles, memberships)
        rehearsals = _build_rehearsal_schedule(semester)
        _deal_running_order(semester)

        self.stdout.write(self.style.SUCCESS(
            f'Seeded Semester "{semester.name}" (published_at={semester.published_at}): '
            f'{len(people)} People, {len(songs)} Songs, {len(rehearsals)} Rehearsals. '
            f'Dev login password for every seeded Person: {DEV_PASSWORD}'
        ))


def _build_semester():
    """Build and return one published Semester (the Live Semester, per `services.get_live_semester()`)."""
    return SemesterFactory()


def _get_or_create_roles():
    """Return the fixed `ROLE_NAMES` as Role rows, creating any that don't already exist.

    Role.name is globally unique and Role is not Semester-scoped (it's a
    semester-independent catalog per CONTEXT.md), so re-running this command
    must fetch an existing Role by name rather than re-inserting it.
    """
    roles = []
    for name in ROLE_NAMES:
        role, _ = Role.objects.get_or_create(name=name, defaults={'is_active': True})
        roles.append(role)
    return roles


def _build_people(count=12):
    """Build `count` People with real, usable dev passwords so they're loggable-in locally.

    The first Person is an admin, so a developer has an admin account to
    test admin-only surfaces without extra setup.
    """
    people = []
    for i in range(count):
        person = PersonFactory(
            email=fake.unique.safe_email(),
            password=DEV_PASSWORD,
            is_admin=(i == 0),
        )
        people.append(person)
    return people


def _build_memberships(semester, people, roles):
    """Build one Membership per Person for `semester`, each declaring one or two Roles; return {person_id: membership}.

    Roles are spread round-robin across People plus a Faker-chosen extra
    for some, so every Role has more than one Person able to fill it.
    """
    memberships = {}
    for i, person in enumerate(people):
        membership = MembershipFactory(person=person, semester=semester)
        primary_role = roles[i % len(roles)]
        MembershipRole.objects.create(membership=membership, role=primary_role)
        if fake.boolean(chance_of_getting_true=35):
            secondary_role = roles[(i + 1) % len(roles)]
            if secondary_role != primary_role:
                MembershipRole.objects.create(membership=membership, role=secondary_role)
        memberships[person.pk] = membership
    return memberships


def _build_songs(semester, count=7):
    """Build `count` Songs on `semester`'s setlist, in concert-order position."""
    return [SongFactory(semester=semester, position=i + 1) for i in range(count)]


def _build_song_requirements_and_assignments(songs, roles, memberships):
    """Build a SongRoleRequirement per Role on every Song, then cast People onto them via SongRoleAssignment.

    Mostly casts a Person whose Membership declares the required Role;
    every third Song intentionally casts a mismatched Person instead
    (`SongRoleAssignment.save()` flags `is_role_mismatch` on its own, per
    ADR-0002 — a realistic seed should include a couple of these rather
    than none).
    """
    people_by_role = {}
    for membership in memberships.values():
        for membership_role in membership.membershiprole_set.all():
            people_by_role.setdefault(membership_role.role_id, []).append(membership.person)

    all_people = [membership.person for membership in memberships.values()]

    for song_index, song in enumerate(songs):
        for role in roles:
            requirement = SongRoleRequirementFactory(song=song, role=role, count=1)
            force_mismatch = song_index % 3 == 0
            candidates = all_people if force_mismatch else people_by_role.get(role.pk, all_people)
            person = fake.random_element(candidates) if candidates else fake.random_element(all_people)
            SongRoleAssignmentFactory(song=requirement.song, role=role, person=person)


def _build_rehearsal_schedule(semester):
    """Build a RehearsalPattern (with two weekly RehearsalTimes and one SkipDate), generate its Rehearsals, and add one Dress Rehearsal.

    Reuses `RehearsalFactory` directly rather than the web-only Pattern
    generation flow (`services.preview_rehearsal_generation()` only computes
    a diff for an admin's in-progress edit; there is no `apply_*` for it to
    call — see its docstring), which is exactly the case CLAUDE.md's task
    brief calls out as fine to hand-roll for a seed command.
    """
    start_date = timezone.now().date() + timedelta(days=7)
    end_date = start_date + timedelta(days=84)
    pattern = RehearsalPatternFactory(semester=semester, start_date=start_date, end_date=end_date)
    rehearsal_time_monday = RehearsalTimeFactory(pattern=pattern, day_of_week=RehearsalTime.MONDAY)
    rehearsal_time_thursday = RehearsalTimeFactory(pattern=pattern, day_of_week=RehearsalTime.THURSDAY)
    skip_date = SkipDateFactory(pattern=pattern, start_date=start_date + timedelta(days=28))

    rehearsal_times = {
        rehearsal_time_monday.day_of_week: rehearsal_time_monday,
        rehearsal_time_thursday.day_of_week: rehearsal_time_thursday,
    }
    skipped = {skip_date.start_date}

    rehearsals = []
    current = start_date
    while current <= end_date:
        rehearsal_time = rehearsal_times.get(current.weekday())
        if rehearsal_time is not None and current not in skipped:
            rehearsals.append(RehearsalFactory(
                semester=semester, date=current,
                start_time=rehearsal_time.start_time, end_time=rehearsal_time.end_time,
            ))
        current += timedelta(days=1)

    # One mandatory-attendance Dress Rehearsal, per ADR-0003/ADR-0006 — its
    # songs are derived live from the setlist, never given RehearsalSong rows.
    rehearsals.append(RehearsalFactory(
        semester=semester, date=end_date + timedelta(days=3), start_time=rehearsal_time_thursday.start_time,
        is_full_setlist=True,
    ))
    return rehearsals


def _deal_running_order(semester):
    """Deal a balanced Running Order across `semester`'s eligible Rehearsals and persist it as RehearsalSong rows.

    `services.deal_running_orders()` is a pure read (issue #223 — there is
    no `apply_schedule_generation`, see `RehearsalDeal`'s docstring); its
    normal consumer is the admin's Pending Buffer via `apply_rehearsal_edits()`.
    For a one-shot seed, writing its proposed rows directly with
    `RehearsalSongFactory` is simpler than constructing that Buffer, and is
    equivalent since every proposed row here is a fresh Song at a fresh
    Rehearsal (`rehearsal_song_id` is always None on a first seed).
    """
    try:
        deal = services.deal_running_orders(semester)
    except (services.EmptySetlistError, services.NoEligibleRehearsalsError, services.DealInfeasibleError):
        return
    rehearsals_by_id = {rehearsal.pk: rehearsal for rehearsal in Rehearsal.objects.filter(semester=semester)}
    songs_by_id = {song.pk: song for song in Song.objects.filter(semester=semester)}
    for dealt_rehearsal in deal.rehearsals:
        rehearsal = rehearsals_by_id[dealt_rehearsal.rehearsal_id]
        for order, row in enumerate(dealt_rehearsal.rows, start=1):
            # Pass the real Song instance (not `song_id=`), since
            # RehearsalSongFactory's `song` is a SubFactory — overriding
            # only `song_id` would leave the SubFactory to build (and
            # persist) an unwanted throwaway Song/Semester of its own.
            RehearsalSongFactory(
                rehearsal=rehearsal, song=songs_by_id[row.song_id], order=order, slot_count=row.slot_count,
            )
