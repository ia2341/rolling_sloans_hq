"""Assignment edit mode on /schedule/: the admin toggle, ✕ chips, and Save Changes (issue #210)."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import SongRoleAssignment
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY

PASSWORD = 'a-strong-test-password-123'


def _schedule_url(rehearsal):
    """Return /schedule/?rehearsal=<id> for `rehearsal`."""
    return f"{reverse('scheduling:schedule')}?rehearsal={rehearsal.pk}"


def _save_url(rehearsal):
    """Return the assignment-save POST endpoint for `rehearsal`."""
    return reverse('scheduling:schedule-assignments-save', args=[rehearsal.pk])


def _save_payload(rehearsal, removed_ids=()):
    """Build a Save Changes POST body against `rehearsal`'s Semester, naming `removed_ids` for deletion."""
    semester = rehearsal.semester
    payload = {
        'assignment_semester_id': str(semester.pk),
        'assignment_semester_updated_at': semester.updated_at.isoformat(),
    }
    if removed_ids:
        payload['removed_assignment_id'] = [str(pk) for pk in removed_ids]
    return payload


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAndNonAdminAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic non-admin Person and a future Rehearsal with one Assignment."""
        cls.person = PersonFactory(password=PASSWORD)
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, is_full_setlist=False)
        cls.song = SongFactory(semester=cls.semester, position=1)
        cls.role = RoleFactory()
        SongRoleRequirementFactory(song=cls.song, role=cls.role, count=1)
        cls.assignment = SongRoleAssignmentFactory(song=cls.song, role=cls.role)

    def test_anonymous_get_schedule_redirects_to_login(self):
        """An anonymous GET at the rehearsal grid redirects to login, same as any other /schedule/ request."""
        url = _schedule_url(self.rehearsal)

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_anonymous_save_post_redirects_to_login(self):
        """An anonymous Save Changes POST redirects to login rather than 403ing."""
        response = self.client.post(_save_url(self.rehearsal), _save_payload(self.rehearsal))

        self.assertRedirects(response, f"{reverse('identity:login')}?next={_save_url(self.rehearsal)}")

    def test_non_admin_sees_no_edit_assignments_button(self):
        """A non-admin's grid carries no 'Edit assignments' control at all."""
        self.client.login(username=self.person.email, password=PASSWORD)

        response = self.client.get(_schedule_url(self.rehearsal))

        self.assertNotContains(response, 'id="edit-assignments-button"')
        self.assertNotContains(response, 'assignment-chip-remove')

    def test_non_admin_save_post_is_forbidden(self):
        """A logged-in non-admin's Save Changes POST is rejected with 403 and writes nothing."""
        self.client.login(username=self.person.email, password=PASSWORD)

        response = self.client.post(_save_url(self.rehearsal), _save_payload(self.rehearsal, [self.assignment.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class EditAssignmentsButtonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic admin Person to log in as before each test."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_admin_sees_the_button_on_a_future_rehearsal(self):
        """An admin viewing a future Rehearsal's grid sees the 'Edit assignments' entry point."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False)

        response = self.client.get(_schedule_url(rehearsal))

        self.assertContains(response, 'id="edit-assignments-button"')

    def test_admin_sees_the_button_on_todays_rehearsal(self):
        """A same-day Rehearsal stays editable all day."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False, date=timezone.localdate())

        response = self.client.get(_schedule_url(rehearsal))

        self.assertContains(response, 'id="edit-assignments-button"')

    def test_button_absent_on_a_past_rehearsal(self):
        """A Rehearsal dated before today offers no edit control — a usability rule, not a data-integrity one."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(
            semester=semester, is_full_setlist=False, date=timezone.localdate() - timedelta(days=1),
        )

        response = self.client.get(_schedule_url(rehearsal))

        self.assertNotContains(response, 'id="edit-assignments-button"')

    def test_admin_sees_the_button_on_the_dress_rehearsal(self):
        """The Dress Rehearsal is always editable, even dated in the past — the backstop for a late Semester."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(
            semester=semester, is_full_setlist=True, date=timezone.localdate() - timedelta(days=10),
        )

        response = self.client.get(_schedule_url(rehearsal))

        self.assertContains(response, 'id="edit-assignments-button"')

    def test_button_renders_on_a_grid_with_no_rows(self):
        """A degenerate grid with no scheduled Songs still offers the button, pointing at scheduling songs in."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False)

        response = self.client.get(_schedule_url(rehearsal))

        self.assertContains(response, 'id="edit-assignments-button"')
        self.assertContains(response, reverse('scheduling:manage-schedule-edit', args=[rehearsal.pk]))

    def test_button_renders_on_a_grid_with_no_columns(self):
        """A Song with no Role Requirement yields zero columns; the button still renders."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False)
        song = SongFactory(semester=semester, position=1)
        RehearsalSongFactory(song=song, rehearsal=rehearsal, order=1)

        response = self.client.get(_schedule_url(rehearsal))

        self.assertContains(response, 'id="edit-assignments-button"')

    def test_button_absent_with_no_semester_at_all(self):
        """With no Semester published or drafted, there's no grid to edit."""
        response = self.client.get(reverse('scheduling:schedule'))

        self.assertNotContains(response, 'id="edit-assignments-button"')

    def test_a_non_live_semester_selected_as_viewing_is_editable_too(self):
        """A draft Semester an admin has selected as their viewing Semester edits normally, under its own banner."""
        SemesterFactory()  # the Live Semester
        draft = SemesterFactory(draft=True)
        rehearsal = RehearsalFactory(semester=draft, is_full_setlist=False)
        session = self.client.session
        session[VIEWING_SEMESTER_SESSION_KEY] = draft.pk
        session.save()

        response = self.client.get(_schedule_url(rehearsal))

        self.assertContains(response, 'id="edit-assignments-button"')

    def test_my_songs_only_filter_still_renders(self):
        """The filter checkbox itself is unaffected by edit-mode wiring — still present for an admin to use."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False)

        response = self.client.get(_schedule_url(rehearsal))

        self.assertContains(response, 'id="my-songs-only-filter"')


@override_settings(SECURE_SSL_REDIRECT=False)
class SaveAssignmentEditsViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build an admin Person, a future Rehearsal, and one existing SongRoleAssignment on it."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, is_full_setlist=False)
        cls.song = SongFactory(semester=cls.semester, position=1)
        cls.role = RoleFactory()
        SongRoleRequirementFactory(song=cls.song, role=cls.role, count=1)
        cls.assignment = SongRoleAssignmentFactory(song=cls.song, role=cls.role)

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_removing_a_chip_deletes_the_assignment_and_redirects_to_the_grid(self):
        """A Save Changes POST naming an assignment id deletes it and redirects back to the rehearsal's grid."""
        response = self.client.post(_save_url(self.rehearsal), _save_payload(self.rehearsal, [self.assignment.pk]))

        self.assertRedirects(response, _schedule_url(self.rehearsal))
        self.assertFalse(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())

    def test_removal_is_semester_wide_not_scoped_to_the_posted_rehearsal(self):
        """The Song's assignment is gone from every Rehearsal's grid, since it carries no rehearsal FK (ADR-0009)."""
        other_rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)

        self.client.post(_save_url(self.rehearsal), _save_payload(self.rehearsal, [self.assignment.pk]))

        self.assertFalse(SongRoleAssignment.objects.filter(song=self.song, role=self.role).exists())
        response = self.client.get(_schedule_url(other_rehearsal))
        self.assertNotContains(response, self.assignment.person.name)

    def test_save_rejected_when_semester_stamp_is_stale(self):
        """A save posting a stale Semester stamp is rejected, writing nothing, and reports the problem."""
        stale_stamp = self.semester.updated_at - timedelta(days=1)
        payload = _save_payload(self.rehearsal, [self.assignment.pk])
        payload['assignment_semester_updated_at'] = stale_stamp.isoformat()

        response = self.client.post(_save_url(self.rehearsal), payload, follow=True)

        self.assertTrue(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())
        self.assertContains(response, 'changed while you were editing')

    def test_save_rejected_when_submitted_semester_is_not_the_viewed_one(self):
        """A save naming a Semester other than the session's viewed one is rejected, writing nothing."""
        other_semester = SemesterFactory(draft=True)
        payload = _save_payload(self.rehearsal, [self.assignment.pk])
        payload['assignment_semester_id'] = str(other_semester.pk)

        self.client.post(_save_url(self.rehearsal), payload)

        self.assertTrue(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())

    def test_save_post_on_a_past_rehearsal_404s(self):
        """A hand-crafted save POST against a past-dated Rehearsal 404s rather than silently applying the removal."""
        past_rehearsal = RehearsalFactory(
            semester=self.semester, is_full_setlist=False, date=timezone.localdate() - timedelta(days=1),
        )

        response = self.client.post(_save_url(past_rehearsal), _save_payload(self.rehearsal, [self.assignment.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())

    def test_empty_removal_set_is_a_legal_no_op_save(self):
        """A Save Changes POST with no removed ids is legal and leaves every assignment in place."""
        response = self.client.post(_save_url(self.rehearsal), _save_payload(self.rehearsal))

        self.assertRedirects(response, _schedule_url(self.rehearsal))
        self.assertTrue(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())
