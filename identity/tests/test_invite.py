"""The invite flow: service function + set-password confirm view (issue #24)."""

import re
from unittest.mock import patch
from urllib.parse import urlsplit

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from faker import Faker

from identity.models import Person
from identity.services import EmailDeliveryError, invite_person

fake = Faker()


def invite_args():
    """Build a fresh, fake (name, email) kwargs dict for calling invite_person in tests."""
    return {'name': fake.name(), 'email': fake.email(domain='example.com')}


def extract_set_password_path(email_body):
    """Pull the path component of the set-password link out of an invite email body."""
    match = re.search(r'https?://\S+', email_body)
    assert match, f'no set-password link found in email body: {email_body!r}'
    return urlsplit(match.group()).path


class InvitePersonTests(TestCase):
    def test_creates_person_with_unusable_password(self):
        """A successful invite creates exactly one Person with no usable password."""
        args = invite_args()
        person = invite_person(**args)

        self.assertFalse(person.has_usable_password())
        self.assertEqual(Person.objects.get(pk=person.pk).email, args['email'])

    def test_sends_invite_email_with_working_link(self):
        """A successful invite sends exactly one email containing a set-password link."""
        args = invite_args()
        invite_person(**args)

        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertIn(args['email'], sent.to)
        self.assertIn('set-password', sent.body)

    def test_rolls_back_person_when_send_mail_raises(self):
        """If send_mail raises, the exception propagates and no Person row is left committed."""
        args = invite_args()

        with patch('identity.services.send_mail', side_effect=RuntimeError('boom')), \
                self.assertRaises(RuntimeError):
            invite_person(**args)

        self.assertFalse(Person.objects.filter(email=args['email']).exists())

    def test_rolls_back_person_when_send_mail_delivers_nothing(self):
        """If send_mail reports zero messages delivered, invite_person raises and rolls back."""
        args = invite_args()

        with patch('identity.services.send_mail', return_value=0), \
                self.assertRaises(EmailDeliveryError):
            invite_person(**args)

        self.assertFalse(Person.objects.filter(email=args['email']).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class SetPasswordFlowTests(TestCase):
    def setUp(self):
        self.person = invite_person(**invite_args())
        self.set_password_path = extract_set_password_path(mail.outbox[0].body)

    def test_link_leads_to_working_set_password_form(self):
        response = self.client.get(self.set_password_path, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['validlink'])

    def test_submitting_new_password_makes_account_loggable_in(self):
        get_response = self.client.get(self.set_password_path, follow=True)
        form_url = get_response.request['PATH_INFO']

        self.assertFalse(self.person.has_usable_password())

        post_response = self.client.post(
            form_url,
            {'new_password1': 'a-strong-new-password-1', 'new_password2': 'a-strong-new-password-1'},
        )

        self.assertRedirects(post_response, reverse('identity:set-password-complete'))
        reloaded = Person.objects.get(pk=self.person.pk)
        self.assertTrue(reloaded.has_usable_password())
        self.assertTrue(reloaded.check_password('a-strong-new-password-1'))

    def test_link_is_single_use_on_replayed_get(self):
        get_response = self.client.get(self.set_password_path, follow=True)
        form_url = get_response.request['PATH_INFO']
        self.client.post(
            form_url,
            {'new_password1': 'a-strong-new-password-1', 'new_password2': 'a-strong-new-password-1'},
        )

        # Re-visiting the original emailed link after the password has
        # already been set must not present a working form.
        self.client.logout()
        second_response = self.client.get(self.set_password_path, follow=True)

        self.assertFalse(second_response.context['validlink'])

    def test_link_is_single_use_on_replayed_post(self):
        get_response = self.client.get(self.set_password_path, follow=True)
        form_url = get_response.request['PATH_INFO']
        self.client.post(
            form_url,
            {'new_password1': 'a-strong-new-password-1', 'new_password2': 'a-strong-new-password-1'},
        )

        # Replaying the POST against the same (now-stale) form URL, in the
        # same session, must not be accepted as a second password change.
        replay_response = self.client.post(
            form_url,
            {'new_password1': 'a-different-password-2', 'new_password2': 'a-different-password-2'},
        )

        self.assertFalse(replay_response.context['validlink'])
        reloaded = Person.objects.get(pk=self.person.pk)
        self.assertTrue(reloaded.check_password('a-strong-new-password-1'))
        self.assertFalse(reloaded.check_password('a-different-password-2'))

    def test_unauthenticated_post_to_set_password_form_without_prior_valid_link_fails(self):
        bogus_url = reverse(
            'identity:set-password-confirm',
            kwargs={'uidb64': 'bogus', 'token': 'bogus-token'},
        )

        response = self.client.get(bogus_url)

        self.assertFalse(response.context['validlink'])
        reloaded = Person.objects.get(pk=self.person.pk)
        self.assertFalse(reloaded.has_usable_password())


@override_settings(SECURE_SSL_REDIRECT=False)
class NoSelfRegistrationTests(TestCase):
    """There is no unauthenticated way to create a Person (issue #24 AC)."""

    def test_no_signup_or_register_url_is_registered(self):
        for name in ('signup', 'register', 'identity:signup', 'identity:register'):
            with self.assertRaises(NoReverseMatch):
                reverse(name)

    def test_admin_add_person_requires_authentication(self):
        add_url = reverse('admin:identity_person_add')
        args = invite_args()

        response = self.client.post(add_url, {
            'email': args['email'],
            'name': args['name'],
            'password1': 'a-strong-password-1',
            'password2': 'a-strong-password-1',
        })

        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login', response.url)
        self.assertFalse(Person.objects.filter(email=args['email']).exists())
