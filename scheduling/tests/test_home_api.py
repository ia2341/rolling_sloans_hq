"""`GET /api/` — Home's Next-rehearsal, Upcoming-rehearsals, Song-progress and setup-checklist read model (issue #332).

Follows `test_schedule_api.py`'s shape: serializer exact-key-set tests pin
the wire shape, view tests cover the envelope/status codes and the
setup-checklist's admin/draft/not-all-done gating, and a privacy test
confirms no Conflict data ever reaches this payload (ADR 0005).
"""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    RehearsalFactory,
    RehearsalPatternFactory,
    RehearsalSongFactory,
    RehearsalTimeFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.serializers import serialize_home

PASSWORD = 'a-strong-test-password-123'


class _RequestStub:
    """A minimal stand-in for `request.user`/`request.session` so `serialize_home()` can be unit-tested without the test client."""

    def __init__(self, person, *, session=None):
        """Stash `person` as `.user` and `session` (a plain dict, supporting `.pop()`) as `.session`."""
        self.user = person
        self.session = {} if session is None else session


class SerializeHomeExactKeySetTests(TestCase):
    """`serialize_home()` names every key it emits, and no more — the enforcement for the no-`asdict()` rule."""

    def test_no_semester_yields_the_empty_shape(self):
        """`None` (no Semester at all) still returns the documented top-level keys, empty rather than absent."""
        person = PersonFactory()

        data = serialize_home(_RequestStub(person), None)

        self.assertEqual(
            set(data.keys()),
            {'semester_name', 'next_rehearsal', 'upcoming_rehearsals', 'song_progress', 'setup_checklist', 'just_created'},
        )
        self.assertIsNone(data['next_rehearsal'])
        self.assertEqual(data['upcoming_rehearsals'], [])
        self.assertEqual(data['song_progress'], [])
        self.assertIsNone(data['setup_checklist'])

    def test_top_level_keys(self):
        """A live Semester with a Rehearsal and a Song returns exactly the documented top-level keys."""
        person = PersonFactory()
        rehearsal = RehearsalFactory(date=timezone.localdate() + timedelta(days=1))
        SongFactory(semester=rehearsal.semester)

        data = serialize_home(_RequestStub(person), rehearsal.semester)

        self.assertEqual(
            set(data.keys()),
            {'semester_name', 'next_rehearsal', 'upcoming_rehearsals', 'song_progress', 'setup_checklist', 'just_created'},
        )

    def test_next_rehearsal_keys(self):
        """The Next-rehearsal card carries exactly its documented keys."""
        person = PersonFactory()
        role = RoleFactory()
        rehearsal = RehearsalFactory(date=timezone.localdate() + timedelta(days=1))
        song = SongFactory(semester=rehearsal.semester)
        RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        SongRoleAssignmentFactory(song=song, role=role, person=person)

        data = serialize_home(_RequestStub(person), rehearsal.semester)

        self.assertEqual(
            set(data['next_rehearsal'].keys()),
            {'rehearsal_id', 'date', 'is_dress', 'arrival_time', 'departure_time', 'timeline'},
        )
        self.assertEqual(
            set(data['next_rehearsal']['timeline'].keys()),
            {
                'slots', 'window_start', 'window_end', 'viewer_song_count',
                'total_song_count', 'viewer_start_time', 'viewer_end_time', 'is_dress_rehearsal',
            },
        )

    def test_upcoming_row_keys(self):
        """An Upcoming-rehearsals row carries exactly its documented keys."""
        person = PersonFactory()
        rehearsal = RehearsalFactory(date=timezone.localdate() + timedelta(days=1))

        data = serialize_home(_RequestStub(person), rehearsal.semester)

        row = data['upcoming_rehearsals'][0]
        self.assertEqual(
            set(row.keys()),
            {'id', 'date', 'start_time', 'end_time', 'is_dress', 'is_past', 'your_window'},
        )

    def test_song_progress_row_keys(self):
        """A Song-progress row carries exactly its documented keys."""
        person = PersonFactory()
        semester = SemesterFactory()
        SongFactory(semester=semester)

        data = serialize_home(_RequestStub(person), semester)

        row = data['song_progress'][0]
        self.assertEqual(
            set(row.keys()),
            {'id', 'title', 'artist', 'length', 'position', 'completed', 'total', 'has_assignment'},
        )

    def test_setup_checklist_item_keys(self):
        """A setup-checklist item carries exactly its documented keys."""
        admin = PersonFactory(is_admin=True)
        semester = SemesterFactory(draft=True)

        data = serialize_home(_RequestStub(admin), semester)

        item = data['setup_checklist']['items'][0]
        self.assertEqual(
            set(item.keys()),
            {'key', 'label', 'is_done', 'status', 'destination', 'waiting_on'},
        )

    def test_no_checklist_for_a_member(self):
        """A member's payload carries no setup-checklist block, even on a draft Semester with everything empty."""
        person = PersonFactory()
        semester = SemesterFactory(draft=True)

        data = serialize_home(_RequestStub(person), semester)

        self.assertIsNone(data['setup_checklist'])

    def test_no_checklist_on_a_live_semester(self):
        """An admin viewing the Live Semester (not a draft) gets no setup-checklist block, however empty it is."""
        admin = PersonFactory(is_admin=True)
        semester = SemesterFactory()

        data = serialize_home(_RequestStub(admin), semester)

        self.assertIsNone(data['setup_checklist'])

    def test_just_created_true_exactly_once(self):
        """`just_created` is true on the first read after the marker is set, then false on the next (the pop consumes it)."""
        admin = PersonFactory(is_admin=True)
        semester = SemesterFactory(draft=True)
        session = {'just_created_semester_id': semester.pk}
        request = _RequestStub(admin, session=session)

        first = serialize_home(request, semester)
        second = serialize_home(request, semester)

        self.assertTrue(first['just_created'])
        self.assertFalse(second['just_created'])

    def test_just_created_false_for_a_member_even_with_the_marker_set(self):
        """A member never sees `just_created`, even if the session marker names their viewing Semester."""
        person = PersonFactory()
        semester = SemesterFactory(draft=True)
        request = _RequestStub(person, session={'just_created_semester_id': semester.pk})

        data = serialize_home(request, semester)

        self.assertFalse(data['just_created'])

    def test_no_checklist_once_everything_is_done(self):
        """A draft Semester with every item done omits the checklist block entirely, rather than an empty items list."""
        admin = PersonFactory(is_admin=True)
        semester = SemesterFactory(draft=True)
        MembershipFactory(semester=semester)
        song = SongFactory(semester=semester)
        role = RoleFactory()
        SongRoleAssignmentFactory(song=song, role=role)
        pattern = RehearsalPatternFactory(semester=semester)
        RehearsalTimeFactory(pattern=pattern)
        RehearsalFactory(semester=semester)

        data = serialize_home(_RequestStub(admin), semester)

        self.assertIsNone(data['setup_checklist'])


@override_settings(SECURE_SSL_REDIRECT=False)
class HomeApiViewTests(TestCase):
    """`GET /api/` (issue #332)."""

    def setUp(self):
        """Log in as an ordinary member before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_anonymous_request_401s_not_302s(self):
        """An anonymous request 401s outright, never a redirect (issue #326)."""
        self.client.logout()

        response = self.client.get('/api/')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_envelope_carries_context_and_data(self):
        """A successful response carries both the `context` block and the Home `data`."""
        SemesterFactory()

        response = self.client.get('/api/')

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn('context', body)
        self.assertIn('data', body)

    def test_no_published_semester_returns_the_empty_shape(self):
        """With nothing published, a member gets the documented empty shape, not an error."""
        response = self.client.get('/api/')

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['data']['next_rehearsal'])

    def test_viewer_not_needed_at_the_next_rehearsal_gets_the_explicit_state(self):
        """A viewer on no Song at the band's literal next Rehearsal gets `next_rehearsal: None`, not an empty timeline."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=1))

        response = self.client.get('/api/')

        self.assertIsNone(response.json()['data']['next_rehearsal'])

    def test_dress_rehearsal_renders_the_whole_window_for_every_viewer(self):
        """The Dress Rehearsal variant reports the whole window for a viewer holding no Role Assignment (ADR 0003, 0006)."""
        semester = SemesterFactory()
        dress = RehearsalFactory(semester=semester, is_full_setlist=True, date=timezone.localdate() + timedelta(days=1))

        response = self.client.get('/api/')

        card = response.json()['data']['next_rehearsal']
        self.assertEqual(card['rehearsal_id'], dress.pk)
        self.assertTrue(card['is_dress'])
        self.assertEqual(card['arrival_time'], dress.start_time.isoformat())
        self.assertEqual(card['departure_time'], dress.end_time.isoformat())

    def test_slot_times_match_the_persisted_rehearsal_song_and_ignore_length(self):
        """Timeline slot times match `RehearsalSong.start_time`/`end_time`, regardless of the Song's `length` (regression guard)."""
        semester = SemesterFactory()
        role = RoleFactory()
        rehearsal = RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=1))
        song = SongFactory(semester=semester, length=timedelta(hours=2))
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        SongRoleAssignmentFactory(song=song, role=role, person=self.person)

        response = self.client.get('/api/')

        slot = response.json()['data']['next_rehearsal']['timeline']['slots'][0]
        self.assertEqual(slot['start_time'], rehearsal_song.start_time.isoformat())
        self.assertEqual(slot['end_time'], rehearsal_song.end_time.isoformat())

    def test_upcoming_list_is_exactly_four_rows_in_date_order(self):
        """The upcoming list is capped at four rows, in date order."""
        semester = SemesterFactory()
        for offset in range(1, 6):
            RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=offset))

        response = self.client.get('/api/')

        rows = response.json()['data']['upcoming_rehearsals']
        self.assertEqual(len(rows), 4)
        self.assertEqual([row['date'] for row in rows], sorted(row['date'] for row in rows))

    def test_upcoming_list_marks_the_dress_rehearsal(self):
        """The Dress Rehearsal's upcoming row reports `is_dress=True`."""
        semester = SemesterFactory()
        dress = RehearsalFactory(semester=semester, is_full_setlist=True, date=timezone.localdate() + timedelta(days=1))

        response = self.client.get('/api/')

        row = next(row for row in response.json()['data']['upcoming_rehearsals'] if row['id'] == dress.pk)
        self.assertTrue(row['is_dress'])

    def test_upcoming_row_reports_not_needed_as_a_null_window(self):
        """A viewer not needed at an upcoming Rehearsal gets `your_window: null`."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=1))

        response = self.client.get('/api/')

        row = response.json()['data']['upcoming_rehearsals'][0]
        self.assertIsNone(row['your_window'])

    def test_song_progress_rows_carry_completed_and_total(self):
        """Song-progress rows carry `completed`/`total` matching the RehearsalSong counts."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        past_rehearsal = RehearsalFactory(semester=semester, date=timezone.localdate() - timedelta(days=1))
        RehearsalSongFactory(rehearsal=past_rehearsal, song=song, order=1)

        response = self.client.get('/api/')

        row = next(row for row in response.json()['data']['song_progress'] if row['id'] == song.pk)
        self.assertEqual(row['completed'], 1)
        self.assertEqual(row['total'], 1)

    def test_song_progress_has_assignment_true_regardless_of_role_mismatch(self):
        """`has_assignment` is true for a Song the viewer is assigned to, even when `is_role_mismatch` (ADR 0002)."""
        semester = SemesterFactory()
        role = RoleFactory()
        song = SongFactory(semester=semester)
        SongRoleAssignmentFactory(song=song, role=role, person=self.person)

        response = self.client.get('/api/')

        row = next(row for row in response.json()['data']['song_progress'] if row['id'] == song.pk)
        self.assertTrue(row['has_assignment'])

    def test_no_songs_yet_is_an_explicit_empty_list(self):
        """A Semester with no Songs returns an explicit empty `song_progress` list."""
        SemesterFactory()

        response = self.client.get('/api/')

        self.assertEqual(response.json()['data']['song_progress'], [])

    def test_admin_with_an_empty_draft_semester_sees_the_checklist(self):
        """An admin viewing an empty draft Semester gets the setup-checklist block."""
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=admin.email, password=PASSWORD)
        SemesterFactory(draft=True)

        response = self.client.get('/api/')

        self.assertIsNotNone(response.json()['data']['setup_checklist'])

    def test_member_never_sees_the_checklist(self):
        """A member never sees the setup-checklist block, even on a draft Semester."""
        SemesterFactory(draft=True)

        response = self.client.get('/api/')

        self.assertIsNone(response.json()['data']['setup_checklist'])

    def test_just_created_fires_once_after_creating_a_semester(self):
        """`POST /api/semesters/create/` then `GET /api/` reports `just_created=True` once, then `False` after."""
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=admin.email, password=PASSWORD)

        create_response = self.client.post(
            '/api/semesters/create/',
            data={
                'name': 'A Brand New Semester',
                'default_rehearsal_duration_minutes': 120,
                'default_setup_grace_minutes': 15,
                'default_teardown_grace_minutes': 15,
                'default_song_slot_count': 1,
                'default_arrival_buffer_minutes': 10,
                'default_departure_buffer_minutes': 10,
            },
            content_type='application/json',
        )
        self.assertTrue(create_response.json()['ok'])

        first = self.client.get('/api/')
        second = self.client.get('/api/')

        self.assertTrue(first.json()['data']['just_created'])
        self.assertFalse(second.json()['data']['just_created'])


@override_settings(SECURE_SSL_REDIRECT=False)
class ApiPrivacyTests(TestCase):
    """ADR-0005: no Conflict-derived field ever reaches `/api/`'s payload (issue #332)."""

    def test_no_conflict_field_in_the_payload(self):
        """Every top-level and nested key across the payload excludes Conflict's fields — asserted on absent keys."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=1))
        song = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        person = PersonFactory(password=PASSWORD)
        self.client.login(username=person.email, password=PASSWORD)

        response = self.client.get('/api/')

        data = response.json()['data']
        forbidden_keys = {'reason', 'declaration_type', 'status', 'adjudication_note', 'covering_for', 'covering_for_name'}
        row_keys = set(data['upcoming_rehearsals'][0].keys()) if data['upcoming_rehearsals'] else set()
        self.assertEqual(forbidden_keys & row_keys, set())
        if data['next_rehearsal'] is not None:
            self.assertEqual(forbidden_keys & set(data['next_rehearsal'].keys()), set())
