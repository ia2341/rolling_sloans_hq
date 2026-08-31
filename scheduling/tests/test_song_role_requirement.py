"""SongRoleRequirement: target Role headcounts per Song (issue #33)."""

from django.db import IntegrityError, transaction
from django.test import TestCase

from scheduling.factories import RoleFactory, SongFactory, SongRoleRequirementFactory
from scheduling.models import SongRoleRequirement


class SongRoleRequirementMultipleRolesTests(TestCase):
    def test_song_can_have_requirements_for_different_roles(self):
        """A Song can carry multiple SongRoleRequirements, one per distinct Role."""
        song = SongFactory()
        singer = RoleFactory(name='Singer')
        guitarist = RoleFactory(name='Guitarist')

        SongRoleRequirementFactory(song=song, role=singer, count=3)
        SongRoleRequirementFactory(song=song, role=guitarist, count=2)

        self.assertEqual(SongRoleRequirement.objects.filter(song=song).count(), 2)

    def test_duplicate_role_on_same_song_is_rejected(self):
        """A second requirement for the same (song, role) pair raises IntegrityError.

        One target count per Role per Song keeps the target unambiguous —
        two rows for the same Role on the same Song would leave it unclear
        which count is the real target.
        """
        song = SongFactory()
        role = RoleFactory()
        SongRoleRequirementFactory(song=song, role=role, count=2)

        with self.assertRaises(IntegrityError), transaction.atomic():
            SongRoleRequirementFactory(song=song, role=role, count=3)


class SongRoleRequirementCountIsATargetTests(TestCase):
    def test_count_does_not_limit_actual_assignments(self):
        """`count` is only a target value — nothing here enforces it against real assignments.

        There is no Role Assignment model yet (per issue #33/#14), so this
        asserts the absence of any enforcement mechanism: SongRoleRequirement
        has no field or constraint tying `count` to any other model.
        """
        song = SongFactory()
        role = RoleFactory()

        requirement = SongRoleRequirementFactory(song=song, role=role, count=1)

        # Nothing prevents the target from being set arbitrarily high or low
        # relative to any real headcount — it's a plain, unenforced integer.
        requirement.count = 100
        requirement.save()
        reloaded = SongRoleRequirement.objects.get(pk=requirement.pk)
        self.assertEqual(reloaded.count, 100)


class SongRoleRequirementFieldTests(TestCase):
    def test_created_with_all_fields(self):
        """A SongRoleRequirement is created with its Song, Role, and count."""
        song = SongFactory()
        role = RoleFactory()

        requirement = SongRoleRequirementFactory(song=song, role=role, count=4)

        reloaded = SongRoleRequirement.objects.get(pk=requirement.pk)
        self.assertEqual(reloaded.song, song)
        self.assertEqual(reloaded.role, role)
        self.assertEqual(reloaded.count, 4)
