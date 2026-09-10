"""`apply_admin_status_change()` and `other_active_admins()` (issue #467)."""

from django.test import TestCase

from identity.factories import PersonFactory
from identity.models import Person
from identity.services import (
    CannotRevokeLastActiveAdminError,
    CannotRevokeOwnAdminStatusError,
    apply_admin_status_change,
    other_active_admins,
)


class OtherActiveAdminsTests(TestCase):
    def test_excludes_the_given_person(self):
        """The given Person never counts as their own 'other' admin, even when they are admin and active."""
        person = PersonFactory(is_admin=True, is_active=True)

        self.assertFalse(other_active_admins(person).exists())

    def test_includes_a_different_active_admin(self):
        """A different Person who is both admin and active is counted."""
        person = PersonFactory(is_admin=True, is_active=True)
        other = PersonFactory(is_admin=True, is_active=True)

        self.assertCountEqual(other_active_admins(person), [other])

    def test_excludes_an_inactive_admin(self):
        """A deactivated admin never counts, per ADR 0017 -- they can't actually log in and administer."""
        person = PersonFactory(is_admin=True, is_active=True)
        PersonFactory(is_admin=True, is_active=False)

        self.assertFalse(other_active_admins(person).exists())

    def test_excludes_a_non_admin(self):
        """An active non-admin never counts."""
        person = PersonFactory(is_admin=True, is_active=True)
        PersonFactory(is_admin=False, is_active=True)

        self.assertFalse(other_active_admins(person).exists())


class ApplyAdminStatusChangeTests(TestCase):
    def test_grants_admin_status(self):
        """Granting admin access is a plain write with no guard to satisfy."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)
        target = PersonFactory(is_admin=False, is_active=True)

        apply_admin_status_change(target=target, is_admin=True, requesting_admin=requesting_admin)

        self.assertTrue(Person.objects.get(pk=target.pk).is_admin)

    def test_grants_are_never_blocked_by_the_self_guard(self):
        """An admin can grant admin access to themselves (a no-op write) without tripping the self-revoke guard."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)

        apply_admin_status_change(target=requesting_admin, is_admin=True, requesting_admin=requesting_admin)

        self.assertTrue(Person.objects.get(pk=requesting_admin.pk).is_admin)

    def test_revokes_admin_status_when_another_active_admin_remains(self):
        """A revoke succeeds so long as some other Person is both admin and active."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)
        target = PersonFactory(is_admin=True, is_active=True)

        apply_admin_status_change(target=target, is_admin=False, requesting_admin=requesting_admin)

        self.assertFalse(Person.objects.get(pk=target.pk).is_admin)

    def test_reapplying_the_current_value_is_a_no_op_write(self):
        """Revoking a Person who is already a non-admin never trips the last-admin guard."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)
        target = PersonFactory(is_admin=False, is_active=True)

        apply_admin_status_change(target=target, is_admin=False, requesting_admin=requesting_admin)

        self.assertFalse(Person.objects.get(pk=target.pk).is_admin)

    def test_refuses_self_revoke(self):
        """An admin cannot revoke their own admin status, even when another active admin exists."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)
        PersonFactory(is_admin=True, is_active=True)

        with self.assertRaises(CannotRevokeOwnAdminStatusError):
            apply_admin_status_change(target=requesting_admin, is_admin=False, requesting_admin=requesting_admin)

        self.assertTrue(Person.objects.get(pk=requesting_admin.pk).is_admin)

    def test_refuses_revoking_the_last_active_admin(self):
        """An admin cannot revoke the last Person who is both admin and active, even a different Person than themselves."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)
        target = PersonFactory(is_admin=True, is_active=True)
        requesting_admin.is_active = False
        requesting_admin.save(update_fields=['is_active'])

        with self.assertRaises(CannotRevokeLastActiveAdminError):
            apply_admin_status_change(target=target, is_admin=False, requesting_admin=requesting_admin)

        self.assertTrue(Person.objects.get(pk=target.pk).is_admin)

    def test_revoking_an_admin_who_is_already_inactive_does_not_require_another_active_admin(self):
        """Revoking a deactivated admin's flag can't strand the band, since they weren't a live admin anyway -- even when no other active admin exists at all."""
        requesting_admin = PersonFactory(is_admin=False, is_active=True)
        target = PersonFactory(is_admin=True, is_active=False)

        apply_admin_status_change(target=target, is_admin=False, requesting_admin=requesting_admin)

        self.assertFalse(Person.objects.get(pk=target.pk).is_admin)
