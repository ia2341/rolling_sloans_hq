"""`apply_person_deactivation()` and `apply_person_reactivation()` (issue #469, ADR 0017)."""

import threading

from django.contrib.sessions.backends.db import SessionStore
from django.db import connection
from django.test import TestCase, TransactionTestCase

from identity.factories import PersonFactory
from identity.models import Person
from identity.services import (
    CannotDeactivateLastActiveAdminError,
    CannotDeactivateSelfError,
    apply_person_deactivation,
    apply_person_reactivation,
)


def _log_in_session_for(person):
    """Create and save a `Session` row that looks like `person` has an open, logged-in session."""
    store = SessionStore()
    store['_auth_user_id'] = str(person.pk)
    store.save()
    return store


class ApplyPersonDeactivationTests(TestCase):
    def test_deactivates_the_target(self):
        """A plain deactivate sets `is_active=False` and touches nothing else."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)
        target = PersonFactory(is_admin=False, is_active=True)

        apply_person_deactivation(target=target, requesting_admin=requesting_admin)

        refreshed = Person.objects.get(pk=target.pk)
        self.assertFalse(refreshed.is_active)

    def test_leaves_admin_status_roles_and_memberships_untouched(self):
        """ADR 0017: admin status only ever changes by its own explicit action, never as a side effect of deactivation."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)
        target = PersonFactory(is_admin=True, is_active=True)
        other_admin = PersonFactory(is_admin=True, is_active=True)  # noqa: F841 -- keeps target from tripping the last-admin guard

        apply_person_deactivation(target=target, requesting_admin=requesting_admin)

        refreshed = Person.objects.get(pk=target.pk)
        self.assertTrue(refreshed.is_admin)

    def test_terminates_the_targets_live_sessions(self):
        """A logged-in target's session row is deleted immediately, per ADR 0017's 30-day-sliding-session concern."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)
        target = PersonFactory(is_admin=False, is_active=True)
        session = _log_in_session_for(target)

        apply_person_deactivation(target=target, requesting_admin=requesting_admin)

        self.assertFalse(SessionStore(session_key=session.session_key).exists(session.session_key))

    def test_leaves_other_peoples_sessions_alone(self):
        """Only the deactivated target's own session is terminated -- a bystander's session survives."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)
        target = PersonFactory(is_admin=False, is_active=True)
        bystander = PersonFactory(is_admin=False, is_active=True)
        bystander_session = _log_in_session_for(bystander)

        apply_person_deactivation(target=target, requesting_admin=requesting_admin)

        self.assertTrue(SessionStore(session_key=bystander_session.session_key).exists(bystander_session.session_key))

    def test_self_deactivation_is_refused(self):
        """An admin cannot deactivate themself -- always recoverable by someone else, per the self-revoke guard's shape."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)

        with self.assertRaises(CannotDeactivateSelfError):
            apply_person_deactivation(target=requesting_admin, requesting_admin=requesting_admin)

        self.assertTrue(Person.objects.get(pk=requesting_admin.pk).is_active)

    def test_deactivating_the_last_active_admin_is_refused(self):
        """Deactivating the only Person who is both admin and active would leave no one able to administer the band."""
        requesting_admin = PersonFactory(is_admin=False, is_active=True)
        target = PersonFactory(is_admin=True, is_active=True)

        with self.assertRaises(CannotDeactivateLastActiveAdminError):
            apply_person_deactivation(target=target, requesting_admin=requesting_admin)

        self.assertTrue(Person.objects.get(pk=target.pk).is_active)

    def test_deactivating_a_non_admin_is_never_blocked_by_the_last_admin_guard(self):
        """A non-admin target never trips the last-active-admin guard, regardless of who else exists."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)
        target = PersonFactory(is_admin=False, is_active=True)

        apply_person_deactivation(target=target, requesting_admin=requesting_admin)

        self.assertFalse(Person.objects.get(pk=target.pk).is_active)

    def test_deactivating_an_admin_is_allowed_when_another_active_admin_remains(self):
        """The last-admin guard only bites when `target` is the sole remaining active admin."""
        requesting_admin = PersonFactory(is_admin=True, is_active=True)
        target = PersonFactory(is_admin=True, is_active=True)
        PersonFactory(is_admin=True, is_active=True)

        apply_person_deactivation(target=target, requesting_admin=requesting_admin)

        self.assertFalse(Person.objects.get(pk=target.pk).is_active)


class ApplyPersonDeactivationConcurrencyTests(TransactionTestCase):
    """Row-locking regression test (issue #469 review) — needs `TransactionTestCase` for real cross-thread commits."""

    serialized_rollback = True

    def test_two_admins_deactivating_each_other_at_once_leaves_one_active_admin(self):
        """Two concurrent mutual deactivations must serialize on the locked admin rows, not both slip past the guard."""
        admin_a = PersonFactory(is_admin=True, is_active=True)
        admin_b = PersonFactory(is_admin=True, is_active=True)
        barrier = threading.Barrier(2)
        errors = []

        def deactivate(target, requesting_admin):
            barrier.wait()
            try:
                apply_person_deactivation(target=target, requesting_admin=requesting_admin)
            except CannotDeactivateLastActiveAdminError as error:
                errors.append(error)
            finally:
                connection.close()

        thread_a = threading.Thread(target=deactivate, args=(admin_b, admin_a))
        thread_b = threading.Thread(target=deactivate, args=(admin_a, admin_b))
        thread_a.start()
        thread_b.start()
        thread_a.join()
        thread_b.join()

        self.assertEqual(len(errors), 1)
        self.assertEqual(Person.objects.filter(is_admin=True, is_active=True).count(), 1)


class ApplyPersonReactivationTests(TestCase):
    def test_reactivates_with_no_guard(self):
        """Reactivate is a plain, unconditional write -- nothing to refuse."""
        target = PersonFactory(is_active=False)

        apply_person_reactivation(target)

        self.assertTrue(Person.objects.get(pk=target.pk).is_active)

    def test_leaves_admin_status_untouched(self):
        """Reactivating a deactivated admin restores login without re-granting or re-revoking anything (ADR 0017)."""
        target = PersonFactory(is_active=False, is_admin=True)

        apply_person_reactivation(target)

        self.assertTrue(Person.objects.get(pk=target.pk).is_admin)
