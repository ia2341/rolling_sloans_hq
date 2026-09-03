"""The self-serve password reset flow (issue #26): request + confirm views."""

import re
from urllib.parse import urlsplit

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from faker import Faker

from identity.factories import PersonFactory
from identity.models import Person

fake = Faker()

OLD_PASSWORD = 'a-strong-old-password-123'
NEW_PASSWORD = 'a-strong-new-password-456'


def extract_reset_path(email_body):
    """Pull the path component of the reset link out of a password-reset email body."""
    match = re.search(r'https?://\S+', email_body)
    assert match, f'no reset link found in email body: {email_body!r}'
    return urlsplit(match.group()).path


@override_settings(SECURE_SSL_REDIRECT=False)
class PasswordResetRequestTests(TestCase):
    def test_requesting_reset_for_known_email_sends_a_working_link(self):
        person = PersonFactory(password=OLD_PASSWORD)

        response = self.client.post(reverse('identity:password-reset'), {'email': person.email})

        self.assertRedirects(response, reverse('identity:password-reset-done'))
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertIn(person.email, sent.to)
        self.assertIn('reset', sent.body)

    def test_requesting_reset_for_unknown_email_does_not_error_or_send_mail(self):
        response = self.client.post(
            reverse('identity:password-reset'),
            {'email': fake.email(domain='example.com')},
        )

        # Same redirect as the known-email case: the response must not leak
        # whether the address exists.
        self.assertRedirects(response, reverse('identity:password-reset-done'))
        self.assertEqual(len(mail.outbox), 0)


@override_settings(SECURE_SSL_REDIRECT=False)
class PasswordResetConfirmFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Request a reset once and extract the reset link every test in this class reuses."""
        cls.person = PersonFactory(password=OLD_PASSWORD)
        cls.client_class().post(reverse('identity:password-reset'), {'email': cls.person.email})
        cls.reset_path = extract_reset_path(mail.outbox[0].body)

    def test_link_leads_to_working_reset_form(self):
        response = self.client.get(self.reset_path, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['validlink'])

    def test_submitting_new_password_allows_login_with_it(self):
        get_response = self.client.get(self.reset_path, follow=True)
        form_url = get_response.request['PATH_INFO']

        post_response = self.client.post(
            form_url,
            {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD},
        )

        self.assertRedirects(post_response, reverse('identity:password-reset-complete'))
        self.client.logout()
        login_response = self.client.post(
            reverse('identity:login'),
            {'username': self.person.email, 'password': NEW_PASSWORD},
        )
        self.assertTrue(login_response.wsgi_request.user.is_authenticated)

    def test_old_password_no_longer_works_after_reset(self):
        get_response = self.client.get(self.reset_path, follow=True)
        form_url = get_response.request['PATH_INFO']
        self.client.post(form_url, {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})

        self.client.logout()
        login_response = self.client.post(
            reverse('identity:login'),
            {'username': self.person.email, 'password': OLD_PASSWORD},
        )

        self.assertFalse(login_response.wsgi_request.user.is_authenticated)

    def test_link_is_single_use_on_replayed_get(self):
        get_response = self.client.get(self.reset_path, follow=True)
        form_url = get_response.request['PATH_INFO']
        self.client.post(form_url, {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})

        self.client.logout()
        second_response = self.client.get(self.reset_path, follow=True)

        self.assertFalse(second_response.context['validlink'])

    def test_link_is_single_use_on_replayed_post(self):
        get_response = self.client.get(self.reset_path, follow=True)
        form_url = get_response.request['PATH_INFO']
        self.client.post(form_url, {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})

        replay_response = self.client.post(
            form_url,
            {'new_password1': 'yet-another-password-789', 'new_password2': 'yet-another-password-789'},
        )

        self.assertFalse(replay_response.context['validlink'])
        reloaded = Person.objects.get(pk=self.person.pk)
        self.assertTrue(reloaded.check_password(NEW_PASSWORD))
        self.assertFalse(reloaded.check_password('yet-another-password-789'))
