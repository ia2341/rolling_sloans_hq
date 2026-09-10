"""Executable counterpart to `docs/person-page-visibility.md` (issue #316), retargeted at `/api/` payloads (issue #333).

This module was written to survive exactly this migration — its own
original docstring said so. `/members/` and `/members/<pk>/` are gone from
this repo's server-rendered surface in favor of `/api/members/` and
`/api/members/<pk>/` (`BandApiView`/`PersonApiView`); this module now plants
the same distinctive placeholder strings in factory-built fixtures and
asserts they never reach the JSON body, for all three viewer states:
teammate, self, and admin-viewing-a-teammate.

Per the doc's "absent, not null" contract, every negative assertion here is
`assertNotIn(key, payload)` against a dict, never `assertIsNone`: a key
present with `null` still discloses that the field exists and is empty for
this viewer, which is exactly the kind of disclosure ADR 0005 exists to
prevent.
"""

from datetime import time, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    BackupFactory,
    ConflictFactory,
    ConflictWindowFactory,
    MembershipFactory,
    PersonRoleFactory,
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Conflict

PASSWORD = 'a-strong-test-password-123'


def band_api_url():
    """Return `/api/members/`."""
    return reverse('api-members')


def person_api_url(person):
    """Return `/api/members/<pk>/` for `person`."""
    return reverse('api-member-detail', args=[person.pk])


@override_settings(SECURE_SSL_REDIRECT=False)
class BandApiPrivacyTests(TestCase):
    """`/api/members/` verdicts: `is_role_mismatch`, `Conflict`/`ConflictWindow`, a remove control, and `email`.

    All `never`, for a Teammate and for Self alike, per the Roster table in
    `docs/person-page-visibility.md` — ADR 0005's boundary is drawn around
    the surface, not the viewer.
    """

    @classmethod
    def setUpTestData(cls):
        """Build a viewer and a teammate, both rostered (and active) on the viewing Semester."""
        cls.semester = SemesterFactory()
        cls.viewer = PersonFactory(password=PASSWORD, name='Viewer Placeholder')
        cls.viewer_membership = MembershipFactory(person=cls.viewer, semester=cls.semester)
        cls.teammate = PersonFactory(password=PASSWORD, name='Teammate Placeholder')
        cls.teammate_membership = MembershipFactory(person=cls.teammate, semester=cls.semester)

    def setUp(self):
        """Log in as the viewer before each test."""
        self.client.login(username=self.viewer.email, password=PASSWORD)

    def _assign_mismatched_song(self, person, role_name):
        """Assign `person` to a fresh Semester Song under an undeclared Role, so is_role_mismatch is True."""
        song = SongFactory(semester=self.semester, title='Song M')
        assignment = SongRoleAssignmentFactory(song=song, person=person, role=RoleFactory(name=role_name))
        self.assertTrue(assignment.is_role_mismatch)
        return assignment

    def test_role_mismatch_is_never_a_key_for_a_teammate_or_self(self):
        """A row's `song_count` reflects a mismatched assignment, but `is_role_mismatch` never appears as a key."""
        self._assign_mismatched_song(self.teammate, 'Undeclared Role A')
        self._assign_mismatched_song(self.viewer, 'Undeclared Role B')

        response = self.client.get(band_api_url())

        body = response.json()
        self.assertEqual(response.status_code, 200)
        for row in body['data']['members']:
            self.assertEqual(row['song_count'], 1)
            self.assertNotIn('is_role_mismatch', row)
        self.assertNotIn('is_role_mismatch', str(body))

    def test_conflict_data_never_reaches_the_roster_payload(self):
        """ADR 0005's boundary is drawn around the surface, not the viewer: no Conflict field reaches the roster."""
        for person in (self.teammate, self.viewer):
            conflict = ConflictFactory(
                person=person,
                rehearsal=RehearsalFactory(semester=self.semester),
                type=Conflict.PARTIAL,
                reason='A distinctive placeholder reason',
            )
            ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 15), unavailable_end=time(18, 45))

        response = self.client.get(band_api_url())

        body_text = str(response.json())
        self.assertNotIn('A distinctive placeholder reason', body_text)
        self.assertNotIn('18:15', body_text)

    def test_no_remove_control_related_key_for_a_non_admin(self):
        """The Roster editor's remove control is admin-edit-mode-only (#336); a non-admin's read payload has none."""
        response = self.client.get(band_api_url())

        body = response.json()
        for row in body['data']['members']:
            self.assertNotIn('remove', str(row).lower())

    def test_own_row_carries_no_email_key_either(self):
        """`Person.email` is `never` on this route even for your own row.

        Scoped to `data`, not the whole envelope: `context.viewer.email` is
        a legitimate, unrelated field (issue #326's own context contract)
        that always carries the requesting Person's own address.
        """
        response = self.client.get(band_api_url())

        data = response.json()['data']
        for row in data['members']:
            self.assertNotIn('email', row)
        self.assertNotIn(self.viewer.email, str(data))


@override_settings(SECURE_SSL_REDIRECT=False)
class PersonApiViewerStateTests(TestCase):
    """`/api/members/<pk>/`'s three viewer states, per `docs/person-page-visibility.md`.

    A teammate and an admin viewing that same teammate must get byte-
    identical keys except `can_edit_roles` (False for the teammate, True
    for the admin) — the whole point of ADR 0005's surface-not-viewer
    boundary.
    """

    @classmethod
    def setUpTestData(cls):
        """Build a self viewer, a teammate, and an admin, all rostered on the viewing Semester."""
        cls.semester = SemesterFactory()
        cls.self_person = PersonFactory(password=PASSWORD, name='Self Placeholder')
        cls.self_membership = MembershipFactory(person=cls.self_person, semester=cls.semester)
        cls.teammate = PersonFactory(password=PASSWORD, name='Teammate Placeholder')
        cls.teammate_membership = MembershipFactory(person=cls.teammate, semester=cls.semester)
        cls.admin = PersonFactory(password=PASSWORD, name='Admin Placeholder', is_admin=True)
        cls.admin_membership = MembershipFactory(person=cls.admin, semester=cls.semester)

    def test_email_is_self_only_absent_for_teammate_and_admin_viewing_teammate(self):
        """`email` is present only in the self payload; absent (not null) for a teammate and for an admin viewer."""
        self.client.login(username=self.self_person.email, password=PASSWORD)
        self_response = self.client.get(person_api_url(self.self_person))
        self.assertEqual(self_response.json()['data']['email'], self.self_person.email)

        self.client.login(username=self.teammate.email, password=PASSWORD)
        teammate_response = self.client.get(person_api_url(self.self_person))
        self.assertNotIn('email', teammate_response.json()['data'])

        self.client.login(username=self.admin.email, password=PASSWORD)
        admin_response = self.client.get(person_api_url(self.self_person))
        self.assertNotIn('email', admin_response.json()['data'])
        self.assertNotIn(self.self_person.email, str(admin_response.json()['data']))

    def test_admin_viewing_a_teammate_gets_the_teammate_key_set_except_can_edit_roles(self):
        """An admin viewing a teammate gets that teammate's exact key set, plus only what `can_edit_roles` gates.

        `can_edit_roles` is the one write-right flag issue #333 grants an
        admin; `available_roles` is gated by that same flag (it's the
        editable Role catalog the write needs), so its presence is a
        consequence of `can_edit_roles` being True, not a second, separate
        divergence — every other key must match byte-for-byte. `is_admin`
        (issue #467) joins `invite_status` under this exact same gate, for
        the same grant/revoke reason, and so does `future_scheduling_footprint`
        (issue #468): present for an admin viewing a teammate, absent for
        the teammate viewing themself.
        """
        self.client.login(username=self.teammate.email, password=PASSWORD)
        teammate_response = self.client.get(person_api_url(self.self_person))
        teammate_data = teammate_response.json()['data']

        self.client.login(username=self.admin.email, password=PASSWORD)
        admin_response = self.client.get(person_api_url(self.self_person))
        admin_data = admin_response.json()['data']

        self.assertFalse(teammate_data['can_edit_roles'])
        self.assertTrue(admin_data['can_edit_roles'])
        self.assertNotIn('available_roles', teammate_data)
        self.assertIn('available_roles', admin_data)
        self.assertIn('invite_status', admin_data)
        self.assertIn('is_admin', admin_data)
        self.assertIn('future_scheduling_footprint', admin_data)
        self.assertEqual(
            set(teammate_data.keys())
            | {'can_edit_roles', 'available_roles', 'invite_status', 'is_admin', 'future_scheduling_footprint'},
            set(admin_data.keys()) | {'can_edit_roles'},
        )
        for key in teammate_data:
            if key in (
                'can_edit_roles', 'available_roles', 'invite_status', 'is_admin', 'future_scheduling_footprint',
            ):
                continue
            self.assertEqual(teammate_data[key], admin_data[key], f'{key} differed between teammate and admin viewer')

    def test_recordings_block_and_its_count_are_self_only(self):
        """The Recordings block, and its `count`, appear only in the self payload — absent, not null, otherwise."""
        rehearsal_song = RehearsalSongFactory(
            song=SongFactory(semester=self.semester), rehearsal=RehearsalFactory(semester=self.semester),
        )
        RecordingFactory(rehearsal_song=rehearsal_song, uploaded_by=self.self_person)

        self.client.login(username=self.self_person.email, password=PASSWORD)
        self_data = self.client.get(person_api_url(self.self_person)).json()['data']
        self.assertIn('recordings', self_data)
        self.assertEqual(self_data['recordings']['count'], 1)

        self.client.login(username=self.teammate.email, password=PASSWORD)
        teammate_data = self.client.get(person_api_url(self.self_person)).json()['data']
        self.assertNotIn('recordings', teammate_data)

        self.client.login(username=self.admin.email, password=PASSWORD)
        admin_data = self.client.get(person_api_url(self.self_person)).json()['data']
        self.assertNotIn('recordings', admin_data)

    def test_conflict_and_conflict_window_and_adjudication_fields_never_appear_for_any_viewer(self):
        """No Conflict field — reason, status, adjudication note, window times — ever reaches this payload."""
        conflict = ConflictFactory(
            person=self.self_person,
            rehearsal=RehearsalFactory(semester=self.semester),
            type=Conflict.PARTIAL,
            reason='A distinctive placeholder reason',
            status=Conflict.APPROVED,
            adjudication_note='A distinctive placeholder adjudication note',
        )
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 15), unavailable_end=time(18, 45))

        for viewer in (self.self_person, self.teammate, self.admin):
            with self.subTest(viewer=viewer.name):
                self.client.login(username=viewer.email, password=PASSWORD)
                body_text = str(self.client.get(person_api_url(self.self_person)).json())
                self.assertNotIn('A distinctive placeholder reason', body_text)
                self.assertNotIn('A distinctive placeholder adjudication note', body_text)
                self.assertNotIn('18:15', body_text)

    def test_backup_and_covering_for_never_appear_for_any_viewer(self):
        """No Backup field — `covering_for` above all — ever reaches this payload, for any of the three viewers."""
        covered_person = PersonFactory(name='Covered Placeholder')
        rehearsal_song = RehearsalSongFactory(
            song=SongFactory(semester=self.semester), rehearsal=RehearsalFactory(semester=self.semester),
        )
        BackupFactory(rehearsal_song=rehearsal_song, person=self.teammate, covering_for=covered_person)

        for viewer in (self.self_person, self.teammate, self.admin):
            with self.subTest(viewer=viewer.name):
                self.client.login(username=viewer.email, password=PASSWORD)
                body_text = str(self.client.get(person_api_url(self.teammate)).json())
                self.assertNotIn('Covered Placeholder', body_text)
                self.assertNotIn('covering_for', body_text)

    def test_is_role_mismatch_never_appears_in_the_songs_list_for_any_viewer(self):
        """A mismatched SongRoleAssignment renders its Song and Role, but `is_role_mismatch` never appears as a key."""
        song = SongFactory(semester=self.semester, title='Song M')
        assignment = SongRoleAssignmentFactory(
            song=song, person=self.teammate, role=RoleFactory(name='Undeclared Role'),
        )
        self.assertTrue(assignment.is_role_mismatch)

        for viewer in (self.self_person, self.teammate, self.admin):
            with self.subTest(viewer=viewer.name):
                self.client.login(username=viewer.email, password=PASSWORD)
                data = self.client.get(person_api_url(self.teammate)).json()['data']
                song_row = next(row for row in data['songs'] if row['song_title'] == 'Song M')
                self.assertNotIn('is_role_mismatch', song_row)
                self.assertNotIn('is_role_mismatch', str(data))

    def test_no_derived_attendance_data_for_any_viewer(self):
        """`attendance_for`, `breaks_for`, `next_attended_rehearsal_for`, `attendance_suggestion_for` never appear."""
        rehearsal = RehearsalFactory(semester=self.semester)

        for viewer in (self.self_person, self.teammate, self.admin):
            with self.subTest(viewer=viewer.name):
                self.client.login(username=viewer.email, password=PASSWORD)
                body = self.client.get(person_api_url(self.self_person)).json()
                for forbidden_key in ('attendance', 'breaks', 'next_attended_rehearsal', 'attendance_suggestion'):
                    self.assertNotIn(forbidden_key, str(body['data']).lower())
                self.assertNotIn(str(rehearsal.date), str(body['data']))

    def test_recording_object_key_never_appears_even_for_its_own_uploader(self):
        """`Recording.file` — the object key — is never a field on the wire, for anyone, including the uploader.

        `playback_url` is a signed GET that necessarily names the object it
        points at (ADR 0004) — the verdict this enforces is that no
        separate `file`/key *field* exists on a Recording row, exactly what
        the exact-key-set test pins; it is not a claim that the key
        substring can never appear inside the signed URL that serves it.
        """
        rehearsal_song = RehearsalSongFactory(
            song=SongFactory(semester=self.semester), rehearsal=RehearsalFactory(semester=self.semester),
        )
        RecordingFactory(
            rehearsal_song=rehearsal_song, uploaded_by=self.self_person, file='recordings/take-distinct.m4a',
        )

        self.client.login(username=self.self_person.email, password=PASSWORD)
        data = self.client.get(person_api_url(self.self_person)).json()['data']

        item = data['recordings']['items'][0]
        self.assertNotIn('file', item)
        self.assertEqual(set(item.keys()), {
            'id', 'song_title', 'rehearsal_date', 'start_time', 'end_time',
            'note', 'file_size', 'uploaded_at', 'playback_url',
        })


@override_settings(SECURE_SSL_REDIRECT=False)
class PersonApiFutureSchedulingFootprintTests(TestCase):
    """`future_scheduling_footprint` (issue #468, ADR-0017): admin-only, and carries `person`'s future-facing state."""

    @classmethod
    def setUpTestData(cls):
        """Build a viewing Semester with an admin and a teammate rostered on it."""
        cls.semester = SemesterFactory()
        cls.admin = PersonFactory(password=PASSWORD, name='Admin Placeholder', is_admin=True)
        MembershipFactory(person=cls.admin, semester=cls.semester)
        cls.teammate = PersonFactory(password=PASSWORD, name='Teammate Placeholder')
        MembershipFactory(person=cls.teammate, semester=cls.semester)

    def test_absent_for_a_plain_teammate_and_for_self(self):
        """A plain Teammate viewer and the Person viewing themself never get this key at all."""
        self.client.login(username=self.teammate.email, password=PASSWORD)
        self_data = self.client.get(person_api_url(self.teammate)).json()['data']
        self.assertNotIn('future_scheduling_footprint', self_data)

        other_teammate = PersonFactory(password=PASSWORD)
        MembershipFactory(person=other_teammate, semester=self.semester)
        self.client.login(username=other_teammate.email, password=PASSWORD)
        teammate_data = self.client.get(person_api_url(self.teammate)).json()['data']
        self.assertNotIn('future_scheduling_footprint', teammate_data)

    def test_empty_for_an_admin_viewing_a_teammate_with_no_future_facing_state(self):
        """An admin viewing a teammate rostered only in the viewing Semester gets three empty lists, not an absent key."""
        self.client.login(username=self.admin.email, password=PASSWORD)
        data = self.client.get(person_api_url(self.teammate)).json()['data']
        footprint = data['future_scheduling_footprint']

        self.assertEqual(footprint['future_memberships'], [])
        self.assertEqual(footprint['future_role_assignments'], [])
        self.assertEqual(footprint['future_rehearsal_appearances'], [])

    def test_carries_future_memberships_role_assignments_and_rehearsal_appearances(self):
        """An admin viewing a teammate sees their other-Semester Membership, other-Semester Assignment, and future Rehearsal appearance."""
        other_semester = SemesterFactory(name='Other Semester', published_at=timezone.now() - timedelta(days=365))
        MembershipFactory(person=self.teammate, semester=other_semester)
        other_song = SongFactory(semester=other_semester, title='Other Semester Song')
        SongRoleAssignmentFactory(song=other_song, person=self.teammate, role=RoleFactory(name='Bass'))

        upcoming_song = SongFactory(semester=self.semester, title='Upcoming Song')
        SongRoleAssignmentFactory(song=upcoming_song, person=self.teammate, role=RoleFactory(name='Vocals'))
        upcoming_rehearsal = RehearsalFactory(semester=self.semester, date=timezone.localdate() + timedelta(days=5))
        RehearsalSongFactory(rehearsal=upcoming_rehearsal, song=upcoming_song, order=1)

        self.client.login(username=self.admin.email, password=PASSWORD)
        data = self.client.get(person_api_url(self.teammate)).json()['data']
        footprint = data['future_scheduling_footprint']

        self.assertEqual(footprint['future_memberships'], [
            {'semester_id': other_semester.pk, 'semester_name': 'Other Semester'},
        ])
        self.assertEqual(footprint['future_role_assignments'], [
            {
                'semester_id': other_semester.pk, 'semester_name': 'Other Semester',
                'song_id': other_song.pk, 'song_title': 'Other Semester Song', 'role_name': 'Bass',
            },
        ])
        self.assertEqual(len(footprint['future_rehearsal_appearances']), 1)
        appearance = footprint['future_rehearsal_appearances'][0]
        self.assertEqual(appearance['rehearsal_id'], upcoming_rehearsal.pk)
        self.assertEqual(appearance['song_id'], upcoming_song.pk)
        self.assertEqual(appearance['role_name'], 'Vocals')
        self.assertEqual(appearance['kind'], 'assignment')


@override_settings(SECURE_SSL_REDIRECT=False)
class PersonApiTeammateRecordingPrivacyTests(TestCase):
    """A teammate's Recordings are `never`, not even a bare count, for a Teammate or an Admin viewer alike."""

    @classmethod
    def setUpTestData(cls):
        """Build a viewer, an admin, and a teammate holding a Recording, all rostered on the viewing Semester."""
        cls.semester = SemesterFactory()
        cls.viewer = PersonFactory(password=PASSWORD, name='Viewer Placeholder')
        MembershipFactory(person=cls.viewer, semester=cls.semester)
        cls.admin = PersonFactory(password=PASSWORD, name='Admin Placeholder', is_admin=True)
        MembershipFactory(person=cls.admin, semester=cls.semester)
        cls.teammate = PersonFactory(name='Teammate Placeholder')
        MembershipFactory(person=cls.teammate, semester=cls.semester)
        rehearsal_song = RehearsalSongFactory(
            song=SongFactory(semester=cls.semester), rehearsal=RehearsalFactory(semester=cls.semester),
        )
        RecordingFactory(rehearsal_song=rehearsal_song, uploaded_by=cls.teammate, note='A distinctive upload note')

    def test_teammate_viewer_sees_no_recordings_trace(self):
        """A plain teammate viewer's payload has no `recordings` key and no trace of the note or a count."""
        self.client.login(username=self.viewer.email, password=PASSWORD)

        data = self.client.get(person_api_url(self.teammate)).json()['data']

        self.assertNotIn('recordings', data)
        self.assertNotIn('A distinctive upload note', str(data))

    def test_admin_viewer_sees_the_same_nothing(self):
        """An admin viewing the teammate gets that same nothing — the boundary is around the surface."""
        self.client.login(username=self.admin.email, password=PASSWORD)

        data = self.client.get(person_api_url(self.teammate)).json()['data']

        self.assertNotIn('recordings', data)
        self.assertNotIn('A distinctive upload note', str(data))


@override_settings(SECURE_SSL_REDIRECT=False)
class PersonApiNotOnRosterTests(TestCase):
    """The not-in-Semester self case: your own pk is reachable with no Membership; a teammate's isn't (ADR 0001)."""

    @classmethod
    def setUpTestData(cls):
        """Build a Semester with no Memberships in it yet."""
        cls.semester = SemesterFactory()
        cls.self_person = PersonFactory(password=PASSWORD, name='Fresh Invite Placeholder')

    def setUp(self):
        """Log in as the not-yet-rostered self viewer before each test."""
        self.client.login(username=self.self_person.email, password=PASSWORD)

    def test_own_pk_with_no_membership_omits_songs_and_recordings_but_still_carries_roles(self):
        """The unsaved-Membership self case renders name/email/can_edit_roles/roles but no songs/recordings keys.

        `roles` (issue #378, ADR-0014) is unconditional: a standing
        `PersonRole` declaration doesn't need a Membership to exist, so a
        newly-invited, not-yet-rostered Person can still declare Roles
        here before an admin rosters them.
        """
        response = self.client.get(person_api_url(self.self_person))

        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['name'], 'Fresh Invite Placeholder')
        self.assertEqual(data['email'], self.self_person.email)
        self.assertFalse(data['has_membership'])
        self.assertEqual(data['roles'], [])
        self.assertNotIn('songs', data)
        self.assertNotIn('recordings', data)

    def test_a_teammates_pk_with_no_membership_404s(self):
        """A teammate with no Membership in the viewing Semester is unreachable, unlike the self case."""
        stranger = PersonFactory(password=PASSWORD)

        response = self.client.get(person_api_url(stranger))

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class PersonRolesApiEditRightsTests(TestCase):
    """`PersonRole`-editing rights on `/api/members/<pk>/roles/` (issues #232, #333, #378): self or an admin, never a plain teammate."""

    @classmethod
    def setUpTestData(cls):
        """Build a self viewer, a teammate, and an admin, all rostered on the viewing Semester."""
        cls.semester = SemesterFactory()
        cls.self_person = PersonFactory(password=PASSWORD, name='Self Placeholder')
        MembershipFactory(person=cls.self_person, semester=cls.semester)
        cls.teammate = PersonFactory(password=PASSWORD, name='Teammate Placeholder')
        MembershipFactory(person=cls.teammate, semester=cls.semester)
        cls.admin = PersonFactory(password=PASSWORD, name='Admin Placeholder', is_admin=True)
        MembershipFactory(person=cls.admin, semester=cls.semester)

    def _roles_url(self, person):
        """Return `/api/members/<pk>/roles/` for `person`."""
        return reverse('api-member-roles', args=[person.pk])

    def test_self_can_edit_their_own_declared_roles(self):
        """The self viewer can declare their own standing Roles through this endpoint."""
        role = RoleFactory(name='Bassist')
        self.client.login(username=self.self_person.email, password=PASSWORD)

        response = self.client.post(
            self._roles_url(self.self_person),
            data={'role_ids': [role.pk]},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertIn('Bassist', str(response.json()['data']['roles']))

    def test_self_can_remove_a_declared_role(self):
        """A second save with the Role omitted deletes the standing `PersonRole` row."""
        role = RoleFactory(name='Bassist')
        PersonRoleFactory(person=self.self_person, role=role)
        self.client.login(username=self.self_person.email, password=PASSWORD)

        response = self.client.post(
            self._roles_url(self.self_person), data={'role_ids': []}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertEqual(response.json()['data']['roles'], [])

    def test_admin_can_edit_anyones_declared_roles(self):
        """An admin can declare standing Roles on any Person, per issue #232/#378."""
        role = RoleFactory(name='Drummer')
        self.client.login(username=self.admin.email, password=PASSWORD)

        response = self.client.post(
            self._roles_url(self.teammate),
            data={'role_ids': [role.pk]},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertIn('Drummer', str(response.json()['data']['roles']))

    def test_non_admin_teammate_gets_a_404_not_a_rejected_form(self):
        """A non-admin teammate's POST to someone else's Roles endpoint 404s rather than rendering a form error."""
        role = RoleFactory()
        self.client.login(username=self.teammate.email, password=PASSWORD)

        response = self.client.post(
            self._roles_url(self.self_person),
            data={'role_ids': [role.pk]},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)

    def test_inactive_or_unknown_role_id_is_rejected_with_ok_false(self):
        """A submitted role id that isn't an active Role is refused as a validation error, not a 500 or a silent no-op."""
        inactive_role = RoleFactory(name='Retired Role', is_active=False)
        self.client.login(username=self.self_person.email, password=PASSWORD)

        response = self.client.post(
            self._roles_url(self.self_person),
            data={'role_ids': [inactive_role.pk]},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['ok'])
        self.assertIn('not valid', str(response.json()['non_field_errors']))

    def test_self_edit_does_not_require_a_membership(self):
        """A not-yet-rostered self viewer (no Membership at all) can still declare standing Roles."""
        unrostered_person = PersonFactory(password=PASSWORD, name='Fresh Invite Placeholder')
        role = RoleFactory(name='Vocalist')
        self.client.login(username=unrostered_person.email, password=PASSWORD)

        response = self.client.post(
            self._roles_url(unrostered_person), data={'role_ids': [role.pk]}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertIn('Vocalist', str(response.json()['data']['roles']))


@override_settings(SECURE_SSL_REDIRECT=False)
class MemberDetailBackupPrivacyTests(TestCase):
    """`/api/members/<pk>/` verdicts for `Backup` (ADR 0007), retargeted from the old HTML surface (issue #333)."""

    @classmethod
    def setUpTestData(cls):
        """Build a viewer, a teammate, and a Backup covering a third Person on a viewing-Semester Rehearsal slot."""
        cls.semester = SemesterFactory()
        cls.viewer = PersonFactory(password=PASSWORD, name='Viewer Placeholder')
        MembershipFactory(person=cls.viewer, semester=cls.semester)
        cls.teammate = PersonFactory(name='Teammate Placeholder')
        MembershipFactory(person=cls.teammate, semester=cls.semester)
        cls.covered_person = PersonFactory(name='Covered Placeholder')
        rehearsal_song = RehearsalSongFactory(
            song=SongFactory(semester=cls.semester), rehearsal=RehearsalFactory(semester=cls.semester),
        )
        cls.backup = BackupFactory(
            rehearsal_song=rehearsal_song, person=cls.teammate, covering_for=cls.covered_person,
        )

    def setUp(self):
        """Log in as the viewer before each test."""
        self.client.login(username=self.viewer.email, password=PASSWORD)

    def test_covering_for_is_never_rendered_on_a_teammates_payload(self):
        """The teammate standing in as a Backup has their payload carry no trace of who they're covering."""
        data = self.client.get(person_api_url(self.teammate)).json()['data']

        self.assertNotIn('Covered Placeholder', str(data))

    def test_no_backup_or_rehearsal_data_on_the_covered_persons_own_payload(self):
        """The covered Person's own payload names no Backup and no trace of who is covering them.

        Not a blanket "no Rehearsal date anywhere" check: the self-only
        Recordings block legitimately lists every RehearsalSong slot in the
        Semester as Upload-a-take picker options (issue #333), which can
        coincidentally share a date with the Backup's Rehearsal — that is
        the unrelated upload picker, not a Backup disclosure.
        """
        self.covered_person.set_password(PASSWORD)
        self.covered_person.save()
        MembershipFactory(person=self.covered_person, semester=self.semester)
        self.client.login(username=self.covered_person.email, password=PASSWORD)

        data = self.client.get(person_api_url(self.covered_person)).json()['data']

        self.assertNotIn('backup', str(data).lower())
        self.assertNotIn(self.teammate.name, str(data))


@override_settings(SECURE_SSL_REDIRECT=False)
class PersonRoleDeclaredRoleTests(TestCase):
    """Declared Roles render alongside a `PersonRole` factory-built row (ADR-0014), sanity-checking the retargeted fixtures."""

    def test_declared_role_renders_on_the_teammate_payload(self):
        """A teammate's standing declared Roles render by name in the `roles` list."""
        semester = SemesterFactory()
        viewer = PersonFactory(password=PASSWORD, name='Viewer Placeholder')
        MembershipFactory(person=viewer, semester=semester)
        teammate = PersonFactory(name='Teammate Placeholder')
        MembershipFactory(person=teammate, semester=semester)
        PersonRoleFactory(person=teammate, role=RoleFactory(name='Bassist'))
        self.client.login(username=viewer.email, password=PASSWORD)

        data = self.client.get(person_api_url(teammate)).json()['data']

        self.assertIn('Bassist', [role['name'] for role in data['roles']])
