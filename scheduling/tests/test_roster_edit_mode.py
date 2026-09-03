"""Edit-roster mode on /members/: the admin toggle, the Person x Role table, and Save Changes (issue #227)."""

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import (
    ConflictFactory,
    MembershipFactory,
    MembershipRoleFactory,
    RehearsalFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Membership, MembershipRole
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY

PASSWORD = 'a-strong-test-password-123'


def _edit_url():
    """Return the same /members/ URL the reader is already on, with the edit-mode query string."""
    return f"{reverse('scheduling:members')}?mode=edit"


def _row_payload(prefix_index, membership, name=None, role_ids=(), remove=False):
    """Build one RosterEditFormSet row's POST fields for `membership`, at formset index `prefix_index`."""
    fields = {
        f'roster-{prefix_index}-person_id': str(membership.person_id),
        f'roster-{prefix_index}-name': name if name is not None else membership.person.name,
        f'roster-{prefix_index}-roles': [str(role_id) for role_id in role_ids],
    }
    if remove:
        fields[f'roster-{prefix_index}-remove'] = 'on'
    return fields


def _formset_payload(rows, semester):
    """Assemble a full RosterEditFormSet POST body (management form, hidden stamp, and every row), plus an empty add-list.

    The add-list's own RosterAddFormSet (issue #229) is a mandatory sibling
    of the edit table in the same POST body — Django raises if a
    formset's management form is missing entirely — so every test here
    that doesn't exercise the add list still supplies its (empty)
    management form.
    """
    payload = {
        'roster-TOTAL_FORMS': str(len(rows)),
        'roster-INITIAL_FORMS': str(len(rows)),
        'roster-MIN_NUM_FORMS': '0',
        'roster-MAX_NUM_FORMS': '1000',
        'roster_add-TOTAL_FORMS': '0',
        'roster_add-INITIAL_FORMS': '0',
        'roster_add-MIN_NUM_FORMS': '0',
        'roster_add-MAX_NUM_FORMS': '1000',
        'roster_semester_id': str(semester.pk),
        'roster_semester_updated_at': semester.updated_at.isoformat(),
    }
    for row in rows:
        payload.update(row)
    return payload


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAndNonAdminAccessTests(TestCase):
    def setUp(self):
        """Log in a synthetic non-admin Person with a Semester in place."""
        self.person = PersonFactory(password=PASSWORD)
        self.semester = SemesterFactory()

    def test_anonymous_get_edit_mode_redirects_to_login(self):
        """An anonymous GET at ?mode=edit redirects to login, same as any other /members/ request."""
        response = self.client.get(_edit_url())

        self.assertRedirects(response, f"{reverse('identity:login')}?next={_edit_url()}")

    def test_anonymous_post_redirects_to_login(self):
        """An anonymous Save Changes POST redirects to login rather than 403ing."""
        response = self.client.post(reverse('scheduling:members'), {})

        self.assertRedirects(response, f"{reverse('identity:login')}?next={reverse('scheduling:members')}")

    def test_non_admin_get_edit_mode_is_silently_ignored(self):
        """A non-admin's ?mode=edit still renders read mode, not the edit table."""
        self.client.login(username=self.person.email, password=PASSWORD)

        response = self.client.get(_edit_url())

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="roster-edit-table"')
        self.assertNotContains(response, 'id="save-roster-changes"')

    def test_non_admin_sees_no_edit_roster_button(self):
        """A non-admin's read-mode page carries no 'Edit roster' button at all."""
        self.client.login(username=self.person.email, password=PASSWORD)

        response = self.client.get(reverse('scheduling:members'))

        self.assertNotContains(response, 'id="edit-roster-button"')

    def test_non_admin_post_is_forbidden(self):
        """A logged-in non-admin's Save Changes POST is rejected with 403."""
        self.client.login(username=self.person.email, password=PASSWORD)

        response = self.client.post(reverse('scheduling:members'), {})

        self.assertEqual(response.status_code, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
class EditRosterButtonTests(TestCase):
    def setUp(self):
        """Log in a synthetic admin Person."""
        self.admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_admin_sees_the_edit_roster_button_when_a_semester_exists(self):
        """An admin viewing a real Semester sees the 'Edit roster' entry point."""
        SemesterFactory()

        response = self.client.get(reverse('scheduling:members'))

        self.assertContains(response, 'id="edit-roster-button"')

    def test_edit_roster_button_is_absent_with_no_semester_at_all(self):
        """With no Semester to write into, the button has nowhere to lead and is hidden."""
        response = self.client.get(reverse('scheduling:members'))

        self.assertNotContains(response, 'id="edit-roster-button"')

    def test_read_mode_is_unchanged_for_an_admin_who_does_not_press_it(self):
        """An admin's plain GET still renders the ordinary roster table and empty-state copy."""
        SemesterFactory()

        response = self.client.get(reverse('scheduling:members'))

        self.assertContains(response, 'No band members on the roster yet.')
        self.assertNotContains(response, 'id="roster-edit-table"')


@override_settings(SECURE_SSL_REDIRECT=False)
class EditModeRenderingTests(TestCase):
    def setUp(self):
        """Log in a synthetic admin Person against a Semester with one other rostered Person."""
        self.admin = PersonFactory(password=PASSWORD, is_admin=True, name='Admin Placeholder')
        self.client.login(username=self.admin.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.role = RoleFactory(name='Bassist')
        self.other = PersonFactory(name='Other Placeholder')
        self.membership = MembershipFactory(semester=self.semester, person=self.other)
        MembershipRoleFactory(membership=self.membership, role=self.role)

    def test_edit_mode_renders_one_row_per_membership(self):
        """The edit table shows one editable row per existing Membership, with the Person's current name."""
        response = self.client.get(_edit_url())

        self.assertContains(response, 'id="roster-edit-table"')
        self.assertContains(response, 'value="Other Placeholder"')

    def test_edit_mode_offers_only_active_roles_as_checkboxes(self):
        """An inactive Role never appears as a choice in the checkbox group."""
        RoleFactory(name='Retired Role', is_active=False)

        response = self.client.get(_edit_url())

        self.assertContains(response, 'Bassist')
        self.assertNotContains(response, 'Retired Role')

    def test_empty_roster_renders_a_usable_empty_edit_table(self):
        """A Semester with no Memberships still offers a working Save/Cancel edit surface."""
        self.membership.delete()

        response = self.client.get(_edit_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="save-roster-changes"')
        self.assertContains(response, 'id="cancel-roster-edit"')

    def test_remove_control_is_absent_from_the_admins_own_row(self):
        """The requesting admin's own row carries no remove checkbox, only a short explanatory reason."""
        MembershipFactory(semester=self.semester, person=self.admin)

        response = self.client.get(_edit_url())

        self.assertContains(response, "You can't remove yourself from the Roster.")

    def test_mismatch_flag_renders_for_a_person_with_a_mismatched_assignment(self):
        """A quiet flag renders next to a row whose Person holds a mismatched SongRoleAssignment."""
        song = SongFactory(semester=self.semester)
        mismatched_role = RoleFactory(name='Drummer')
        SongRoleAssignmentFactory(song=song, person=self.other, role=mismatched_role)

        response = self.client.get(_edit_url())

        self.assertContains(response, 'roster-role-mismatch-flag')

    def test_no_mismatch_flag_for_a_matching_assignment(self):
        """A Person whose assigned Role matches a declared Role renders no mismatch flag."""
        song = SongFactory(semester=self.semester)
        SongRoleAssignmentFactory(song=song, person=self.other, role=self.role)

        response = self.client.get(_edit_url())

        self.assertNotContains(response, 'roster-role-mismatch-flag')

    def test_no_conflict_field_appears_in_edit_mode(self):
        """Conflict.reason never renders anywhere in the rendered edit table."""
        rehearsal = RehearsalFactory(semester=self.semester)
        ConflictFactory(person=self.other, rehearsal=rehearsal, adjudication_note='')

        response = self.client.get(_edit_url())

        self.assertNotContains(response, 'reason')

    def test_person_email_does_not_appear_in_the_edit_table(self):
        """Person.email is absent from the edit table, matching the read-mode roster."""
        response = self.client.get(_edit_url())

        self.assertNotContains(response, self.other.email)

    def test_renders_the_non_live_banner_when_viewing_a_draft(self):
        """Edit mode on a session-selected draft Semester carries the shared non-live banner."""
        live = SemesterFactory()
        draft = SemesterFactory(draft=True)
        session = self.client.session
        session[VIEWING_SEMESTER_SESSION_KEY] = draft.pk
        session.save()
        del live

        response = self.client.get(_edit_url())

        self.assertContains(response, 'not what members see')


@override_settings(SECURE_SSL_REDIRECT=False)
class SaveChangesTests(TestCase):
    def setUp(self):
        """Log in a synthetic admin Person against a Semester with one other rostered Person and one active Role."""
        self.admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=self.admin.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.role = RoleFactory(name='Bassist')
        self.other = PersonFactory(name='Original Name')
        self.membership = MembershipFactory(semester=self.semester, person=self.other)

    def test_save_changes_commits_a_name_edit_role_change_and_removal_together(self):
        """One Save Changes batch lands a name edit, a Role change, and a removal in the same transaction."""
        kept = self.other
        removed_membership = MembershipFactory(semester=self.semester)
        removed_person = removed_membership.person
        payload = _formset_payload(
            [
                _row_payload(0, self.membership, name='New Name', role_ids=[self.role.pk]),
                _row_payload(1, removed_membership, remove=True),
            ],
            self.semester,
        )

        response = self.client.post(reverse('scheduling:members'), payload)

        self.assertRedirects(response, reverse('scheduling:members'))
        kept.refresh_from_db()
        self.assertEqual(kept.name, 'New Name')
        self.assertEqual(
            set(MembershipRole.objects.filter(membership=self.membership).values_list('role_id', flat=True)),
            {self.role.pk},
        )
        self.assertFalse(Membership.objects.filter(person=removed_person, semester=self.semester).exists())

    def test_cancel_link_returns_to_read_mode_without_a_post(self):
        """The edit table's Cancel control is a plain link back to /members/, not a form submission."""
        response = self.client.get(_edit_url())

        self.assertContains(response, f'href="{reverse("scheduling:members")}"')

    def test_invalid_buffer_rerenders_with_every_submitted_value_preserved(self):
        """A blank name re-renders the whole edit table with per-row errors, writing nothing at all."""
        second_membership = MembershipFactory(semester=self.semester, person=PersonFactory(name='Second Person'))
        payload = _formset_payload(
            [
                _row_payload(0, self.membership, name='', role_ids=[self.role.pk]),
                _row_payload(1, second_membership, remove=True),
            ],
            self.semester,
        )

        response = self.client.post(reverse('scheduling:members'), payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="roster-edit-table"')
        self.other.refresh_from_db()
        self.assertEqual(self.other.name, 'Original Name')
        self.assertFalse(MembershipRole.objects.filter(membership=self.membership).exists())
        self.assertTrue(Membership.objects.filter(pk=second_membership.pk).exists())
        # Every submitted value survives the re-render: the pending removal checkbox and the newly ticked Role.
        self.assertContains(response, 'checked')
        self.assertContains(response, f'value="{self.role.pk}"')

    def test_a_hand_crafted_self_removal_is_rejected_and_writes_nothing(self):
        """Even a hand-crafted POST removing the requesting admin's own Person is rejected, per #226's backstop."""
        admin_membership = MembershipFactory(semester=self.semester, person=self.admin)
        payload = _formset_payload(
            [
                _row_payload(0, self.membership),
                _row_payload(1, admin_membership, remove=True),
            ],
            self.semester,
        )

        response = self.client.post(reverse('scheduling:members'), payload)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Membership.objects.filter(pk=admin_membership.pk).exists())

    def test_save_changes_writes_to_the_session_selected_draft_not_the_live_semester(self):
        """A Save Changes batch lands on the session-selected draft Semester, leaving the Live Semester untouched."""
        draft = SemesterFactory(draft=True)
        draft_membership = MembershipFactory(semester=draft, person=PersonFactory(name='Draft Person'))
        session = self.client.session
        session[VIEWING_SEMESTER_SESSION_KEY] = draft.pk
        session.save()
        payload = _formset_payload([_row_payload(0, draft_membership, name='Renamed Draft Person')], draft)

        response = self.client.post(reverse('scheduling:members'), payload)

        self.assertRedirects(response, reverse('scheduling:members'))
        draft_membership.person.refresh_from_db()
        self.assertEqual(draft_membership.person.name, 'Renamed Draft Person')
        self.other.refresh_from_db()
        self.assertEqual(self.other.name, 'Original Name')
