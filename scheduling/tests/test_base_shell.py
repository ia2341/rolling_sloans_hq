"""Shared member nav shell + Overview placeholder route (issue #85)."""

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory

PASSWORD = 'a-strong-test-password-123'

NAV_ROUTES = {
    'scheduling:overview': 'Overview',
    'scheduling:schedule': 'My Schedule',
    'scheduling:conflicts': 'Conflicts',
    'scheduling:setlist': 'Songs',
    'scheduling:profile': 'Profile',
}


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAccessTests(TestCase):
    def test_each_nav_route_redirects_anonymous_users_to_login(self):
        """An anonymous request to any of the five nav routes redirects to login."""
        for view_name in NAV_ROUTES:
            with self.subTest(view_name=view_name):
                url = reverse(view_name)

                response = self.client.get(url)

                self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")


@override_settings(SECURE_SSL_REDIRECT=False)
class NavRenderingTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_each_route_marks_its_own_tab_as_current(self):
        """Each of the five nav routes renders with aria-current="page" on its own tab link and no other."""
        for view_name, label in NAV_ROUTES.items():
            with self.subTest(view_name=view_name):
                response = self.client.get(reverse(view_name))

                content = response.content.decode()
                self.assertEqual(response.status_code, 200)
                current_count = content.count('aria-current="page"')
                self.assertEqual(current_count, 1)
                self.assertIn(f'aria-current="page">{label}</a>', content)


@override_settings(SECURE_SSL_REDIRECT=False)
class OverviewViewTests(TestCase):
    def test_authenticated_request_renders_placeholder_overview(self):
        """An authenticated request to '' returns 200 and renders the placeholder Overview view."""
        person = PersonFactory(password=PASSWORD)
        self.client.login(username=person.email, password=PASSWORD)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'scheduling/overview.html')
