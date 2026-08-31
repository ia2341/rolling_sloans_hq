import unittest

from django.conf import settings
from django.test import TestCase

from identity.factories import PersonFactory
from identity.models import Person


class AuthUserModelTests(unittest.TestCase):
    def test_auth_user_model_points_at_identity_person(self):
        self.assertEqual(settings.AUTH_USER_MODEL, 'identity.Person')

    def test_no_username_field(self):
        self.assertFalse(hasattr(Person, 'username'))
        self.assertEqual(Person.USERNAME_FIELD, 'email')


class PersonPasswordTests(TestCase):
    def test_password_is_stored_hashed_not_plaintext(self):
        person = PersonFactory.create(password='a-strong-password')

        self.assertNotEqual(person.password, 'a-strong-password')
        self.assertTrue(person.check_password('a-strong-password'))


class PersonIsAdminSyncTests(TestCase):
    def test_promoting_is_admin_sets_staff_and_superuser(self):
        person = PersonFactory.create(is_admin=True)

        reloaded = Person.objects.get(pk=person.pk)
        self.assertTrue(reloaded.is_admin)
        self.assertTrue(reloaded.is_staff)
        self.assertTrue(reloaded.is_superuser)

    def test_demoting_is_admin_reverses_staff_and_superuser(self):
        """Verify that demoting an administrator clears staff and superuser privileges."""
        person = PersonFactory.create(is_admin=True)

        person.is_admin = False
        person.save()

        reloaded = Person.objects.get(pk=person.pk)
        self.assertFalse(reloaded.is_admin)
        self.assertFalse(reloaded.is_staff)
        self.assertFalse(reloaded.is_superuser)

    def test_non_admin_person_is_not_staff_or_superuser(self):
        person = PersonFactory.create(is_admin=False)

        reloaded = Person.objects.get(pk=person.pk)
        self.assertFalse(reloaded.is_staff)
        self.assertFalse(reloaded.is_superuser)

    def test_update_fields_save_still_persists_mirrored_flags(self):
        person = PersonFactory.create(is_admin=False)

        person.is_admin = True
        person.save(update_fields=['is_admin'])

        reloaded = Person.objects.get(pk=person.pk)
        self.assertTrue(reloaded.is_admin)
        self.assertTrue(reloaded.is_staff)
        self.assertTrue(reloaded.is_superuser)
