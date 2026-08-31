import string
from datetime import timedelta

import factory
from faker import Faker

from identity.factories import PersonFactory
from scheduling.models import Membership, Role, Semester, Song

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
