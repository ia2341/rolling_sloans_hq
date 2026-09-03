"""Roster service seams: create_or_reactivate_role(), import_roster_from_semester() (#225) and unrostered_people_for() (#229)."""

from django.db import transaction
from django.test import TestCase, TransactionTestCase

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    MembershipRoleFactory,
    RoleFactory,
    SemesterFactory,
)
from scheduling.models import Membership, MembershipRole, Role
from scheduling.services import (
    RosterImportProposal,
    create_or_reactivate_role,
    import_roster_from_semester,
    unrostered_people_for,
)


class CreateOrReactivateRoleTests(TestCase):
    def test_creates_a_role_that_does_not_exist(self):
        """A brand-new name creates a Role and reports created=True."""
        result = create_or_reactivate_role('Trombone')

        self.assertTrue(result.created)
        self.assertFalse(result.reactivated)
        self.assertEqual(result.role.name, 'Trombone')
        self.assertTrue(Role.objects.filter(name='Trombone').exists())

    def test_case_insensitive_match_creates_nothing(self):
        """A name differing only by case matches the existing Role instead of duplicating it."""
        existing = RoleFactory(name='Trombone')

        result = create_or_reactivate_role('trombone')

        self.assertFalse(result.created)
        self.assertFalse(result.reactivated)
        self.assertEqual(result.role, existing)
        self.assertEqual(Role.objects.filter(name__iexact='trombone').count(), 1)

    def test_match_against_retired_role_reactivates_it(self):
        """A name matching a retired Role flips it back to active rather than creating a second Role."""
        retired = RoleFactory(name='Trombone', is_active=False)

        result = create_or_reactivate_role('Trombone')

        self.assertFalse(result.created)
        self.assertTrue(result.reactivated)
        self.assertEqual(result.role.pk, retired.pk)
        retired.refresh_from_db()
        self.assertTrue(retired.is_active)
        self.assertEqual(Role.objects.filter(name__iexact='trombone').count(), 1)

    def test_active_match_is_not_reported_as_reactivated(self):
        """Matching a Role that was already active reports reactivated=False."""
        RoleFactory(name='Trombone', is_active=True)

        result = create_or_reactivate_role('Trombone')

        self.assertFalse(result.reactivated)


class CreateOrReactivateRoleCommitsIndependentlyTests(TransactionTestCase):
    def test_role_survives_a_later_batch_transaction_being_abandoned(self):
        """A Role created here is unaffected by a later, unrelated transaction that rolls back.

        Uses TransactionTestCase (unlike the other tests in this module)
        because Django's plain TestCase wraps every test in its own
        transaction, which would hide the very thing this test checks:
        create_or_reactivate_role() writes with no surrounding
        transaction.atomic() and no on_commit() deferral, so it commits
        immediately in Django's default autocommit mode — proving a
        caller's later Pending Buffer save (or any other failed batch)
        cannot roll a Role it already created back out of existence.
        """
        result = create_or_reactivate_role('Trombone')

        try:
            with transaction.atomic():
                RoleFactory()
                raise RuntimeError('simulated batch failure, unrelated to the Role above')
        except RuntimeError:
            pass

        self.assertTrue(Role.objects.filter(pk=result.role.pk).exists())


class ImportRosterFromSemesterTests(TestCase):
    def test_returns_prior_semesters_roster_with_declared_roles(self):
        """The proposal carries the prior Semester's rostered People with their declared Roles copied."""
        prior = SemesterFactory()
        target = SemesterFactory()
        membership = MembershipFactory(semester=prior)
        role = RoleFactory(name='Singer')
        MembershipRoleFactory(membership=membership, role=role)

        proposal = import_roster_from_semester(target)

        self.assertEqual(proposal.source_semester, prior)
        self.assertEqual(len(proposal.people), 1)
        [imported] = proposal.people
        self.assertEqual(imported.person, membership.person)
        self.assertEqual(imported.roles, [role])

    def test_writes_nothing(self):
        """The read creates no rows and leaves the prior Semester's state untouched."""
        prior = SemesterFactory()
        target = SemesterFactory()
        membership = MembershipFactory(semester=prior)
        MembershipRoleFactory(membership=membership)
        membership_role_count_before = MembershipRole.objects.count()

        import_roster_from_semester(target)

        self.assertEqual(MembershipRole.objects.count(), membership_role_count_before)
        self.assertTrue(Membership.objects.filter(pk=membership.pk).exists())

    def test_deactivated_people_are_excluded_silently(self):
        """A deactivated Person's Membership on the prior Semester is dropped from the proposal without error."""
        prior = SemesterFactory()
        target = SemesterFactory()
        inactive_person = PersonFactory(is_active=False)
        MembershipFactory(semester=prior, person=inactive_person)

        proposal = import_roster_from_semester(target)

        self.assertEqual(proposal.people, [])

    def test_returned_roles_are_copies_not_references(self):
        """Saving the proposal's Roles for the target Semester leaves the prior Semester's MembershipRole rows untouched (ADR 0001)."""
        prior = SemesterFactory()
        target = SemesterFactory()
        membership = MembershipFactory(semester=prior)
        role = RoleFactory()
        prior_membership_role = MembershipRoleFactory(membership=membership, role=role)

        proposal = import_roster_from_semester(target)
        [imported] = proposal.people
        new_membership = MembershipFactory(semester=target, person=imported.person)
        for imported_role in imported.roles:
            MembershipRoleFactory(membership=new_membership, role=imported_role)

        self.assertTrue(MembershipRole.objects.filter(pk=prior_membership_role.pk).exists())
        self.assertEqual(
            MembershipRole.objects.filter(membership__semester=prior).count(),
            1,
        )
        self.assertEqual(
            MembershipRole.objects.filter(membership__semester=target).count(),
            1,
        )

    def test_no_prior_semester_returns_empty_proposal(self):
        """With no earlier Semester to import from, the read returns an empty proposal rather than raising."""
        target = SemesterFactory()

        proposal = import_roster_from_semester(target)

        self.assertEqual(proposal, RosterImportProposal(source_semester=None, people=[]))


class UnrosteredPeopleForTests(TestCase):
    def test_returns_active_people_with_no_membership_in_the_semester_ordered_by_name(self):
        """People holding no Membership in the Semester come back sorted by name."""
        semester = SemesterFactory()
        zed = PersonFactory(name='Zed Placeholder')
        amy = PersonFactory(name='Amy Placeholder')

        people = unrostered_people_for(semester)

        self.assertEqual(people, [amy, zed])

    def test_excludes_a_person_already_rostered_in_the_semester(self):
        """A Person already holding a Membership in the Semester is absent from the list."""
        semester = SemesterFactory()
        membership = MembershipFactory(semester=semester)

        people = unrostered_people_for(semester)

        self.assertNotIn(membership.person, people)

    def test_a_person_rostered_only_in_another_semester_is_still_offered(self):
        """A Membership in a different Semester doesn't exclude a Person from this Semester's add list."""
        other_semester = SemesterFactory()
        semester = SemesterFactory()
        membership = MembershipFactory(semester=other_semester)

        people = unrostered_people_for(semester)

        self.assertIn(membership.person, people)

    def test_excludes_deactivated_people_silently(self):
        """A deactivated Person never appears in the add list, with no error."""
        semester = SemesterFactory()
        PersonFactory(is_active=False)

        people = unrostered_people_for(semester)

        self.assertEqual(people, [])
