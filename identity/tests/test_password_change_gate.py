"""The request-level `must_change_password` gate (issue #487, ADR 0018).

`config.views.BaseView` refuses every route it gates to a signed-in Person
who still carries an admin-generated temp password, except the one route
that lets the flag clear (`PasswordChangeApiView`). This is deliberately a
server-side check, not a client-only redirect the SPA could skip -- these
tests exercise it directly against a real `/api/` route rather than
against `BaseView` in isolation, since the gate's whole point is that it
holds no matter which view is asked.
"""

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory

PASSWORD = 'a-strong-test-password-123'


@override_settings(SECURE_SSL_REDIRECT=False)
class PasswordChangeRequiredGateTests(TestCase):
    def setUp(self):
        """Log in as a synthetic Person who must change their password."""
        self.person = PersonFactory(password=PASSWORD, must_change_password=True)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_a_gated_route_refuses_with_the_documented_403(self):
        """An ordinary `/api/` route answers the documented JSON 403, not the view's usual response."""
        response = self.client.get(reverse('api-members'))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['error'], 'password_change_required')

    def test_the_change_password_endpoint_is_exempt(self):
        """`PasswordChangeApiView` is the one route this Person can still reach."""
        response = self.client.post(
            reverse('api-password-change'),
            data={'old_password': PASSWORD, 'new_password1': 'a-new-strong-password-456', 'new_password2': 'a-new-strong-password-456'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])

    def test_a_person_without_the_flag_is_not_gated(self):
        """A Person whose password isn't admin-generated (or already changed) is never gated."""
        clear_person = PersonFactory(password=PASSWORD, must_change_password=False)
        self.client.login(username=clear_person.email, password=PASSWORD)

        response = self.client.get(reverse('api-members'))

        self.assertEqual(response.status_code, 200)

    def test_login_itself_is_not_gated(self):
        """`LoginApiView` doesn't inherit `BaseView` at all, so a must-change-password Person can still authenticate."""
        self.client.logout()

        response = self.client.post(
            reverse('api-login'),
            data=f'{{"email": "{self.person.email}", "password": "{PASSWORD}"}}',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertTrue(response.json()['context']['viewer']['must_change_password'])
