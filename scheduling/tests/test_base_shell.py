"""Shared member nav shell + Overview placeholder route (issue #85)."""

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import SemesterFactory, SongFactory

PASSWORD = 'a-strong-test-password-123'

NAV_MARKER = '<nav>'

NAV_ROUTES = {
    'scheduling:overview': 'Overview',
    'scheduling:schedule': 'My Schedule',
    'scheduling:setlist': 'Songs',
    'scheduling:members': 'Band Members',
    'scheduling:member-detail': 'Profile',
}


def nav_url(view_name, person):
    """Reverse a nav route, supplying `person`'s pk for the per-person Profile tab."""
    if view_name == 'scheduling:member-detail':
        return reverse(view_name, args=[person.pk])
    return reverse(view_name)


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAccessTests(TestCase):
    def test_each_nav_route_redirects_anonymous_users_to_login(self):
        """An anonymous request to any of the nav routes redirects to login."""
        person = PersonFactory()
        for view_name in NAV_ROUTES:
            with self.subTest(view_name=view_name):
                url = nav_url(view_name, person)

                response = self.client.get(url)

                self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")


@override_settings(SECURE_SSL_REDIRECT=False)
class NavRenderingTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_each_route_marks_its_own_tab_as_current(self):
        """Each of the nav routes renders with aria-current="page" on its own tab link and no other."""
        for view_name, label in NAV_ROUTES.items():
            with self.subTest(view_name=view_name):
                response = self.client.get(nav_url(view_name, self.person))

                content = response.content.decode()
                self.assertEqual(response.status_code, 200)
                current_count = content.count('aria-current="page"')
                self.assertEqual(current_count, 1)
                self.assertIn(f'aria-current="page">{label}</a>', content)

    def test_recordings_renders_the_nav(self):
        """recordings.html, retrofitted onto the shell, renders the shared nav."""
        response = self.client.get(reverse('scheduling:recordings'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, NAV_MARKER)

    def test_song_detail_renders_the_nav(self):
        """song_detail.html, retrofitted onto the shell, renders the shared nav."""
        song = SongFactory()

        response = self.client.get(reverse('scheduling:song-detail', args=[song.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, NAV_MARKER)

    def test_member_detail_renders_the_nav(self):
        """member_detail.html renders the shared nav — your own page is reachable without a Membership."""
        SemesterFactory()

        response = self.client.get(reverse('scheduling:member-detail', args=[self.person.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, NAV_MARKER)

    def test_logout_form_posts_to_logout_and_ends_the_session(self):
        """The shell's logout form action, POSTed from a rendered page, ends the session."""
        response = self.client.get(reverse('scheduling:overview'))
        self.assertContains(response, f'action="{reverse("identity:logout")}"')
        self.assertIn('_auth_user_id', self.client.session)

        self.client.post(reverse('identity:logout'))

        self.assertNotIn('_auth_user_id', self.client.session)


@override_settings(SECURE_SSL_REDIRECT=False)
class OverviewViewTests(TestCase):
    def test_authenticated_request_renders_overview(self):
        """An authenticated request to '' returns 200 and renders the Overview view."""
        person = PersonFactory(password=PASSWORD)
        self.client.login(username=person.email, password=PASSWORD)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'scheduling/overview.html')
