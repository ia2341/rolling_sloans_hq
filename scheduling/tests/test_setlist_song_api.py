"""`/api/setlist/` and `/api/songs/<pk>/` — the SPA's first two read surfaces (issue #330).

#330 is #317's designated pipeline prover, so this module's shape is the
template later read tickets (#331, #332, #333) copy: serializer
exact-key-set tests pin the wire shape, and privacy tests retarget the
`docs/person-page-visibility.md` verdicts (ADR 0005, ADR 0002, ADR 0007) at
JSON bodies instead of HTML.
"""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    BackupFactory,
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.serializers import serialize_setlist, serialize_song

PASSWORD = 'a-strong-test-password-123'


class SerializeSetlistExactKeySetTests(TestCase):
    """`serialize_setlist()` names every key it emits, and no more — the enforcement for the no-`asdict()` rule."""

    def test_top_level_keys(self):
        """The top-level payload carries exactly the five documented keys."""
        semester = SemesterFactory()

        data = serialize_setlist(semester)

        self.assertEqual(
            set(data.keys()),
            {'semester_name', 'song_count', 'total_running_time', 'roles', 'songs'},
        )

    def test_role_legend_entry_keys(self):
        """A `roles` legend entry carries exactly `id`, `name`, `code`."""
        semester = SemesterFactory()
        RoleFactory()

        data = serialize_setlist(semester)

        self.assertEqual(set(data['roles'][0].keys()), {'id', 'name', 'code'})

    def test_song_row_keys(self):
        """A `songs` row carries exactly the documented Setlist row keys."""
        semester = SemesterFactory()
        SongFactory(semester=semester)

        data = serialize_setlist(semester)

        self.assertEqual(
            set(data['songs'][0].keys()),
            {'id', 'title', 'artist', 'length', 'position', 'notes', 'cast', 'recording_count'},
        )

    def test_cast_entry_and_performer_keys(self):
        """A cast entry, and a filled one's performer, carry exactly their documented keys."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        role = RoleFactory()
        SongRoleAssignmentFactory(song=song, role=role)

        data = serialize_setlist(semester)

        cast_entry = data['songs'][0]['cast'][0]
        self.assertEqual(set(cast_entry.keys()), {'role_id', 'role_name', 'code', 'performers'})
        self.assertEqual(set(cast_entry['performers'][0].keys()), {'id', 'name', 'is_role_mismatch'})

    def test_no_semester_yields_the_empty_shape_with_the_same_keys(self):
        """`None` (no Semester at all) still returns the documented top-level keys, empty rather than absent."""
        data = serialize_setlist(None)

        self.assertEqual(
            set(data.keys()),
            {'semester_name', 'song_count', 'total_running_time', 'roles', 'songs'},
        )
        self.assertEqual(data['song_count'], 0)
        self.assertEqual(data['songs'], [])


class SerializeSongExactKeySetTests(TestCase):
    """`serialize_song()` names every key it emits, and no more."""

    def test_member_viewer_keys(self):
        """A member viewer's payload carries exactly the documented keys, with no `next_rehearsal` key at all."""
        song = SongFactory()

        data = serialize_song(song, is_admin=False, next_rehearsal=None)

        self.assertEqual(
            set(data.keys()),
            {'id', 'title', 'artist', 'length', 'position', 'notes', 'cast', 'recording_groups', 'rehearsed_at'},
        )

    def test_admin_viewer_keys_add_next_rehearsal(self):
        """An admin viewer's payload adds exactly one key, `next_rehearsal`, over the member shape."""
        song = SongFactory()
        rehearsal = RehearsalFactory(semester=song.semester)

        data = serialize_song(song, is_admin=True, next_rehearsal=rehearsal)

        self.assertEqual(
            set(data.keys()),
            {
                'id', 'title', 'artist', 'length', 'position', 'notes',
                'cast', 'recording_groups', 'rehearsed_at', 'next_rehearsal',
            },
        )
        self.assertEqual(set(data['next_rehearsal'].keys()), {'id', 'date'})

    def test_recording_group_and_recording_keys(self):
        """A recording group, and its recordings, carry exactly their documented keys."""
        song = SongFactory()
        rehearsal_song = RehearsalSongFactory(song=song, rehearsal=RehearsalFactory(semester=song.semester))
        RecordingFactory(rehearsal_song=rehearsal_song)

        data = serialize_song(song, is_admin=False, next_rehearsal=None)

        group = data['recording_groups'][0]
        self.assertEqual(
            set(group.keys()),
            {'rehearsal_id', 'date', 'start_time', 'end_time', 'take_count', 'recordings'},
        )
        self.assertEqual(set(group['recordings'][0].keys()), {'id', 'uploaded_by_name', 'note', 'playback_url'})

    def test_rehearsed_at_row_keys(self):
        """A `rehearsed_at` row carries exactly its documented keys."""
        song = SongFactory()
        RehearsalSongFactory(song=song, rehearsal=RehearsalFactory(semester=song.semester))

        data = serialize_song(song, is_admin=False, next_rehearsal=None)

        self.assertEqual(
            set(data['rehearsed_at'][0].keys()),
            {'rehearsal_id', 'date', 'is_dress_rehearsal', 'start_time', 'end_time'},
        )


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistApiViewTests(TestCase):
    """`GET /api/setlist/` (issue #330)."""

    def setUp(self):
        """Log in as an ordinary member before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_envelope_carries_context_and_data(self):
        """A successful response carries both the `context` block and the Setlist `data`."""
        SemesterFactory()

        response = self.client.get('/api/setlist/')

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn('context', body)
        self.assertIn('data', body)
        self.assertEqual(body['context']['viewer']['id'], self.person.pk)

    def test_no_published_semester_returns_the_empty_shape(self):
        """With nothing published, a member gets the documented empty Setlist shape, not an error."""
        response = self.client.get('/api/setlist/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['songs'], [])

    def test_songs_are_returned_in_position_order(self):
        """Songs are returned in Semester position order."""
        semester = SemesterFactory()
        second = SongFactory(semester=semester, position=2, title='Second')
        first = SongFactory(semester=semester, position=1, title='First')

        response = self.client.get('/api/setlist/')

        titles = [row['title'] for row in response.json()['data']['songs']]
        self.assertEqual(titles, [first.title, second.title])


@override_settings(SECURE_SSL_REDIRECT=False)
class SongDetailApiViewTests(TestCase):
    """`GET /api/songs/<pk>/` (issue #330)."""

    def setUp(self):
        """Log in as an ordinary member before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_anonymous_request_401s_not_302s(self):
        """An anonymous request to the parameterised Song route still gets the bare 401 (issue #326/#330)."""
        song = SongFactory()
        self.client.logout()

        response = self.client.get(f'/api/songs/{song.pk}/')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_song_in_the_live_semester_returns_200(self):
        """A Song in the Live Semester (the member's viewing Semester) returns 200 with its envelope."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)

        response = self.client.get(f'/api/songs/{song.pk}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['id'], song.pk)

    def test_song_outside_the_viewing_semester_404s(self):
        """A Song from a different Semester than the viewing one 404s (ADR 0001)."""
        other_semester = SemesterFactory()
        SemesterFactory()  # published later, becomes the Live Semester
        song = SongFactory(semester=other_semester)

        response = self.client.get(f'/api/songs/{song.pk}/')

        self.assertEqual(response.status_code, 404)

    def test_unknown_song_id_404s(self):
        """A nonexistent Song id 404s."""
        response = self.client.get('/api/songs/999999/')

        self.assertEqual(response.status_code, 404)

    def test_member_viewer_gets_no_next_rehearsal_key(self):
        """A non-admin viewer's payload carries no `next_rehearsal` key at all."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)

        response = self.client.get(f'/api/songs/{song.pk}/')

        self.assertNotIn('next_rehearsal', response.json()['data'])

    def test_admin_viewer_gets_the_next_rehearsal_pointer(self):
        """An admin viewer's payload carries the next upcoming Rehearsal for the ADR-0009 pointer."""
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=admin.email, password=PASSWORD)
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        upcoming = RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=3))

        response = self.client.get(f'/api/songs/{song.pk}/')

        self.assertEqual(response.json()['data']['next_rehearsal']['id'], upcoming.pk)


@override_settings(SECURE_SSL_REDIRECT=False)
class ApiPrivacyTests(TestCase):
    """`docs/person-page-visibility.md`'s ADR-0005/0002/0007 verdicts, retargeted at the two `/api/` JSON bodies (issue #330)."""

    @classmethod
    def setUpTestData(cls):
        """Build a Semester with a Song a teammate performs on, is mismatched on, and has recorded."""
        cls.viewer = PersonFactory(password=PASSWORD)
        cls.semester = SemesterFactory()
        cls.teammate = PersonFactory(name='Teammate Placeholder')
        cls.song = SongFactory(semester=cls.semester)
        cls.role = RoleFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester)
        cls.rehearsal_song = RehearsalSongFactory(song=cls.song, rehearsal=cls.rehearsal, order=1)
        # No SongRoleRequirement for cls.role, so the assignment below is a mismatch (ADR-0002).
        SongRoleAssignmentFactory(song=cls.song, role=cls.role, person=cls.teammate)

    def setUp(self):
        """Log in as the viewer before each test."""
        self.client.login(username=self.viewer.email, password=PASSWORD)

    def test_setlist_identifies_performers_by_name_never_email(self):
        """The Setlist payload names a teammate performer by `.name`, never carries `Person.email`."""
        response = self.client.get('/api/setlist/')

        body = response.json()
        self.assertIn(self.teammate.name, str(body))
        self.assertNotIn(self.teammate.email, str(body))

    def test_song_detail_identifies_performers_by_name_never_email(self):
        """The Song payload names a teammate performer by `.name`, never carries `Person.email`."""
        response = self.client.get(f'/api/songs/{self.song.pk}/')

        body = response.json()
        self.assertIn(self.teammate.name, str(body))
        self.assertNotIn(self.teammate.email, str(body))

    def test_song_detail_carries_is_role_mismatch_deliberately(self):
        """`is_role_mismatch` IS present on this surface — the deliberate exception to the roster routes' `never`."""
        response = self.client.get(f'/api/songs/{self.song.pk}/')

        data = response.json()['data']
        performer = next(
            performer
            for entry in data['cast']
            for performer in entry['performers']
            if performer['id'] == self.teammate.pk
        )
        self.assertTrue(performer['is_role_mismatch'])

    def test_no_conflict_or_backup_fields_anywhere(self):
        """Neither payload carries any Conflict/ConflictWindow field or any Backup field (ADR 0005, ADR 0007)."""
        BackupFactory(rehearsal_song=self.rehearsal_song, role=self.role, covering_for=self.teammate)

        setlist_data = self.client.get('/api/setlist/').json()['data']
        song_data = self.client.get(f'/api/songs/{self.song.pk}/').json()['data']

        for data in (setlist_data, song_data):
            # `context.pending_conflict_count` legitimately carries "conflict" in its
            # name — the assertion is scoped to `data`, where no Conflict/Backup field
            # of any kind may appear at all (ADR 0005, ADR 0007).
            serialized = str(data)
            self.assertNotIn('covering_for', serialized)
            self.assertNotIn('conflict', serialized.lower())
