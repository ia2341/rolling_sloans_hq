"""The invite flow: service function + set-password confirm view (issue #24)."""

import re
import sys
from io import StringIO
from unittest.mock import patch
from urllib.parse import urlsplit

from django.core import mail
from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from faker import Faker

from identity.factories import PersonFactory
from identity.models import Person
from identity.services import (
    TEMP_PASSWORD_ALPHABET,
    AlreadyHasPasswordError,
    EmailDeliveryError,
    add_person,
    create_person_with_temp_password,
    invite_person,
    invite_status_for,
    resend_invite,
)

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

    def test_invite_email_never_carries_a_password(self):
        """The invite mail carries a link, never a plaintext password or code (#327)."""
        args = invite_args()
        person = invite_person(**args)

        sent = mail.outbox[0]
        self.assertNotIn(person.password, sent.body)
        self.assertNotRegex(sent.body, r'\b\d{6}\b')

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

    def test_stamps_invited_at(self):
        """A successful invite stamps invited_at (issue #397)."""
        person = invite_person(**invite_args())

        self.assertIsNotNone(person.invited_at)
        self.assertIsNotNone(Person.objects.get(pk=person.pk).invited_at)


class AddPersonTests(TestCase):
    """`add_person()`: create a Person with no invite sent at all (issue #397)."""

    def test_creates_person_with_unusable_password_and_no_invite(self):
        """A successful add creates a Person with no usable password, unset invited_at, and sends no mail."""
        args = invite_args()

        person = add_person(**args)

        self.assertFalse(person.has_usable_password())
        self.assertIsNone(person.invited_at)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Person.objects.get(pk=person.pk).email, args['email'])


class InviteStatusForTests(TestCase):
    """`invite_status_for()`: the two-state credential lifecycle status (issue #482, ADR 0018)."""

    def test_must_change_password_for_a_person_with_the_flag_set(self):
        person = PersonFactory(must_change_password=True)

        self.assertEqual(invite_status_for(person), 'must_change_password')

    def test_active_for_a_person_with_the_flag_clear(self):
        person = PersonFactory(must_change_password=False)

        self.assertEqual(invite_status_for(person), 'active')

    def test_active_for_a_legacy_invited_person_ignoring_password_usability(self):
        """The legacy `has_usable_password()`/`invited_at` signals no longer factor in at all — only `must_change_password` does."""
        person = invite_person(**invite_args())

        self.assertEqual(invite_status_for(person), 'active')


class CreatePersonWithTempPasswordTests(TestCase):
    """`create_person_with_temp_password()`: the one creation path (issue #482, ADR 0018)."""

    def test_creates_a_person_with_a_real_usable_password(self):
        """The returned Person can sign in immediately -- no unusable password, no separate accept step."""
        args = invite_args()

        person, temp_password = create_person_with_temp_password(**args)

        self.assertTrue(person.has_usable_password())
        self.assertTrue(person.check_password(temp_password))
        self.assertEqual(Person.objects.get(pk=person.pk).email, args['email'])

    def test_sets_must_change_password(self):
        person, _ = create_person_with_temp_password(**invite_args())

        self.assertTrue(person.must_change_password)
        self.assertTrue(Person.objects.get(pk=person.pk).must_change_password)

    def test_sends_no_mail(self):
        create_person_with_temp_password(**invite_args())

        self.assertEqual(len(mail.outbox), 0)

    def test_temp_password_avoids_visually_ambiguous_characters(self):
        """ADR 0018: the generated password is read aloud or typed from a text, so it drops 0/O, 1/l/I."""
        _, temp_password = create_person_with_temp_password(**invite_args())

        self.assertEqual(len(temp_password), 12)
        self.assertTrue(set(temp_password) <= set(TEMP_PASSWORD_ALPHABET))
        for ambiguous in '0O1lI':
            self.assertNotIn(ambiguous, temp_password)

    def test_two_calls_generate_different_passwords(self):
        """Not a fixed or reused string -- each call mints a fresh plaintext."""
        _, first = create_person_with_temp_password(**invite_args())
        _, second = create_person_with_temp_password(**invite_args())

        self.assertNotEqual(first, second)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend')
class ConsoleBackendInviteTests(TestCase):
    """The local-dev path (issue #299): the console backend a DEBUG=True checkout gets by default.

    Django's test runner swaps in the locmem backend, so the backend a
    developer actually runs against is never otherwise exercised. These pin
    that an invite through it succeeds — no Resend call, so no 401 — and that
    the set-password link reaches the terminal, which is the whole point of
    the fallback.
    """

    def test_invite_succeeds_and_prints_the_set_password_link(self):
        """An invite under the console backend commits the Person and writes the link to stdout."""
        args = invite_args()

        with patch.object(sys, 'stdout', new=StringIO()) as captured:
            person = invite_person(**args)
            printed = captured.getvalue()

        self.assertTrue(Person.objects.filter(pk=person.pk).exists())
        self.assertIn(args['email'], printed)
        self.assertIn('set-password', extract_set_password_path(printed))


@override_settings(SECURE_SSL_REDIRECT=False)
class SetPasswordFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Invite a Person once and extract the set-password link every test in this class reuses.

        `setUpTestData` runs in `setUpClass`, before Django's per-test
        `mail.outbox` reset, so it can start behind whatever the previous
        class's last test method left in the outbox: clear it first rather
        than trusting `mail.outbox[0]` to be this invite.
        """
        mail.outbox = []
        cls.person = invite_person(**invite_args())
        cls.set_password_path = extract_set_password_path(mail.outbox[0].body)

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

        self.assertEqual(post_response.status_code, 200)
        self.assertTrue(post_response.context['done'])
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


class ResendInviteTests(TestCase):
    def test_resends_to_a_never_set_password_person_without_creating_a_second_row(self):
        """resend_invite() on a pending Person sends and creates no second Person row."""
        person = PersonFactory()
        self.assertFalse(person.has_usable_password())

        resend_invite(person)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(person.email, mail.outbox[0].to)
        self.assertIn('set-password', mail.outbox[0].body)
        self.assertEqual(Person.objects.filter(email=person.email).count(), 1)

    def test_refused_for_a_person_with_a_usable_password(self):
        """resend_invite() on a Person who already set a password is refused and sends nothing."""
        person = PersonFactory(password='a-strong-password-123')

        with self.assertRaises(AlreadyHasPasswordError):
            resend_invite(person)

        self.assertEqual(len(mail.outbox), 0)

    def test_stamps_invited_at_for_a_never_invited_person(self):
        """resend_invite() on a not-yet-invited Person (issue #397) sends and stamps invited_at, same as a fresh invite."""
        person = add_person(**invite_args())
        self.assertIsNone(person.invited_at)

        resend_invite(person)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIsNotNone(Person.objects.get(pk=person.pk).invited_at)


class InvitePersonSendModeTests(TestCase):
    """The `send_via_on_commit` seam #336's roster Pending Buffer apply needs (#327)."""

    def test_inline_mode_rolls_back_the_person_on_send_failure(self):
        """The default (inline) mode still rolls the Person row back if the send fails."""
        args = invite_args()

        with patch('identity.services.send_mail', side_effect=RuntimeError('boom')), \
                self.assertRaises(RuntimeError):
            invite_person(**args, send_via_on_commit=False)

        self.assertFalse(Person.objects.filter(email=args['email']).exists())

    def test_on_commit_mode_sends_nothing_until_commit(self):
        """`send_via_on_commit=True` defers the send past the end of the calling transaction.

        `TestCase` itself wraps every test in an outer atomic block that's
        rolled back rather than committed, so `on_commit` callbacks never
        fire on their own here; `captureOnCommitCallbacks(execute=True)`
        is Django's documented way to still exercise them under `TestCase`.
        """
        args = invite_args()

        with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
            invite_person(**args, send_via_on_commit=True)
            self.assertEqual(len(mail.outbox), 0)

        self.assertEqual(len(mail.outbox), 1)

    def test_on_commit_mode_sends_nothing_under_rollback(self):
        """`send_via_on_commit=True` sends nothing at all if the outer transaction rolls back (an admin Preview, ADR 0008)."""
        args = invite_args()

        with self.assertRaises(RuntimeError), transaction.atomic():
            invite_person(**args, send_via_on_commit=True)
            raise RuntimeError('simulate a Preview rollback')

        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(Person.objects.filter(email=args['email']).exists())
