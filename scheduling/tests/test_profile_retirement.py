"""`/me/profile/` is retired in favour of `/members/<pk>/` (issue #139, slice 3 of map #135).

These are migration tests, not feature tests: they assert the old route is
*gone* — unreversible, unroutable, and unlinked — because `MemberDetailView`
now carries the behaviour it used to hold. Nothing shipped to users, so no
redirect is kept.
"""

from django.template import TemplateDoesNotExist, loader
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from identity.factories import PersonFactory
from scheduling.factories import MembershipFactory, SemesterFactory

PASSWORD = 'a-strong-test-password-123'


@override_settings(SECURE_SSL_REDIRECT=False)
class ProfileRouteRetiredTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_profile_route_name_no_longer_reverses(self):
        """`scheduling:profile` is not a route name any more, so reversing it raises."""
        with self.assertRaises(NoReverseMatch):
            reverse('scheduling:profile')

    def test_profile_path_is_not_routed(self):
        """A GET to the retired /me/profile/ path 404s rather than redirecting anywhere."""
        response = self.client.get('/me/profile/')

        self.assertEqual(response.status_code, 404)

    def test_profile_path_is_not_routed_for_post(self):
        """A POST to the retired /me/profile/ path 404s too — no write surface survives there."""
        response = self.client.post('/me/profile/', {'roles': []})

        self.assertEqual(response.status_code, 404)

    def test_profile_template_is_gone(self):
        """The retired profile.html is no longer loadable, so nothing can render it by accident."""
        with self.assertRaises(TemplateDoesNotExist):
            loader.get_template('scheduling/profile.html')


@override_settings(SECURE_SSL_REDIRECT=False)
class ProfileNavItemTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_nav_profile_item_points_at_your_own_member_page(self):
        """The Profile nav item links to /members/<your pk>/, not the retired route."""
        response = self.client.get(reverse('scheduling:overview'))

        own_url = reverse('scheduling:member-detail', args=[self.person.pk])
        self.assertContains(response, f'href="{own_url}"')
        self.assertNotContains(response, 'href="/me/profile/"')

    def test_nav_profile_item_is_current_on_your_own_page(self):
        """Your own member page marks the Profile tab as the current page."""
        SemesterFactory()

        response = self.client.get(reverse('scheduling:member-detail', args=[self.person.pk]))

        self.assertContains(response, 'aria-current="page">Profile</a>')

    def test_nav_profile_item_is_not_current_on_a_teammates_page(self):
        """A teammate's member page is not your Profile, so no nav tab is marked current."""
        semester = SemesterFactory()
        teammate = PersonFactory()
        MembershipFactory(person=teammate, semester=semester)

        response = self.client.get(reverse('scheduling:member-detail', args=[teammate.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'aria-current="page"')

    def test_nav_profile_item_resolves_without_a_current_semester_membership(self):
        """A member with no current-Semester Membership still reaches their own page from the nav."""
        SemesterFactory()

        response = self.client.get(reverse('scheduling:member-detail', args=[self.person.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-current="page">Profile</a>')

    def test_nav_profile_item_resolves_with_no_current_semester_at_all(self):
        """With no Semester created yet, the Profile nav item still resolves and renders."""
        response = self.client.get(reverse('scheduling:member-detail', args=[self.person.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-current="page">Profile</a>')
