"""`/api/members/` and `/api/members/<pk>/` — the Band and Person surfaces (issue #333).

Follows `test_setlist_song_api.py`'s shape (#330's designated template):
serializer exact-key-set tests pin the wire shape for `serialize_band()`,
`serialize_person()` and `serialize_person_recordings()`, and view-level
tests cover the envelope, the admin-only `invite_status` key, ordering, and
the `PersonRolesApiView` write path. Privacy verdicts (ADR 0005/0002/0007)
live in `test_person_page_visibility.py`, not here.
"""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from identity.models import Person
from identity.services import (
    CannotDeactivateLastActiveAdminError,
    CannotRevokeLastActiveAdminError,
)
from scheduling.factories import (
    MembershipFactory,
    PersonRoleFactory,
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    RoleGroupFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Membership, PersonRole
from scheduling.serializers import (
    serialize_band,
    serialize_person,
    serialize_person_recordings,
)
from scheduling.services import (
    recording_slot_options_for,
    roster_for,
    unassigned_role_holders_for,
)
from scheduling.tests.api_test_helpers import admin_client, member_client, select

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
        """A `members` row carries exactly `id`, `name`, `roles`, `song_count` for a non-admin viewer."""
        semester = SemesterFactory()
        person = PersonFactory(password=PASSWORD)
        MembershipFactory(person=person, semester=semester)
        memberships = roster_for(Membership.objects.filter(semester=semester))

        data = serialize_band(memberships, semester)

        self.assertEqual(set(data['members'][0].keys()), {'id', 'name', 'roles', 'song_count'})

    def test_member_row_keys_for_admin_viewer_add_invite_status(self):
        """An admin viewer's `members` row additionally carries `invite_status` (issue #455)."""
        semester = SemesterFactory()
        person = PersonFactory(password=PASSWORD)
        MembershipFactory(person=person, semester=semester)
        memberships = roster_for(Membership.objects.filter(semester=semester))

        data = serialize_band(memberships, semester, is_admin=True)

        self.assertEqual(set(data['members'][0].keys()), {'id', 'name', 'roles', 'song_count', 'invite_status'})

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
        """An admin viewing a teammate (can_edit_roles True, is_self False) adds `available_roles`, `invite_status`, `is_admin`, `is_active` and `future_scheduling_footprint` (#397, #467, #468, #469), never email/recordings."""
        semester = SemesterFactory()
        person = PersonFactory(name='Teammate Placeholder')
        membership = MembershipFactory(person=person, semester=semester)

        data = serialize_person(person, semester=semester, is_self=False, can_edit_roles=True, membership=membership)

        self.assertEqual(
            set(data.keys()),
            {
                'id', 'name', 'is_self', 'can_edit_roles', 'has_membership', 'semester_name',
                'roles', 'songs', 'available_roles', 'invite_status', 'is_admin', 'is_active',
                'future_scheduling_footprint',
            },
        )
        self.assertNotIn('email', data)
        self.assertNotIn('recordings', data)

    def test_is_admin_reflects_the_targets_actual_admin_flag(self):
        """`is_admin` (admin-viewing-a-teammate only) reads the target Person's real flag, not the viewer's (issue #467)."""
        semester = SemesterFactory()
        admin_target = PersonFactory(name='Admin Placeholder', is_admin=True)
        non_admin_target = PersonFactory(name='Non-admin Placeholder', is_admin=False)
        for person in (admin_target, non_admin_target):
            MembershipFactory(person=person, semester=semester)

        self.assertTrue(
            serialize_person(
                admin_target, semester=semester, is_self=False, can_edit_roles=True,
                membership=Membership.objects.get(person=admin_target),
            )['is_admin'],
        )
        self.assertFalse(
            serialize_person(
                non_admin_target, semester=semester, is_self=False, can_edit_roles=True,
                membership=Membership.objects.get(person=non_admin_target),
            )['is_admin'],
        )

    def test_is_active_reflects_the_targets_actual_active_flag(self):
        """`is_active` (admin-viewing-a-teammate only) reads the target Person's real flag, not the viewer's (issue #469)."""
        semester = SemesterFactory()
        active_target = PersonFactory(name='Active Placeholder', is_active=True)
        inactive_target = PersonFactory(name='Inactive Placeholder', is_active=False)
        for person in (active_target, inactive_target):
            MembershipFactory(person=person, semester=semester)

        self.assertTrue(
            serialize_person(
                active_target, semester=semester, is_self=False, can_edit_roles=True,
                membership=Membership.objects.get(person=active_target),
            )['is_active'],
        )
        self.assertFalse(
            serialize_person(
                inactive_target, semester=semester, is_self=False, can_edit_roles=True,
                membership=Membership.objects.get(person=inactive_target),
            )['is_active'],
        )

    def test_invite_status_reflects_the_persons_must_change_password_flag(self):
        """`invite_status` (admin-viewing-a-teammate only) reads `must_change_password` directly (#482, ADR 0018)."""
        semester = SemesterFactory()
        must_change = PersonFactory(name='Must Change Placeholder', must_change_password=True)
        active = PersonFactory(name='Active Placeholder', password='a-strong-test-password-123')
        for person in (must_change, active):
            MembershipFactory(person=person, semester=semester)

        self.assertEqual(
            serialize_person(
                must_change, semester=semester, is_self=False, can_edit_roles=True,
                membership=Membership.objects.get(person=must_change),
            )['invite_status'],
            'must_change_password',
        )
        self.assertEqual(
            serialize_person(
                active, semester=semester, is_self=False, can_edit_roles=True,
                membership=Membership.objects.get(person=active),
            )['invite_status'],
            'active',
        )

    def test_role_entry_keys(self):
        """A `roles`/`available_roles` entry carries exactly `id`, `name`."""
        semester = SemesterFactory()
        person = PersonFactory(name='Self Placeholder')
        membership = MembershipFactory(person=person, semester=semester)
        PersonRoleFactory(person=person, role=RoleFactory(name='Bassist'))

        data = serialize_person(person, semester=semester, is_self=True, can_edit_roles=True, membership=membership)

        self.assertEqual(set(data['roles'][0].keys()), {'id', 'name'})
        self.assertEqual(set(data['available_roles'][0].keys()), {'id', 'name'})

    def test_available_roles_stays_ungrouped_two_roles_in_the_same_group_both_appear(self):
        """`available_roles` is flat, never collapsed by RoleGroup (issue #506).

        RoleGroup only drives the Setlist/Schedule cast tables' column
        collapsing (`frontend/src/lib/roleColumns.ts`) -- it has nothing
        to do with this picker. Locking this in as a regression guard: a
        future dev skimming ADR-0016 and seeing `Role.group` might
        plausibly "fix" this picker into grouping by mistake, deduplicating
        two same-group Roles into one option.
        """
        semester = SemesterFactory()
        person = PersonFactory(name='Self Placeholder')
        membership = MembershipFactory(person=person, semester=semester)
        shared_group = RoleGroupFactory(name='Guitars Placeholder')
        RoleFactory(name='Lead Guitar', group=shared_group)
        RoleFactory(name='Rhythm Guitar', group=shared_group)

        data = serialize_person(person, semester=semester, is_self=True, can_edit_roles=True, membership=membership)

        available_names = {role['name'] for role in data['available_roles']}
        self.assertIn('Lead Guitar', available_names)
        self.assertIn('Rhythm Guitar', available_names)
        self.assertEqual(len(data['available_roles']), 2)

    def test_song_row_keys(self):
        """A `songs` row carries exactly `song_id`, `song_title`, `artist`, `role_name` — never `is_role_mismatch`."""
        semester = SemesterFactory()
        person = PersonFactory(name='Self Placeholder')
        membership = MembershipFactory(person=person, semester=semester)
        song = SongFactory(semester=semester)
        SongRoleAssignmentFactory(song=song, person=person)

        data = serialize_person(person, semester=semester, is_self=True, can_edit_roles=True, membership=membership)

        self.assertEqual(set(data['songs'][0].keys()), {'song_id', 'song_title', 'artist', 'role_name'})

    def test_no_membership_omits_songs_and_recordings_but_not_roles_email_or_available_roles(self):
        """An unsaved Membership (the not-yet-rostered self case) omits `songs`/`recordings`, but not `roles` (issue #378, ADR-0014)."""
        semester = SemesterFactory()
        person = PersonFactory(name='Fresh Invite Placeholder')
        unsaved_membership = Membership(person=person, semester=semester)

        data = serialize_person(
            person, semester=semester, is_self=True, can_edit_roles=True, membership=unsaved_membership,
        )

        self.assertFalse(data['has_membership'])
        self.assertEqual(data['roles'], [])
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
        RehearsalSongFactory(
            song=SongFactory(semester=semester),
            rehearsal=RehearsalFactory(semester=semester, date=timezone.now().date()),
        )

        data = serialize_person_recordings(person, semester)

        self.assertEqual(
            set(data['upload_slots'][0].keys()),
            {'id', 'song_id', 'song_title', 'rehearsal_date', 'start_time', 'end_time'},
        )


class RecordingSlotOptionsForTests(TestCase):
    """`recording_slot_options_for()` only offers Rehearsals dated today or earlier (issue #395)."""

    def test_excludes_a_future_rehearsal(self):
        """A slot on a Rehearsal dated after today is never offered."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        RehearsalSongFactory(
            song=song, rehearsal=RehearsalFactory(semester=semester, date=timezone.now().date() + timedelta(days=1)),
        )

        self.assertEqual(recording_slot_options_for(semester), [])

    def test_includes_a_rehearsal_dated_today(self):
        """A slot on a Rehearsal dated today (not just strictly in the past) is offered."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        rehearsal_song = RehearsalSongFactory(
            song=song, rehearsal=RehearsalFactory(semester=semester, date=timezone.now().date()),
        )

        self.assertEqual([option.id for option in recording_slot_options_for(semester)], [rehearsal_song.pk])

    def test_includes_a_past_rehearsal(self):
        """A slot on a Rehearsal dated before today is offered."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        rehearsal_song = RehearsalSongFactory(
            song=song, rehearsal=RehearsalFactory(semester=semester, date=timezone.now().date() - timedelta(days=7)),
        )

        self.assertEqual([option.id for option in recording_slot_options_for(semester)], [rehearsal_song.pk])


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

    def test_invited_but_not_yet_active_person_still_shows_on_the_band_list(self):
        """A Person with no usable password (not yet invited, or invited-but-inactive) still shows on the Band list (issue #455) -- Membership alone gates the roster, not invite state."""
        semester = SemesterFactory()
        MembershipFactory(person=self.person, semester=semester)
        not_yet_active = PersonFactory(name='Not Yet Active Placeholder')  # unusable password by default
        MembershipFactory(person=not_yet_active, semester=semester)

        response = self.client.get(band_api_url())

        names = [row['name'] for row in response.json()['data']['members']]
        self.assertIn(self.person.name, names)
        self.assertIn(not_yet_active.name, names)
        self.assertEqual(response.json()['data']['member_count'], 2)

    def test_invite_status_is_absent_for_a_non_admin_viewer(self):
        """A plain member viewer's rows never carry `invite_status` (issue #455) -- that's an admin-only fact."""
        semester = SemesterFactory()
        not_yet_active = PersonFactory(name='Not Yet Active Placeholder')
        MembershipFactory(person=not_yet_active, semester=semester)

        response = self.client.get(band_api_url())

        row = response.json()['data']['members'][0]
        self.assertNotIn('invite_status', row)

    def test_invite_status_is_present_for_an_admin_viewer(self):
        """An admin viewer's row for a must-change-password Person carries `invite_status: 'must_change_password'` (issue #455, #482)."""
        semester = SemesterFactory()
        must_change = PersonFactory(name='Must Change Placeholder', must_change_password=True)
        MembershipFactory(person=must_change, semester=semester)
        admin_client(self)
        select(self, semester)

        response = self.client.get(band_api_url())

        row = response.json()['data']['members'][0]
        self.assertEqual(row['invite_status'], 'must_change_password')

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
        MembershipFactory(person=self.person, semester=semester)
        PersonRoleFactory(person=self.person, role=RoleFactory(name='Bassist'))
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


@override_settings(SECURE_SSL_REDIRECT=False)
class PersonApiViewOlderSemesterRecordingsTests(TestCase):
    """Issue #364: does an admin viewing an older, non-live Semester still get an Add-a-recording affordance?

    `get_viewing_semester()` honours an admin's session selection
    regardless of liveness (ADR 0010), and neither
    `serialize_person_recordings()` nor `recording_slot_options_for()`
    filter by `published_at` — see `scheduling/services.py`'s
    `person_recordings_for()`/`recording_slot_options_for()` docstrings.
    (`recording_slot_options_for()` does filter by Rehearsal date since
    issue #395 — dated today or earlier only — so this test uses an
    explicitly past-dated Rehearsal to stay eligible.) This test recreates
    the reported scenario end-to-end (an admin, a real Membership, and a
    real eligible `RehearsalSong` in an older, non-live Semester) to
    confirm the read model already exposes the affordance there, pinning
    that as a regression test rather than shipping a fix for a bug that
    isn't there.
    """

    def test_upload_slots_and_recordings_block_present_for_a_selected_older_semester(self):
        """Selecting an older, non-live Semester still returns a non-empty `upload_slots` and the `recordings` block."""
        older_semester = SemesterFactory()
        SemesterFactory()  # a strictly-later-published Semester, so `older_semester` is not the Live Semester.
        admin = admin_client(self)
        MembershipFactory(person=admin, semester=older_semester)
        rehearsal_song = RehearsalSongFactory(
            song=SongFactory(semester=older_semester),
            rehearsal=RehearsalFactory(semester=older_semester, date=timezone.now().date() - timedelta(days=1)),
        )
        select(self, older_semester)

        response = self.client.get(person_api_url(admin))

        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertIn('recordings', data)
        self.assertEqual(
            [slot['id'] for slot in data['recordings']['upload_slots']], [rehearsal_song.pk],
        )


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
        RehearsalSongFactory(
            song=SongFactory(semester=semester),
            rehearsal=RehearsalFactory(semester=semester, date=timezone.now().date()),
        )

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
    """`POST /api/members/<pk>/roles/` (issue #333, issue #232, retargeted at PersonRole by issue #378/ADR-0014)."""

    def setUp(self):
        """Build a Semester and log in as an ordinary member before each test."""
        self.semester = SemesterFactory()
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_first_submission_writes_a_standing_personrole_with_no_membership_required(self):
        """A first-time POST with no prior Membership writes a standing `PersonRole`, and creates no Membership."""
        role = RoleFactory()

        response = self.client.post(
            reverse('api-member-roles', args=[self.person.pk]),
            data={'role_ids': [role.pk]},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertTrue(PersonRole.objects.filter(person=self.person, role=role).exists())
        self.assertFalse(Membership.objects.filter(person=self.person, semester=self.semester).exists())

    def test_invalid_role_id_reports_a_non_field_error_without_writing(self):
        """A nonexistent Role id reports a non-field error via the write envelope rather than a 500."""
        response = self.client.post(
            reverse('api-member-roles', args=[self.person.pk]),
            data={'role_ids': [999999]},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['ok'])
        self.assertTrue(body['non_field_errors'])
        self.assertFalse(PersonRole.objects.filter(person=self.person).exists())


def admin_status_api_url(person):
    """Return `/api/members/<pk>/admin-status/` for `person`."""
    return reverse('api-member-admin-status', args=[person.pk])


@override_settings(SECURE_SSL_REDIRECT=False)
class PersonAdminStatusApiViewTests(TestCase):
    """`POST /api/members/<pk>/admin-status/` (issue #467): grant/revoke, gated by `AdminApiView`."""

    def setUp(self):
        """Log in as a synthetic admin before each test."""
        self.admin = admin_client(self)

    def test_anonymous_request_401s_not_302s(self):
        """An unauthenticated POST gets a JSON 401, never a redirect (ApiView's contract)."""
        self.client.logout()
        target = PersonFactory()

        response = self.client.post(
            admin_status_api_url(target), data={'is_admin': True}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 401)

    def test_non_admin_request_403s(self):
        """A logged-in non-admin gets a JSON 403 (AdminApiView's contract), never a redirect."""
        self.client.logout()
        member_client(self)
        target = PersonFactory()

        response = self.client.post(
            admin_status_api_url(target), data={'is_admin': True}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)

    def test_grants_admin_status_and_returns_the_fresh_person_payload(self):
        """A successful grant flips the flag and returns `data` with `is_admin: true`."""
        target = PersonFactory(is_admin=False)

        response = self.client.post(
            admin_status_api_url(target), data={'is_admin': True}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['ok'])
        self.assertTrue(body['data']['is_admin'])
        self.assertTrue(Person.objects.get(pk=target.pk).is_admin)

    def test_revokes_admin_status_when_another_active_admin_remains(self):
        """A successful revoke flips the flag and returns `data` with `is_admin: false`."""
        target = PersonFactory(is_admin=True, is_active=True)

        response = self.client.post(
            admin_status_api_url(target), data={'is_admin': False}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['ok'])
        self.assertFalse(body['data']['is_admin'])
        self.assertFalse(Person.objects.get(pk=target.pk).is_admin)

    def test_self_revoke_is_refused_as_ok_false_not_a_4xx(self):
        """Revoking your own admin status is a 200 with `ok: false`, not a 4xx -- a well-formed request refused, not malformed."""
        PersonFactory(is_admin=True, is_active=True)

        response = self.client.post(
            admin_status_api_url(self.admin), data={'is_admin': False}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['ok'])
        self.assertTrue(body['non_field_errors'])
        self.assertTrue(Person.objects.get(pk=self.admin.pk).is_admin)

    def test_revoking_the_last_active_admin_is_refused_as_ok_false(self):
        """The view reports `CannotRevokeLastActiveAdminError` as `ok: false`, never a 4xx.

        A live authenticated admin session can never itself trigger this
        guard through this endpoint -- the requesting admin, being active
        by dint of holding the session, always counts as "another active
        admin" for any target other than themselves (self-revoke has its
        own, earlier-checked guard). `apply_admin_status_change()` is
        patched to raise it directly so this test pins the view's own
        error-handling branch; `identity.tests.test_admin_status` covers
        the guard's real logic.
        """
        target = PersonFactory(is_admin=True, is_active=True)

        with patch(
            'scheduling.api_views.apply_admin_status_change',
            side_effect=CannotRevokeLastActiveAdminError(f'{target.name} is the last active admin and cannot be revoked.'),
        ):
            response = self.client.post(
                admin_status_api_url(target), data={'is_admin': False}, content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['ok'])
        self.assertTrue(body['non_field_errors'])


def deactivate_api_url(person):
    """Return `/api/members/<pk>/deactivate/` for `person`."""
    return reverse('api-member-deactivate', args=[person.pk])


def reactivate_api_url(person):
    """Return `/api/members/<pk>/reactivate/` for `person`."""
    return reverse('api-member-reactivate', args=[person.pk])


@override_settings(SECURE_SSL_REDIRECT=False)
class PersonDeactivationApiViewTests(TestCase):
    """`POST /api/members/<pk>/deactivate/` (issue #469): deactivate, gated by `AdminApiView`."""

    def setUp(self):
        """Log in as a synthetic admin before each test."""
        self.admin = admin_client(self)

    def test_anonymous_request_401s_not_302s(self):
        """An unauthenticated POST gets a JSON 401, never a redirect (ApiView's contract)."""
        self.client.logout()
        target = PersonFactory()

        response = self.client.post(deactivate_api_url(target))

        self.assertEqual(response.status_code, 401)

    def test_non_admin_request_403s(self):
        """A logged-in non-admin gets a JSON 403 (AdminApiView's contract), never a redirect."""
        self.client.logout()
        member_client(self)
        target = PersonFactory()

        response = self.client.post(deactivate_api_url(target))

        self.assertEqual(response.status_code, 403)

    def test_deactivates_and_returns_the_fresh_person_payload(self):
        """A successful deactivate flips `is_active` and returns `data` with `is_active: false`."""
        target = PersonFactory(is_active=True)

        response = self.client.post(deactivate_api_url(target))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['ok'])
        self.assertFalse(body['data']['is_active'])
        self.assertFalse(Person.objects.get(pk=target.pk).is_active)

    def test_self_deactivation_is_refused_as_ok_false_not_a_4xx(self):
        """Deactivating yourself is a 200 with `ok: false`, not a 4xx -- a well-formed request refused, not malformed."""
        response = self.client.post(deactivate_api_url(self.admin))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['ok'])
        self.assertTrue(body['non_field_errors'])
        self.assertTrue(Person.objects.get(pk=self.admin.pk).is_active)

    def test_deactivating_the_last_active_admin_is_refused_as_ok_false(self):
        """The view reports `CannotDeactivateLastActiveAdminError` as `ok: false`, never a 4xx.

        Patched the same way `test_revoking_the_last_active_admin_is_refused_as_ok_false`
        pins `PersonAdminStatusApiView`'s error-handling branch:
        `identity.tests.test_deactivation` covers the guard's real logic.
        """
        target = PersonFactory(is_admin=True, is_active=True)

        with patch(
            'scheduling.api_views.apply_person_deactivation',
            side_effect=CannotDeactivateLastActiveAdminError(
                f'{target.name} is the last active admin and cannot be deactivated.'
            ),
        ):
            response = self.client.post(deactivate_api_url(target))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['ok'])
        self.assertTrue(body['non_field_errors'])

    def test_deactivate_terminates_the_target_persons_live_session(self):
        """A logged-in target's session is destroyed the moment they're deactivated (ADR 0017)."""
        target = PersonFactory(password=PASSWORD, is_active=True)
        target_client = self.client_class()
        target_client.login(username=target.email, password=PASSWORD)
        self.assertIn('_auth_user_id', target_client.session)

        self.client.post(deactivate_api_url(target))

        from django.contrib.sessions.models import Session
        self.assertFalse(
            any(
                session.get_decoded().get('_auth_user_id') == str(target.pk)
                for session in Session.objects.all()
            )
        )


@override_settings(SECURE_SSL_REDIRECT=False)
class PersonReactivationApiViewTests(TestCase):
    """`POST /api/members/<pk>/reactivate/` (issue #469): reactivate, gated by `AdminApiView`."""

    def setUp(self):
        """Log in as a synthetic admin before each test."""
        self.admin = admin_client(self)

    def test_anonymous_request_401s_not_302s(self):
        """An unauthenticated POST gets a JSON 401, never a redirect (ApiView's contract)."""
        self.client.logout()
        target = PersonFactory(is_active=False)

        response = self.client.post(reactivate_api_url(target))

        self.assertEqual(response.status_code, 401)

    def test_non_admin_request_403s(self):
        """A logged-in non-admin gets a JSON 403 (AdminApiView's contract), never a redirect."""
        self.client.logout()
        member_client(self)
        target = PersonFactory(is_active=False)

        response = self.client.post(reactivate_api_url(target))

        self.assertEqual(response.status_code, 403)

    def test_reactivates_with_no_guard_and_returns_the_fresh_person_payload(self):
        """A successful reactivate flips `is_active` back and returns `data` with `is_active: true`."""
        target = PersonFactory(is_active=False)

        response = self.client.post(reactivate_api_url(target))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['ok'])
        self.assertTrue(body['data']['is_active'])
        self.assertTrue(Person.objects.get(pk=target.pk).is_active)

    def test_reactivate_leaves_admin_status_untouched(self):
        """Reactivating a deactivated admin leaves `is_admin` exactly as it was (ADR 0017)."""
        target = PersonFactory(is_active=False, is_admin=True)

        self.client.post(reactivate_api_url(target))

        self.assertTrue(Person.objects.get(pk=target.pk).is_admin)


def reset_password_api_url(person):
    """Return `/api/members/<pk>/reset-password/` for `person`."""
    return reverse('api-member-reset-password', args=[person.pk])


@override_settings(SECURE_SSL_REDIRECT=False)
class PersonPasswordResetApiViewTests(TestCase):
    """`POST /api/members/<pk>/reset-password/` (issue #483, ADR 0018): admin-relayed reset, gated by `AdminApiView`."""

    def setUp(self):
        """Log in as a synthetic admin before each test."""
        self.admin = admin_client(self)

    def test_anonymous_request_401s_not_302s(self):
        """An unauthenticated POST gets a JSON 401, never a redirect (ApiView's contract)."""
        self.client.logout()
        target = PersonFactory()

        response = self.client.post(reset_password_api_url(target))

        self.assertEqual(response.status_code, 401)

    def test_non_admin_request_403s(self):
        """A logged-in non-admin gets a JSON 403 (AdminApiView's contract), never a redirect."""
        self.client.logout()
        member_client(self)
        target = PersonFactory()

        response = self.client.post(reset_password_api_url(target))

        self.assertEqual(response.status_code, 403)

    def test_resets_password_and_returns_the_fresh_person_payload_and_temp_password(self):
        """A successful reset sets a usable password, flags `must_change_password`, and reveals the plaintext once."""
        target = PersonFactory(is_active=True, must_change_password=False)

        response = self.client.post(reset_password_api_url(target))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['ok'])
        temp_password = body['data']['temp_password']
        self.assertTrue(temp_password)
        refreshed = Person.objects.get(pk=target.pk)
        self.assertTrue(refreshed.must_change_password)
        self.assertTrue(refreshed.check_password(temp_password))
        self.assertEqual(body['data']['person']['id'], target.pk)

    def test_reset_on_a_deactivated_target_is_refused_as_ok_false_not_a_4xx(self):
        """Resetting a deactivated Person's password is a 200 with `ok: false`, not a 4xx."""
        target = PersonFactory(is_active=False)
        old_password_hash = target.password

        response = self.client.post(reset_password_api_url(target))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['ok'])
        self.assertTrue(body['non_field_errors'])
        self.assertEqual(Person.objects.get(pk=target.pk).password, old_password_hash)

    def test_self_reset_is_refused_as_ok_false_not_a_4xx(self):
        """Resetting your own password through this endpoint is a 200 with `ok: false`, not a 4xx."""
        old_password_hash = self.admin.password

        response = self.client.post(reset_password_api_url(self.admin))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['ok'])
        self.assertTrue(body['non_field_errors'])
        self.assertEqual(Person.objects.get(pk=self.admin.pk).password, old_password_hash)
