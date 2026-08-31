import factory

from scheduling.models import Role, Semester


class SemesterFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Semester

    name = factory.Sequence(lambda n: f'Semester {n}')
    default_rehearsal_duration_minutes = 90
    default_setup_grace_minutes = 15
    default_teardown_grace_minutes = 15
    default_song_slot_count = 5


class RoleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Role

    name = factory.Sequence(lambda n: f'Role {n}')
    is_active = True
