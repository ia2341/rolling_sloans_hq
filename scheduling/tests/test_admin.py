from django.contrib import admin
from django.test import TestCase

from scheduling.factories import RoleFactory
from scheduling.models import Rehearsal, Role, Semester, Song


class AdminRegistrationTests(TestCase):
    def test_semester_and_role_are_registered(self):
        """Semester and Role are registered in Django admin for create/list/edit."""
        self.assertIn(Semester, admin.site._registry)
        self.assertIn(Role, admin.site._registry)

    def test_song_is_registered(self):
        """Song is registered in Django admin for create/list/edit (issue #32)."""
        self.assertIn(Song, admin.site._registry)

    def test_rehearsal_is_registered(self):
        """Rehearsal is registered in Django admin for create/list/edit (issue #36)."""
        self.assertIn(Rehearsal, admin.site._registry)


class RoleAdminDeletionTests(TestCase):
    def test_role_admin_has_no_delete_permission(self):
        """There is no deletion path for a Role, including through the admin UI."""
        role_admin = admin.site._registry[Role]
        role = RoleFactory()

        self.assertFalse(role_admin.has_delete_permission(request=None, obj=role))
        self.assertIsNone(role_admin.actions)
