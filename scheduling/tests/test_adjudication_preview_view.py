"""AdjudicationPreviewView: the Feasibility Preview for the adjudication table (issue #194, ADR 0008)."""

from datetime import time

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import (
    ConflictFactory,
    ConflictWindowFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Conflict
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY
from scheduling.tests.preview_helpers import assert_preview_writes_nothing

PASSWORD = 'a-strong-test-password-123'


def _preview_url(rehearsal):
    """Return the Feasibility Preview endpoint's URL for `rehearsal`."""
    return reverse('scheduling:manage-conflicts-preview', args=[rehearsal.pk])


def _formset_payload(entries, semester):
    """Assemble a full AdjudicationFormSet POST body (management form, hidden stamp, and every row)."""
    payload = {
        'adjudication-TOTAL_FORMS': str(len(entries)),
        'adjudication-INITIAL_FORMS': str(len(entries)),
        'adjudication-MIN_NUM_FORMS': '0',
        'adjudication-MAX_NUM_FORMS': '1000',
        'semester_id': str(semester.pk),
        'semester_updated_at': semester.updated_at.isoformat(),
    }
    for index, (conflict, status, note) in enumerate(entries):
        payload[f'adjudication-{index}-conflict_id'] = str(conflict.pk)
        payload[f'adjudication-{index}-status'] = status
        payload[f'adjudication-{index}-note'] = note
    return payload


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewAccessControlTests(TestCase):
    def setUp(self):
        """Build a Rehearsal so the preview route has something to resolve against."""
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)

    def test_anonymous_post_redirects_to_login(self):
        """An anonymous POST to the Preview endpoint redirects to login rather than running anything."""
        url = _preview_url(self.rehearsal)

        response = self.client.post(url, {})

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_non_admin_post_is_forbidden(self):
        """A logged-in non-admin's POST to the Preview endpoint is rejected with 403."""
        person = PersonFactory(password=PASSWORD)
        self.client.login(username=person.email, password=PASSWORD)

        response = self.client.post(_preview_url(self.rehearsal), {})

        self.assertEqual(response.status_code, 403)

    def test_get_is_not_allowed(self):
        """A GET to the Preview endpoint is rejected with 405 -- it is POST-only."""
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=admin.email, password=PASSWORD)

        response = self.client.get(_preview_url(self.rehearsal))

        self.assertEqual(response.status_code, 405)


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewRenderingTests(TestCase):
    def setUp(self):
        """Log in a synthetic admin against a Rehearsal with two Songs and one partial Conflict."""
        self.admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=self.admin.email, password=PASSWORD)
        self.semester = SemesterFactory(default_song_slot_count=2)
        self.rehearsal = RehearsalFactory(
            semester=self.semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(19, 0),
        )
        self.song_a = SongFactory(semester=self.semester)
        self.song_b = SongFactory(semester=self.semester)
        RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song_a, order=1, slot_count=1)
        RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song_b, order=2, slot_count=1)
        self.person = PersonFactory(name='Conflicted Person')
        SongRoleAssignmentFactory(song=self.song_a, person=self.person)
        SongRoleAssignmentFactory(song=self.song_b, person=self.person)
        self.conflict = ConflictFactory(person=self.person, rehearsal=self.rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=self.conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))

    def test_approving_an_infeasible_conflict_renders_loud_fallout_and_writes_nothing(self):
        """Approving a Conflict no ordering resolves renders loud Fallout naming the person, and writes nothing."""
        payload = _formset_payload([(self.conflict, Conflict.APPROVED, '')], self.semester)

        response = assert_preview_writes_nothing(
            self, _preview_url(self.rehearsal), payload,
            models_to_check=[(Conflict, {'status': Conflict.APPROVED})], semester=self.semester,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="adjudication-fallout-loud"')
        self.assertContains(response, 'Conflicted Person')
        self.assertContains(response, 'Infeasible')

    def test_pending_conflict_renders_no_fallout_region(self):
        """Leaving the Conflict pending renders the table with no loud/quiet Fallout region."""
        payload = _formset_payload([(self.conflict, Conflict.PENDING, '')], self.semester)

        response = assert_preview_writes_nothing(
            self, _preview_url(self.rehearsal), payload,
            models_to_check=[(Conflict, {'status': Conflict.APPROVED})], semester=self.semester,
        )

        self.assertNotContains(response, 'id="adjudication-fallout-loud"')
        self.assertNotContains(response, 'id="adjudication-fallout-quiet"')

    def test_invalid_formset_renders_validation_error_and_preserves_submitted_values(self):
        """An out-of-range status renders a Validation Error banner, and writes nothing."""
        payload = _formset_payload([(self.conflict, 'not-a-real-status', 'my note')], self.semester)

        response = assert_preview_writes_nothing(
            self, _preview_url(self.rehearsal), payload,
            models_to_check=[(Conflict, {'status': Conflict.APPROVED})], semester=self.semester,
        )

        self.assertContains(response, 'id="adjudication-preview-validation-error"')
        self.assertContains(response, 'my note')

    def test_wrong_semester_id_hard_blocks(self):
        """A Buffer whose semester id doesn't match the viewing Semester hard-fails, distinct from Fallout."""
        other_semester = SemesterFactory()
        session = self.client.session
        session[VIEWING_SEMESTER_SESSION_KEY] = self.semester.pk
        session.save()
        payload = _formset_payload([(self.conflict, Conflict.APPROVED, '')], other_semester)

        response = assert_preview_writes_nothing(
            self, _preview_url(self.rehearsal), payload,
            models_to_check=[(Conflict, {'status': Conflict.APPROVED})], semester=self.semester,
        )

        self.assertContains(response, 'id="adjudication-preview-validation-error"')

    def test_stale_stamp_renders_preview_with_a_banner_not_an_error_page(self):
        """A stale Semester.updated_at renders the Preview with a stale banner rather than refusing it."""
        stale_stamp = self.semester.updated_at.replace(year=self.semester.updated_at.year - 1)
        payload = _formset_payload([(self.conflict, Conflict.APPROVED, '')], self.semester)
        payload['semester_updated_at'] = stale_stamp.isoformat()

        response = assert_preview_writes_nothing(
            self, _preview_url(self.rehearsal), payload,
            models_to_check=[(Conflict, {'status': Conflict.APPROVED})], semester=self.semester,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="adjudication-preview-stale-banner"')
        self.assertContains(response, 'id="adjudication-table"')

    def test_writes_nothing_for_a_buffer_with_approvals_rejections_and_re_decisions(self):
        """The mandatory shared-helper exercise: approvals, rejections and re-decisions together write nothing."""
        second_person = PersonFactory()
        already_approved = ConflictFactory(
            person=second_person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT, status=Conflict.APPROVED,
        )
        already_rejected = ConflictFactory(rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT, status=Conflict.REJECTED)
        payload = _formset_payload(
            [
                (self.conflict, Conflict.APPROVED, ''),
                (already_approved, Conflict.REJECTED, 'changed my mind'),
                (already_rejected, Conflict.APPROVED, 're-decided'),
            ],
            self.semester,
        )

        response = assert_preview_writes_nothing(
            self, _preview_url(self.rehearsal), payload,
            models_to_check=[
                (Conflict, {'status': Conflict.APPROVED}),
                (Conflict, {'status': Conflict.REJECTED}),
                (Conflict, {'status': Conflict.PENDING}),
            ],
            semester=self.semester,
        )

        self.assertEqual(response.status_code, 200)

    def test_no_semester_is_handled_gracefully(self):
        """With no viewing Semester at all, the Preview endpoint returns a response rather than crashing."""
        self.semester.delete()
        payload = _formset_payload([], self.semester)

        response = self.client.post(_preview_url(self.rehearsal), payload)

        self.assertLess(response.status_code, 500)
