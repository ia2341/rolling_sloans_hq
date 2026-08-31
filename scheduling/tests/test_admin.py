from datetime import time

from django.contrib import admin
from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import RoleFactory, SemesterFactory
from scheduling.models import (
    Rehearsal,
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


@override_settings(SECURE_SSL_REDIRECT=False)
class RehearsalAdminCreateTests(TestCase):
    def test_leaving_grace_periods_and_end_time_blank_inherits_semester_defaults(self):
        """Submitting the real admin add form with these fields blank inherits the Semester's defaults."""
        admin_person = PersonFactory(is_admin=True)
        self.client.force_login(admin_person)
        semester = SemesterFactory(
            default_setup_grace_minutes=20,
            default_teardown_grace_minutes=10,
            default_rehearsal_duration_minutes=90,
        )

        response = self.client.post(reverse('admin:scheduling_rehearsal_add'), {
            'semester': semester.pk,
            'date': '2026-09-15',
            'start_time': '18:00:00',
            'end_time': '',
            'setup_grace_minutes': '',
            'teardown_grace_minutes': '',
        })

        self.assertEqual(response.status_code, 302, response.context['adminform'].form.errors if response.status_code == 200 else None)
        rehearsal = Rehearsal.objects.get(semester=semester)
        self.assertEqual(rehearsal.setup_grace_minutes, 20)
        self.assertEqual(rehearsal.teardown_grace_minutes, 10)
        self.assertEqual(rehearsal.end_time, time(19, 30))

    def test_default_duration_crossing_midnight_is_a_form_error_not_a_500(self):
        """A late start_time whose default duration would cross midnight fails as a form error, not a crash."""
        admin_person = PersonFactory(is_admin=True)
        self.client.force_login(admin_person)
        semester = SemesterFactory(default_rehearsal_duration_minutes=90)

        response = self.client.post(reverse('admin:scheduling_rehearsal_add'), {
            'semester': semester.pk,
            'date': '2026-09-15',
            'start_time': '23:30:00',
            'end_time': '',
            'setup_grace_minutes': '',
            'teardown_grace_minutes': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn('end_time', response.context['adminform'].form.errors)
        self.assertFalse(Rehearsal.objects.filter(semester=semester).exists())
