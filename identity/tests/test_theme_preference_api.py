"""`POST /api/theme/` (issue #500): the SPA's self-only theme-preference endpoint."""

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory

PASSWORD = 'a-strong-password-123'


def theme_url():
    """Return `/api/theme/`."""
    return reverse('api-theme-preference')


@override_settings(SECURE_SSL_REDIRECT=False)
class ThemePreferenceApiViewTests(TestCase):
    """Self-only by construction: there is no `pk` in this route, so it can only ever act on `request.user`."""

    def setUp(self):
        """Log in as a synthetic Person before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def _post(self, theme_preference):
        """Return the response for a theme-preference POST with the given value."""
        return self.client.post(
            theme_url(), data={'theme_preference': theme_preference}, content_type='application/json',
        )

    def test_new_person_defaults_to_system(self):
        """A freshly created Person (first-time login) starts on `system`, never `light`/`dark`."""
        self.assertEqual(self.person.theme_preference, 'system')

    def test_valid_change_persists_and_echoes_in_context(self):
        """A valid change reports ok, persists, and shows up in the same response's `context.viewer`."""
        response = self._post('dark')

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['context']['viewer']['theme_preference'], 'dark')
        self.person.refresh_from_db()
        self.assertEqual(self.person.theme_preference, 'dark')

    def test_can_switch_back_to_system(self):
        """A Person who already picked `light`/`dark` can switch back to `system`."""
        self._post('light')

        response = self._post('system')

        self.assertTrue(response.json()['ok'])
        self.person.refresh_from_db()
        self.assertEqual(self.person.theme_preference, 'system')

    def test_unrecognized_value_is_rejected_and_changes_nothing(self):
        """A value outside light/dark/system reports ok: false and leaves the stored preference untouched."""
        response = self._post('rainbow')

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['ok'])
        self.assertIn('theme_preference', body['non_field_errors'][0])
        self.person.refresh_from_db()
        self.assertEqual(self.person.theme_preference, 'system')

    def test_anonymous_request_401s_not_302s(self):
        """An anonymous POST gets the bare JSON 401, never a redirect (issue #326)."""
        self.client.logout()

        response = self._post('dark')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)
