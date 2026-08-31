import string
from datetime import time, timedelta

import factory
from faker import Faker

from identity.factories import PersonFactory
from scheduling.models import (
    Membership,
    Recording,
    Rehearsal,
    RehearsalSong,
    Role,
    Semester,
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
    class Meta:
        model = Semester

    name = factory.LazyFunction(fake_semester_name)
    default_rehearsal_duration_minutes = 90
    default_setup_grace_minutes = 15
    default_teardown_grace_minutes = 15
    default_song_slot_count = 5


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

    Leaves setup_grace_minutes, teardown_grace_minutes, and end_time unset
    (None) so Rehearsal.save() copies them from the Semester's defaults, the
    same as a real creation through the admin would.
    """

    class Meta:
        model = Rehearsal

    semester = factory.SubFactory(SemesterFactory)
    date = factory.LazyFunction(lambda: fake.date_between(start_date='+1d', end_date='+120d'))
    start_time = time(18, 0)
    end_time = None
    setup_grace_minutes = None
    teardown_grace_minutes = None
    is_full_setlist = False


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
