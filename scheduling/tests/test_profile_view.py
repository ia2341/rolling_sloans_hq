"""Member profile self-service: /me/profile/ (issue #57)."""

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    MembershipRoleFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Membership, MembershipRole

PASSWORD = 'a-strong-test-password-123'


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAccessTests(TestCase):
    def test_profile_redirects_anonymous_users_to_login(self):
        """An anonymous request to /me/profile/ redirects to the login page."""
        url = reverse('scheduling:profile')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")


@override_settings(SECURE_SSL_REDIRECT=False)
class ProfileViewGetTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person and create the current Semester before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()

    def test_shows_no_active_semester_message_when_none_exists(self):
        """With no Semester at all, the page renders without a form instead of erroring."""
        self.semester.delete()

        response = self.client.get(reverse('scheduling:profile'))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('form', response.context)

    def test_shows_empty_form_when_member_has_no_membership_yet(self):
        """A member with no Membership for the current Semester sees an empty, unsaved-instance form."""
        response = self.client.get(reverse('scheduling:profile'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].instance.pk)
        self.assertFalse(Membership.objects.filter(person=self.person, semester=self.semester).exists())

    def test_shows_currently_declared_roles(self):
        """A member's existing MembershipRoles for the current Semester are preselected."""
        membership = MembershipFactory(person=self.person, semester=self.semester)
        role = RoleFactory()
        MembershipRoleFactory(membership=membership, role=role)

        response = self.client.get(reverse('scheduling:profile'))

        self.assertEqual(response.status_code, 200)
        self.assertIn(role, response.context['form'].fields['roles'].initial)

    def test_shows_name_and_email(self):
        """The logged-in member's name and email are shown, read-only, on the page."""
        response = self.client.get(reverse('scheduling:profile'))

        self.assertContains(response, self.person.name)
        self.assertContains(response, self.person.email)

    def test_roles_count_reflects_declared_roles(self):
        """roles_count in the context matches the member's declared-Role count for the current Semester."""
        membership = MembershipFactory(person=self.person, semester=self.semester)
        MembershipRoleFactory(membership=membership, role=RoleFactory())
        MembershipRoleFactory(membership=membership, role=RoleFactory())

        response = self.client.get(reverse('scheduling:profile'))

        self.assertEqual(response.context['roles_count'], 2)

    def test_songs_played_count_reflects_distinct_songs_in_current_semester(self):
        """songs_played_count counts distinct Songs the member has a SongRoleAssignment on, in the current Semester only."""
        other_semester_song = SongFactory(semester=self.semester)  # self.semester is the "other" (non-current) one here
        current_semester = SemesterFactory()  # created after self.semester, so this is now the current Semester
        song_a = SongFactory(semester=current_semester)
        song_b = SongFactory(semester=current_semester)
        SongRoleAssignmentFactory(song=song_a, person=self.person)
        SongRoleAssignmentFactory(song=song_a, person=self.person, role=RoleFactory())
        SongRoleAssignmentFactory(song=song_b, person=self.person)
        SongRoleAssignmentFactory(song=other_semester_song, person=self.person)

        response = self.client.get(reverse('scheduling:profile'))

        self.assertEqual(response.context['semester'], current_semester)
        self.assertEqual(response.context['songs_played_count'], 2)


@override_settings(SECURE_SSL_REDIRECT=False)
class ProfileViewPostTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person and create the current Semester before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()

    def test_valid_post_creates_membership_and_roles_and_redirects_with_message(self):
        """A valid POST with no prior Membership creates one, sets its Roles, and redirects with a success message."""
        role = RoleFactory()

        response = self.client.post(reverse('scheduling:profile'), {'roles': [role.pk]}, follow=True)

        self.assertRedirects(response, reverse('scheduling:profile'))
        membership = Membership.objects.get(person=self.person, semester=self.semester)
        self.assertEqual(list(MembershipRole.objects.filter(membership=membership).values_list('role', flat=True)), [role.pk])
        messages = [str(m) for m in response.context['messages']]
        self.assertIn('Profile updated.', messages)

    def test_valid_post_replaces_previously_declared_roles(self):
        """A valid POST removes previously declared Roles that weren't resubmitted."""
        membership = MembershipFactory(person=self.person, semester=self.semester)
        old_role = RoleFactory()
        new_role = RoleFactory()
        MembershipRoleFactory(membership=membership, role=old_role)

        self.client.post(reverse('scheduling:profile'), {'roles': [new_role.pk]})

        declared_role_ids = set(MembershipRole.objects.filter(membership=membership).values_list('role_id', flat=True))
        self.assertEqual(declared_role_ids, {new_role.pk})

    def test_invalid_post_rerenders_form_with_errors(self):
        """A POST referencing a nonexistent Role id re-renders the form with a field error, not a 500."""
        response = self.client.post(reverse('scheduling:profile'), {'roles': [999999]})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'is not one of the available choices')
        self.assertFalse(Membership.objects.filter(person=self.person, semester=self.semester).exists())

    def test_post_is_scoped_to_the_logged_in_user_only(self):
        """A member's POST can never edit another Person's Membership — there is no person parameter."""
        other_person = PersonFactory()
        other_membership = MembershipFactory(person=other_person, semester=self.semester)
        role = RoleFactory()

        self.client.post(reverse('scheduling:profile'), {'roles': [role.pk]})

        self.assertFalse(MembershipRole.objects.filter(membership=other_membership, role=role).exists())
