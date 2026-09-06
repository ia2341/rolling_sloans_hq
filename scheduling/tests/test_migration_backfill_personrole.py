"""The 0023 data migration backfilling PersonRole from every existing MembershipRole (issue #376)."""

from importlib import import_module

from django.apps import apps
from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import MembershipFactory, RoleFactory, SemesterFactory
from scheduling.models import MembershipRole, PersonRole

backfill_person_role = import_module(
    'scheduling.migrations.0023_backfill_personrole',
).backfill_person_role


class BackfillPersonRoleTests(TestCase):
    """Exercises the migration's own function against real models via `apps.get_model`."""

    def test_creates_one_personrole_per_declared_membershiprole(self):
        """A single declared MembershipRole backfills into exactly one matching PersonRole."""
        person = PersonFactory()
        role = RoleFactory()
        membership = MembershipFactory(person=person, semester=SemesterFactory())
        MembershipRole.objects.create(membership=membership, role=role)

        backfill_person_role(apps, None)

        self.assertTrue(PersonRole.objects.filter(person=person, role=role).exists())
        self.assertEqual(PersonRole.objects.count(), 1)

    def test_unions_a_persons_declarations_across_semesters(self):
        """A Role declared in two different Semesters by the same Person backfills into one PersonRole, not two."""
        person = PersonFactory()
        role = RoleFactory()
        first_membership = MembershipFactory(person=person, semester=SemesterFactory())
        second_membership = MembershipFactory(person=person, semester=SemesterFactory())
        MembershipRole.objects.create(membership=first_membership, role=role)
        MembershipRole.objects.create(membership=second_membership, role=role)

        backfill_person_role(apps, None)

        self.assertEqual(PersonRole.objects.filter(person=person, role=role).count(), 1)

    def test_a_persons_different_roles_across_semesters_all_survive(self):
        """A Person who declared different Roles in different Semesters gets one PersonRole per distinct Role."""
        person = PersonFactory()
        singer = RoleFactory(name='Singer')
        guitarist = RoleFactory(name='Guitarist')
        earlier_membership = MembershipFactory(person=person, semester=SemesterFactory())
        later_membership = MembershipFactory(person=person, semester=SemesterFactory())
        MembershipRole.objects.create(membership=earlier_membership, role=singer)
        MembershipRole.objects.create(membership=later_membership, role=guitarist)

        backfill_person_role(apps, None)

        self.assertEqual(
            set(PersonRole.objects.filter(person=person).values_list('role', flat=True)),
            {singer.pk, guitarist.pk},
        )

    def test_different_people_declaring_the_same_role_each_get_their_own_row(self):
        """Two distinct People who both declared the same Role each backfill their own PersonRole."""
        role = RoleFactory()
        first_membership = MembershipFactory(semester=SemesterFactory())
        second_membership = MembershipFactory(semester=SemesterFactory())
        MembershipRole.objects.create(membership=first_membership, role=role)
        MembershipRole.objects.create(membership=second_membership, role=role)

        backfill_person_role(apps, None)

        self.assertEqual(PersonRole.objects.filter(role=role).count(), 2)

    def test_running_twice_does_not_duplicate(self):
        """Re-running the migration (idempotency safety net) creates no duplicate PersonRole rows."""
        membership = MembershipFactory(semester=SemesterFactory())
        role = RoleFactory()
        MembershipRole.objects.create(membership=membership, role=role)

        backfill_person_role(apps, None)
        backfill_person_role(apps, None)

        self.assertEqual(PersonRole.objects.filter(person=membership.person, role=role).count(), 1)

    def test_no_membershiprole_rows_backfills_nothing(self):
        """An empty MembershipRole table leaves PersonRole empty rather than raising."""
        backfill_person_role(apps, None)

        self.assertEqual(PersonRole.objects.count(), 0)
