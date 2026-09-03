"""Semester setup step 3: import the roster from the prior Semester (issue #201)."""

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    MembershipRoleFactory,
    RoleFactory,
    SemesterFactory,
)
from scheduling.models import Membership, MembershipRole, Semester

PASSWORD = 'a-strong-test-password-123'


def admin_client(test_case):
    """Log a synthetic admin Person into `test_case`'s client and return that Person."""
    person = PersonFactory(password=PASSWORD, is_admin=True)
    test_case.client.login(username=person.email, password=PASSWORD)
    return person


def member_client(test_case):
    """Log a synthetic non-admin Person into `test_case`'s client and return that Person."""
    person = PersonFactory(password=PASSWORD)
    test_case.client.login(username=person.email, password=PASSWORD)
    return person


def roster_url(semester):
    """Return the roster-import step's URL for `semester`."""
    return reverse('scheduling:manage-semester-setup-roster', args=[semester.pk])


@override_settings(SECURE_SSL_REDIRECT=False)
class RosterStepAuthTests(TestCase):
    def test_anonymous_get_redirects_to_login(self):
        """An anonymous GET to the roster step redirects to login."""
        semester = SemesterFactory(draft=True)

        response = self.client.get(roster_url(semester))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('identity:login'), response.url)

    def test_anonymous_post_redirects_to_login(self):
        """An anonymous POST to the roster step redirects to login."""
        semester = SemesterFactory(draft=True)

        response = self.client.post(roster_url(semester))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('identity:login'), response.url)

    def test_member_get_is_forbidden(self):
        """A logged-in non-admin gets a 403 for the roster step."""
        semester = SemesterFactory(draft=True)
        member_client(self)

        response = self.client.get(roster_url(semester))

        self.assertEqual(response.status_code, 403)

    def test_member_post_is_forbidden_and_creates_nothing(self):
        """A logged-in non-admin's POST to the roster step is a 403, and no Membership is created."""
        prior = SemesterFactory()
        semester = SemesterFactory(draft=True)
        membership = MembershipFactory(semester=prior)
        member_client(self)

        response = self.client.post(roster_url(semester), {'person_id': [membership.person.pk]})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Membership.objects.filter(semester=semester).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class RosterStepGetTests(TestCase):
    def test_no_prior_semester_redirects_straight_to_the_setlist_step(self):
        """With no prior Semester, the step is skipped entirely rather than rendered empty."""
        semester = SemesterFactory(draft=True)
        admin_client(self)

        response = self.client.get(roster_url(semester))

        self.assertRedirects(response, reverse('scheduling:manage-semester-setup-setlist', args=[semester.pk]))

    def test_renders_the_prior_semesters_roster_ticked_by_default(self):
        """Each of the prior Semester's People renders, pre-ticked, with their declared Roles shown read-only."""
        prior = SemesterFactory()
        semester = SemesterFactory(draft=True)
        role = RoleFactory(name='Singer')
        membership = MembershipFactory(semester=prior)
        MembershipRoleFactory(membership=membership, role=role)
        admin_client(self)

        response = self.client.get(roster_url(semester))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, membership.person.name)
        self.assertContains(response, 'Singer')
        self.assertContains(
            response, f'name="person_id" value="{membership.person.pk}" class="roster-import-checkbox" checked',
        )

    def test_no_role_editing_or_invite_affordance_appear(self):
        """The step shows no Role checkboxes/Add Role control and no invite form."""
        prior = SemesterFactory()
        semester = SemesterFactory(draft=True)
        MembershipFactory(semester=prior)
        admin_client(self)

        response = self.client.get(roster_url(semester))

        self.assertNotContains(response, 'roster-invite-form')
        self.assertNotContains(response, 'Add Role')
        self.assertNotContains(response, 'name="roles"')


@override_settings(SECURE_SSL_REDIRECT=False)
class RosterStepPostTests(TestCase):
    def test_ticked_people_land_on_the_new_semester_only(self):
        """Committing creates fresh Membership/MembershipRole rows on the new Semester, none on the prior one."""
        prior = SemesterFactory()
        semester = SemesterFactory(draft=True)
        role = RoleFactory(name='Bassist')
        prior_membership = MembershipFactory(semester=prior)
        prior_membership_role = MembershipRoleFactory(membership=prior_membership, role=role)
        admin_client(self)

        response = self.client.post(roster_url(semester), {'person_id': [prior_membership.person.pk]})

        self.assertRedirects(response, reverse('scheduling:manage-semester-setup-setlist', args=[semester.pk]))
        new_membership = Membership.objects.get(semester=semester, person=prior_membership.person)
        new_roles = list(MembershipRole.objects.filter(membership=new_membership).values_list('role', flat=True))
        self.assertEqual(new_roles, [role.pk])
        # The prior Semester's own rows are untouched: still exactly the one Membership/MembershipRole built above.
        self.assertTrue(Membership.objects.filter(pk=prior_membership.pk).exists())
        self.assertTrue(MembershipRole.objects.filter(pk=prior_membership_role.pk).exists())
        self.assertEqual(Membership.objects.filter(semester=prior).count(), 1)
        self.assertEqual(MembershipRole.objects.filter(membership__semester=prior).count(), 1)

    def test_no_row_references_the_source_semester(self):
        """The imported Membership carries no field pointing at the source Semester."""
        prior = SemesterFactory()
        semester = SemesterFactory(draft=True)
        prior_membership = MembershipFactory(semester=prior)
        admin_client(self)

        self.client.post(roster_url(semester), {'person_id': [prior_membership.person.pk]})

        new_membership = Membership.objects.get(semester=semester, person=prior_membership.person)
        self.assertEqual(new_membership.semester_id, semester.pk)
        self.assertNotEqual(new_membership.pk, prior_membership.pk)

    def test_unticked_people_are_not_imported(self):
        """A Person left unticked is not added to the new Semester's roster."""
        prior = SemesterFactory()
        semester = SemesterFactory(draft=True)
        included = MembershipFactory(semester=prior)
        excluded = MembershipFactory(semester=prior)
        admin_client(self)

        self.client.post(roster_url(semester), {'person_id': [included.person.pk]})

        self.assertTrue(Membership.objects.filter(semester=semester, person=included.person).exists())
        self.assertFalse(Membership.objects.filter(semester=semester, person=excluded.person).exists())

    def test_empty_submission_imports_nobody_and_still_moves_on(self):
        """Unticking everyone (select-none) is a valid submission that imports no one."""
        prior = SemesterFactory()
        semester = SemesterFactory(draft=True)
        MembershipFactory(semester=prior)
        admin_client(self)

        response = self.client.post(roster_url(semester), {})

        self.assertRedirects(response, reverse('scheduling:manage-semester-setup-setlist', args=[semester.pk]))
        self.assertFalse(Membership.objects.filter(semester=semester).exists())

    def test_no_prior_semester_post_redirects_straight_to_the_setlist_step_and_creates_nothing(self):
        """Posting to the step with no prior Semester also just redirects onward, creating nothing."""
        semester = SemesterFactory(draft=True)
        admin_client(self)

        response = self.client.post(roster_url(semester), {'person_id': ['999999']})

        self.assertRedirects(response, reverse('scheduling:manage-semester-setup-setlist', args=[semester.pk]))
        self.assertFalse(Membership.objects.filter(semester=semester).exists())

    def test_skipping_the_step_leaves_a_valid_draft(self):
        """The Skip link is a plain GET to the setlist step, and the draft Semester still exists afterwards."""
        prior = SemesterFactory()
        semester = SemesterFactory(draft=True)
        MembershipFactory(semester=prior)
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-setlist', args=[semester.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Semester.objects.filter(pk=semester.pk, published_at=None).exists())
        self.assertFalse(Membership.objects.filter(semester=semester).exists())
