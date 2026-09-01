"""Semester & Role catalog (issue #30)."""

from django.test import TestCase

from scheduling.factories import RoleFactory, SemesterFactory
from scheduling.models import Role, Semester


class SemesterTests(TestCase):
    def test_created_with_default_fields(self):
        """A Semester is created with its name and default timing fields."""
        semester = SemesterFactory(
            name='Fall 2026',
            default_rehearsal_duration_minutes=90,
            default_setup_grace_minutes=15,
            default_teardown_grace_minutes=10,
            default_song_slot_count=5,
            default_arrival_buffer_minutes=10,
            default_departure_buffer_minutes=5,
        )

        reloaded = Semester.objects.get(pk=semester.pk)
        self.assertEqual(reloaded.name, 'Fall 2026')
        self.assertEqual(reloaded.default_rehearsal_duration_minutes, 90)
        self.assertEqual(reloaded.default_setup_grace_minutes, 15)
        self.assertEqual(reloaded.default_teardown_grace_minutes, 10)
        self.assertEqual(reloaded.default_song_slot_count, 5)
        self.assertEqual(reloaded.default_arrival_buffer_minutes, 10)
        self.assertEqual(reloaded.default_departure_buffer_minutes, 5)


class RoleTests(TestCase):
    def test_active_by_default(self):
        """A newly created Role is active by default."""
        role = RoleFactory()

        self.assertTrue(role.is_active)

    def test_deactivating_is_a_soft_update(self):
        """Deactivating a Role flips is_active without deleting the row."""
        role = RoleFactory(is_active=True)

        role.is_active = False
        role.save()

        reloaded = Role.objects.get(pk=role.pk)
        self.assertFalse(reloaded.is_active)

    def test_can_be_reactivated(self):
        """A deactivated Role can be reactivated by flipping is_active back."""
        role = RoleFactory(is_active=False)

        role.is_active = True
        role.save()

        reloaded = Role.objects.get(pk=role.pk)
        self.assertTrue(reloaded.is_active)

    def test_not_scoped_to_a_semester(self):
        """The Role catalog is global: Role carries no semester field or FK."""
        field_names = {field.name for field in Role._meta.get_fields()}

        self.assertNotIn('semester', field_names)
