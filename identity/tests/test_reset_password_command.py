"""`manage.py reset_password <email>` (issue #487, ADR 0018): the break-glass sole-active-admin recovery path."""

from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from identity.factories import PersonFactory
from identity.models import Person

OLD_PASSWORD = 'a-strong-old-password-123'


class ResetPasswordCommandTests(TestCase):
    def test_resets_the_password_and_flags_must_change_password(self):
        """A successful run sets a real, usable password and flags the forced change."""
        person = PersonFactory(password=OLD_PASSWORD, must_change_password=False)

        out = StringIO()
        call_command('reset_password', person.email, stdout=out)

        refreshed = Person.objects.get(pk=person.pk)
        self.assertTrue(refreshed.has_usable_password())
        self.assertFalse(refreshed.check_password(OLD_PASSWORD))
        self.assertTrue(refreshed.must_change_password)

    def test_prints_the_plaintext_to_stdout(self):
        """The generated temp password is printed, and it's the one that was actually set."""
        person = PersonFactory(password=OLD_PASSWORD)

        out = StringIO()
        call_command('reset_password', person.email, stdout=out)
        printed = out.getvalue()

        self.assertIn(person.email, printed)
        refreshed = Person.objects.get(pk=person.pk)
        # Pull the plaintext back out of the last line and confirm it's live.
        temp_password = printed.strip().splitlines()[-1].split(': ')[-1]
        self.assertTrue(refreshed.check_password(temp_password))

    def test_unknown_email_raises_command_error(self):
        """An email with no matching Person raises CommandError rather than crashing or silently doing nothing."""
        with self.assertRaises(CommandError):
            call_command('reset_password', 'no-such-person@example.com', stdout=StringIO())

    def test_carries_no_admin_count_guardrail(self):
        """Unlike `apply_password_reset()`, this command will happily reset the sole active admin (ADR 0018: no guardrail)."""
        sole_admin = PersonFactory(password=OLD_PASSWORD, is_admin=True, is_active=True)
        self.assertEqual(Person.objects.filter(is_admin=True, is_active=True).count(), 1)

        call_command('reset_password', sole_admin.email, stdout=StringIO())

        refreshed = Person.objects.get(pk=sole_admin.pk)
        self.assertFalse(refreshed.check_password(OLD_PASSWORD))
        self.assertTrue(refreshed.must_change_password)

    def test_works_on_a_deactivated_person_too(self):
        """No deactivation guard either -- an operator with DB access can reset anyone."""
        deactivated = PersonFactory(password=OLD_PASSWORD, is_active=False)

        call_command('reset_password', deactivated.email, stdout=StringIO())

        refreshed = Person.objects.get(pk=deactivated.pk)
        self.assertFalse(refreshed.check_password(OLD_PASSWORD))
        self.assertTrue(refreshed.must_change_password)

    def test_email_lookup_is_case_insensitive(self):
        """The operator can type the email in any case and still find the Person."""
        person = PersonFactory(password=OLD_PASSWORD, email='mixed-case@example.com')

        call_command('reset_password', 'MIXED-CASE@EXAMPLE.COM', stdout=StringIO())

        refreshed = Person.objects.get(pk=person.pk)
        self.assertFalse(refreshed.check_password(OLD_PASSWORD))
