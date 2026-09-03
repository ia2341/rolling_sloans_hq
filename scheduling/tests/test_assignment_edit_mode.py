"""Assignment edit mode on /schedule/: the admin toggle, ✕ chips, + picker, and Save Changes (issues #210, #211)."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    MembershipRoleFactory,
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


def _picker_url(rehearsal, song, role):
    """Return the "+" picker's fetch endpoint for one (Song, Role) cell on `rehearsal`'s grid."""
    return reverse('scheduling:schedule-assignments-picker', args=[rehearsal.pk, song.pk, role.pk])


def _save_payload(rehearsal, removed_ids=(), added_entries=()):
    """Build a Save Changes POST body against `rehearsal`'s Semester, naming `removed_ids`/`added_entries` to apply."""
    semester = rehearsal.semester
    payload = {
        'assignment_semester_id': str(semester.pk),
        'assignment_semester_updated_at': semester.updated_at.isoformat(),
    }
    if removed_ids:
        payload['removed_assignment_id'] = [str(pk) for pk in removed_ids]
    if added_entries:
        payload['added_assignment_entry'] = [f'{song_id}:{role_id}:{person_id}' for song_id, role_id, person_id in added_entries]
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

    def test_anonymous_picker_get_redirects_to_login(self):
        """An anonymous GET at the picker fetch endpoint redirects to login (issue #211)."""
        url = _picker_url(self.rehearsal, self.song, self.role)

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_non_admin_picker_get_is_forbidden(self):
        """A logged-in non-admin's picker fetch is rejected with 403."""
        self.client.login(username=self.person.email, password=PASSWORD)

        response = self.client.get(_picker_url(self.rehearsal, self.song, self.role))

        self.assertEqual(response.status_code, 403)


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

    def test_saving_a_picked_person_creates_the_assignment(self):
        """A Save Changes POST naming an added (song, role, person) entry creates that SongRoleAssignment (issue #211)."""
        membership = MembershipFactory(semester=self.semester)

        response = self.client.post(
            _save_url(self.rehearsal),
            _save_payload(self.rehearsal, added_entries=[(self.song.pk, self.role.pk, membership.person.pk)]),
        )

        self.assertRedirects(response, _schedule_url(self.rehearsal))
        self.assertTrue(
            SongRoleAssignment.objects.filter(song=self.song, role=self.role, person=membership.person).exists()
        )

    def test_a_buffer_mixing_a_pick_and_a_removal_produces_exactly_the_intended_rows(self):
        """One Save Changes POST applies a removal and a pick together, atomically (issue #211 acceptance)."""
        membership = MembershipFactory(semester=self.semester)

        response = self.client.post(
            _save_url(self.rehearsal),
            _save_payload(
                self.rehearsal,
                removed_ids=[self.assignment.pk],
                added_entries=[(self.song.pk, self.role.pk, membership.person.pk)],
            ),
        )

        self.assertRedirects(response, _schedule_url(self.rehearsal))
        self.assertFalse(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())
        self.assertTrue(
            SongRoleAssignment.objects.filter(song=self.song, role=self.role, person=membership.person).exists()
        )


@override_settings(SECURE_SSL_REDIRECT=False)
class AssignmentPickerViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build an admin Person, a future Rehearsal with one Song/Role column, and one rostered Member each in and out of the declared Role."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, is_full_setlist=False)
        cls.song = SongFactory(semester=cls.semester, position=1)
        cls.role = RoleFactory(name='Singer')
        SongRoleRequirementFactory(song=cls.song, role=cls.role, count=1)
        RehearsalSongFactory(song=cls.song, rehearsal=cls.rehearsal, order=1)

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_labels_the_assigned_section_with_its_scope(self):
        """The picker's assignment section is labelled with its every-rehearsal-and-concert scope (issue #211 acceptance)."""
        response = self.client.get(_picker_url(self.rehearsal, self.song, self.role))

        self.assertContains(response, 'Assigned (every rehearsal + concert)')

    def test_names_where_rostering_happens(self):
        """The picker says it lists rostered members only, naming /members/ as where rostering happens."""
        response = self.client.get(_picker_url(self.rehearsal, self.song, self.role))

        self.assertContains(response, reverse('scheduling:members'))
        self.assertContains(response, 'rostered members only')

    def test_declared_member_listed_outside_the_show_all_disclosure(self):
        """A Member who declared the cell's Role is offered outside the 'Show all members' disclosure."""
        declarer = PersonFactory(name='Declared Dana')
        membership = MembershipFactory(person=declarer, semester=self.semester)
        MembershipRoleFactory(membership=membership, role=self.role)

        response = self.client.get(_picker_url(self.rehearsal, self.song, self.role))

        self.assertContains(response, 'Declared Dana')
        self.assertContains(response, f'data-picker-person-id="{declarer.pk}"')

    def test_non_declaring_member_sits_behind_show_all_members_and_is_marked(self):
        """A Member who hasn't declared the Role is offered behind 'Show all members' and marked as such."""
        non_declarer = PersonFactory(name='Undeclared Uma')
        MembershipFactory(person=non_declarer, semester=self.semester)

        response = self.client.get(_picker_url(self.rehearsal, self.song, self.role))

        self.assertContains(response, 'Show all members')
        self.assertContains(response, 'Undeclared Uma')
        self.assertContains(response, 'Has not declared Singer')

    def test_a_non_rostered_person_is_not_offered_at_all(self):
        """A Person with no Membership in the viewed Semester never appears in the picker."""
        PersonFactory(name='Outsider Olga')

        response = self.client.get(_picker_url(self.rehearsal, self.song, self.role))

        self.assertNotContains(response, 'Outsider Olga')

    def test_an_already_assigned_person_is_not_reoffered(self):
        """A Person already assigned to this exact (Song, Role) cell isn't offered again in the 'Assigned' section.

        They may still appear in the separate "Backup (this rehearsal
        only)" section (issue #216) — a standing assignee is not barred
        from also covering their own cell for one evening — so this
        checks the "Assigned" section's picker attribute specifically,
        not the person's name anywhere on the page.
        """
        already = SongRoleAssignmentFactory(song=self.song, role=self.role)
        MembershipFactory(person=already.person, semester=self.semester)

        response = self.client.get(_picker_url(self.rehearsal, self.song, self.role))

        self.assertNotContains(response, f'data-picker-person-id="{already.person.pk}"')

    def test_picker_get_on_a_past_rehearsal_404s(self):
        """A hand-crafted picker fetch against a non-editable (past-dated) Rehearsal's grid 404s."""
        past_rehearsal = RehearsalFactory(
            semester=self.semester, is_full_setlist=False, date=timezone.localdate() - timedelta(days=1),
        )

        response = self.client.get(_picker_url(past_rehearsal, self.song, self.role))

        self.assertEqual(response.status_code, 404)
