from django.contrib import admin
from django.test import TestCase

from scheduling.models import Role, Semester


class AdminRegistrationTests(TestCase):
    def test_semester_and_role_are_registered(self):
        """Semester and Role are registered in Django admin for create/list/edit."""
        self.assertIn(Semester, admin.site._registry)
        self.assertIn(Role, admin.site._registry)
