"""Login + sessions (issue #25): login/logout views and sliding session expiry."""

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from identity.factories import PersonFactory

PASSWORD = 'a-strong-test-password-123'


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


class LogoutViewTests(TestCase):
    def test_logout_clears_the_session(self):
        """Logging out clears the session."""
        person = PersonFactory(password=PASSWORD)
        self.client.login(username=person.email, password=PASSWORD)
        self.assertIn('_auth_user_id', self.client.session)

        self.client.post(reverse('identity:logout'))

        self.assertNotIn('_auth_user_id', self.client.session)


class SessionSettingsTests(TestCase):
    def test_session_cookie_age_is_30_days(self):
        """SESSION_COOKIE_AGE is 30 days, for a month-long sliding session."""
        self.assertEqual(settings.SESSION_COOKIE_AGE, 60 * 60 * 24 * 30)

    def test_session_save_every_request_is_enabled(self):
        """SESSION_SAVE_EVERY_REQUEST is enabled, so activity extends the session."""
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)
