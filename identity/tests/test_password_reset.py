"""`password-reset/`'s static "contact an admin" page (issue #487, ADR 0018).

The self-serve forgot-password flow this route used to serve is retired:
the recovery path is now an admin's Reset password action on
`/members/<pk>/`, or `manage.py reset_password` for the sole-active-admin
lockout case. The URL is kept live (not deleted) so a bookmark or a
search-engine-cached link doesn't 404 — it just renders a static message
now, with no form to submit and no email sent.
"""

from django.core import mail
from django.test import TestCase
from django.urls import reverse


class PasswordResetRequestViewTests(TestCase):
    def test_get_renders_a_contact_an_admin_message(self):
        """The page renders successfully and points a locked-out member at an admin."""
        response = self.client.get(reverse('identity:password-reset'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'admin')

    def test_post_is_refused_and_sends_no_mail(self):
        """The page takes no form input: an old bookmarked form's POST is refused (405), and nothing is ever mailed."""
        response = self.client.post(reverse('identity:password-reset'), {'email': 'someone@example.com'})

        self.assertEqual(response.status_code, 405)
        self.assertEqual(len(mail.outbox), 0)
