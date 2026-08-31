from django.contrib import admin
from django.test import TestCase

from scheduling.factories import RoleFactory
from scheduling.models import (
    Role,
    Semester,
    Song,
    SongRoleAssignment,
    SongRoleRequirement,
)


class AdminRegistrationTests(TestCase):
    def test_semester_and_role_are_registered(self):
        """Semester and Role are registered in Django admin for create/list/edit."""
        self.assertIn(Semester, admin.site._registry)
        self.assertIn(Role, admin.site._registry)

    def test_song_is_registered(self):
        """Song is registered in Django admin for create/list/edit (issue #32)."""
        self.assertIn(Song, admin.site._registry)

    def test_song_role_requirement_is_registered(self):
        """SongRoleRequirement is registered in Django admin for create/list/edit (issue #33)."""
        self.assertIn(SongRoleRequirement, admin.site._registry)

    def test_song_role_assignment_is_registered_with_mismatch_visible_and_filterable(self):
        """SongRoleAssignment is registered with is_role_mismatch shown and filterable (issue #35)."""
        self.assertIn(SongRoleAssignment, admin.site._registry)
        assignment_admin = admin.site._registry[SongRoleAssignment]
        self.assertIn('is_role_mismatch', assignment_admin.list_display)
        self.assertIn('is_role_mismatch', assignment_admin.list_filter)


class RoleAdminDeletionTests(TestCase):
    def test_role_admin_has_no_delete_permission(self):
        """There is no deletion path for a Role, including through the admin UI."""
        role_admin = admin.site._registry[Role]
        role = RoleFactory()

        self.assertFalse(role_admin.has_delete_permission(request=None, obj=role))
        self.assertIsNone(role_admin.actions)
