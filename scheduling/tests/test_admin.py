from datetime import time

from django.contrib import admin
from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import (
    BackupFactory,
    ConflictFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
)
from scheduling.models import (
    Backup,
    Conflict,
    ConflictWindow,
    Rehearsal,
    RehearsalSong,
    Role,
    Semester,
    Song,
    SongRoleAssignment,
    SongRoleRequirement,
)

# Empty RehearsalSongInline management-form data, required by Django's admin
# formset validation whenever posting to the Rehearsal add/change form
# (issue #37 added the inline).
REHEARSAL_SONG_INLINE_MANAGEMENT_FORM_DATA = {
    'rehearsalsong_set-TOTAL_FORMS': '0',
    'rehearsalsong_set-INITIAL_FORMS': '0',
    'rehearsalsong_set-MIN_NUM_FORMS': '0',
    'rehearsalsong_set-MAX_NUM_FORMS': '1000',
}


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

    def test_rehearsal_song_is_registered_and_inlined_on_rehearsal(self):
        """RehearsalSong is registered directly and inlined on the Rehearsal admin page (issue #37)."""
        self.assertIn(RehearsalSong, admin.site._registry)
        rehearsal_admin = admin.site._registry[Rehearsal]
        inline_models = [inline.model for inline in rehearsal_admin.inlines]
        self.assertIn(RehearsalSong, inline_models)

    def test_conflict_is_registered(self):
        """Conflict is registered in Django admin for create/list/edit (issue #48)."""
        self.assertIn(Conflict, admin.site._registry)

    def test_conflict_window_is_registered_and_inlined_on_conflict(self):
        """ConflictWindow is registered directly and inlined on the Conflict admin page (issue #49)."""
        self.assertIn(ConflictWindow, admin.site._registry)
        conflict_admin = admin.site._registry[Conflict]
        inline_models = [inline.model for inline in conflict_admin.inlines]
        self.assertIn(ConflictWindow, inline_models)


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
            **REHEARSAL_SONG_INLINE_MANAGEMENT_FORM_DATA,
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
            **REHEARSAL_SONG_INLINE_MANAGEMENT_FORM_DATA,
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn('end_time', response.context['adminform'].form.errors)
        self.assertFalse(Rehearsal.objects.filter(semester=semester).exists())


class BackupAdminTests(TestCase):
    def test_backup_is_registered_with_list_display_filters_search_and_readonly_fields(self):
        """Backup is registered with the slot/Role/Person columns, filters, search and readonly fields (issue #176)."""
        self.assertIn(Backup, admin.site._registry)
        backup_admin = admin.site._registry[Backup]

        self.assertIn('rehearsal_song', backup_admin.list_display)
        self.assertIn('role', backup_admin.list_display)
        self.assertIn('person', backup_admin.list_display)
        self.assertIn('covering_for', backup_admin.list_display)
        self.assertIn('is_role_mismatch', backup_admin.list_display)

        self.assertIn('is_role_mismatch', backup_admin.list_filter)
        self.assertIn('rehearsal_song__rehearsal__semester', backup_admin.list_filter)

        self.assertIn('person__name', backup_admin.search_fields)
        self.assertIn('person__email', backup_admin.search_fields)
        self.assertIn('rehearsal_song__song__title', backup_admin.search_fields)

        self.assertIn('is_role_mismatch', backup_admin.readonly_fields)

    def test_stale_advisory_is_a_readonly_display_and_never_stored(self):
        """The stale advisory renders as a readonly display and reflects Backup.is_stale() without persisting it."""
        backup_admin = admin.site._registry[Backup]
        self.assertIn('stale_advisory', backup_admin.readonly_fields)

        rehearsal_song = RehearsalSongFactory()
        covered_person = PersonFactory()
        conflict = ConflictFactory(person=covered_person, rehearsal=rehearsal_song.rehearsal)
        backup = BackupFactory(rehearsal_song=rehearsal_song, covering_for=covered_person)

        self.assertFalse(backup_admin.stale_advisory(backup))

        conflict.delete()

        self.assertTrue(backup_admin.stale_advisory(backup))
        self.assertFalse(hasattr(Backup, 'stale_advisory'))

    @override_settings(SECURE_SSL_REDIRECT=False)
    def test_backup_can_be_deleted_from_the_admin(self):
        """Deleting a Backup via the real admin delete view succeeds, since the Role.is_active convention doesn't apply here."""
        admin_person = PersonFactory(is_admin=True)
        self.client.force_login(admin_person)
        backup = BackupFactory()

        response = self.client.post(
            reverse('admin:scheduling_backup_delete', args=[backup.pk]), {'post': 'yes'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Backup.objects.filter(pk=backup.pk).exists())
