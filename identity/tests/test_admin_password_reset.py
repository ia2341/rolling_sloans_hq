"""`apply_password_reset()` (issue #483, ADR 0018): the admin-relayed reset path.

Not `test_password_reset.py` -- that file covers the legacy self-serve
`password-reset/` email flow ADR 0018 is retiring; this covers the new
admin action that replaces the reason it existed.
"""

from django.test import TestCase

from identity.factories import PersonFactory
from identity.models import Person
from identity.services import (
    CannotResetOwnPasswordError,
    PersonIsDeactivatedError,
    apply_password_reset,
)


class ApplyPasswordResetTests(TestCase):
    def test_sets_a_usable_password_and_flags_must_change_password(self):
        """A successful reset gives the target a real, immediately-usable password and flags the forced change."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)
        target = PersonFactory(is_active=True, must_change_password=False)

        _, temp_password = apply_password_reset(target=target, requesting_admin=requesting_admin)

        refreshed = Person.objects.get(pk=target.pk)
        self.assertTrue(refreshed.has_usable_password())
        self.assertTrue(refreshed.check_password(temp_password))
        self.assertTrue(refreshed.must_change_password)

    def test_returns_a_fresh_temp_password_each_call(self):
        """Reset works on anyone at any time: calling it twice never errors and yields a different plaintext."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)
        target = PersonFactory(is_active=True)

        _, first_password = apply_password_reset(target=target, requesting_admin=requesting_admin)
        _, second_password = apply_password_reset(target=target, requesting_admin=requesting_admin)

        self.assertNotEqual(first_password, second_password)
        self.assertTrue(Person.objects.get(pk=target.pk).check_password(second_password))

    def test_deactivated_target_is_refused(self):
        """A deactivated Person cannot be handed a working credential through this door."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)
        target = PersonFactory(is_active=False)
        old_password_hash = target.password

        with self.assertRaises(PersonIsDeactivatedError):
            apply_password_reset(target=target, requesting_admin=requesting_admin)

        self.assertEqual(Person.objects.get(pk=target.pk).password, old_password_hash)

    def test_self_reset_is_refused(self):
        """An admin cannot reset their own password through this path -- they must use the self-serve change-password flow."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)
        old_password_hash = requesting_admin.password

        with self.assertRaises(CannotResetOwnPasswordError):
            apply_password_reset(target=requesting_admin, requesting_admin=requesting_admin)

        self.assertEqual(Person.objects.get(pk=requesting_admin.pk).password, old_password_hash)
