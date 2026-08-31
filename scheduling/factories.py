import factory
from faker import Faker

from scheduling.models import Role, Semester

fake = Faker()


def fake_semester_name():
    """A synthetic, realistic-looking semester name, e.g. "Fall 2026"."""
    season = fake.random_element(('Spring', 'Fall'))
    year = fake.random_int(min=2020, max=2035)
    return f'{season} {year}'


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
