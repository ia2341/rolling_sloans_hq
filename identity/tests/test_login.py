"""Login + sessions (issue #25): login/logout views and sliding session expiry."""

import re
from urllib.parse import urlsplit

from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from faker import Faker

from identity.factories import PersonFactory
from identity.services import invite_person

PASSWORD = 'a-strong-test-password-123'
fake = Faker()


@override_settings(SECURE_SSL_REDIRECT=False)
class LoginViewTests(TestCase):
    def test_valid_credentials_log_the_user_in(self):
        """POSTing valid credentials for a Person with a set password logs the user in."""
        person = PersonFactory(password=PASSWORD)

        response = self.client.post(
            reverse('identity:login'),
            {'username': person.email, 'password': PASSWORD},
        )

        self.assertTrue(response.wsgi_request.user.is_authenticated)
        self.assertIn('_auth_user_id', self.client.session)

    def test_invalid_credentials_do_not_log_the_user_in(self):
        """POSTing invalid credentials does not log the user in."""
        person = PersonFactory(password=PASSWORD)

        response = self.client.post(
            reverse('identity:login'),
            {'username': person.email, 'password': 'wrong-password'},
        )

        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertNotIn('_auth_user_id', self.client.session)


@override_settings(SECURE_SSL_REDIRECT=False)
class LogoutViewTests(TestCase):
    def test_logout_clears_the_session(self):
        """Logging out clears the session."""
        person = PersonFactory(password=PASSWORD)
        self.client.login(username=person.email, password=PASSWORD)
        self.assertIn('_auth_user_id', self.client.session)

        self.client.post(reverse('identity:logout'))

        self.assertNotIn('_auth_user_id', self.client.session)


@override_settings(SECURE_SSL_REDIRECT=False)
class LoginRedirectTests(TestCase):
    """A next-less login must land somewhere real, not Django's default /accounts/profile/ (issue #296)."""

    def test_bounce_then_login_still_honours_next(self):
        """LoginRequiredMixin's bounce carries ?next=, and a login through it still lands there."""
        person = PersonFactory(password=PASSWORD)
        bounce = self.client.get(reverse('scheduling:schedule'), follow=True)
        login_path = bounce.redirect_chain[-1][0]
        self.assertIn(f'next={reverse("scheduling:schedule")}', login_path)

        response = self.client.post(
            login_path,
            {'username': person.email, 'password': PASSWORD},
        )

        self.assertRedirects(response, reverse('scheduling:schedule'))

    def test_direct_login_visit_then_login_lands_on_a_real_page(self):
        """Visiting /accounts/login/ directly (no ?next=), then logging in, must not 404."""
        person = PersonFactory(password=PASSWORD)

        response = self.client.post(
            reverse('identity:login'),
            {'username': person.email, 'password': PASSWORD},
        )

        self.assertRedirects(response, reverse('scheduling:overview'))

    def test_logout_then_login_lands_on_a_real_page(self):
        """Logging out and logging back in (no ?next=) must not 404."""
        person = PersonFactory(password=PASSWORD)
        self.client.login(username=person.email, password=PASSWORD)
        self.client.post(reverse('identity:logout'))

        response = self.client.post(
            reverse('identity:login'),
            {'username': person.email, 'password': PASSWORD},
        )

        self.assertRedirects(response, reverse('scheduling:overview'))

    def test_invite_set_password_then_login_lands_on_a_real_page(self):
        """A brand-new invited member's very first login, right after setting their password, must not 404."""
        person = invite_person(name=fake.name(), email=fake.email(domain='example.com'))
        set_password_link = re.search(r'https?://\S+', mail.outbox[0].body).group()
        set_password_path = urlsplit(set_password_link).path

        get_response = self.client.get(set_password_path, follow=True)
        form_url = get_response.request['PATH_INFO']
        self.client.post(
            form_url,
            {'new_password1': PASSWORD, 'new_password2': PASSWORD},
        )
        self.client.logout()

        response = self.client.post(
            reverse('identity:login'),
            {'username': person.email, 'password': PASSWORD},
        )

        self.assertRedirects(response, reverse('scheduling:overview'))


class LoginUrlSettingTests(TestCase):
    def test_login_url_matches_the_login_route(self):
        """settings.LOGIN_URL must track identity:login, so a route rename fails loudly instead of breaking redirects."""
        self.assertEqual(settings.LOGIN_URL, reverse('identity:login'))


class SessionSettingsTests(TestCase):
    def test_session_cookie_age_is_30_days(self):
        """SESSION_COOKIE_AGE is 30 days, for a month-long sliding session."""
        self.assertEqual(settings.SESSION_COOKIE_AGE, 60 * 60 * 24 * 30)

    def test_session_save_every_request_is_enabled(self):
        """SESSION_SAVE_EVERY_REQUEST is enabled, so activity extends the session."""
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)
