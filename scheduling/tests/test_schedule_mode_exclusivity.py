"""Mode exclusivity between rehearsal editing and assignment editing on /schedule/ (issue #218).

The two modes write disjoint tables (`Rehearsal`/`RehearsalSong` versus
`SongRoleAssignment`/`Backup`) and each has its own ADR-0008 preview/apply
pair. Rehearsal editing is a separate URL (`/schedule/edit/`) htmx-swapped
into `?view=all`; assignment editing is inline on the rehearsal-detail view
(the default/`?rehearsal=<id>` branch). Because those are two different
full-page template branches with no shared session flag, the two buffers
can never both be open on one rendered page, and navigating away from
either always discards its own unsaved (purely client-side, Alpine) buffer
rather than carrying it into the other mode. These tests pin that guarantee
down directly rather than leaving it to be re-derived from the templates.
"""

from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    BackupFactory,
    MembershipFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import Backup, Rehearsal, RehearsalSong, SongRoleAssignment
from scheduling.tests.test_assignment_edit_mode import (
    _save_payload as _assignment_save_payload,
)
from scheduling.tests.test_schedule_edit_view import formset_data

PASSWORD = 'a-strong-test-password-123'
TOMORROW = timezone.localdate() + timedelta(days=1)


def admin_client(test_case):
    """Log a synthetic admin Person into `test_case`'s client and return that Person."""
    person = PersonFactory(password=PASSWORD, is_admin=True)
    test_case.client.login(username=person.email, password=PASSWORD)
    return person


@override_settings(SECURE_SSL_REDIRECT=False)
class PageSeparationTests(TestCase):
    """Each mode's markup renders on its own page only — never both in one response."""

    @classmethod
    def setUpTestData(cls):
        """Build a Semester with one future Rehearsal, one Song/Role slot, and one existing Assignment."""
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, is_full_setlist=False, date=TOMORROW)
        cls.song = SongFactory(semester=cls.semester, position=1)
        cls.role = RoleFactory()
        SongRoleRequirementFactory(song=cls.song, role=cls.role, count=1)
        SongRoleAssignmentFactory(song=cls.song, role=cls.role)

    def setUp(self):
        """Log in as a synthetic admin Person before each test."""
        admin_client(self)

    def test_all_rehearsals_view_carries_no_assignment_edit_markup(self):
        """`?view=all` (rehearsal-edit's home) renders no assignment-edit button or form, even for an admin."""
        response = self.client.get(f"{reverse('scheduling:schedule')}?view=all")

        self.assertContains(response, 'id="edit-rehearsals-button"')
        self.assertNotContains(response, 'id="edit-assignments-button"')
        self.assertNotContains(response, 'id="assignment-edit-form"')

    def test_rehearsal_detail_view_carries_no_rehearsal_edit_markup(self):
        """The rehearsal-detail view (assignment-edit's home) renders no rehearsal-edit button or form."""
        response = self.client.get(f"{reverse('scheduling:schedule')}?rehearsal={self.rehearsal.pk}")

        self.assertContains(response, 'id="edit-assignments-button"')
        self.assertNotContains(response, 'id="edit-rehearsals-button"')
        self.assertNotContains(response, 'id="schedule-edit-form"')

    def test_direct_schedule_edit_page_carries_no_assignment_edit_markup(self):
        """A direct (non-htmx) GET at /schedule/edit/'s full page renders no assignment-edit affordance either."""
        response = self.client.get(reverse('scheduling:schedule-edit'))

        self.assertContains(response, 'id="schedule-edit-form"')
        self.assertNotContains(response, 'id="edit-assignments-button"')
        self.assertNotContains(response, 'id="assignment-edit-form"')


@override_settings(SECURE_SSL_REDIRECT=False)
class ApplyWritesOnlyItsOwnTablesTests(TestCase):
    """Each mode's Save endpoint ignores the other mode's fields, even when both are mixed into one POST body."""

    @classmethod
    def setUpTestData(cls):
        """Build a Semester with one future Rehearsal, one Song/Role slot, one Assignment, and one Backup."""
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, is_full_setlist=False, date=TOMORROW)
        cls.song = SongFactory(semester=cls.semester, position=1)
        cls.role = RoleFactory()
        SongRoleRequirementFactory(song=cls.song, role=cls.role, count=1)
        cls.assignment = SongRoleAssignmentFactory(song=cls.song, role=cls.role)
        cls.rehearsal_song = RehearsalSongFactory(song=cls.song, rehearsal=cls.rehearsal, order=1)
        cls.backup = BackupFactory(rehearsal_song=cls.rehearsal_song, role=cls.role)

    def setUp(self):
        """Log in as a synthetic admin Person before each test."""
        admin_client(self)

    def test_rehearsal_edit_save_never_touches_assignment_or_backup_tables(self):
        """A schedule-edit Save carrying assignment-shaped fields leaves SongRoleAssignment/Backup untouched.

        The submitted Running Order must re-list the existing RehearsalSong
        (rather than omitting it) so this is a genuine no-op resubmission —
        omitting it would delete the row and legitimately cascade-delete the
        Backup anchored to it (ADR-0007), which would be rehearsal editing
        correctly acting on its own `RehearsalSong` table rather than a
        mode-exclusivity violation.
        """
        payload = formset_data([self.rehearsal], running_order=[
            {
                'rehearsal_row_key': 'rehearsal-0',
                'song_id': self.song.pk,
                'slot_count': 1,
                'rehearsal_song_id': self.rehearsal_song.pk,
            },
        ])
        payload['assignment_semester_id'] = str(self.semester.pk)
        payload['assignment_semester_updated_at'] = self.semester.updated_at.isoformat()
        payload['removed_assignment_id'] = str(self.assignment.pk)
        payload['removed_backup_id'] = str(self.backup.pk)
        payload['added_assignment_entry'] = f'{self.song.pk}:{self.role.pk}:{self.assignment.person.pk}'

        response = self.client.post(reverse('scheduling:schedule-edit'), payload)

        self.assertRedirects(response, f"{reverse('scheduling:schedule')}?view=all")
        self.assertTrue(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())
        self.assertTrue(Backup.objects.filter(pk=self.backup.pk).exists())

    def test_assignment_save_never_touches_rehearsal_or_rehearsal_song_tables(self):
        """An assignment-edit Save carrying a genuine rehearsal-edit change leaves that Rehearsal's own fields untouched too.

        The contaminating payload names a real, different `end_time` for
        the Rehearsal (not a no-op resubmission) — proving the assignment
        Save view truly never reads or applies rehearsal-edit fields, not
        just that a no-op edit happened to leave row counts unchanged.
        """
        rehearsal_count_before = Rehearsal.objects.count()
        rehearsal_song_count_before = RehearsalSong.objects.count()
        original_end_time = self.rehearsal.end_time
        different_end_time = (
            (timezone.datetime.combine(timezone.localdate(), original_end_time) + timedelta(hours=1)).time()
        )
        payload = _assignment_save_payload(self.rehearsal, removed_ids=[self.assignment.pk])
        payload.update(formset_data(
            [self.rehearsal], edits={self.rehearsal.pk: {'end_time': different_end_time.isoformat()}},
        ))

        response = self.client.post(
            reverse('scheduling:schedule-assignments-save', args=[self.rehearsal.pk]), payload,
        )

        self.assertRedirects(
            response, f"{reverse('scheduling:schedule')}?rehearsal={self.rehearsal.pk}",
        )
        self.assertFalse(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())
        self.assertEqual(Rehearsal.objects.count(), rehearsal_count_before)
        self.assertEqual(RehearsalSong.objects.count(), rehearsal_song_count_before)
        self.rehearsal.refresh_from_db()
        self.assertEqual(self.rehearsal.end_time, original_end_time)


@override_settings(SECURE_SSL_REDIRECT=False)
class OnlyOnePreviewFiresPerRequestTests(TestCase):
    """A single Preview POST invokes exactly one mode's preview function, never both — asserted directly (issue #218)."""

    @classmethod
    def setUpTestData(cls):
        """Build a Semester with one future Rehearsal, one Song/Role slot, and one existing Assignment."""
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, is_full_setlist=False, date=TOMORROW)
        cls.song = SongFactory(semester=cls.semester, position=1)
        cls.role = RoleFactory()
        SongRoleRequirementFactory(song=cls.song, role=cls.role, count=1)
        cls.assignment = SongRoleAssignmentFactory(song=cls.song, role=cls.role)

    def setUp(self):
        """Log in as a synthetic admin Person before each test."""
        admin_client(self)

    def test_rehearsal_edit_preview_never_calls_the_assignment_preview_function(self):
        """POSTing /schedule/edit/preview/ with assignment-shaped fields mixed in calls only preview_rehearsal_edits."""
        payload = formset_data([self.rehearsal])
        payload['assignment_semester_id'] = str(self.semester.pk)
        payload['assignment_semester_updated_at'] = self.semester.updated_at.isoformat()
        payload['removed_assignment_id'] = str(self.assignment.pk)

        with (
            mock.patch('scheduling.views.preview_rehearsal_edits') as rehearsal_preview,
            mock.patch('scheduling.views.preview_song_role_assignments') as assignment_preview,
        ):
            rehearsal_preview.side_effect = self._real_preview_rehearsal_edits
            self.client.post(reverse('scheduling:schedule-edit-preview'), payload)

        rehearsal_preview.assert_called_once()
        assignment_preview.assert_not_called()

    def test_assignment_preview_never_calls_the_rehearsal_edit_preview_function(self):
        """POSTing the assignment Preview endpoint with rehearsal-edit-shaped fields calls only preview_song_role_assignments."""
        payload = _assignment_save_payload(self.rehearsal, removed_ids=[self.assignment.pk])
        payload.update(formset_data([self.rehearsal]))

        with (
            mock.patch('scheduling.views.preview_song_role_assignments') as assignment_preview,
            mock.patch('scheduling.views.preview_rehearsal_edits') as rehearsal_preview,
        ):
            assignment_preview.side_effect = self._real_preview_song_role_assignments
            self.client.post(
                reverse('scheduling:schedule-assignments-preview', args=[self.rehearsal.pk]), payload,
            )

        assignment_preview.assert_called_once()
        rehearsal_preview.assert_not_called()

    @staticmethod
    def _real_preview_rehearsal_edits(*args, **kwargs):
        """Delegate to the un-mocked `preview_rehearsal_edits`, so the mocked call still renders a real response."""
        from scheduling.services import preview_rehearsal_edits

        return preview_rehearsal_edits(*args, **kwargs)

    @staticmethod
    def _real_preview_song_role_assignments(*args, **kwargs):
        """Delegate to the un-mocked `preview_song_role_assignments`, so the mocked call still renders a real response."""
        from scheduling.services import preview_song_role_assignments

        return preview_song_role_assignments(*args, **kwargs)


@override_settings(SECURE_SSL_REDIRECT=False)
class BlockedSaveOnlyRestoresItsOwnBufferTests(TestCase):
    """A blocked save re-renders with its own mode's pending state only, never the other mode's (issue #218)."""

    @classmethod
    def setUpTestData(cls):
        """Build a Semester with one future Rehearsal, one Song/Role slot, and one existing Assignment."""
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, is_full_setlist=False, date=TOMORROW)
        cls.song = SongFactory(semester=cls.semester, position=1)
        cls.role = RoleFactory()
        SongRoleRequirementFactory(song=cls.song, role=cls.role, count=1)
        cls.assignment = SongRoleAssignmentFactory(song=cls.song, role=cls.role)

    def setUp(self):
        """Log in as a synthetic admin Person before each test."""
        admin_client(self)

    def test_a_blocked_assignment_save_re_renders_with_no_rehearsal_edit_markup(self):
        """A stale-stamp assignment save re-render carries the assignment buffer only — no rehearsal-edit form present."""
        membership = MembershipFactory(semester=self.semester)
        stale_stamp = self.semester.updated_at - timedelta(days=1)
        payload = _assignment_save_payload(
            self.rehearsal,
            removed_ids=[self.assignment.pk],
            added_entries=[(self.song.pk, self.role.pk, membership.person.pk)],
        )
        payload['assignment_semester_updated_at'] = stale_stamp.isoformat()

        response = self.client.post(
            reverse('scheduling:schedule-assignments-save', args=[self.rehearsal.pk]), payload,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="assignment-edit-form"')
        self.assertNotContains(response, 'id="schedule-edit-form"')

    def test_a_blocked_rehearsal_edit_save_re_renders_with_no_assignment_edit_markup(self):
        """A stale-stamp rehearsal-edit save re-render carries its own buffer only — no assignment-edit form present."""
        payload = formset_data([self.rehearsal])
        payload['schedule_semester_updated_at'] = (self.semester.updated_at - timedelta(days=1)).isoformat()

        response = self.client.post(reverse('scheduling:schedule-edit'), payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="schedule-edit-form"')
        self.assertNotContains(response, 'id="assignment-edit-form"')
