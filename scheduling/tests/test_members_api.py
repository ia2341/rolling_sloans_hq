"""`/api/members/` and `/api/members/<pk>/` — the Band and Person surfaces (issue #333).

Follows `test_setlist_song_api.py`'s shape (#330's designated template):
serializer exact-key-set tests pin the wire shape for `serialize_band()`,
`serialize_person()` and `serialize_person_recordings()`, and view-level
tests cover the envelope, the roster's active-only filter, ordering, and
the `PersonRolesApiView` write path. Privacy verdicts (ADR 0005/0002/0007)
live in `test_person_page_visibility.py`, not here.
"""

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    MembershipRoleFactory,
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Membership
from scheduling.serializers import (
    serialize_band,
    serialize_person,
    serialize_person_recordings,
)
from scheduling.services import active_roster_for, unassigned_role_holders_for

PASSWORD = 'a-strong-test-password-123'


def band_api_url():
    """Return `/api/members/`."""
    return reverse('api-members')


def person_api_url(person):
    """Return `/api/members/<pk>/` for `person`."""
    return reverse('api-member-detail', args=[person.pk])


class SerializeBandExactKeySetTests(TestCase):
    """`serialize_band()` names every key it emits, and no more."""

    def test_top_level_keys(self):
        """The top-level payload carries exactly the three documented keys."""
        semester = SemesterFactory()

        data = serialize_band(Membership.objects.none(), semester)

        self.assertEqual(set(data.keys()), {'semester_name', 'member_count', 'members'})

    def test_member_row_keys(self):
        """A `members` row carries exactly `id`, `name`, `roles`, `song_count`."""
        semester = SemesterFactory()
        person = PersonFactory(password=PASSWORD)
        MembershipFactory(person=person, semester=semester)
        memberships = active_roster_for(Membership.objects.filter(semester=semester))

        data = serialize_band(memberships, semester)

        self.assertEqual(set(data['members'][0].keys()), {'id', 'name', 'roles', 'song_count'})

    def test_no_semester_yields_the_empty_shape_with_the_same_keys(self):
        """`None` (no Semester at all) still returns the documented top-level keys, empty rather than absent."""
        data = serialize_band(Membership.objects.none(), None)

        self.assertEqual(set(data.keys()), {'semester_name', 'member_count', 'members'})
        self.assertEqual(data['member_count'], 0)
        self.assertEqual(data['members'], [])

    def test_unassigned_role_holders_omitted_when_not_passed(self):
        """The gap-flag key is absent, not null, when the caller passes no queryset (a non-admin viewer)."""
        semester = SemesterFactory()

        data = serialize_band(Membership.objects.none(), semester)

        self.assertNotIn('unassigned_role_holders', data)

    def test_unassigned_role_holders_present_and_shaped_when_passed(self):
        """Passing a queryset (an admin viewer) adds `unassigned_role_holders` with exactly `count`/`names`."""
        semester = SemesterFactory()
        gap_person = PersonFactory(name='Uncast Placeholder')
        song = SongFactory(semester=semester)
        SongRoleAssignmentFactory(song=song, person=gap_person)

        data = serialize_band(
            Membership.objects.none(), semester,
            unassigned_role_holders=unassigned_role_holders_for(semester),
        )

        self.assertEqual(set(data['unassigned_role_holders'].keys()), {'count', 'names'})
        self.assertEqual(data['unassigned_role_holders']['count'], 1)
        self.assertEqual(data['unassigned_role_holders']['names'], ['Uncast Placeholder'])


class SerializePersonExactKeySetTests(TestCase):
    """`serialize_person()` names every key it emits, in each of the three viewer states."""

    def test_teammate_keys_no_membership_edit_rights(self):
        """A plain teammate viewer (no membership edit rights) gets exactly the base + roles/songs keys."""
        semester = SemesterFactory()
        person = PersonFactory(name='Teammate Placeholder')
        membership = MembershipFactory(person=person, semester=semester)

        data = serialize_person(person, semester=semester, is_self=False, can_edit_roles=False, membership=membership)

        self.assertEqual(
            set(data.keys()),
            {'id', 'name', 'is_self', 'can_edit_roles', 'has_membership', 'semester_name', 'roles', 'songs'},
        )

    def test_self_keys_add_email_available_roles_and_recordings(self):
        """The self viewer's payload adds exactly `email`, `available_roles` and `recordings` over the base shape."""
        semester = SemesterFactory()
        person = PersonFactory(name='Self Placeholder')
        membership = MembershipFactory(person=person, semester=semester)

        data = serialize_person(person, semester=semester, is_self=True, can_edit_roles=True, membership=membership)

        self.assertEqual(
            set(data.keys()),
            {
                'id', 'name', 'is_self', 'can_edit_roles', 'has_membership', 'semester_name',
                'roles', 'songs', 'email', 'available_roles', 'recordings',
            },
        )

    def test_admin_viewing_a_teammate_adds_only_available_roles(self):
        """An admin viewing a teammate (can_edit_roles True, is_self False) adds only `available_roles`, never email/recordings."""
        semester = SemesterFactory()
        person = PersonFactory(name='Teammate Placeholder')
        membership = MembershipFactory(person=person, semester=semester)

        data = serialize_person(person, semester=semester, is_self=False, can_edit_roles=True, membership=membership)

        self.assertEqual(
            set(data.keys()),
            {
                'id', 'name', 'is_self', 'can_edit_roles', 'has_membership', 'semester_name',
                'roles', 'songs', 'available_roles',
            },
        )
        self.assertNotIn('email', data)
        self.assertNotIn('recordings', data)

    def test_role_entry_keys(self):
        """A `roles`/`available_roles` entry carries exactly `id`, `name`."""
        semester = SemesterFactory()
        person = PersonFactory(name='Self Placeholder')
        membership = MembershipFactory(person=person, semester=semester)
        MembershipRoleFactory(membership=membership, role=RoleFactory(name='Bassist'))

        data = serialize_person(person, semester=semester, is_self=True, can_edit_roles=True, membership=membership)

        self.assertEqual(set(data['roles'][0].keys()), {'id', 'name'})
        self.assertEqual(set(data['available_roles'][0].keys()), {'id', 'name'})

    def test_song_row_keys(self):
        """A `songs` row carries exactly `song_id`, `song_title`, `artist`, `role_name` — never `is_role_mismatch`."""
        semester = SemesterFactory()
        person = PersonFactory(name='Self Placeholder')
        membership = MembershipFactory(person=person, semester=semester)
        song = SongFactory(semester=semester)
        SongRoleAssignmentFactory(song=song, person=person)

        data = serialize_person(person, semester=semester, is_self=True, can_edit_roles=True, membership=membership)

        self.assertEqual(set(data['songs'][0].keys()), {'song_id', 'song_title', 'artist', 'role_name'})

    def test_no_membership_omits_roles_and_songs_but_not_email_or_recordings(self):
        """An unsaved Membership (the not-yet-rostered self case) omits `roles`/`songs`/`recordings` entirely."""
        semester = SemesterFactory()
        person = PersonFactory(name='Fresh Invite Placeholder')
        unsaved_membership = Membership(person=person, semester=semester)

        data = serialize_person(
            person, semester=semester, is_self=True, can_edit_roles=True, membership=unsaved_membership,
        )

        self.assertFalse(data['has_membership'])
        self.assertNotIn('roles', data)
        self.assertNotIn('songs', data)
        self.assertNotIn('recordings', data)
        self.assertIn('email', data)
        self.assertIn('available_roles', data)


class SerializePersonRecordingsExactKeySetTests(TestCase):
    """`serialize_person_recordings()` names every key it emits, and no more (self-only Recordings block)."""

    def test_top_level_keys(self):
        """The top-level block carries exactly `count`, `items`, `upload_slots`."""
        semester = SemesterFactory()
        person = PersonFactory()

        data = serialize_person_recordings(person, semester)

        self.assertEqual(set(data.keys()), {'count', 'items', 'upload_slots'})

    def test_item_keys_never_include_the_object_key(self):
        """A Recording row carries exactly the documented keys, and never `file` — ADR 0004's protected field."""
        semester = SemesterFactory()
        person = PersonFactory()
        rehearsal_song = RehearsalSongFactory(song=SongFactory(semester=semester), rehearsal=RehearsalFactory(semester=semester))
        RecordingFactory(rehearsal_song=rehearsal_song, uploaded_by=person)

        data = serialize_person_recordings(person, semester)

        self.assertEqual(
            set(data['items'][0].keys()),
            {'id', 'song_title', 'rehearsal_date', 'start_time', 'end_time', 'note', 'file_size', 'uploaded_at', 'playback_url'},
        )

    def test_upload_slot_keys(self):
        """An `upload_slots` entry carries exactly the documented picker-option keys."""
        semester = SemesterFactory()
        person = PersonFactory()
        RehearsalSongFactory(song=SongFactory(semester=semester), rehearsal=RehearsalFactory(semester=semester))

        data = serialize_person_recordings(person, semester)

        self.assertEqual(
            set(data['upload_slots'][0].keys()),
            {'id', 'song_id', 'song_title', 'rehearsal_date', 'start_time', 'end_time'},
        )


@override_settings(SECURE_SSL_REDIRECT=False)
class BandApiViewTests(TestCase):
    """`GET /api/members/` (issue #333)."""

    def setUp(self):
        """Log in as an ordinary member before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_envelope_carries_context_and_data(self):
        """A successful response carries both the `context` block and the Band `data`."""
        SemesterFactory()

        response = self.client.get(band_api_url())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn('context', body)
        self.assertIn('data', body)

    def test_no_published_semester_returns_the_empty_shape(self):
        """With nothing published, a member gets the documented empty Band shape, not an error."""
        response = self.client.get(band_api_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['members'], [])

    def test_invited_but_not_yet_active_person_is_excluded(self):
        """A Person with no usable password (invited, not yet active) stays off the Band list."""
        semester = SemesterFactory()
        MembershipFactory(person=self.person, semester=semester)
        not_yet_active = PersonFactory(name='Not Yet Active Placeholder')  # unusable password by default
        MembershipFactory(person=not_yet_active, semester=semester)

        response = self.client.get(band_api_url())

        names = [row['name'] for row in response.json()['data']['members']]
        self.assertIn(self.person.name, names)
        self.assertNotIn(not_yet_active.name, names)

    def test_members_ordered_by_name(self):
        """The roster is ordered by the Person's name."""
        semester = SemesterFactory()
        MembershipFactory(person=PersonFactory(password=PASSWORD, name='Yolanda Placeholder'), semester=semester)
        MembershipFactory(person=PersonFactory(password=PASSWORD, name='Anders Placeholder'), semester=semester)

        response = self.client.get(band_api_url())

        names = [row['name'] for row in response.json()['data']['members']]
        self.assertEqual(names, ['Anders Placeholder', 'Yolanda Placeholder'])

    def test_song_count_and_roles_render_per_row(self):
        """Each row carries its declared Role names and its distinct assigned-Song count."""
        semester = SemesterFactory()
        membership = MembershipFactory(person=self.person, semester=semester)
        MembershipRoleFactory(membership=membership, role=RoleFactory(name='Bassist'))
        song = SongFactory(semester=semester)
        SongRoleAssignmentFactory(song=song, person=self.person)

        response = self.client.get(band_api_url())

        row = response.json()['data']['members'][0]
        self.assertEqual(row['roles'], ['Bassist'])
        self.assertEqual(row['song_count'], 1)

    def test_member_with_membership_but_no_assignment_shows_normally(self):
        """A Person with only a Membership (no SongRoleAssignment) still appears on the Roster as usual."""
        semester = SemesterFactory()
        MembershipFactory(person=self.person, semester=semester)

        response = self.client.get(band_api_url())

        names = [row['name'] for row in response.json()['data']['members']]
        self.assertIn(self.person.name, names)

    def test_gap_field_absent_for_a_non_admin_viewer(self):
        """A non-admin viewer's payload never carries `unassigned_role_holders`, even when a gap exists."""
        semester = SemesterFactory()
        gap_person = PersonFactory(name='Uncast Placeholder')
        SongRoleAssignmentFactory(song=SongFactory(semester=semester), person=gap_person)

        response = self.client.get(band_api_url())

        self.assertNotIn('unassigned_role_holders', response.json()['data'])


@override_settings(SECURE_SSL_REDIRECT=False)
class BandApiViewAdminGapFlagTests(TestCase):
    """`GET /api/members/`'s admin-only `unassigned_role_holders` gap flag (assignment without Membership)."""

    def setUp(self):
        """Log in as an admin before each test."""
        self.admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_assignment_only_person_is_excluded_from_the_main_roster(self):
        """A Person with a SongRoleAssignment but no Membership for the Semester never appears in `members`."""
        semester = SemesterFactory()
        gap_person = PersonFactory(name='Uncast Placeholder')
        SongRoleAssignmentFactory(song=SongFactory(semester=semester), person=gap_person)

        response = self.client.get(band_api_url())

        names = [row['name'] for row in response.json()['data']['members']]
        self.assertNotIn(gap_person.name, names)

    def test_assignment_only_person_is_counted_and_named_in_the_gap_flag(self):
        """That same Person is counted and named in `unassigned_role_holders` for an admin viewer."""
        semester = SemesterFactory()
        gap_person = PersonFactory(name='Uncast Placeholder')
        SongRoleAssignmentFactory(song=SongFactory(semester=semester), person=gap_person)

        response = self.client.get(band_api_url())

        gap = response.json()['data']['unassigned_role_holders']
        self.assertEqual(gap['count'], 1)
        self.assertEqual(gap['names'], ['Uncast Placeholder'])

    def test_gap_flag_empty_when_everyone_with_an_assignment_has_a_membership(self):
        """A Person with both a Membership and a SongRoleAssignment never appears in the gap flag."""
        semester = SemesterFactory()
        MembershipFactory(person=self.admin, semester=semester)
        SongRoleAssignmentFactory(song=SongFactory(semester=semester), person=self.admin)

        response = self.client.get(band_api_url())

        self.assertEqual(response.json()['data']['unassigned_role_holders']['count'], 0)

    def test_gap_flag_absent_with_no_published_semester(self):
        """With no viewing Semester at all, the response falls into the empty Band shape, which carries no gap key."""
        response = self.client.get(band_api_url())

        self.assertNotIn('unassigned_role_holders', response.json()['data'])


class UnassignedRoleHoldersForTests(TestCase):
    """`services.unassigned_role_holders_for()` (the Band page's admin-only casting-without-roster gap)."""

    def test_none_semester_returns_an_empty_queryset(self):
        """Passing `None` (no viewing Semester) returns an empty queryset, matching sibling viewing-Semester helpers."""
        self.assertEqual(list(unassigned_role_holders_for(None)), [])

    def test_excludes_a_person_with_a_membership_for_the_semester(self):
        """A Person who has both a Membership and a SongRoleAssignment for the Semester is not a gap."""
        semester = SemesterFactory()
        person = PersonFactory(name='Rostered Placeholder')
        MembershipFactory(person=person, semester=semester)
        SongRoleAssignmentFactory(song=SongFactory(semester=semester), person=person)

        self.assertEqual(list(unassigned_role_holders_for(semester)), [])

    def test_includes_a_person_with_an_assignment_but_no_membership(self):
        """A Person with a SongRoleAssignment on the Semester's Songs but no Membership row is a gap."""
        semester = SemesterFactory()
        gap_person = PersonFactory(name='Uncast Placeholder')
        SongRoleAssignmentFactory(song=SongFactory(semester=semester), person=gap_person)

        self.assertEqual(list(unassigned_role_holders_for(semester)), [gap_person])

    def test_does_not_include_a_person_whose_assignment_is_on_a_different_semester(self):
        """A SongRoleAssignment scoped to another Semester's Song never counts as a gap for this one."""
        semester = SemesterFactory()
        other_semester = SemesterFactory()
        other_person = PersonFactory(name='Other Semester Placeholder')
        SongRoleAssignmentFactory(song=SongFactory(semester=other_semester), person=other_person)

        self.assertEqual(list(unassigned_role_holders_for(semester)), [])

    def test_distinct_across_multiple_assignments_for_the_same_person(self):
        """A Person with several assignments this Semester appears only once in the gap list."""
        semester = SemesterFactory()
        gap_person = PersonFactory(name='Uncast Placeholder')
        SongRoleAssignmentFactory(song=SongFactory(semester=semester), person=gap_person)
        SongRoleAssignmentFactory(song=SongFactory(semester=semester), person=gap_person)

        self.assertEqual(list(unassigned_role_holders_for(semester)), [gap_person])


@override_settings(SECURE_SSL_REDIRECT=False)
class PersonApiViewTests(TestCase):
    """`GET /api/members/<pk>/` (issue #333)."""

    def setUp(self):
        """Log in as an ordinary member before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_anonymous_request_401s_not_302s(self):
        """An anonymous request to the parameterised Person route still gets the bare 401 (issue #326/#333)."""
        self.client.logout()

        response = self.client.get(person_api_url(self.person))

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_own_pk_returns_200_even_with_no_membership(self):
        """Your own pk is reachable even with no Membership in the viewing Semester, unlike a teammate's."""
        SemesterFactory()

        response = self.client.get(person_api_url(self.person))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['data']['is_self'])

    def test_unknown_person_id_404s(self):
        """A nonexistent Person id 404s."""
        response = self.client.get(reverse('api-member-detail', args=[999999]))

        self.assertEqual(response.status_code, 404)


def recording_slots_api_url():
    """Return `/api/members/recordings/slots/`."""
    return reverse('api-recordings-slots')


@override_settings(SECURE_SSL_REDIRECT=False)
class RecordingSlotsApiViewTests(TestCase):
    """`GET /api/members/recordings/slots/` (issue: UI overhaul round 2) — backs the reusable upload popup."""

    def setUp(self):
        """Log in as an ordinary member before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_anonymous_request_401s_not_302s(self):
        """An anonymous request gets the bare 401, matching every other `/api/` endpoint."""
        self.client.logout()

        response = self.client.get(recording_slots_api_url())

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_returns_the_same_shape_serialize_person_recordings_does(self):
        """The response carries `upload_slots` for the current viewer, matching a fresh Person-page load."""
        semester = SemesterFactory()
        RehearsalSongFactory(song=SongFactory(semester=semester), rehearsal=RehearsalFactory(semester=semester))

        response = self.client.get(recording_slots_api_url())

        data = response.json()['data']
        self.assertEqual(set(data.keys()), {'count', 'items', 'upload_slots'})
        self.assertEqual(len(data['upload_slots']), 1)

    def test_no_published_semester_returns_the_empty_shape(self):
        """With no Semester being viewed, the popup gets an empty (not erroring) shape."""
        response = self.client.get(recording_slots_api_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], {'count': 0, 'items': [], 'upload_slots': []})


@override_settings(SECURE_SSL_REDIRECT=False)
class PersonRolesApiViewTests(TestCase):
    """`POST /api/members/<pk>/roles/` (issue #333, issue #232)."""

    def setUp(self):
        """Build a Semester and log in as an ordinary member before each test."""
        self.semester = SemesterFactory()
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_first_submission_creates_the_membership(self):
        """A first-time POST with no prior Membership creates one and writes its Roles."""
        role = RoleFactory()

        response = self.client.post(
            reverse('api-member-roles', args=[self.person.pk]),
            data={'role_ids': [role.pk]},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertTrue(Membership.objects.filter(person=self.person, semester=self.semester).exists())

    def test_invalid_role_id_reports_a_field_error_without_writing(self):
        """A nonexistent Role id reports a field error via the write envelope rather than a 500."""
        response = self.client.post(
            reverse('api-member-roles', args=[self.person.pk]),
            data={'role_ids': [999999]},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['ok'])
        self.assertIn('roles', body['errors'])
