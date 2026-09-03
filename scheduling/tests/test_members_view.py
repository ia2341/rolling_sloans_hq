"""Band Members roster list: /members/ (issue #137, slice 1 of map #135)."""

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
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

PASSWORD = 'a-strong-test-password-123'


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAccessTests(TestCase):
    def test_members_redirects_anonymous_users_to_login(self):
        """An anonymous request to /members/ redirects to the login page."""
        url = reverse('scheduling:members')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")


@override_settings(SECURE_SSL_REDIRECT=False)
class MembersViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic Person and the current Semester."""
        cls.person = PersonFactory(password=PASSWORD, name='Zoe Placeholder')
        cls.semester = SemesterFactory()

    def setUp(self):
        """Log in as the synthetic Person before each test."""
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_shows_empty_state_when_no_semester_exists(self):
        """With no Semester at all, the page renders an empty roster instead of erroring."""
        self.semester.delete()

        response = self.client.get(reverse('scheduling:members'))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['semester'])
        self.assertEqual(list(response.context['members']), [])
        self.assertContains(response, 'No band members on the roster yet.')

    def test_shows_empty_state_when_semester_has_no_memberships(self):
        """A current Semester with no Memberships renders the same empty state."""
        response = self.client.get(reverse('scheduling:members'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['members']), [])
        self.assertContains(response, 'No band members on the roster yet.')

    def test_lists_only_current_semesters_memberships(self):
        """A Membership in an older Semester is absent from the roster (per ADR 0001)."""
        older_semester = SemesterFactory()
        self.semester = SemesterFactory()
        MembershipFactory(semester=older_semester)
        current = MembershipFactory(semester=self.semester)

        response = self.client.get(reverse('scheduling:members'))

        self.assertEqual([membership.pk for membership in response.context['members']], [current.pk])

    def test_orders_members_by_name(self):
        """The roster is ordered by the Person's name, not by Membership creation order."""
        last = MembershipFactory(semester=self.semester, person=PersonFactory(name='Yolanda Placeholder'))
        first = MembershipFactory(semester=self.semester, person=PersonFactory(name='Anders Placeholder'))
        middle = MembershipFactory(semester=self.semester, person=PersonFactory(name='Marlow Placeholder'))

        response = self.client.get(reverse('scheduling:members'))

        self.assertEqual(
            [membership.pk for membership in response.context['members']],
            [first.pk, middle.pk, last.pk],
        )

    def test_renders_each_members_name_declared_roles_and_song_count(self):
        """Each row shows the Person's name, their declared Roles for the Semester, and their Song count."""
        membership = MembershipFactory(semester=self.semester, person=self.person)
        MembershipRoleFactory(membership=membership, role=RoleFactory(name='Bassist'))
        MembershipRoleFactory(membership=membership, role=RoleFactory(name='Vocalist'))
        song = SongFactory(semester=self.semester)
        SongRoleAssignmentFactory(song=song, person=self.person)

        response = self.client.get(reverse('scheduling:members'))

        self.assertContains(response, 'Zoe Placeholder')
        self.assertContains(response, 'Bassist')
        self.assertContains(response, 'Vocalist')
        self.assertEqual(response.context['members'][0].songs_count, 1)

    def test_declared_roles_are_listed_alphabetically(self):
        """A member's declared Roles render in Role-name order, whatever order they were declared in."""
        membership = MembershipFactory(semester=self.semester, person=self.person)
        MembershipRoleFactory(membership=membership, role=RoleFactory(name='Vocalist'))
        MembershipRoleFactory(membership=membership, role=RoleFactory(name='Bassist'))

        response = self.client.get(reverse('scheduling:members'))

        content = response.content.decode()
        self.assertLess(content.index('Bassist'), content.index('Vocalist'))

    def test_shows_a_dash_for_a_member_with_no_declared_roles(self):
        """A Membership with no MembershipRoles still renders a row, with a placeholder in the Roles column."""
        MembershipFactory(semester=self.semester, person=self.person)

        response = self.client.get(reverse('scheduling:members'))

        self.assertEqual(response.context['members'][0].songs_count, 0)
        self.assertContains(response, '&mdash;')

    def test_song_count_counts_distinct_songs_in_the_current_semester_only(self):
        """A member assigned twice to one Song counts it once, and older-Semester Songs never count."""
        older_semester = SemesterFactory()
        self.semester = SemesterFactory()
        MembershipFactory(semester=self.semester, person=self.person)
        song = SongFactory(semester=self.semester)
        SongRoleAssignmentFactory(song=song, person=self.person, role=RoleFactory())
        SongRoleAssignmentFactory(song=song, person=self.person, role=RoleFactory())
        SongRoleAssignmentFactory(song=SongFactory(semester=older_semester), person=self.person)

        response = self.client.get(reverse('scheduling:members'))

        self.assertEqual(response.context['members'][0].songs_count, 1)

    def test_song_count_is_per_member(self):
        """Another member's Song assignments don't inflate this member's count."""
        MembershipFactory(semester=self.semester, person=self.person)
        other = PersonFactory(name='Anders Placeholder')
        MembershipFactory(semester=self.semester, person=other)
        SongRoleAssignmentFactory(song=SongFactory(semester=self.semester), person=other)

        response = self.client.get(reverse('scheduling:members'))

        counts = {membership.person.name: membership.songs_count for membership in response.context['members']}
        self.assertEqual(counts, {'Anders Placeholder': 1, 'Zoe Placeholder': 0})

    def test_each_name_links_to_the_person_page(self):
        """A member's name links to their own /members/<pk>/ page (issue #138, slice 2 of map #135)."""
        MembershipFactory(semester=self.semester, person=self.person)

        response = self.client.get(reverse('scheduling:members'))

        expected_href = reverse('scheduling:member-detail', args=[self.person.pk])
        self.assertContains(response, f'href="{expected_href}"')

    def test_does_not_expose_email_or_admin_status(self):
        """The roster is deliberately name/roles/songs only — no email column, no admin badge."""
        admin = PersonFactory(name='Anders Placeholder', is_admin=True)
        MembershipFactory(semester=self.semester, person=admin)

        response = self.client.get(reverse('scheduling:members'))

        self.assertNotContains(response, admin.email)
        self.assertNotContains(response, 'Admin')

    def test_roster_query_count_does_not_grow_with_the_roster(self):
        """Rendering the roster costs a fixed number of queries however many members there are."""
        for name in ('Anders Placeholder', 'Marlow Placeholder'):
            membership = MembershipFactory(semester=self.semester, person=PersonFactory(name=name))
            MembershipRoleFactory(membership=membership, role=RoleFactory())
            SongRoleAssignmentFactory(song=SongFactory(semester=self.semester), person=membership.person)

        with CaptureQueriesContext(connection) as small_roster:
            self.client.get(reverse('scheduling:members'))

        for name in ('Bennet Placeholder', 'Corin Placeholder', 'Delia Placeholder'):
            membership = MembershipFactory(semester=self.semester, person=PersonFactory(name=name))
            MembershipRoleFactory(membership=membership, role=RoleFactory())
            SongRoleAssignmentFactory(song=SongFactory(semester=self.semester), person=membership.person)

        with self.assertNumQueries(len(small_roster.captured_queries)):
            self.client.get(reverse('scheduling:members'))
