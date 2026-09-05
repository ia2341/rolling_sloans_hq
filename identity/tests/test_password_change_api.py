"""`POST /api/password/` (issue #333): the SPA's self-only change-password endpoint.

`test_password_change.py` already pins the load-bearing contract that
`update_session_auth_hash()` keeps a changed session authenticated,
independent of any particular view. This module covers the endpoint itself:
a valid change, its per-field errors (wrong current password, mismatched
confirmation, a weak new password tripping `AUTH_PASSWORD_VALIDATORS`), and
that a valid change really does leave the session that made it signed in.
"""

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory

OLD_PASSWORD = 'a-strong-old-password-123'
NEW_PASSWORD = 'a-strong-new-password-456'


def password_change_url():
    """Return `/api/password/`."""
    return reverse('api-password-change')


@override_settings(SECURE_SSL_REDIRECT=False)
class PasswordChangeApiViewTests(TestCase):
    """Self-only by construction: there is no `pk` in this route, so it can only ever act on `request.user`."""

    def setUp(self):
        """Log in as a synthetic Person before each test."""
        self.person = PersonFactory(password=OLD_PASSWORD)
        self.client.login(username=self.person.email, password=OLD_PASSWORD)

    def _post(self, old_password, new_password1, new_password2):
        """Return the response for a change-password POST with the given field values."""
        return self.client.post(
            password_change_url(),
            data={
                'old_password': old_password,
                'new_password1': new_password1,
                'new_password2': new_password2,
            },
            content_type='application/json',
        )

    def test_valid_change_succeeds_and_keeps_the_session_authenticated(self):
        """A valid change reports ok, and a subsequent authenticated request in the same session still succeeds."""
        response = self._post(OLD_PASSWORD, NEW_PASSWORD, NEW_PASSWORD)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.person.refresh_from_db()
        self.assertTrue(self.person.check_password(NEW_PASSWORD))

        # update_session_auth_hash() is load-bearing (issue #333 user story
        # 49): without it, this next request would find the session's auth
        # hash stale and treat the user as logged out.
        follow_up = self.client.get(reverse('api-members'))
        self.assertEqual(follow_up.status_code, 200)

    def test_invalid_old_password_reports_a_per_field_error(self):
        """A wrong current password reports a field error on `old_password`, changing nothing."""
        response = self._post('not-the-real-password', NEW_PASSWORD, NEW_PASSWORD)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['ok'])
        self.assertIn('old_password', body['errors'])
        self.person.refresh_from_db()
        self.assertTrue(self.person.check_password(OLD_PASSWORD))

    def test_mismatched_confirmation_reports_a_per_field_error(self):
        """A new_password2 that doesn't match new_password1 reports a field error, changing nothing."""
        response = self._post(OLD_PASSWORD, NEW_PASSWORD, 'a-different-confirmation-789')

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['ok'])
        self.assertIn('new_password2', body['errors'])
        self.person.refresh_from_db()
        self.assertTrue(self.person.check_password(OLD_PASSWORD))

    def test_weak_new_password_reports_a_per_field_error(self):
        """A new password violating AUTH_PASSWORD_VALIDATORS (too short) reports a field error, changing nothing."""
        response = self._post(OLD_PASSWORD, 'short', 'short')

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['ok'])
        self.assertIn('new_password2', body['errors'])
        self.person.refresh_from_db()
        self.assertTrue(self.person.check_password(OLD_PASSWORD))

    def test_anonymous_request_401s_not_302s(self):
        """An anonymous POST gets the bare JSON 401, never a redirect (issue #326)."""
        self.client.logout()

        response = self._post(OLD_PASSWORD, NEW_PASSWORD, NEW_PASSWORD)

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)
