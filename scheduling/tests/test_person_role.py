"""PersonRole: durable person-level standing Roles, with no Semester dimension (ADR-0014, issue #376).

Also covers the `is_role_mismatch` resweep signal (issue #377) and the
`scheduling.services` read/write functions issue #378 added for the
person-page Role editor (`declared_roles_for_person`, `sync_person_roles`).
"""

from django.db import IntegrityError, transaction
from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import (
    PersonRoleFactory,
    RoleFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import PersonRole
from scheduling.services import (
    PersonRoleValidationError,
    declared_roles_for_person,
    sync_person_roles,
)


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


class PersonRoleMismatchResweepTests(TestCase):
    """Issue #377: creating/deleting a `PersonRole` resweeps `is_role_mismatch` on affected `SongRoleAssignment` rows."""

    def test_creating_a_person_role_clears_a_mismatched_assignment(self):
        """Declaring a standing PersonRole for a Role a Person already holds a mismatched assignment on clears the flag."""
        person = PersonFactory()
        role = RoleFactory(name='Bassist')
        song = SongFactory()
        assignment = SongRoleAssignmentFactory(song=song, person=person, role=role)
        self.assertTrue(assignment.is_role_mismatch)

        PersonRoleFactory(person=person, role=role)

        assignment.refresh_from_db()
        self.assertFalse(assignment.is_role_mismatch)

    def test_deleting_a_person_role_re_flags_a_previously_matched_assignment(self):
        """Removing a standing PersonRole re-flags a previously-matched assignment as mismatched."""
        person = PersonFactory()
        role = RoleFactory(name='Bassist')
        song = SongFactory()
        person_role = PersonRoleFactory(person=person, role=role)
        assignment = SongRoleAssignmentFactory(song=song, person=person, role=role)
        self.assertFalse(assignment.is_role_mismatch)

        person_role.delete()

        assignment.refresh_from_db()
        self.assertTrue(assignment.is_role_mismatch)


class DeclaredRolesForPersonTests(TestCase):
    """`services.declared_roles_for_person()` (issue #378): the person-level replacement for the retired `declared_roles_for(membership)`."""

    def test_returns_the_persons_standing_roles_in_name_order(self):
        """Declared Roles come back sorted by name, regardless of any Membership."""
        person = PersonFactory()
        PersonRoleFactory(person=person, role=RoleFactory(name='Zither'))
        PersonRoleFactory(person=person, role=RoleFactory(name='Accordion'))

        roles = declared_roles_for_person(person)

        self.assertEqual([role.name for role in roles], ['Accordion', 'Zither'])

    def test_empty_for_a_person_with_no_standing_roles(self):
        """A Person with no PersonRole rows gets an empty list, not an error."""
        person = PersonFactory()

        self.assertEqual(declared_roles_for_person(person), [])


class SyncPersonRolesTests(TestCase):
    """`services.sync_person_roles()` (issue #378): the write-side replace-list sync backing `PersonRolesApiView`."""

    def test_creates_rows_for_a_first_submission(self):
        """Submitting role_ids for a Person with no prior PersonRole rows creates exactly those rows."""
        person = PersonFactory()
        role = RoleFactory()

        sync_person_roles(person, [role.pk])

        self.assertEqual(list(PersonRole.objects.filter(person=person).values_list('role_id', flat=True)), [role.pk])

    def test_removes_rows_omitted_from_a_later_submission(self):
        """A later submission that omits a previously-declared Role deletes its PersonRole row."""
        person = PersonFactory()
        kept_role = RoleFactory()
        removed_role = RoleFactory()
        PersonRoleFactory(person=person, role=kept_role)
        PersonRoleFactory(person=person, role=removed_role)

        sync_person_roles(person, [kept_role.pk])

        declared_role_ids = set(PersonRole.objects.filter(person=person).values_list('role_id', flat=True))
        self.assertEqual(declared_role_ids, {kept_role.pk})

    def test_leaves_already_declared_rows_untouched(self):
        """Resubmitting an already-declared Role doesn't delete and recreate its PersonRole row."""
        person = PersonFactory()
        role = RoleFactory()
        existing = PersonRoleFactory(person=person, role=role)

        sync_person_roles(person, [role.pk])

        self.assertTrue(PersonRole.objects.filter(pk=existing.pk).exists())

    def test_rejects_an_inactive_role_id_without_writing_anything(self):
        """An inactive Role id raises PersonRoleValidationError before any row is written."""
        person = PersonFactory()
        inactive_role = RoleFactory(is_active=False)

        with self.assertRaises(PersonRoleValidationError):
            sync_person_roles(person, [inactive_role.pk])

        self.assertFalse(PersonRole.objects.filter(person=person).exists())

    def test_rejects_an_unknown_role_id(self):
        """A role id that doesn't exist at all raises PersonRoleValidationError."""
        person = PersonFactory()

        with self.assertRaises(PersonRoleValidationError):
            sync_person_roles(person, [999999])
