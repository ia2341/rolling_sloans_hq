"""`/api/schedule/<id>/assignments/{picker,preview,save}/`: the assignment editor over HTTP (issue #338, ADR 0009).

Backend retargets `test_assignment_edit_mode.py`/`test_backup_picker.py`'s
HTML assertions onto JSON, following `test_setlist_api_preview_save.py`'s
shape. Service-level derivation (`apply_song_role_assignments()`,
`preview_song_role_assignments()`, `assignment_matrix_for()`,
`assignment_picker_for()`) is untouched and already covered by
`test_apply_song_role_assignments.py`/`test_preview_song_role_assignments.py`/
`test_backup.py` — this file exercises only what changed: the HTTP
boundary.
"""

import json
from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    BackupFactory,
    ConflictFactory,
    MembershipFactory,
    PersonRoleFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import (
    Backup,
    Conflict,
    SongRoleAssignment,
    SongRoleRequirement,
)
from scheduling.tests.api_test_helpers import (
    admin_client,
    member_client,
    select,
)
from scheduling.tests.preview_helpers import assert_preview_writes_nothing

PASSWORD = 'a-strong-test-password-123'


def _picker_url(rehearsal, song, role):
    """Return the picker `/api/` endpoint for one (Song, Role) cell on `rehearsal`'s grid."""
    return reverse('api-schedule-assignments-picker', args=[rehearsal.pk, song.pk, role.pk])


def _preview_url(rehearsal):
    """Return the assignment editor's Preview `/api/` endpoint for `rehearsal`."""
    return reverse('api-schedule-assignments-preview', args=[rehearsal.pk])


def _save_url(rehearsal):
    """Return the assignment editor's Save `/api/` endpoint for `rehearsal`."""
    return reverse('api-schedule-assignments-save', args=[rehearsal.pk])


def _schedule_url(rehearsal):
    """Return `/api/schedule/?rehearsal=<id>` for `rehearsal`."""
    return f"{reverse('api-schedule')}?rehearsal={rehearsal.pk}"


def _post_json(test_case, url, body):
    """POST `body` as a JSON request body and return `(response, parsed envelope)`."""
    response = test_case.client.post(url, data=json.dumps(body), content_type='application/json')
    return response, json.loads(response.content)


def _get_json(test_case, url):
    """GET `url` and return `(response, parsed envelope)`."""
    response = test_case.client.get(url)
    return response, json.loads(response.content)


def _valid_body(semester, **overrides):
    """Build a well-formed `/api/schedule/<id>/assignments/{preview,save}/` request body for `semester`."""
    body = {
        'semester_id': semester.pk,
        'semester_updated_at': semester.updated_at.isoformat(),
        'removed_assignment_ids': [],
        'added_entries': [],
        'removed_backup_ids': [],
        'added_backup_entries': [],
        'backup_covering_for_updates': [],
    }
    body.update(overrides)
    return body


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessControlTests(TestCase):
    """The picker, Preview and Save endpoints gate identically to every other `AdminApiView`/`AdminPreviewApiView`."""

    def setUp(self):
        """Build a future Rehearsal with one Song/Role so every endpoint has something to resolve against."""
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(semester=self.semester)
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()

    def test_anonymous_picker_get_is_401(self):
        """An anonymous GET to the picker answers the documented JSON 401, never a redirect."""
        response = self.client.get(_picker_url(self.rehearsal, self.song, self.role))

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_anonymous_preview_post_is_401(self):
        """An anonymous POST to Preview answers the documented JSON 401, never a redirect."""
        response = self.client.post(_preview_url(self.rehearsal), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_anonymous_save_post_is_401(self):
        """An anonymous POST to Save answers the documented JSON 401, never a redirect."""
        response = self.client.post(_save_url(self.rehearsal), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_non_admin_picker_get_is_403(self):
        """A logged-in non-admin's GET to the picker is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.get(_picker_url(self.rehearsal, self.song, self.role))

        self.assertEqual(response.status_code, 403)

    def test_non_admin_preview_post_is_403(self):
        """A logged-in non-admin's POST to Preview is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.post(_preview_url(self.rehearsal), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def test_non_admin_save_post_is_403(self):
        """A logged-in non-admin's POST to Save is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.post(_save_url(self.rehearsal), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def test_preview_get_is_not_allowed(self):
        """A GET to Preview is rejected — it is POST-only."""
        admin_client(self)

        response = self.client.get(_preview_url(self.rehearsal))

        self.assertEqual(response.status_code, 405)

    def test_picker_post_is_not_allowed(self):
        """A POST to the picker is rejected — it is GET-only."""
        admin_client(self)

        response = self.client.post(_picker_url(self.rehearsal, self.song, self.role))

        self.assertEqual(response.status_code, 405)


@override_settings(SECURE_SSL_REDIRECT=False)
class PastRehearsalTests(TestCase):
    """A past, non-Dress Rehearsal's grid is read-only (ADR-0009); the Dress Rehearsal stays editable as the backstop."""

    def setUp(self):
        """Log in a synthetic admin against a Semester holding one past Rehearsal and one past Dress Rehearsal."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        yesterday = timezone.localdate() - timedelta(days=1)
        self.past_rehearsal = RehearsalFactory(semester=self.semester, date=yesterday, is_full_setlist=False)
        self.past_dress = RehearsalFactory(
            semester=self.semester, date=yesterday - timedelta(days=1), is_full_setlist=True,
        )
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()

    def test_past_rehearsal_picker_404s(self):
        """The picker 404s for a past, non-Dress Rehearsal."""
        response = self.client.get(_picker_url(self.past_rehearsal, self.song, self.role))

        self.assertEqual(response.status_code, 404)

    def test_past_rehearsal_save_404s(self):
        """Save 404s for a past, non-Dress Rehearsal — never silently applying a removal/add."""
        response = self.client.post(
            _save_url(self.past_rehearsal), data=json.dumps(_valid_body(self.semester)), content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)

    def test_past_dress_rehearsal_save_is_not_404(self):
        """Save on the (past) Dress Rehearsal is not rejected as non-editable — it is the ADR-0009 backstop."""
        response = self.client.post(
            _save_url(self.past_dress), data=json.dumps(_valid_body(self.semester)), content_type='application/json',
        )

        self.assertNotEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class PickerTests(TestCase):
    """The picker's contents: declared-first ordering, the Backup section, and the conflict note (issue #338, story 15)."""

    def setUp(self):
        """Log in a synthetic admin against a Rehearsal with one Song/Role and a rostered declaring/non-declaring pair."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(semester=self.semester)
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()
        self.rehearsal_song = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song)
        self.declaring_membership = MembershipFactory(semester=self.semester)
        PersonRoleFactory(person=self.declaring_membership.person, role=self.role)
        self.other_membership = MembershipFactory(semester=self.semester)

    def test_declared_members_are_split_from_others(self):
        """A Person who declared the cell's Role lists under `declared`; everyone else rostered lists under `others`."""
        response, envelope = _get_json(self, _picker_url(self.rehearsal, self.song, self.role))

        self.assertEqual(response.status_code, 200)
        declared_ids = {option['person_id'] for option in envelope['data']['declared']}
        other_ids = {option['person_id'] for option in envelope['data']['others']}
        self.assertIn(self.declaring_membership.person_id, declared_ids)
        self.assertIn(self.other_membership.person_id, other_ids)
        self.assertNotIn(self.declaring_membership.person_id, other_ids)

    def test_already_assigned_person_is_excluded(self):
        """A Person already assigned to this exact (Song, Role) is offered nowhere in the picker."""
        SongRoleAssignmentFactory(song=self.song, role=self.role, person=self.declaring_membership.person)

        _response, envelope = _get_json(self, _picker_url(self.rehearsal, self.song, self.role))

        all_ids = {o['person_id'] for o in envelope['data']['declared'] + envelope['data']['others']}
        self.assertNotIn(self.declaring_membership.person_id, all_ids)

    def test_backup_section_is_populated_for_a_regular_rehearsal(self):
        """The Backup section's `rehearsal_song_id` names the cell's RehearsalSong for a regular Rehearsal."""
        _response, envelope = _get_json(self, _picker_url(self.rehearsal, self.song, self.role))

        self.assertEqual(envelope['data']['rehearsal_song_id'], self.rehearsal_song.pk)
        backup_ids = {o['person_id'] for o in envelope['data']['backup_declared'] + envelope['data']['backup_others']}
        self.assertIn(self.declaring_membership.person_id, backup_ids)

    def test_backup_section_is_empty_for_the_dress_rehearsal(self):
        """The Dress Rehearsal's picker returns `rehearsal_song_id: None` and empty Backup lists (ADR-0006)."""
        dress = RehearsalFactory(semester=self.semester, is_full_setlist=True)

        response, envelope = _get_json(self, _picker_url(dress, self.song, self.role))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(envelope['data']['rehearsal_song_id'])
        self.assertEqual(envelope['data']['backup_declared'], [])
        self.assertEqual(envelope['data']['backup_others'], [])

    def test_full_conflict_carries_a_bare_marker_and_no_reason_text(self):
        """A Person with a full Conflict for this Rehearsal is marked `has_conflict: True`, never their reason (ADR 0005)."""
        ConflictFactory(
            person=self.declaring_membership.person, rehearsal=self.rehearsal,
            type=Conflict.FULL_CONFLICT, reason='a private medical reason',
        )

        response, envelope = _get_json(self, _picker_url(self.rehearsal, self.song, self.role))

        option = next(
            o for o in envelope['data']['declared'] if o['person_id'] == self.declaring_membership.person_id
        )
        self.assertIs(option['has_conflict'], True)
        self.assertNotIn('conflict_note', option)
        self.assertNotIn('medical', response.content.decode())


@override_settings(SECURE_SSL_REDIRECT=False)
class WrongSemesterTests(TestCase):
    """A `semester_id` that doesn't match the viewing Semester hard-fails on both Preview and Save."""

    def setUp(self):
        """Log in a synthetic admin viewing one Semester, with a second Semester the Buffer will wrongly claim."""
        admin_client(self)
        self.viewing_semester = SemesterFactory()
        self.other_semester = SemesterFactory()
        select(self, self.viewing_semester)
        self.rehearsal = RehearsalFactory(semester=self.viewing_semester)

    def test_wrong_semester_id_previews_a_4xx(self):
        """Preview answers a wrong `semester_id` with a 4xx, not a 200 Validation Error."""
        response, envelope = _post_json(self, _preview_url(self.rehearsal), _valid_body(self.other_semester))

        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.assertEqual(envelope['error'], 'wrong_semester')

    def test_wrong_semester_id_save_is_a_4xx(self):
        """Save answers a wrong `semester_id` with a 4xx, not a 200 Validation Error."""
        response, envelope = _post_json(self, _save_url(self.rehearsal), _valid_body(self.other_semester))

        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.assertEqual(envelope['error'], 'wrong_semester')


@override_settings(SECURE_SSL_REDIRECT=False)
class StaleSemesterTests(TestCase):
    """A stale `semester_updated_at` is reported, never refused on Preview, and refused (without corrupting data) on Save."""

    def setUp(self):
        """Log in a synthetic admin against a Rehearsal/Song/Role, with a stamp a year behind reality."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(semester=self.semester)
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()
        RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song)
        self.person = MembershipFactory(semester=self.semester).person
        self.stale_stamp = self.semester.updated_at.replace(year=self.semester.updated_at.year - 1)

    def _stale_body(self):
        """Build a well-formed Buffer body whose `semester_updated_at` is the stale (year-behind) stamp."""
        return _valid_body(
            self.semester,
            semester_updated_at=self.stale_stamp.isoformat(),
            added_entries=[{'song_id': self.song.pk, 'role_id': self.role.pk, 'person_id': self.person.pk}],
        )

    def test_stale_preview_reports_is_stale_true_with_fallout_still_computed(self):
        """Preview against a stale stamp still computes Fallout and reports `is_stale: true`, `ok: true`."""
        response, envelope = _post_json(self, _preview_url(self.rehearsal), self._stale_body())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertIsNotNone(envelope['fallout'])
        self.assertTrue(envelope['fallout']['is_stale'])

    def test_stale_save_is_refused_without_corrupting_data(self):
        """Save against a stale stamp reports `ok: false` (not a hard 4xx) and creates no SongRoleAssignment."""
        response, envelope = _post_json(self, _save_url(self.rehearsal), self._stale_body())

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        self.assertFalse(SongRoleAssignment.objects.filter(song=self.song, role=self.role, person=self.person).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewWritesNothingTests(TestCase):
    """A mixed add+remove+Backup Buffer previews `ok: true` with Fallout and echoed `values`, writing nothing (ADR 0008)."""

    def setUp(self):
        """Build a Rehearsal with a removable Assignment, a removable Backup and roster to add fresh entries for."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(semester=self.semester)
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()
        self.rehearsal_song = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song)
        self.removable_assignment = SongRoleAssignmentFactory(song=self.song, role=self.role)
        self.removable_backup = BackupFactory(rehearsal_song=self.rehearsal_song, role=self.role)
        self.new_person = MembershipFactory(semester=self.semester).person
        self.new_backup_person = MembershipFactory(semester=self.semester).person

    def test_mixed_buffer_previews_ok_and_writes_nothing(self):
        """A Buffer removing an Assignment and a Backup while adding a fresh one of each previews cleanly and writes nothing."""
        body = _valid_body(
            self.semester,
            removed_assignment_ids=[self.removable_assignment.pk],
            added_entries=[{'song_id': self.song.pk, 'role_id': self.role.pk, 'person_id': self.new_person.pk}],
            removed_backup_ids=[self.removable_backup.pk],
            added_backup_entries=[{
                'rehearsal_song_id': self.rehearsal_song.pk, 'role_id': self.role.pk,
                'person_id': self.new_backup_person.pk, 'covering_for_id': None,
            }],
        )

        response = assert_preview_writes_nothing(
            self, _preview_url(self.rehearsal),
            models_to_check=[SongRoleAssignment, Backup], semester=self.semester, json_body=body,
        )
        envelope = json.loads(response.content)

        self.assertTrue(envelope['ok'])
        self.assertIsNotNone(envelope['values'])
        self.assertEqual(
            envelope['values']['added_entries'],
            [{'song_id': self.song.pk, 'role_id': self.role.pk, 'person_id': self.new_person.pk}],
        )


@override_settings(SECURE_SSL_REDIRECT=False)
class SaveCommitsTests(TestCase):
    """A valid Save actually persists the Buffer's removals/adds, and never echoes `values`."""

    def setUp(self):
        """Build a Rehearsal with a removable Assignment and one Person to add a fresh Assignment for."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(semester=self.semester)
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()
        RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song)
        self.removable_assignment = SongRoleAssignmentFactory(song=self.song, role=self.role)
        self.new_person = MembershipFactory(semester=self.semester).person

    def test_valid_save_persists_and_does_not_echo_values(self):
        """A valid Save removes the old Assignment, creates the new one, and answers with `values: null`."""
        body = _valid_body(
            self.semester,
            removed_assignment_ids=[self.removable_assignment.pk],
            added_entries=[{'song_id': self.song.pk, 'role_id': self.role.pk, 'person_id': self.new_person.pk}],
        )

        response, envelope = _post_json(self, _save_url(self.rehearsal), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertIsNone(envelope['values'])
        self.assertFalse(SongRoleAssignment.objects.filter(pk=self.removable_assignment.pk).exists())
        self.assertTrue(
            SongRoleAssignment.objects.filter(song=self.song, role=self.role, person=self.new_person).exists()
        )

    def test_duplicate_add_is_a_no_op(self):
        """Adding an entry that already exists as a SongRoleAssignment is a no-op, never an IntegrityError."""
        body = _valid_body(
            self.semester,
            added_entries=[{
                'song_id': self.removable_assignment.song_id,
                'role_id': self.removable_assignment.role_id,
                'person_id': self.removable_assignment.person_id,
            }],
        )

        response, envelope = _post_json(self, _save_url(self.rehearsal), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertEqual(
            SongRoleAssignment.objects.filter(
                song=self.removable_assignment.song, role=self.removable_assignment.role,
                person=self.removable_assignment.person,
            ).count(),
            1,
        )

    def test_adding_a_role_column_writes_no_song_role_requirement(self):
        """Assigning a Role nobody wrote a Requirement for still writes zero SongRoleRequirement rows (ADR-0009)."""
        addable_role = RoleFactory()
        body = _valid_body(
            self.semester,
            added_entries=[{'song_id': self.song.pk, 'role_id': addable_role.pk, 'person_id': self.new_person.pk}],
        )

        response, envelope = _post_json(self, _save_url(self.rehearsal), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertFalse(SongRoleRequirement.objects.filter(song=self.song, role=addable_role).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class BackupScopingTests(TestCase):
    """A Backup add/covering-for update is scoped to `rehearsal` — a hand-crafted request naming a different one is ignored."""

    def setUp(self):
        """Build two Rehearsals in one Semester, each with its own RehearsalSong for the same Song."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()
        self.rehearsal = RehearsalFactory(semester=self.semester)
        self.other_rehearsal = RehearsalFactory(semester=self.semester)
        self.rehearsal_song = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song)
        self.other_rehearsal_song = RehearsalSongFactory(rehearsal=self.other_rehearsal, song=self.song)
        self.person = MembershipFactory(semester=self.semester).person

    def test_backup_add_naming_a_different_rehearsals_slot_is_ignored(self):
        """A Backup add naming a RehearsalSong from a different Rehearsal in the same Semester is silently dropped."""
        body = _valid_body(
            self.semester,
            added_backup_entries=[{
                'rehearsal_song_id': self.other_rehearsal_song.pk, 'role_id': self.role.pk,
                'person_id': self.person.pk, 'covering_for_id': None,
            }],
        )

        response, envelope = _post_json(self, _save_url(self.rehearsal), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertFalse(Backup.objects.filter(rehearsal_song=self.other_rehearsal_song).exists())

    def test_covering_for_naming_a_non_standing_assignee_is_dropped_to_none(self):
        """A `covering_for_id` naming someone with no standing Assignment on that (Song, Role) is dropped to None, not refused."""
        body = _valid_body(
            self.semester,
            added_backup_entries=[{
                'rehearsal_song_id': self.rehearsal_song.pk, 'role_id': self.role.pk,
                'person_id': self.person.pk, 'covering_for_id': self.person.pk,
            }],
        )

        response, envelope = _post_json(self, _save_url(self.rehearsal), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        backup = Backup.objects.get(rehearsal_song=self.rehearsal_song, role=self.role, person=self.person)
        self.assertIsNone(backup.covering_for_id)


@override_settings(SECURE_SSL_REDIRECT=False)
class MemberVisibilityTests(TestCase):
    """`/api/schedule/` never carries `covering_for_name` for a non-admin viewer (ADR 0005, 0007)."""

    def setUp(self):
        """Build a Rehearsal with a Backup naming who it covers for."""
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(semester=self.semester)
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()
        self.rehearsal_song = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song)
        # A Backup needs a Role column to appear on (Role + Requirement/Assignment, per
        # assignment_matrix_for()), so this covered Person also holds the standing Assignment.
        self.standing_assignment = SongRoleAssignmentFactory(song=self.song, role=self.role)
        self.covered_person = self.standing_assignment.person
        self.backup = BackupFactory(rehearsal_song=self.rehearsal_song, role=self.role, covering_for=self.covered_person)
        member_client(self)
        select(self, self.semester)

    def test_member_payload_carries_no_covering_for_name_key(self):
        """A member's `/api/schedule/` payload has no `covering_for_name` key at all on the Backup's matrix entry — absent, not null."""
        response, envelope = _get_json(self, _schedule_url(self.rehearsal))

        self.assertEqual(response.status_code, 200)
        entry = self._backup_entry(envelope)
        self.assertNotIn('covering_for_name', entry)

    def _backup_entry(self, envelope):
        """Return the Backup's `AssignmentMatrixEntry` from the schedule payload's rehearsal-detail rows."""
        for row in envelope['data']['selected']['rows']:
            for cell in row['cells']:
                for entry in cell['entries']:
                    if entry['kind'] == 'backup':
                        return entry
        raise AssertionError('No backup entry found in the schedule payload.')

    def test_admin_payload_does_carry_covering_for_name(self):
        """An admin's `/api/schedule/` payload does carry `covering_for_name` on the same Backup entry."""
        self.client.logout()
        admin_client(self)
        select(self, self.semester)

        _response, envelope = _get_json(self, _schedule_url(self.rehearsal))

        entry = self._backup_entry(envelope)
        self.assertEqual(entry['covering_for_name'], self.covered_person.name)


@override_settings(SECURE_SSL_REDIRECT=False)
class AddableRolesTests(TestCase):
    """`/api/schedule/`'s rehearsal detail carries `addable_roles` for an admin, and omits it for a member (issue #338)."""

    def setUp(self):
        """Build a Rehearsal with one Song and one Role that isn't yet a matrix column."""
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(semester=self.semester)
        self.song = SongFactory(semester=self.semester, position=1)
        RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song)
        self.addable_role = RoleFactory()

    def test_admin_payload_carries_addable_roles(self):
        """An admin's rehearsal detail lists the Role not yet used as a column."""
        admin_client(self)
        select(self, self.semester)

        _response, envelope = _get_json(self, _schedule_url(self.rehearsal))

        addable_ids = {role['id'] for role in envelope['data']['selected']['addable_roles']}
        self.assertIn(self.addable_role.pk, addable_ids)

    def test_member_payload_has_no_addable_roles_key(self):
        """A member's rehearsal detail carries no `addable_roles` key at all."""
        member_client(self)
        select(self, self.semester)

        _response, envelope = _get_json(self, _schedule_url(self.rehearsal))

        self.assertNotIn('addable_roles', envelope['data']['selected'])


@override_settings(SECURE_SSL_REDIRECT=False)
class AvailableSongsTests(TestCase):
    """`/api/schedule/`'s rehearsal detail carries `available_songs` for an admin's song-swap dropdown (issue #406)."""

    def setUp(self):
        """Build a regular Rehearsal with one scheduled Song and one Song not yet scheduled here, plus a Dress Rehearsal."""
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)
        self.dress = RehearsalFactory(semester=self.semester, is_full_setlist=True)
        self.role = RoleFactory()
        self.song_scheduled = SongFactory(semester=self.semester, position=1)
        self.song_unscheduled = SongFactory(semester=self.semester, position=2)
        self.rehearsal_song = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song_scheduled)
        SongRoleRequirementFactory(song=self.song_unscheduled, role=self.role)
        self.assignment = SongRoleAssignmentFactory(song=self.song_unscheduled, role=self.role)

    def test_admin_payload_lists_every_setlist_song_with_its_cells(self):
        """An admin's rehearsal detail lists every setlist Song, including one not currently scheduled here, with its standing assignments as cells."""
        admin_client(self)
        select(self, self.semester)

        _response, envelope = _get_json(self, _schedule_url(self.rehearsal))

        options = {option['id']: option for option in envelope['data']['selected']['available_songs']}
        self.assertIn(self.song_scheduled.pk, options)
        self.assertIn(self.song_unscheduled.pk, options)
        unscheduled_option = options[self.song_unscheduled.pk]
        role_ids_with_entries = {
            cell['role_id'] for cell in unscheduled_option['cells'] if cell['entries']
        }
        self.assertIn(self.role.pk, role_ids_with_entries)
        entry = next(
            entry
            for cell in unscheduled_option['cells']
            for entry in cell['entries']
            if cell['role_id'] == self.role.pk
        )
        self.assertEqual(entry['person_id'], self.assignment.person_id)

    def test_member_payload_has_no_available_songs_key(self):
        """A member's rehearsal detail carries no `available_songs` key at all."""
        member_client(self)
        select(self, self.semester)

        _response, envelope = _get_json(self, _schedule_url(self.rehearsal))

        self.assertNotIn('available_songs', envelope['data']['selected'])

    def test_dress_rehearsal_has_no_available_songs_key(self):
        """The Dress Rehearsal has no RehearsalSong row to swap (ADR-0003), so it carries no `available_songs` key even for an admin."""
        admin_client(self)
        select(self, self.semester)

        _response, envelope = _get_json(self, _schedule_url(self.dress))

        self.assertNotIn('available_songs', envelope['data']['selected'])


@override_settings(SECURE_SSL_REDIRECT=False)
class AssignableRosterTests(TestCase):
    """`/api/schedule/`'s rehearsal detail carries `roster`/`conflicted_person_ids` for an admin, the "+" picker's client-side candidate source (issue #399), and omits both for a member."""

    def setUp(self):
        """Build a Rehearsal with a rostered declarer, a rostered non-declarer, and a Conflict on the non-declarer."""
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(semester=self.semester)
        self.role = RoleFactory()
        self.declarer = PersonFactory(name='Ada')
        MembershipFactory(person=self.declarer, semester=self.semester)
        PersonRoleFactory(person=self.declarer, role=self.role)
        self.conflicted = PersonFactory(name='Bea')
        MembershipFactory(person=self.conflicted, semester=self.semester)
        ConflictFactory(rehearsal=self.rehearsal, person=self.conflicted)

    def test_admin_payload_carries_roster_with_declared_role_ids(self):
        """An admin's rehearsal detail lists every rostered Person plus their declared Role ids."""
        admin_client(self)
        select(self, self.semester)

        _response, envelope = _get_json(self, _schedule_url(self.rehearsal))

        roster = {entry['person_id']: entry for entry in envelope['data']['selected']['roster']}
        self.assertEqual(roster[self.declarer.pk]['declared_role_ids'], [self.role.pk])
        self.assertEqual(roster[self.conflicted.pk]['declared_role_ids'], [])

    def test_admin_payload_carries_conflicted_person_ids(self):
        """An admin's rehearsal detail lists the Person ids with a Conflict on this Rehearsal, bare ids only (ADR 0005)."""
        admin_client(self)
        select(self, self.semester)

        _response, envelope = _get_json(self, _schedule_url(self.rehearsal))

        self.assertEqual(envelope['data']['selected']['conflicted_person_ids'], [self.conflicted.pk])

    def test_member_payload_has_no_roster_or_conflicted_person_ids_keys(self):
        """A member's rehearsal detail carries neither admin-only key — `conflicted_person_ids` would otherwise reveal an unassigned Member's Conflict (ADR 0005)."""
        member_client(self)
        select(self, self.semester)

        _response, envelope = _get_json(self, _schedule_url(self.rehearsal))

        self.assertNotIn('roster', envelope['data']['selected'])
        self.assertNotIn('conflicted_person_ids', envelope['data']['selected'])
