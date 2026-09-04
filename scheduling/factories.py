import string
from datetime import time, timedelta

import factory
from django.utils import timezone
from faker import Faker

from identity.factories import PersonFactory
from scheduling.models import (
    Backup,
    Conflict,
    ConflictWindow,
    Membership,
    MembershipRole,
    Recording,
    Rehearsal,
    RehearsalPattern,
    RehearsalSong,
    RehearsalTime,
    Role,
    Semester,
    SkipDate,
    Song,
    SongRoleAssignment,
    SongRoleRequirement,
)

fake = Faker()


def fake_semester_name():
    """A synthetic, realistic-looking semester name, e.g. "Fall 2026"."""
    season = fake.random_element(('Spring', 'Fall'))
    year = fake.random_int(min=2020, max=2035)
    return f'{season} {year}'


def fake_song_title(n):
    """A synthetic, obviously-fake song title, e.g. "Song A", per CONTRIBUTING.md."""
    return f'Song {string.ascii_uppercase[n % len(string.ascii_uppercase)]}'


class SemesterFactory(factory.django.DjangoModelFactory):
    """A Semester, **published** by default — the only state a member can see, so the state most tests want.

    Pass `draft=True` for an unpublished Semester (a null `published_at`),
    or an explicit `published_at` to place a Semester in the publish order.
    Each published Semester's default `published_at` strictly increases, so
    the most recently built one is unambiguously the Live Semester.
    """

    class Meta:
        model = Semester

    class Params:
        draft = factory.Trait(published_at=None)

    name = factory.LazyFunction(fake_semester_name)
    published_at = factory.Sequence(lambda n: timezone.now() + timedelta(microseconds=n))
    default_rehearsal_duration_minutes = 90
    default_setup_grace_minutes = 15
    default_teardown_grace_minutes = 15
    default_song_slot_count = 5
    default_arrival_buffer_minutes = 5
    default_departure_buffer_minutes = 5


class RoleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Role

    name = factory.Sequence(lambda n: f'Role {n}')
    is_active = True


class MembershipFactory(factory.django.DjangoModelFactory):
    """A Person's roster entry for a Semester, with synthetic person/semester by default."""

    class Meta:
        model = Membership

    person = factory.SubFactory(PersonFactory)
    semester = factory.SubFactory(SemesterFactory)


class MembershipRoleFactory(factory.django.DjangoModelFactory):
    """Builds a Role a Membership has declared for its Semester, with a fresh Membership/Role by default."""

    class Meta:
        model = MembershipRole

    membership = factory.SubFactory(MembershipFactory)
    role = factory.SubFactory(RoleFactory)


class SongFactory(factory.django.DjangoModelFactory):
    """Builds a Song with a synthetic title/artist and a fresh Semester by default."""

    class Meta:
        model = Song

    semester = factory.SubFactory(SemesterFactory)
    title = factory.Sequence(fake_song_title)
    artist = factory.Faker('name')
    length = timedelta(minutes=3, seconds=30)
    notes = ''
    position = factory.Sequence(lambda n: n + 1)


class SongRoleRequirementFactory(factory.django.DjangoModelFactory):
    """Builds a target Role headcount for a Song, with a fresh Song/Role by default."""

    class Meta:
        model = SongRoleRequirement

    song = factory.SubFactory(SongFactory)
    role = factory.SubFactory(RoleFactory)
    count = 1


class SongRoleAssignmentFactory(factory.django.DjangoModelFactory):
    """Builds a Person's Role assignment on a Song, with a fresh Song/Role/Person by default.

    Leaves is_role_mismatch unset since SongRoleAssignment.save() always
    recomputes it from the Person's current Membership.
    """

    class Meta:
        model = SongRoleAssignment

    song = factory.SubFactory(SongFactory)
    role = factory.SubFactory(RoleFactory)
    person = factory.SubFactory(PersonFactory)


class RehearsalFactory(factory.django.DjangoModelFactory):
    """Builds a Rehearsal with a fresh Semester by default.

    Leaves setup_grace_minutes, teardown_grace_minutes,
    arrival_buffer_minutes, departure_buffer_minutes, and end_time unset
    (None) so Rehearsal.save() copies them from the Semester's defaults, the
    same as a real creation through the admin would.
    """

    class Meta:
        model = Rehearsal

    semester = factory.SubFactory(SemesterFactory)
    # A monotonically increasing offset, not a random one: `unique_rehearsal_date_per_semester`
    # means two Rehearsals built for the same Semester in one test must never land on the same day,
    # and a random `fake.date_between()` draw from a bounded window collides often enough over a
    # full suite run to flake (~1/120 chance per pair, seen in practice on issue #122's CI run).
    date = factory.Sequence(lambda n: timezone.now().date() + timedelta(days=1 + n))
    start_time = time(18, 0)
    end_time = None
    setup_grace_minutes = None
    teardown_grace_minutes = None
    arrival_buffer_minutes = None
    departure_buffer_minutes = None
    is_full_setlist = False


class RehearsalPatternFactory(factory.django.DjangoModelFactory):
    """Builds a Semester's Rehearsal Pattern, with a fresh Semester and a ~90-day generation range by default."""

    class Meta:
        model = RehearsalPattern

    semester = factory.SubFactory(SemesterFactory)
    start_date = factory.LazyFunction(lambda: fake.date_between(start_date='+1d', end_date='+14d'))
    end_date = factory.LazyAttribute(lambda o: o.start_date + timedelta(days=90))


class RehearsalTimeFactory(factory.django.DjangoModelFactory):
    """Builds a recurring day/time within a Rehearsal Pattern, defaulting to Wednesdays 7-11pm."""

    class Meta:
        model = RehearsalTime

    pattern = factory.SubFactory(RehearsalPatternFactory)
    day_of_week = RehearsalTime.WEDNESDAY
    start_time = time(19, 0)
    end_time = time(23, 0)


class SkipDateFactory(factory.django.DjangoModelFactory):
    """Builds a Skip Date within a Rehearsal Pattern, defaulting to a single date (end_date left blank)."""

    class Meta:
        model = SkipDate

    pattern = factory.SubFactory(RehearsalPatternFactory)
    start_date = factory.LazyFunction(lambda: fake.date_between(start_date='+1d', end_date='+30d'))
    end_date = None


class RehearsalSongFactory(factory.django.DjangoModelFactory):
    """Builds a Song's timed slot in a Rehearsal, with a fresh Rehearsal/Song by default.

    Leaves start_time/end_time unset since RehearsalSong.save() always
    recomputes them from the Rehearsal's fixed window and slot_count.
    """

    class Meta:
        model = RehearsalSong

    rehearsal = factory.SubFactory(RehearsalFactory)
    song = factory.SubFactory(SongFactory)
    order = factory.Sequence(lambda n: n + 1)
    slot_count = 1


class ConflictFactory(factory.django.DjangoModelFactory):
    """Builds a Person's declared unavailability for a Rehearsal, with a fresh Person/Rehearsal by default.

    Defaults to an unadjudicated declaration — pending, with no note —
    which is what a member's own declaration produces. Pass `status` and
    `adjudication_note` to build an already-decided Conflict; synthesize
    the note through Faker rather than writing a realistic-looking one,
    per the repo's privacy constraint.
    """

    class Meta:
        model = Conflict

    person = factory.SubFactory(PersonFactory)
    rehearsal = factory.SubFactory(RehearsalFactory)
    type = Conflict.FULL_CONFLICT
    status = Conflict.PENDING
    adjudication_note = ''


class ConflictWindowFactory(factory.django.DjangoModelFactory):
    """Builds a disjoint unavailable time range for a partial Conflict, with a fresh partial Conflict by default.

    Defaults 18:15-18:45, which falls within RehearsalFactory's default
    18:00-19:30 span, so the default build is valid without overrides.
    """

    class Meta:
        model = ConflictWindow

    conflict = factory.SubFactory(ConflictFactory, type=Conflict.PARTIAL)
    unavailable_start = time(18, 15)
    unavailable_end = time(18, 45)


class BackupFactory(factory.django.DjangoModelFactory):
    """Builds a Person covering a Role at a RehearsalSong's slot, with a fresh RehearsalSong/Role/Person by default.

    covering_for defaults to None (an unattributed stand-in is legal per
    ADR-0007) and is_role_mismatch is left unset since Backup.save() always
    recomputes it from the Person's current Membership.
    """

    class Meta:
        model = Backup

    rehearsal_song = factory.SubFactory(RehearsalSongFactory)
    role = factory.SubFactory(RoleFactory)
    person = factory.SubFactory(PersonFactory)
    covering_for = None


class RecordingFactory(factory.django.DjangoModelFactory):
    """Builds a Recording with synthetic upload metadata and relationships by default."""

    class Meta:
        model = Recording

    rehearsal_song = factory.SubFactory(RehearsalSongFactory)
    uploaded_by = factory.SubFactory(PersonFactory)
    file = factory.Sequence(lambda n: f'recordings/recording-{n}.m4a')
    content_type = 'audio/mp4'
    file_size = 1_024
    note = factory.Faker('sentence')
