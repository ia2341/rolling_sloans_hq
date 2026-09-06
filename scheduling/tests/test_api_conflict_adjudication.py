"""`/api/conflicts/*`: the Conflict-adjudication index, detail, Preview and Save surfaces (issue #340, ADR 0008).

Mirrors `test_roster_api.py`'s shape: access-control coverage, a read
surface's exact key-set assertions (per this repo's ADR-0005 privacy
convention), Preview writing nothing, wrong/stale-Semester handling, and a
Buffer-identity test proving `build_adjudication_buffer_from_request()` is
the one construction path Preview and Save both call.
"""

import json
from datetime import time

from django.http import HttpRequest
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.api_builders import (
    AdjudicationBufferValidationError,
    build_adjudication_buffer_from_request,
)
from scheduling.factories import (
    ConflictFactory,
    ConflictWindowFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Conflict
from scheduling.tests.preview_helpers import assert_preview_writes_nothing
from scheduling.tests.test_setlist_reorder_add_delete import (
    admin_client,
    member_client,
    select,
)

PASSWORD = 'a-strong-test-password-123'


def _index_url():
    """Return the adjudication index `/api/` endpoint's URL."""
    return reverse('api-conflicts-index')


def _detail_url(rehearsal_id):
    """Return the adjudication detail `/api/` endpoint's URL for `rehearsal_id`."""
    return reverse('api-conflicts-detail', args=[rehearsal_id])


def _preview_url(rehearsal_id):
    """Return the adjudication Preview `/api/` endpoint's URL for `rehearsal_id`."""
    return reverse('api-conflicts-preview', args=[rehearsal_id])


def _save_url(rehearsal_id):
    """Return the adjudication Save `/api/` endpoint's URL for `rehearsal_id`."""
    return reverse('api-conflicts-save', args=[rehearsal_id])


def _post_json(test_case, url, body):
    """POST `body` (a dict) as a JSON request body and return `(response, parsed envelope)`."""
    response = test_case.client.post(url, data=json.dumps(body), content_type='application/json')
    return response, json.loads(response.content)


def _fake_request(body: dict) -> HttpRequest:
    """Build a bare `HttpRequest` carrying `body` as its JSON-encoded `.body`, for calling the builder directly."""
    request = HttpRequest()
    request._body = json.dumps(body).encode('utf-8')
    return request


def _valid_body(semester, entries=None):
    """Build a well-formed `/api/conflicts/<id>/{preview,save}/` request body for `semester`."""
    return {
        'semester_id': semester.pk,
        'semester_updated_at': semester.updated_at.isoformat(),
        'entries': entries or [],
    }


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessControlTests(TestCase):
    """Every adjudication endpoint gates identically to every other `AdminApiView`/`AdminPreviewApiView`."""

    def setUp(self):
        """Build a Semester with one future Rehearsal so a request has something to resolve against."""
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)

    def test_anonymous_index_get_is_401(self):
        """An anonymous GET to the index answers the documented JSON 401, never a redirect."""
        response = self.client.get(_index_url())

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_non_admin_index_get_is_403(self):
        """A logged-in non-admin's GET to the index is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.get(_index_url())

        self.assertEqual(response.status_code, 403)

    def test_anonymous_detail_get_is_401(self):
        """An anonymous GET to the detail route answers 401, never a redirect."""
        response = self.client.get(_detail_url(self.rehearsal.pk))

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_non_admin_detail_get_is_403(self):
        """A logged-in non-admin's GET to the detail route is rejected with 403."""
        member_client(self)

        response = self.client.get(_detail_url(self.rehearsal.pk))

        self.assertEqual(response.status_code, 403)

    def test_anonymous_preview_post_is_401(self):
        """An anonymous POST to Preview answers 401, never a redirect."""
        response = self.client.post(_preview_url(self.rehearsal.pk), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_non_admin_preview_post_is_403(self):
        """A logged-in non-admin's POST to Preview is rejected with 403."""
        member_client(self)

        response = self.client.post(_preview_url(self.rehearsal.pk), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def test_anonymous_save_post_is_401(self):
        """An anonymous POST to Save answers 401, never a redirect."""
        response = self.client.post(_save_url(self.rehearsal.pk), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_non_admin_save_post_is_403(self):
        """A logged-in non-admin's POST to Save is rejected with 403."""
        member_client(self)

        response = self.client.post(_save_url(self.rehearsal.pk), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def test_preview_get_is_not_allowed(self):
        """A GET to Preview is rejected — it is POST-only."""
        admin_client(self)

        response = self.client.get(_preview_url(self.rehearsal.pk))

        self.assertEqual(response.status_code, 405)

    def test_save_get_is_not_allowed(self):
        """A GET to Save is rejected — it is POST-only."""
        admin_client(self)

        response = self.client.get(_save_url(self.rehearsal.pk))

        self.assertEqual(response.status_code, 405)


@override_settings(SECURE_SSL_REDIRECT=False)
class IndexReadTests(TestCase):
    """`GET /api/conflicts/`: the adjudication index's exact key set, counts and Semester scoping."""

    def setUp(self):
        """Log in a synthetic admin against a fresh Semester."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)

    def test_no_semester_returns_the_empty_shape(self):
        """With nothing selected, the index returns the documented empty shape rather than erroring."""
        from scheduling.services import VIEWING_SEMESTER_SESSION_KEY

        session = self.client.session
        del session[VIEWING_SEMESTER_SESSION_KEY]
        session.save()
        # Also make sure there is no Semester at all to fall back to.
        self.semester.delete()

        response = self.client.get(_index_url())
        envelope = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(envelope['data']['rows'], [])

    def test_zero_conflict_rehearsal_still_appears(self):
        """A future, non-Dress Rehearsal with zero Conflicts still gets a row, all counts zero."""
        rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)

        response = self.client.get(_index_url())
        envelope = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        rows = envelope['data']['rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['rehearsal_id'], rehearsal.pk)
        self.assertEqual(rows[0]['pending_count'], 0)
        self.assertEqual(rows[0]['approved_count'], 0)
        self.assertEqual(rows[0]['rejected_count'], 0)

    def test_dress_rehearsal_never_appears(self):
        """A future Dress Rehearsal is absent from the index."""
        RehearsalFactory(semester=self.semester, is_full_setlist=True)

        response = self.client.get(_index_url())
        envelope = json.loads(response.content)

        self.assertEqual(envelope['data']['rows'], [])

    def test_counts_are_correct_and_disjoint(self):
        """Pending, approved and rejected counts are each correct and don't leak into one another."""
        rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)
        ConflictFactory(rehearsal=rehearsal, status=Conflict.PENDING)
        ConflictFactory(rehearsal=rehearsal, status=Conflict.PENDING)
        ConflictFactory(rehearsal=rehearsal, status=Conflict.APPROVED)
        ConflictFactory(rehearsal=rehearsal, status=Conflict.REJECTED)

        response = self.client.get(_index_url())
        envelope = json.loads(response.content)

        row = envelope['data']['rows'][0]
        self.assertEqual(row['pending_count'], 2)
        self.assertEqual(row['approved_count'], 1)
        self.assertEqual(row['rejected_count'], 1)

    def test_scoped_to_the_viewing_semester(self):
        """A Rehearsal in a different Semester never appears in this Semester's rows."""
        other_semester = SemesterFactory()
        RehearsalFactory(semester=other_semester, is_full_setlist=False)

        response = self.client.get(_index_url())
        envelope = json.loads(response.content)

        self.assertEqual(envelope['data']['rows'], [])

    def test_row_key_set_carries_no_person_declaration_reason_or_note(self):
        """A row's key set is exactly the documented seven keys — no Person, declaration, reason or note leak in (ADR 0005)."""
        rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)
        ConflictFactory(rehearsal=rehearsal, status=Conflict.PENDING)

        response = self.client.get(_index_url())
        envelope = json.loads(response.content)

        row = envelope['data']['rows'][0]
        self.assertEqual(
            set(row.keys()),
            {'rehearsal_id', 'date', 'start_time', 'end_time', 'pending_count', 'approved_count', 'rejected_count'},
        )
        for forbidden in ('person', 'person_id', 'person_name', 'reason', 'note', 'declared_time', 'status'):
            self.assertNotIn(forbidden, row)


@override_settings(SECURE_SSL_REDIRECT=False)
class DetailReadTests(TestCase):
    """`GET /api/conflicts/<rehearsal_id>/`: the whole adjudication table, in one round trip."""

    def setUp(self):
        """Log in a synthetic admin against a fresh Semester with one future Rehearsal."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)

    def test_row_key_set_includes_person_reason_and_note(self):
        """A detail row's key set includes person_id/person_name/reason/note — this admin-only route is where they belong."""
        person = PersonFactory(name='Detail Test Person')
        conflict = ConflictFactory(
            rehearsal=self.rehearsal, person=person, reason='a synthetic reason for testing',
        )

        response = self.client.get(_detail_url(self.rehearsal.pk))
        envelope = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        row = envelope['data']['rows'][0]
        self.assertEqual(
            set(row.keys()),
            {'conflict_id', 'person_id', 'person_name', 'type_label', 'declared_time', 'reason', 'status', 'note'},
        )
        self.assertEqual(row['conflict_id'], conflict.pk)
        self.assertEqual(row['person_id'], person.pk)
        self.assertEqual(row['person_name'], 'Detail Test Person')
        self.assertEqual(row['reason'], 'a synthetic reason for testing')

    def test_top_level_shape_carries_window_pending_count_and_stamp(self):
        """The top-level envelope carries the Rehearsal's window, live pending_count and the Semester's stamp."""
        ConflictFactory(rehearsal=self.rehearsal, status=Conflict.PENDING)
        ConflictFactory(rehearsal=self.rehearsal, status=Conflict.APPROVED)

        response = self.client.get(_detail_url(self.rehearsal.pk))
        envelope = json.loads(response.content)

        data = envelope['data']
        self.assertEqual(data['rehearsal_id'], self.rehearsal.pk)
        self.assertEqual(data['date'], self.rehearsal.date.isoformat())
        self.assertEqual(data['pending_count'], 1)
        self.assertEqual(data['semester_updated_at'], self.semester.updated_at.isoformat())
        self.assertEqual(len(data['rows']), 2)

    def test_feasibility_resolves_song_and_role_names_for_a_standing_overlap(self):
        """The feasibility map, keyed by string conflict_id, resolves the overlap Song/Role to display names."""
        semester = SemesterFactory(default_song_slot_count=1)
        rehearsal = RehearsalFactory(
            semester=semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(18, 30),
        )
        select(self, semester)
        song = SongFactory(semester=semester, title='Overlap Song')
        RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1, slot_count=1)
        role = RoleFactory(name='Overlap Role')
        person = PersonFactory()
        SongRoleAssignmentFactory(song=song, person=person, role=role)
        conflict = ConflictFactory(
            person=person, rehearsal=rehearsal, type=Conflict.PARTIAL, status=Conflict.APPROVED,
        )
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))

        response = self.client.get(_detail_url(rehearsal.pk))
        envelope = json.loads(response.content)

        feasibility = envelope['data']['feasibility'][str(conflict.pk)]
        self.assertTrue(feasibility['has_standing_overlap'])
        self.assertEqual(feasibility['overlap_song_id'], song.pk)
        self.assertEqual(feasibility['overlap_role_id'], role.pk)
        self.assertEqual(feasibility['overlap_song_title'], 'Overlap Song')
        self.assertEqual(feasibility['overlap_role_name'], 'Overlap Role')

    def test_404s_for_a_rehearsal_in_another_semester(self):
        """A Rehearsal belonging to a different Semester 404s rather than leaking across scope."""
        other_semester = SemesterFactory(draft=True)
        foreign_rehearsal = RehearsalFactory(semester=other_semester, is_full_setlist=False)

        response = self.client.get(_detail_url(foreign_rehearsal.pk))

        self.assertEqual(response.status_code, 404)

    def test_404s_for_the_dress_rehearsal(self):
        """The Dress Rehearsal 404s — it can hold no Conflict at all (ADR 0006)."""
        dress = RehearsalFactory(semester=self.semester, is_full_setlist=True)

        response = self.client.get(_detail_url(dress.pk))

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewTests(TestCase):
    """`POST /api/conflicts/<rehearsal_id>/preview/`: run for real and rolled back."""

    def setUp(self):
        """Log in a synthetic admin against a fresh Semester with one future Rehearsal and one Conflict."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)
        self.conflict = ConflictFactory(rehearsal=self.rehearsal, status=Conflict.PENDING)

    def test_preview_writes_nothing(self):
        """A valid Preview writes no Conflict/Semester change and sends no mail (ADR 0008, mandatory helper)."""
        body = _valid_body(self.semester, entries=[
            {'conflict_id': self.conflict.pk, 'status': Conflict.APPROVED, 'note': 'a synthetic note'},
        ])

        response = assert_preview_writes_nothing(
            self, _preview_url(self.rehearsal.pk), models_to_check=[Conflict], semester=self.semester, json_body=body,
        )
        envelope = json.loads(response.content)

        self.assertTrue(envelope['ok'])
        self.conflict.refresh_from_db()
        self.assertEqual(self.conflict.status, Conflict.PENDING)

    def test_preview_reports_feasibility_in_the_fallout(self):
        """Preview's Fallout carries a feasibility entry for every Conflict on the Rehearsal."""
        body = _valid_body(self.semester, entries=[
            {'conflict_id': self.conflict.pk, 'status': Conflict.APPROVED, 'note': ''},
        ])

        response, envelope = _post_json(self, _preview_url(self.rehearsal.pk), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertIn(str(self.conflict.pk), envelope['fallout']['feasibility'])

    def test_wrong_semester_id_previews_a_4xx(self):
        """Preview answers a wrong `semester_id` with a 4xx, not a 200 Validation Error."""
        other_semester = SemesterFactory()
        body = _valid_body(other_semester)

        response, envelope = _post_json(self, _preview_url(self.rehearsal.pk), body)

        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.assertEqual(envelope['error'], 'wrong_semester')

    def test_unknown_conflict_id_previews_blocked_without_raising(self):
        """A Conflict id from another Rehearsal previews `is_blocked: true`, never a 500."""
        other_rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)
        foreign_conflict = ConflictFactory(rehearsal=other_rehearsal)
        body = _valid_body(self.semester, entries=[
            {'conflict_id': foreign_conflict.pk, 'status': Conflict.APPROVED, 'note': ''},
        ])

        response, envelope = _post_json(self, _preview_url(self.rehearsal.pk), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertTrue(envelope['fallout']['is_blocked'])

    def test_stale_semester_reports_is_stale_true(self):
        """A stale `semester_updated_at` still computes Fallout and reports `is_stale: true`."""
        stale_stamp = self.semester.updated_at.replace(year=self.semester.updated_at.year - 1)
        body = {
            'semester_id': self.semester.pk,
            'semester_updated_at': stale_stamp.isoformat(),
            'entries': [{'conflict_id': self.conflict.pk, 'status': Conflict.APPROVED, 'note': ''}],
        }

        response, envelope = _post_json(self, _preview_url(self.rehearsal.pk), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertTrue(envelope['fallout']['is_stale'])

    def test_over_long_note_previews_ok_false_with_a_row_error(self):
        """An over-long note is rejected as a per-row field error, not silently truncated."""
        body = _valid_body(self.semester, entries=[
            {'conflict_id': self.conflict.pk, 'status': Conflict.APPROVED, 'note': 'x' * 256},
        ])

        response, envelope = _post_json(self, _preview_url(self.rehearsal.pk), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertIn(f'conflict-{self.conflict.pk}', envelope['errors'])
        self.assertIn('note', envelope['errors'][f'conflict-{self.conflict.pk}'])


@override_settings(SECURE_SSL_REDIRECT=False)
class SaveTests(TransactionTestCase):
    """`POST /api/conflicts/<rehearsal_id>/save/`: the real, committing write.

    `TransactionTestCase`, not `TestCase`, mirroring `test_roster_api.py`'s
    `SaveCommitsTests`: `apply_adjudications()` doesn't itself defer
    anything to `transaction.on_commit()`, but staying consistent with the
    rest of this surface's Save coverage costs nothing.
    """

    def setUp(self):
        """Log in a synthetic admin against a fresh Semester with one future Rehearsal and one Conflict."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)
        self.conflict = ConflictFactory(rehearsal=self.rehearsal, status=Conflict.PENDING)

    def test_valid_save_applies_all_entries(self):
        """A valid Save applies every entry's status and note in one transaction."""
        body = _valid_body(self.semester, entries=[
            {'conflict_id': self.conflict.pk, 'status': Conflict.APPROVED, 'note': 'a synthetic approval note'},
        ])

        response, envelope = _post_json(self, _save_url(self.rehearsal.pk), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertIsNone(envelope['values'])
        self.conflict.refresh_from_db()
        self.assertEqual(self.conflict.status, Conflict.APPROVED)
        self.assertEqual(self.conflict.adjudication_note, 'a synthetic approval note')

    def test_save_with_empty_entries_is_refused(self):
        """Save refuses an empty Buffer outright — user story 38, 'Save refused while nothing is pending'."""
        body = _valid_body(self.semester, entries=[])

        response, envelope = _post_json(self, _save_url(self.rehearsal.pk), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        self.conflict.refresh_from_db()
        self.assertEqual(self.conflict.status, Conflict.PENDING)

    def test_wrong_semester_id_save_is_a_4xx(self):
        """Save answers a wrong `semester_id` with a 4xx, not a 200 Validation Error."""
        other_semester = SemesterFactory()
        body = _valid_body(other_semester, entries=[
            {'conflict_id': self.conflict.pk, 'status': Conflict.APPROVED, 'note': ''},
        ])

        response, envelope = _post_json(self, _save_url(self.rehearsal.pk), body)

        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.assertEqual(envelope['error'], 'wrong_semester')

    def test_stale_semester_save_is_refused_without_corrupting_data(self):
        """Save against a stale stamp reports `ok: false` (not a hard 4xx) and applies no change."""
        stale_stamp = self.semester.updated_at.replace(year=self.semester.updated_at.year - 1)
        body = {
            'semester_id': self.semester.pk,
            'semester_updated_at': stale_stamp.isoformat(),
            'entries': [{'conflict_id': self.conflict.pk, 'status': Conflict.APPROVED, 'note': ''}],
        }

        response, envelope = _post_json(self, _save_url(self.rehearsal.pk), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        self.conflict.refresh_from_db()
        self.assertEqual(self.conflict.status, Conflict.PENDING)

    def test_unknown_conflict_id_save_is_refused(self):
        """A Conflict id naming one that doesn't exist at all is refused, not a 500."""
        stale_conflict_id = self.conflict.pk + 100000
        body = _valid_body(self.semester, entries=[
            {'conflict_id': stale_conflict_id, 'status': Conflict.APPROVED, 'note': ''},
        ])

        response, envelope = _post_json(self, _save_url(self.rehearsal.pk), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])

    def test_conflict_from_a_different_rehearsal_save_is_refused(self):
        """A Conflict id belonging to a different Rehearsal is refused — user story 41."""
        other_rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)
        foreign_conflict = ConflictFactory(rehearsal=other_rehearsal, status=Conflict.PENDING)
        body = _valid_body(self.semester, entries=[
            {'conflict_id': foreign_conflict.pk, 'status': Conflict.APPROVED, 'note': ''},
        ])

        response, envelope = _post_json(self, _save_url(self.rehearsal.pk), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        foreign_conflict.refresh_from_db()
        self.assertEqual(foreign_conflict.status, Conflict.PENDING)

    def test_over_long_note_save_is_refused_preserving_every_other_row(self):
        """An over-long note on one row is refused with a per-row error, applying nothing — user story 42.

        Mirrors `RosterSaveApiView`'s validation-failure shape exactly:
        `values` is `None` on Save (unlike Preview, which echoes
        `raw_body`) — the "preserve every other row" guarantee lives in
        `errors` only naming the row that actually failed, so a client
        renders the second row's verdict/note as still valid instead of
        wiping the whole form.
        """
        second_conflict = ConflictFactory(rehearsal=self.rehearsal, status=Conflict.PENDING)
        body = _valid_body(self.semester, entries=[
            {'conflict_id': self.conflict.pk, 'status': Conflict.APPROVED, 'note': 'x' * 256},
            {'conflict_id': second_conflict.pk, 'status': Conflict.REJECTED, 'note': 'a fine, short note'},
        ])

        response, envelope = _post_json(self, _save_url(self.rehearsal.pk), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertIsNone(envelope['values'])
        self.assertIn(f'conflict-{self.conflict.pk}', envelope['errors'])
        self.assertNotIn(f'conflict-{second_conflict.pk}', envelope['errors'])
        self.conflict.refresh_from_db()
        second_conflict.refresh_from_db()
        self.assertEqual(self.conflict.status, Conflict.PENDING)
        self.assertEqual(second_conflict.status, Conflict.PENDING)


@override_settings(SECURE_SSL_REDIRECT=False)
class BufferIdentityTests(TestCase):
    """`build_adjudication_buffer_from_request()` is the ONE construction path Preview and Save both call (issue #340, ADR 0008)."""

    def setUp(self):
        """Log in a synthetic admin against a fresh Semester with one future Rehearsal and one Conflict."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)
        self.conflict = ConflictFactory(rehearsal=self.rehearsal, status=Conflict.PENDING)

    def test_valid_body_builds_an_identical_buffer_every_time(self):
        """A well-formed body builds byte-for-byte identical (frozen-dataclass-equal) Buffers on repeated calls."""
        body = _valid_body(self.semester, entries=[
            {'conflict_id': self.conflict.pk, 'status': Conflict.APPROVED, 'note': 'n'},
        ])

        first = build_adjudication_buffer_from_request(_fake_request(body), rehearsal_id=self.rehearsal.pk)
        second = build_adjudication_buffer_from_request(_fake_request(body), rehearsal_id=self.rehearsal.pk)

        self.assertEqual(first, second)

    def test_per_field_validation_failure_raises_the_same_shape_every_time(self):
        """A body with a per-field failure (bad status) raises the identical row_errors/non_field_errors every time."""
        body = _valid_body(self.semester, entries=[
            {'conflict_id': self.conflict.pk, 'status': 'not-a-real-status', 'note': ''},
        ])

        with self.assertRaises(AdjudicationBufferValidationError) as first_capture:
            build_adjudication_buffer_from_request(_fake_request(body), rehearsal_id=self.rehearsal.pk)
        with self.assertRaises(AdjudicationBufferValidationError) as second_capture:
            build_adjudication_buffer_from_request(_fake_request(body), rehearsal_id=self.rehearsal.pk)

        self.assertEqual(first_capture.exception.row_errors, second_capture.exception.row_errors)
        self.assertEqual(first_capture.exception.non_field_errors, second_capture.exception.non_field_errors)

    def test_invalid_body_fails_both_live_endpoints_with_the_identical_row_errors(self):
        """Driving Preview and Save with the identical invalid body proves neither reimplements construction."""
        body = _valid_body(self.semester, entries=[
            {'conflict_id': self.conflict.pk, 'status': 'not-a-real-status', 'note': ''},
        ])

        preview_response, preview_envelope = _post_json(self, _preview_url(self.rehearsal.pk), body)
        save_response, save_envelope = _post_json(self, _save_url(self.rehearsal.pk), body)

        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(save_response.status_code, 200)
        self.assertFalse(preview_envelope['ok'])
        self.assertFalse(save_envelope['ok'])
        self.assertEqual(preview_envelope['errors'], save_envelope['errors'])
