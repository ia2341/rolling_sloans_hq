"""RosterPreviewView and RosterRemovalConfirmView: the Roster's first Preview surface (issue #228, ADR 0008)."""

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from identity.models import Person
from scheduling.factories import (
    MembershipFactory,
    RoleFactory,
    SemesterFactory,
)
from scheduling.models import Conflict, Membership, MembershipRole, SongRoleAssignment
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY
from scheduling.tests.preview_helpers import assert_preview_writes_nothing

PASSWORD = 'a-strong-test-password-123'


def _preview_url():
    """Return the Roster Preview endpoint's URL."""
    return reverse('scheduling:members-preview')


def _confirm_removal_url():
    """Return the Roster removal confirmation endpoint's URL."""
    return reverse('scheduling:members-preview-confirm-removal')


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
    """Assemble a full RosterEditFormSet POST body (management form, hidden stamp, and every row)."""
    payload = {
        'roster-TOTAL_FORMS': str(len(rows)),
        'roster-INITIAL_FORMS': str(len(rows)),
        'roster-MIN_NUM_FORMS': '0',
        'roster-MAX_NUM_FORMS': '1000',
        'roster_semester_id': str(semester.pk),
        'roster_semester_updated_at': semester.updated_at.isoformat(),
    }
    for row in rows:
        payload.update(row)
    return payload


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewAccessControlTests(TestCase):
    def setUp(self):
        """Build a Semester so the preview route has something to resolve against."""
        self.semester = SemesterFactory()

    def test_anonymous_post_redirects_to_login(self):
        """An anonymous POST to the Preview endpoint redirects to login rather than running anything."""
        response = self.client.post(_preview_url(), {})

        self.assertRedirects(response, f"{reverse('identity:login')}?next={_preview_url()}")

    def test_non_admin_post_is_forbidden(self):
        """A logged-in non-admin's POST to the Preview endpoint is rejected with 403."""
        person = PersonFactory(password=PASSWORD)
        self.client.login(username=person.email, password=PASSWORD)

        response = self.client.post(_preview_url(), {})

        self.assertEqual(response.status_code, 403)

    def test_get_is_not_allowed(self):
        """A GET to the Preview endpoint is rejected with 405 -- it is POST-only."""
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=admin.email, password=PASSWORD)

        response = self.client.get(_preview_url())

        self.assertEqual(response.status_code, 405)

    def test_put_is_not_allowed(self):
        """A PUT to the Preview endpoint is rejected with 405."""
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=admin.email, password=PASSWORD)

        response = self.client.put(_preview_url())

        self.assertEqual(response.status_code, 405)

    def test_delete_is_not_allowed(self):
        """A DELETE to the Preview endpoint is rejected with 405."""
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=admin.email, password=PASSWORD)

        response = self.client.delete(_preview_url())

        self.assertEqual(response.status_code, 405)


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewRenderingTests(TestCase):
    def setUp(self):
        """Log in a synthetic admin Person against a Semester with one other rostered Person and one active Role."""
        self.admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=self.admin.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.role = RoleFactory(name='Bassist')
        self.other = PersonFactory(name='Original Name')
        self.membership = MembershipFactory(semester=self.semester, person=self.other)

    def test_valid_buffer_renders_fallout_and_pending_changes(self):
        """A valid Preview POST renders the Fallout region naming the pending change, and writes nothing."""
        payload = _formset_payload(
            [_row_payload(0, self.membership, name='New Name', role_ids=[self.role.pk])], self.semester,
        )

        response = assert_preview_writes_nothing(
            self, _preview_url(), payload,
            models_to_check=[Membership, MembershipRole, SongRoleAssignment, Conflict, Person],
            semester=self.semester,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="roster-fallout"')
        self.assertContains(response, 'Original Name')

    def test_invalid_formset_renders_validation_error_not_fallout(self):
        """A structurally invalid Buffer renders a Validation Error banner, distinct from a Fallout region, and writes nothing."""
        payload = _formset_payload([_row_payload(0, self.membership, name='')], self.semester)

        response = assert_preview_writes_nothing(
            self, _preview_url(), payload,
            models_to_check=[Membership, MembershipRole], semester=self.semester,
        )

        self.assertContains(response, 'id="roster-fallout-validation-error"')
        self.assertNotContains(response, 'id="roster-fallout-pending"')

    def test_wrong_semester_id_hard_blocks(self):
        """A Buffer whose semester id doesn't match the viewing Semester hard-fails, distinct from Fallout."""
        other_semester = SemesterFactory()
        session = self.client.session
        session[VIEWING_SEMESTER_SESSION_KEY] = self.semester.pk
        session.save()
        payload = _formset_payload([_row_payload(0, self.membership)], other_semester)

        response = assert_preview_writes_nothing(
            self, _preview_url(), payload,
            models_to_check=[Membership, MembershipRole], semester=self.semester,
        )

        self.assertContains(response, 'id="roster-fallout-validation-error"')

    def test_self_removal_hard_blocks(self):
        """A Buffer removing the requesting admin's own Person hard-fails on Preview too."""
        admin_membership = MembershipFactory(semester=self.semester, person=self.admin)
        payload = _formset_payload(
            [_row_payload(0, self.membership), _row_payload(1, admin_membership, remove=True)], self.semester,
        )

        response = assert_preview_writes_nothing(
            self, _preview_url(), payload,
            models_to_check=[Membership, MembershipRole], semester=self.semester,
        )

        self.assertContains(response, 'id="roster-fallout-validation-error"')

    def test_stale_stamp_renders_preview_with_a_banner_not_an_error_page(self):
        """A stale Semester.updated_at renders the Preview with a stale banner rather than refusing it."""
        stale_stamp = self.semester.updated_at.replace(year=self.semester.updated_at.year - 1)
        payload = _formset_payload([_row_payload(0, self.membership)], self.semester)
        payload['roster_semester_updated_at'] = stale_stamp.isoformat()

        response = assert_preview_writes_nothing(
            self, _preview_url(), payload,
            models_to_check=[Membership, MembershipRole], semester=self.semester,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="roster-fallout-stale-banner"')
        self.assertContains(response, 'id="roster-fallout-pending"')

    def test_writes_nothing_for_an_add_a_mutation_and_a_removal_together(self):
        """The mandatory shared-helper exercise: a Buffer with an add, a mutation and a removal together writes nothing."""
        added = PersonFactory(name='Brand New Person')
        removed_membership = MembershipFactory(semester=self.semester)
        payload = _formset_payload(
            [
                _row_payload(0, self.membership, name='Mutated Name', role_ids=[self.role.pk]),
                _row_payload(1, removed_membership, remove=True),
            ],
            self.semester,
        )
        payload.update({
            'roster-TOTAL_FORMS': '3',
            'roster-INITIAL_FORMS': '2',
            'roster-2-person_id': str(added.pk),
            'roster-2-name': added.name,
            'roster-2-roles': [],
        })

        response = assert_preview_writes_nothing(
            self, _preview_url(), payload,
            models_to_check=[Membership, MembershipRole, SongRoleAssignment, Conflict, Person],
            semester=self.semester,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_no_semester_is_handled_gracefully(self):
        """With no viewing Semester at all, the Preview endpoint returns a response rather than crashing."""
        self.semester.delete()
        payload = _formset_payload([], self.semester)

        response = self.client.post(_preview_url(), payload)

        self.assertLess(response.status_code, 500)


@override_settings(SECURE_SSL_REDIRECT=False)
class RemovalConfirmViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic admin Person against a Semester with a Person about to be removed."""
        self.admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=self.admin.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.removed = PersonFactory(name='Gone Person')
        self.removed_membership = MembershipFactory(semester=self.semester, person=self.removed)

    def test_confirm_dialog_renders_each_removed_persons_email(self):
        """The removal confirmation dialog names each removed Person's email, mirroring the on-page Fallout."""
        payload = _formset_payload([_row_payload(0, self.removed_membership, remove=True)], self.semester)

        response = assert_preview_writes_nothing(
            self, _confirm_removal_url(), payload,
            models_to_check=[Membership, MembershipRole], semester=self.semester,
        )

        self.assertContains(response, 'Gone Person')
        self.assertContains(response, self.removed.email)

    def test_anonymous_post_redirects_to_login(self):
        """An anonymous POST to the removal confirmation endpoint redirects to login."""
        self.client.logout()

        response = self.client.post(_confirm_removal_url(), {})

        self.assertRedirects(response, f"{reverse('identity:login')}?next={_confirm_removal_url()}")

    def test_non_admin_post_is_forbidden(self):
        """A logged-in non-admin's POST to the removal confirmation endpoint is rejected with 403."""
        self.client.logout()
        person = PersonFactory(password=PASSWORD)
        self.client.login(username=person.email, password=PASSWORD)

        response = self.client.post(_confirm_removal_url(), {})

        self.assertEqual(response.status_code, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewOnDraftSemesterTests(TestCase):
    def test_preview_runs_against_the_session_selected_draft_not_the_live_semester(self):
        """A Preview computed while a draft is session-selected reports Fallout for the draft, not the Live Semester."""
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=admin.email, password=PASSWORD)
        draft = SemesterFactory(draft=True)
        draft_membership = MembershipFactory(semester=draft, person=PersonFactory(name='Draft Person'))
        session = self.client.session
        session[VIEWING_SEMESTER_SESSION_KEY] = draft.pk
        session.save()
        payload = _formset_payload([_row_payload(0, draft_membership, name='Renamed Draft Person')], draft)

        response = assert_preview_writes_nothing(
            self, _preview_url(), payload, models_to_check=[Membership, MembershipRole], semester=draft,
        )

        self.assertContains(response, 'Draft Person')
