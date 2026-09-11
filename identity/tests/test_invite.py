"""Person creation: `add_person()` (no credential) and `create_person_with_temp_password()` (issue #482, ADR 0018)."""

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from faker import Faker

from identity.factories import PersonFactory
from identity.models import Person
from identity.services import (
    TEMP_PASSWORD_ALPHABET,
    add_person,
    clear_must_change_password,
    create_person_with_temp_password,
    invite_status_for,
)

fake = Faker()


def person_args():
    """Build a fresh, fake (name, email) kwargs dict for calling a Person-creation service function in tests."""
    return {'name': fake.name(), 'email': fake.email(domain='example.com')}


class AddPersonTests(TestCase):
    """`add_person()`: create a Person with no credential at all (issue #397)."""

    def test_creates_person_with_unusable_password_and_no_invite(self):
        """A successful add creates a Person with no usable password and sends no mail."""
        args = person_args()

        person = add_person(**args)

        self.assertFalse(person.has_usable_password())
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


class ClearMustChangePasswordTests(TestCase):
    """`clear_must_change_password()` (issue #484): the one place that retires the temp-password nag."""

    def test_clears_a_set_flag(self):
        """A Person flagged must_change_password comes back unflagged after the call, in the database too."""
        person = PersonFactory(must_change_password=True)

        clear_must_change_password(person)

        self.assertFalse(person.must_change_password)
        self.assertFalse(Person.objects.get(pk=person.pk).must_change_password)

    def test_is_a_no_op_on_an_already_clear_flag(self):
        """Calling it on a Person who never had the flag set leaves it clear, without erroring."""
        person = PersonFactory(must_change_password=False)

        clear_must_change_password(person)

        self.assertFalse(Person.objects.get(pk=person.pk).must_change_password)


class CreatePersonWithTempPasswordTests(TestCase):
    """`create_person_with_temp_password()`: the one creation path (issue #482, ADR 0018)."""

    def test_creates_a_person_with_a_real_usable_password(self):
        """The returned Person can sign in immediately -- no unusable password, no separate accept step."""
        args = person_args()

        person, temp_password = create_person_with_temp_password(**args)

        self.assertTrue(person.has_usable_password())
        self.assertTrue(person.check_password(temp_password))
        self.assertEqual(Person.objects.get(pk=person.pk).email, args['email'])

    def test_sets_must_change_password(self):
        person, _ = create_person_with_temp_password(**person_args())

        self.assertTrue(person.must_change_password)
        self.assertTrue(Person.objects.get(pk=person.pk).must_change_password)

    def test_sends_no_mail(self):
        create_person_with_temp_password(**person_args())

        self.assertEqual(len(mail.outbox), 0)

    def test_temp_password_avoids_visually_ambiguous_characters(self):
        """ADR 0018: the generated password is read aloud or typed from a text, so it drops 0/O, 1/l/I."""
        _, temp_password = create_person_with_temp_password(**person_args())

        self.assertEqual(len(temp_password), 12)
        self.assertTrue(set(temp_password) <= set(TEMP_PASSWORD_ALPHABET))
        for ambiguous in '0O1lI':
            self.assertNotIn(ambiguous, temp_password)

    def test_two_calls_generate_different_passwords(self):
        """Not a fixed or reused string -- each call mints a fresh plaintext."""
        _, first = create_person_with_temp_password(**person_args())
        _, second = create_person_with_temp_password(**person_args())

        self.assertNotEqual(first, second)


@override_settings(SECURE_SSL_REDIRECT=False)
class NoSelfRegistrationTests(TestCase):
    """There is no unauthenticated way to create a Person (issue #24 AC)."""

    def test_no_signup_or_register_url_is_registered(self):
        for name in ('signup', 'register', 'identity:signup', 'identity:register'):
            with self.assertRaises(NoReverseMatch):
                reverse(name)

    def test_admin_add_person_requires_authentication(self):
        add_url = reverse('admin:identity_person_add')
        args = person_args()

        response = self.client.post(add_url, {
            'email': args['email'],
            'name': args['name'],
            'password1': 'a-strong-password-1',
            'password2': 'a-strong-password-1',
        })

        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login', response.url)
        self.assertFalse(Person.objects.filter(email=args['email']).exists())
