"""`GET`/`POST /api/login/` (issue #362): the SPA's own sign-in endpoint.

`test_login.py` already covers the server-rendered `identity:login` view and
its rate limit; this module covers the JSON sibling the SPA's `/login`
route actually posts to, including that both share one `LoginAttempt`-backed
rate limit rather than two independent ones.
"""

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from identity.models import LoginAttempt
from identity.services import MAX_FAILED_LOGIN_ATTEMPTS

PASSWORD = 'a-strong-test-password-123'


def login_api_url():
    """Return `/api/login/`."""
    return reverse('api-login')


@override_settings(SECURE_SSL_REDIRECT=False)
class LoginApiViewGetTests(TestCase):
    """`GET /api/login/`: reports whether the requester already has a session, for the Login page to redirect away."""

    def test_anonymous_request_reports_not_authenticated(self):
        """An anonymous GET reports `authenticated: false`, at 200 (never a 401 — this is the auth-status check itself)."""
        response = self.client.get(login_api_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'authenticated': False})

    def test_authenticated_request_reports_authenticated_with_context(self):
        """A signed-in GET reports `authenticated: true` alongside the usual `/api/` context block."""
        person = PersonFactory(password=PASSWORD)
        self.client.login(username=person.email, password=PASSWORD)

        response = self.client.get(login_api_url())

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body['authenticated'])
        self.assertEqual(body['context']['viewer']['id'], person.pk)


@override_settings(SECURE_SSL_REDIRECT=False)
class LoginApiViewPostTests(TestCase):
    """`POST /api/login/`: authenticates email + password and starts a session on success."""

    def _post(self, email, password):
        """Return the response for a login POST with the given JSON body."""
        return self.client.post(
            login_api_url(),
            data={'email': email, 'password': password},
            content_type='application/json',
        )

    def test_valid_credentials_start_a_session_and_return_context(self):
        """Valid credentials log the session in and echo the viewer's own context block."""
        person = PersonFactory(password=PASSWORD)

        response = self._post(person.email, PASSWORD)

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body['ok'])
        self.assertEqual(body['context']['viewer']['id'], person.pk)
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_wrong_password_reports_a_generic_invalid_credentials_failure(self):
        """A wrong password reports the same generic reason a nonexistent email would (#327: never say which was wrong)."""
        person = PersonFactory(password=PASSWORD)

        response = self._post(person.email, 'not-the-real-password')

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(body['ok'])
        self.assertEqual(body['reason'], 'invalid_credentials')
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_unknown_email_reports_the_same_generic_failure(self):
        """An email with no account at all reports the identical failure shape a wrong password does."""
        response = self._post('nobody@example.com', 'whatever-password')

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(body['ok'])
        self.assertEqual(body['reason'], 'invalid_credentials')

    def test_malformed_body_reports_400(self):
        """A body that isn't parseable JSON gets the documented 400, matching every other /api/ endpoint."""
        response = self.client.post(
            login_api_url(),
            data=b'not json',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)

    def test_failed_attempts_are_recorded_and_eventually_rate_limited(self):
        """Enough failed attempts for one email trips the same rate limit `LoginView` enforces (#327), sharing one counter."""
        person = PersonFactory(password=PASSWORD)

        for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
            self._post(person.email, 'wrong-password')

        self.assertEqual(
            LoginAttempt.objects.filter(email=person.email, was_successful=False).count(),
            MAX_FAILED_LOGIN_ATTEMPTS,
        )

        response = self._post(person.email, PASSWORD)

        body = response.json()
        self.assertFalse(body['ok'])
        self.assertEqual(body['reason'], 'throttled')
        self.assertFalse(response.wsgi_request.user.is_authenticated)
