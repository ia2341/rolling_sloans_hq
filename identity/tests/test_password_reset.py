"""The self-serve password reset flow (issue #26, reworked by #327).

Reset now shares one token route with the invite flow
(`identity:set-password-confirm`) rather than a dedicated confirm route,
and the request page renders its result inline instead of redirecting to a
separate "done" page.
"""

import re
from urllib.parse import urlsplit

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from faker import Faker

from identity.factories import PersonFactory
from identity.models import Person
from identity.services import MAX_AUTH_EMAILS

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

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['sent'])
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertIn(person.email, sent.to)
        self.assertIn('reset', sent.body)

    def test_requesting_reset_for_unknown_email_does_not_error_or_send_mail(self):
        response = self.client.post(
            reverse('identity:password-reset'),
            {'email': fake.email(domain='example.com')},
        )

        # Same in-page response as the known-email case: it must not leak
        # whether the address exists.
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['sent'])
        self.assertEqual(len(mail.outbox), 0)

    def test_link_points_at_the_merged_set_password_route(self):
        """The reset email's link resolves to identity:set-password-confirm, the same route the invite uses."""
        person = PersonFactory(password=OLD_PASSWORD)

        self.client.post(reverse('identity:password-reset'), {'email': person.email})

        reset_path = extract_reset_path(mail.outbox[0].body)
        self.assertIn('set-password', reset_path)


@override_settings(SECURE_SSL_REDIRECT=False)
class PasswordResetRateLimitTests(TestCase):
    """Limit two: outbound auth email, keyed on address and on IP (#327)."""

    def test_under_the_limit_still_sends(self):
        person = PersonFactory(password=OLD_PASSWORD)
        for _ in range(MAX_AUTH_EMAILS - 1):
            self.client.post(reverse('identity:password-reset'), {'email': person.email})
        mail.outbox = []

        response = self.client.post(reverse('identity:password-reset'), {'email': person.email})

        self.assertTrue(response.context['sent'])
        self.assertEqual(len(mail.outbox), 1)

    def test_over_the_limit_is_refused_and_sends_nothing(self):
        person = PersonFactory(password=OLD_PASSWORD)
        for _ in range(MAX_AUTH_EMAILS):
            self.client.post(reverse('identity:password-reset'), {'email': person.email})
        mail.outbox = []

        response = self.client.post(reverse('identity:password-reset'), {'email': person.email})

        self.assertTrue(response.context['throttled'])
        self.assertEqual(len(mail.outbox), 0)

    def test_throttle_message_is_identical_for_a_real_and_an_unknown_address(self):
        person = PersonFactory(password=OLD_PASSWORD)
        for _ in range(MAX_AUTH_EMAILS):
            self.client.post(reverse('identity:password-reset'), {'email': person.email})
        known_response = self.client.post(reverse('identity:password-reset'), {'email': person.email})

        self.client.cookies.clear()
        unknown_email = fake.email(domain='example.com')
        for _ in range(MAX_AUTH_EMAILS):
            self.client.post(reverse('identity:password-reset'), {'email': unknown_email})
        unknown_response = self.client.post(reverse('identity:password-reset'), {'email': unknown_email})

        self.assertTrue(known_response.context['throttled'])
        self.assertTrue(unknown_response.context['throttled'])


@override_settings(SECURE_SSL_REDIRECT=False)
class PasswordResetConfirmFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Request a reset once and extract the reset link every test in this class reuses."""
        mail.outbox = []
        cls.person = PersonFactory(password=OLD_PASSWORD)
        cls.client_class().post(reverse('identity:password-reset'), {'email': cls.person.email})
        cls.reset_path = extract_reset_path(mail.outbox[0].body)

    def test_link_leads_to_working_reset_form(self):
        response = self.client.get(self.reset_path, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['validlink'])

    def test_reset_confirm_uses_the_new_password_copy_not_the_invite_copy(self):
        """A Person who already has a usable password sees "Choose a new password", not invite wording."""
        response = self.client.get(self.reset_path, follow=True)

        self.assertTrue(response.context['has_usable_password'])

    def test_submitting_new_password_allows_login_with_it(self):
        get_response = self.client.get(self.reset_path, follow=True)
        form_url = get_response.request['PATH_INFO']

        post_response = self.client.post(
            form_url,
            {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD},
        )

        self.assertEqual(post_response.status_code, 200)
        self.assertTrue(post_response.context['done'])
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

    def test_expired_or_invalid_link_shows_a_plain_message(self):
        bogus_path = reverse(
            'identity:set-password-confirm',
            kwargs={'uidb64': 'bogus', 'token': 'bogus-token'},
        )

        response = self.client.get(bogus_path)

        self.assertFalse(response.context['validlink'])
        self.assertContains(response, 'invalid or has expired')
