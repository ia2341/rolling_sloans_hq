"""Membership & MembershipRole (issue #31)."""

from django.db import IntegrityError, transaction
from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import MembershipFactory, RoleFactory, SemesterFactory
from scheduling.models import Membership, MembershipRole


class MembershipTests(TestCase):
    def test_links_person_to_semester(self):
        """Creating a Membership links a Person to a Semester."""
        person = PersonFactory()
        semester = SemesterFactory()

        membership = MembershipFactory(person=person, semester=semester)

        reloaded = Membership.objects.get(pk=membership.pk)
        self.assertEqual(reloaded.person, person)
        self.assertEqual(reloaded.semester, semester)

    def test_can_declare_multiple_roles(self):
        """A Membership can declare multiple Roles via MembershipRole."""
        membership = MembershipFactory()
        singer = RoleFactory(name='Singer')
        guitarist = RoleFactory(name='Guitarist')

        MembershipRole.objects.create(membership=membership, role=singer)
        MembershipRole.objects.create(membership=membership, role=guitarist)

        declared_roles = {mr.role for mr in membership.membershiprole_set.all()}
        self.assertEqual(declared_roles, {singer, guitarist})

    def test_same_person_holds_independent_memberships_across_semesters(self):
        """The same Person's declared roles are independent per-Semester Membership."""
        person = PersonFactory()
        fall = SemesterFactory()
        spring = SemesterFactory()
        singer = RoleFactory(name='Singer')
        drummer = RoleFactory(name='Drummer')

        fall_membership = MembershipFactory(person=person, semester=fall)
        spring_membership = MembershipFactory(person=person, semester=spring)
        MembershipRole.objects.create(membership=fall_membership, role=singer)
        MembershipRole.objects.create(membership=spring_membership, role=drummer)

        fall_roles = {mr.role for mr in fall_membership.membershiprole_set.all()}
        spring_roles = {mr.role for mr in spring_membership.membershiprole_set.all()}
        self.assertEqual(fall_roles, {singer})
        self.assertEqual(spring_roles, {drummer})

    def test_person_cannot_be_added_to_the_same_semester_twice(self):
        """A Person can only hold one Membership per Semester (one roster entry)."""
        person = PersonFactory()
        semester = SemesterFactory()
        MembershipFactory(person=person, semester=semester)

        with self.assertRaises(IntegrityError), transaction.atomic():
            MembershipFactory(person=person, semester=semester)


class MembershipRoleTests(TestCase):
    def test_same_role_cannot_be_declared_twice_on_one_membership(self):
        """A Membership cannot declare the same Role more than once."""
        membership = MembershipFactory()
        singer = RoleFactory(name='Singer')
        MembershipRole.objects.create(membership=membership, role=singer)

        with self.assertRaises(IntegrityError), transaction.atomic():
            MembershipRole.objects.create(membership=membership, role=singer)
