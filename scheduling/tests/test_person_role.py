"""PersonRole: durable person-level standing Roles, with no Semester dimension (ADR-0014, issue #376)."""

from django.db import IntegrityError, transaction
from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import PersonRoleFactory, RoleFactory
from scheduling.models import PersonRole


class PersonRoleTests(TestCase):
    def test_links_person_to_role_with_no_semester(self):
        """Creating a PersonRole links a Person to a Role directly."""
        person = PersonFactory()
        role = RoleFactory()

        person_role = PersonRoleFactory(person=person, role=role)

        reloaded = PersonRole.objects.get(pk=person_role.pk)
        self.assertEqual(reloaded.person, person)
        self.assertEqual(reloaded.role, role)

    def test_same_role_cannot_be_declared_twice_for_one_person(self):
        """A Person cannot hold the same standing Role more than once."""
        person = PersonFactory()
        role = RoleFactory()
        PersonRoleFactory(person=person, role=role)

        with self.assertRaises(IntegrityError), transaction.atomic():
            PersonRoleFactory(person=person, role=role)

    def test_removing_a_person_role_is_a_hard_delete(self):
        """Deleting a PersonRole removes the row outright — there is no is_active soft-delete flag."""
        person_role = PersonRoleFactory()
        pk = person_role.pk

        person_role.delete()

        self.assertFalse(PersonRole.objects.filter(pk=pk).exists())
        self.assertNotIn('is_active', [f.name for f in PersonRole._meta.get_fields()])

    def test_same_person_can_hold_multiple_roles(self):
        """A Person can hold several standing Roles simultaneously."""
        person = PersonFactory()
        singer = RoleFactory(name='Singer')
        guitarist = RoleFactory(name='Guitarist')

        PersonRoleFactory(person=person, role=singer)
        PersonRoleFactory(person=person, role=guitarist)

        declared_roles = set(PersonRole.objects.filter(person=person).values_list('role', flat=True))
        self.assertEqual(declared_roles, {singer.pk, guitarist.pk})
