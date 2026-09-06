"""`/api/schedule/` and its two Conflict writes — the merged Schedule read surface (issue #331).

Ports `test_schedule_availability.py`'s HTML-era coverage to JSON, following
`test_setlist_song_api.py`'s shape (#330's pipeline-prover template):
serializer exact-key-set tests pin the wire shape, view tests cover the
envelope/status codes, and privacy tests retarget the ADR-0005/0006/0007
verdicts at the JSON body.
"""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    BackupFactory,
    ConflictFactory,
    ConflictWindowFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import Conflict
from scheduling.serializers import serialize_schedule

PASSWORD = 'a-strong-test-password-123'


class _RequestStub:
    """A minimal stand-in for `request.user` so `serialize_schedule()` can be unit-tested without the test client."""

    def __init__(self, person):
        """Stash `person` as `.user`, matching a real `HttpRequest`'s shape enough for the serializer's needs."""
        self.user = person


class SerializeScheduleExactKeySetTests(TestCase):
    """`serialize_schedule()` names every key it emits, and no more — the enforcement for the no-`asdict()` rule."""

    def test_no_semester_yields_the_empty_shape(self):
        """`None` (no Semester at all) still returns the documented top-level keys, empty rather than absent."""
        person = PersonFactory()

        data = serialize_schedule(_RequestStub(person), None)

        self.assertEqual(set(data.keys()), {'semester_name', 'schedule', 'selected'})
        self.assertEqual(data['schedule'], {'past': [], 'future': []})
        self.assertIsNone(data['selected'])

    def test_top_level_keys(self):
        """A Semester with one Rehearsal returns exactly the documented top-level keys."""
        person = PersonFactory()
        rehearsal = RehearsalFactory()
        SongRoleAssignmentFactory(person=person, song=SongFactory(semester=rehearsal.semester))
        RehearsalSongFactory(rehearsal=rehearsal, song=SongFactory(semester=rehearsal.semester))

        data = serialize_schedule(_RequestStub(person), rehearsal.semester)

        self.assertEqual(set(data.keys()), {'semester_name', 'schedule', 'selected'})

    def test_schedule_list_row_keys_for_a_member(self):
        """A member's All-rehearsals list row carries exactly the documented keys, with no `pending_count`."""
        person = PersonFactory()
        rehearsal = RehearsalFactory(date=timezone.localdate() + timedelta(days=1))

        data = serialize_schedule(_RequestStub(person), rehearsal.semester)

        row = data['schedule']['future'][0]
        self.assertEqual(
            set(row.keys()),
            {'id', 'date', 'start_time', 'end_time', 'is_dress', 'is_past', 'song_count', 'your_state'},
        )

    def test_schedule_list_row_keys_for_an_admin_add_pending_count(self):
        """An admin's future-rehearsal row adds exactly one key, `pending_count`, over the member shape."""
        admin = PersonFactory(is_admin=True)
        rehearsal = RehearsalFactory(date=timezone.localdate() + timedelta(days=1))

        data = serialize_schedule(_RequestStub(admin), rehearsal.semester)

        row = data['schedule']['future'][0]
        self.assertEqual(
            set(row.keys()),
            {'id', 'date', 'start_time', 'end_time', 'is_dress', 'is_past', 'song_count', 'your_state', 'pending_count'},
        )

    def test_selected_rehearsal_detail_keys_for_a_member(self):
        """A member's selected-Rehearsal detail carries exactly the documented keys, with no admin-only key."""
        person = PersonFactory()
        rehearsal = RehearsalFactory()

        data = serialize_schedule(_RequestStub(person), rehearsal.semester, rehearsal_id=rehearsal.pk)

        selected = data['selected']
        self.assertEqual(
            set(selected.keys()),
            {
                'id', 'date', 'start_time', 'end_time', 'is_dress', 'is_past',
                'can_edit_assignments', 'timeline', 'availability', 'roles', 'rows',
            },
        )

    def test_availability_block_keys(self):
        """The "Your availability" block carries exactly the documented keys."""
        person = PersonFactory()
        rehearsal = RehearsalFactory()

        data = serialize_schedule(_RequestStub(person), rehearsal.semester, rehearsal_id=rehearsal.pk)

        self.assertEqual(
            set(data['selected']['availability'].keys()),
            {'declaration_type', 'type_label', 'declared_time', 'reason', 'status', 'admin_note', 'is_dress', 'is_editable'},
        )

    def test_timeline_keys(self):
        """The timeline block carries exactly the documented keys."""
        person = PersonFactory()
        rehearsal = RehearsalFactory()

        data = serialize_schedule(_RequestStub(person), rehearsal.semester, rehearsal_id=rehearsal.pk)

        self.assertEqual(
            set(data['selected']['timeline'].keys()),
            {
                'slots', 'window_start', 'window_end', 'viewer_song_count',
                'total_song_count', 'viewer_start_time', 'viewer_end_time', 'is_dress_rehearsal',
            },
        )

    def test_matrix_row_and_cell_and_entry_keys_for_a_member(self):
        """A matrix row/cell/entry carry exactly their documented keys, with no `covering_for_name` for a member."""
        person = PersonFactory()
        rehearsal = RehearsalFactory()
        role = RoleFactory()
        song = SongFactory(semester=rehearsal.semester)
        RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        SongRoleAssignmentFactory(song=song, role=role, person=person)

        data = serialize_schedule(_RequestStub(person), rehearsal.semester, rehearsal_id=rehearsal.pk)

        row = data['selected']['rows'][0]
        self.assertEqual(set(row.keys()), {'song_id', 'song_title', 'start_time', 'cells'})
        cell = row['cells'][0]
        self.assertEqual(set(cell.keys()), {'role_id', 'entries'})
        entry = cell['entries'][0]
        self.assertEqual(set(entry.keys()), {'id', 'kind', 'person_id', 'person_name', 'is_role_mismatch', 'has_conflict'})

    def test_matrix_entry_keys_for_an_admin_add_covering_for_name(self):
        """An admin's matrix entry adds exactly one key, `covering_for_name`, over the member shape."""
        admin = PersonFactory(is_admin=True)
        rehearsal = RehearsalFactory()
        role = RoleFactory()
        song = SongFactory(semester=rehearsal.semester)
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        SongRoleRequirementFactory(song=song, role=role)
        BackupFactory(rehearsal_song=rehearsal_song, role=role)

        data = serialize_schedule(_RequestStub(admin), rehearsal.semester, rehearsal_id=rehearsal.pk)

        row = data['selected']['rows'][0]
        entry = row['cells'][0]['entries'][0]
        self.assertEqual(
            set(entry.keys()),
            {'id', 'kind', 'person_id', 'person_name', 'is_role_mismatch', 'has_conflict', 'covering_for_name'},
        )


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleApiViewTests(TestCase):
    """`GET /api/schedule/` (issue #331)."""

    def setUp(self):
        """Log in as an ordinary member before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_anonymous_request_401s_not_302s(self):
        """An anonymous request 401s outright, never a redirect (issue #326)."""
        self.client.logout()

        response = self.client.get('/api/schedule/')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_envelope_carries_context_and_data(self):
        """A successful response carries both the `context` block and the Schedule `data`."""
        SemesterFactory()

        response = self.client.get('/api/schedule/')

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn('context', body)
        self.assertIn('data', body)

    def test_no_published_semester_returns_the_empty_shape(self):
        """With nothing published, a member gets the documented empty shape, not an error."""
        response = self.client.get('/api/schedule/')

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['data']['selected'])

    def test_rehearsal_outside_the_viewing_semester_404s(self):
        """A `?rehearsal=` id from a different Semester than the viewing one 404s (ADR 0001)."""
        other_semester = SemesterFactory()
        SemesterFactory()  # published later, becomes the Live Semester
        rehearsal = RehearsalFactory(semester=other_semester)

        response = self.client.get(f'/api/schedule/?rehearsal={rehearsal.pk}')

        self.assertEqual(response.status_code, 404)

    def test_non_numeric_rehearsal_id_404s(self):
        """A non-numeric `?rehearsal=` value 404s rather than 500ing."""
        SemesterFactory()

        response = self.client.get('/api/schedule/?rehearsal=not-a-number')

        self.assertEqual(response.status_code, 404)

    def test_landing_rehearsal_is_selected_with_no_rehearsal_param(self):
        """With no `?rehearsal=`, the viewer's landing Rehearsal is selected."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=1))
        song = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=rehearsal, song=song)
        SongRoleAssignmentFactory(song=song, person=self.person)

        response = self.client.get('/api/schedule/')

        self.assertEqual(response.json()['data']['selected']['id'], rehearsal.pk)

    def test_dress_rehearsal_availability_is_locked_and_mandatory(self):
        """The Dress Rehearsal's availability block reports `is_dress=True` and no declare control is implied by `is_editable=False`."""
        semester = SemesterFactory()
        dress = RehearsalFactory(semester=semester, is_full_setlist=True, date=timezone.localdate() + timedelta(days=1))

        response = self.client.get(f'/api/schedule/?rehearsal={dress.pk}')

        availability = response.json()['data']['selected']['availability']
        self.assertTrue(availability['is_dress'])
        self.assertFalse(availability['is_editable'])

    def test_past_rehearsal_availability_is_not_editable(self):
        """A past Rehearsal's availability block reports `is_editable=False`."""
        semester = SemesterFactory()
        past = RehearsalFactory(semester=semester, date=timezone.localdate() - timedelta(days=1))

        response = self.client.get(f'/api/schedule/?rehearsal={past.pk}')

        self.assertFalse(response.json()['data']['selected']['availability']['is_editable'])

    def test_pending_declaration_status(self):
        """A pending declaration's availability block reports `status='pending'`."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=1))
        ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT, status=Conflict.PENDING)

        response = self.client.get(f'/api/schedule/?rehearsal={rehearsal.pk}')

        availability = response.json()['data']['selected']['availability']
        self.assertEqual(availability['status'], 'pending')
        self.assertEqual(availability['declaration_type'], 'full_absence')

    def test_approved_declaration_with_admin_note_is_visible_to_its_owner(self):
        """An approved declaration's admin note IS visible on the owner's own row (ADR 0005's one exception)."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=1))
        ConflictFactory(
            person=self.person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT,
            status=Conflict.APPROVED, adjudication_note='Noted.',
        )

        response = self.client.get(f'/api/schedule/?rehearsal={rehearsal.pk}')

        availability = response.json()['data']['selected']['availability']
        self.assertEqual(availability['status'], 'approved')
        self.assertEqual(availability['admin_note'], 'Noted.')

    def test_rejected_declaration_status(self):
        """A rejected declaration's availability block reports `status='rejected'`."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=1))
        ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT, status=Conflict.REJECTED)

        response = self.client.get(f'/api/schedule/?rehearsal={rehearsal.pk}')

        self.assertEqual(response.json()['data']['selected']['availability']['status'], 'rejected')

    def test_all_rehearsals_dress_row_reads_mandatory(self):
        """The Dress Rehearsal's list row reports `your_state.kind == 'mandatory'`, never 'not_needed'."""
        semester = SemesterFactory()
        dress = RehearsalFactory(semester=semester, is_full_setlist=True, date=timezone.localdate() + timedelta(days=1))

        response = self.client.get('/api/schedule/')

        row = next(row for row in response.json()['data']['schedule']['future'] if row['id'] == dress.pk)
        self.assertEqual(row['your_state']['kind'], 'mandatory')

    def test_all_rehearsals_past_rows_are_flagged_past(self):
        """A past Rehearsal's list row reports `is_past=True`."""
        semester = SemesterFactory()
        past = RehearsalFactory(semester=semester, date=timezone.localdate() - timedelta(days=1))

        response = self.client.get('/api/schedule/')

        row = next(row for row in response.json()['data']['schedule']['past'] if row['id'] == past.pk)
        self.assertTrue(row['is_past'])

    def test_no_admin_pending_count_for_a_member(self):
        """A member's list row carries no `pending_count` key at all."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=1))

        response = self.client.get('/api/schedule/')

        row = response.json()['data']['schedule']['future'][0]
        self.assertNotIn('pending_count', row)

    def test_admin_pending_count_counts_only_pending(self):
        """An admin's list row's `pending_count` counts only PENDING Conflicts, never approved/rejected ones."""
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=admin.email, password=PASSWORD)
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=1))
        ConflictFactory(rehearsal=rehearsal, status=Conflict.PENDING)
        ConflictFactory(rehearsal=rehearsal, status=Conflict.APPROVED)

        response = self.client.get('/api/schedule/')

        row = next(row for row in response.json()['data']['schedule']['future'] if row['id'] == rehearsal.pk)
        self.assertEqual(row['pending_count'], 1)


@override_settings(SECURE_SSL_REDIRECT=False)
class ConflictDeclareApiViewTests(TestCase):
    """`POST /api/schedule/<rehearsal_id>/conflict/` (issue #331)."""

    def setUp(self):
        """Log in as an ordinary member before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def _post(self, rehearsal_id, payload):
        """POST `payload` as JSON to the declare endpoint for `rehearsal_id`."""
        return self.client.post(
            f'/api/schedule/{rehearsal_id}/conflict/', data=payload, content_type='application/json',
        )

    def test_anonymous_request_401s(self):
        """An anonymous request 401s."""
        rehearsal = RehearsalFactory(date=timezone.localdate() + timedelta(days=1))
        self.client.logout()

        response = self._post(rehearsal.pk, {'declaration_type': 'full_absence', 'reason': ''})

        self.assertEqual(response.status_code, 401)

    def test_full_absence_declares_a_conflict(self):
        """A valid `full_absence` declaration creates a FULL_CONFLICT Conflict and returns ok."""
        rehearsal = RehearsalFactory(date=timezone.localdate() + timedelta(days=1))

        response = self._post(rehearsal.pk, {'declaration_type': 'full_absence', 'reason': 'Test reason.'})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['data']['declaration_type'], 'full_absence')
        self.assertTrue(Conflict.objects.filter(person=self.person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT).exists())

    def test_late_arrival_requires_a_time_within_the_window(self):
        """A `late_arrival` declaration with no time comes back with a per-field error at HTTP 200, writing nothing."""
        rehearsal = RehearsalFactory(date=timezone.localdate() + timedelta(days=1))

        response = self._post(rehearsal.pk, {'declaration_type': 'late_arrival', 'reason': 'Stuck in traffic.'})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['ok'])
        self.assertIn('arrival_time', body['errors'])
        self.assertFalse(Conflict.objects.filter(person=self.person, rehearsal=rehearsal).exists())

    def test_editing_a_declaration_replaces_it_and_resets_adjudication(self):
        """Re-declaring against the same Rehearsal edits the existing Conflict in place, resetting its verdict to pending."""
        rehearsal = RehearsalFactory(date=timezone.localdate() + timedelta(days=1))
        ConflictFactory(
            person=self.person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT,
            status=Conflict.APPROVED, adjudication_note='Old note.',
        )

        response = self._post(rehearsal.pk, {'declaration_type': 'full_absence', 'reason': 'Changed my mind.'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Conflict.objects.filter(person=self.person, rehearsal=rehearsal).count(), 1)
        conflict = Conflict.objects.get(person=self.person, rehearsal=rehearsal)
        self.assertEqual(conflict.status, Conflict.PENDING)
        self.assertEqual(conflict.adjudication_note, '')

    def test_dress_rehearsal_declaration_404s_not_500s(self):
        """Declaring against the Dress Rehearsal 404s (via `future_rehearsals_for()`), never reaching a 500 (ADR 0006)."""
        dress = RehearsalFactory(is_full_setlist=True, date=timezone.localdate() + timedelta(days=1))

        response = self._post(dress.pk, {'declaration_type': 'full_absence', 'reason': ''})

        self.assertEqual(response.status_code, 404)

    def test_past_rehearsal_declaration_404s(self):
        """Declaring against a past Rehearsal 404s."""
        past = RehearsalFactory(date=timezone.localdate() - timedelta(days=1))

        response = self._post(past.pk, {'declaration_type': 'full_absence', 'reason': ''})

        self.assertEqual(response.status_code, 404)

    def test_rehearsal_outside_the_viewing_semester_404s(self):
        """Declaring against a Rehearsal from a non-viewing Semester 404s."""
        other_semester = SemesterFactory()
        SemesterFactory()  # published later, becomes the Live Semester
        rehearsal = RehearsalFactory(semester=other_semester, date=timezone.localdate() + timedelta(days=1))

        response = self._post(rehearsal.pk, {'declaration_type': 'full_absence', 'reason': ''})

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class ConflictWithdrawApiViewTests(TestCase):
    """`POST /api/schedule/<rehearsal_id>/conflict/withdraw/` (issue #331)."""

    def setUp(self):
        """Log in as an ordinary member before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_withdraws_the_viewers_own_conflict(self):
        """A future Conflict is deleted, cascading its ConflictWindows."""
        rehearsal = RehearsalFactory(date=timezone.localdate() + timedelta(days=1))
        conflict = ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=conflict)

        response = self.client.post(f'/api/schedule/{rehearsal.pk}/conflict/withdraw/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertFalse(Conflict.objects.filter(pk=conflict.pk).exists())

    def test_past_rehearsal_withdrawal_404s(self):
        """Withdrawing a Conflict on a now-past Rehearsal 404s."""
        past = RehearsalFactory(date=timezone.localdate() - timedelta(days=1))
        ConflictFactory(person=self.person, rehearsal=past, type=Conflict.FULL_CONFLICT)

        response = self.client.post(f'/api/schedule/{past.pk}/conflict/withdraw/')

        self.assertEqual(response.status_code, 404)

    def test_no_existing_conflict_404s(self):
        """Withdrawing when there's nothing declared 404s."""
        rehearsal = RehearsalFactory(date=timezone.localdate() + timedelta(days=1))

        response = self.client.post(f'/api/schedule/{rehearsal.pk}/conflict/withdraw/')

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class OldConflictsRouteRemovalTests(TestCase):
    """The Conflicts page is gone outright, with no redirect (issue #190) — no `/me/conflicts/`-shaped API route exists."""

    def setUp(self):
        """Log in as an ordinary member before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_no_me_conflicts_api_route(self):
        """`/api/me/conflicts/` is not a real route — it 404s through the terminal catch-all."""
        response = self.client.get('/api/me/conflicts/')

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class ApiPrivacyTests(TestCase):
    """ADR-0005/0007 verdicts, retargeted at `/api/schedule/`'s JSON body (issue #331)."""

    @classmethod
    def setUpTestData(cls):
        """Build a Semester with a Rehearsal, a teammate Conflict, and a Backup covering for someone."""
        cls.viewer = PersonFactory(password=PASSWORD)
        cls.semester = SemesterFactory()
        cls.teammate = PersonFactory(name='Teammate Placeholder')
        cls.covered = PersonFactory(name='Covered Placeholder')
        cls.role = RoleFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, date=timezone.localdate() + timedelta(days=1))
        cls.song = SongFactory(semester=cls.semester)
        cls.rehearsal_song = RehearsalSongFactory(rehearsal=cls.rehearsal, song=cls.song, order=1)
        SongRoleAssignmentFactory(song=cls.song, role=cls.role, person=cls.teammate)
        cls.teammate_conflict = ConflictFactory(
            person=cls.teammate, rehearsal=cls.rehearsal, type=Conflict.FULL_CONFLICT, reason='Private reason.',
        )
        cls.backup = BackupFactory(rehearsal_song=cls.rehearsal_song, role=cls.role, covering_for=cls.covered)

    def setUp(self):
        """Log in as the viewer before each test."""
        self.client.login(username=self.viewer.email, password=PASSWORD)

    def test_teammate_conflict_renders_a_marker_and_never_a_reason_or_status(self):
        """A teammate's Conflict never reaches the payload beyond a `has_conflict` marker on their matrix entry."""
        response = self.client.get(f'/api/schedule/?rehearsal={self.rehearsal.pk}')

        data = response.json()['data']
        entries = [entry for row in data['selected']['rows'] for cell in row['cells'] for entry in cell['entries']]
        teammate_entry = next(entry for entry in entries if entry['person_id'] == self.teammate.pk)
        self.assertTrue(teammate_entry['has_conflict'])
        serialized = str(data)
        self.assertNotIn('Private reason.', serialized)
        self.assertNotIn(self.teammate.email, serialized)

    def test_covering_for_is_absent_for_a_member(self):
        """`covering_for_name` is absent (not null) on a member's matrix entries, per ADR 0007."""
        response = self.client.get(f'/api/schedule/?rehearsal={self.rehearsal.pk}')

        data = response.json()['data']
        entries = [entry for row in data['selected']['rows'] for cell in row['cells'] for entry in cell['entries']]
        backup_entry = next(entry for entry in entries if entry['kind'] == 'backup')
        self.assertNotIn('covering_for_name', backup_entry)

    def test_covering_for_is_present_for_an_admin(self):
        """`covering_for_name` IS present for an admin viewer, naming the covered Person (ADR 0007)."""
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=admin.email, password=PASSWORD)

        response = self.client.get(f'/api/schedule/?rehearsal={self.rehearsal.pk}')

        data = response.json()['data']
        entries = [entry for row in data['selected']['rows'] for cell in row['cells'] for entry in cell['entries']]
        backup_entry = next(entry for entry in entries if entry['kind'] == 'backup')
        self.assertEqual(backup_entry['covering_for_name'], self.covered.name)

    def test_admin_viewing_own_availability_only_sees_their_own(self):
        """An admin viewer's own availability block still carries only their own Conflict, never the teammate's."""
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=admin.email, password=PASSWORD)

        response = self.client.get(f'/api/schedule/?rehearsal={self.rehearsal.pk}')

        availability = response.json()['data']['selected']['availability']
        self.assertIsNone(availability['declaration_type'])
