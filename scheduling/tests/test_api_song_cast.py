"""`/api/songs/<pk>/cast/{picker,preview,save}/`: the Song-level cast editor over HTTP (issue #499, ADR-0019).

Service-level derivation (`apply_song_cast_edits()`,
`preview_song_cast_edits()`, `song_cast_conflict_summary_for()`,
`assignment_picker_for()`) is covered by
`test_apply_song_cast_edits.py`/`test_preview_song_cast_edits.py`/
`test_song_cast_conflict_summary.py` — this file exercises the HTTP
boundary: gating, the envelope, staleness and the Requirement gate as
`ok: false`.
"""

import json
from datetime import time, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from scheduling.factories import (
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
from scheduling.models import Conflict, SongRoleAssignment
from scheduling.tests.api_test_helpers import admin_client, member_client, select


def _picker_url(song, role):
    """Return the Song-level cast picker endpoint for one (Song, Role) pair."""
    return reverse('api-song-cast-picker', args=[song.pk, role.pk])


def _preview_url(song):
    """Return the Cast editor's Preview endpoint for `song`."""
    return reverse('api-song-cast-preview', args=[song.pk])


def _save_url(song):
    """Return the Cast editor's Save endpoint for `song`."""
    return reverse('api-song-cast-save', args=[song.pk])


def _post_json(test_case, url, body):
    """POST `body` as a JSON request body and return `(response, parsed envelope)`."""
    response = test_case.client.post(url, data=json.dumps(body), content_type='application/json')
    return response, json.loads(response.content)


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessControlTests(TestCase):
    """The picker, Preview and Save endpoints gate identically to every other `AdminApiView`/`AdminPreviewApiView`."""

    def setUp(self):
        """Build a Semester with one Song and one Role so every endpoint has something to resolve against."""
        self.semester = SemesterFactory()
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()

    def test_anonymous_picker_get_is_401(self):
        """An anonymous GET to the picker answers the documented JSON 401, never a redirect."""
        response = self.client.get(_picker_url(self.song, self.role))

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_anonymous_preview_post_is_401(self):
        """An anonymous POST to Preview answers the documented JSON 401, never a redirect."""
        response = self.client.post(_preview_url(self.song), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_anonymous_save_post_is_401(self):
        """An anonymous POST to Save answers the documented JSON 401, never a redirect."""
        response = self.client.post(_save_url(self.song), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)

    def test_member_picker_get_is_403(self):
        """A logged-in non-admin is refused the picker — it carries Conflict reasons (ADR-0005)."""
        member_client(self)
        select(self, self.semester)

        response = self.client.get(_picker_url(self.song, self.role))

        self.assertEqual(response.status_code, 403)

    def test_member_save_post_is_403(self):
        """A logged-in non-admin cannot cast anyone."""
        member_client(self)
        select(self, self.semester)

        response = self.client.post(_save_url(self.song), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def test_a_song_from_another_semester_is_404_for_an_admin(self):
        """A Song outside the viewing Semester 404s on every endpoint (ADR-0001)."""
        admin_client(self)
        select(self, self.semester)
        other_song = SongFactory(semester=SemesterFactory(draft=True))

        self.assertEqual(self.client.get(_picker_url(other_song, self.role)).status_code, 404)
        self.assertEqual(
            self.client.post(_save_url(other_song), data='{}', content_type='application/json').status_code, 404,
        )


@override_settings(SECURE_SSL_REDIRECT=False)
class PickerTests(TestCase):
    """`GET /api/songs/<pk>/cast/picker/<role_id>/` — candidates, the declared split, and the conflict summary."""

    def setUp(self):
        """Log an admin in against a Semester with one Song on one future Rehearsal's Running Order."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()
        SongRoleRequirementFactory(song=self.song, role=self.role, count=1)
        self.rehearsal = RehearsalFactory(
            semester=self.semester, is_full_setlist=False, start_time=time(18, 0),
            date=timezone.localdate() + timedelta(days=7),
        )
        RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song, order=1, slot_count=1)

    def _get(self):
        """GET the picker for this Song/Role pair and return the parsed `data` block."""
        return json.loads(self.client.get(_picker_url(self.song, self.role)).content)['data']

    def test_payload_carries_exactly_the_documented_keys(self):
        """The picker's own shape — no Backup lists, no write-envelope fields."""
        data = self._get()

        self.assertEqual(
            set(data.keys()), {'song_id', 'song_title', 'role_id', 'role_name', 'declared', 'others'},
        )

    def test_declared_members_are_split_from_others(self):
        """A candidate who declared the Role lands in `declared`; one who hasn't lands in `others` (ADR-0014)."""
        declared = MembershipFactory(semester=self.semester).person
        PersonRoleFactory(person=declared, role=self.role)
        undeclared = MembershipFactory(semester=self.semester).person

        data = self._get()

        self.assertEqual([option['person_id'] for option in data['declared']], [declared.pk])
        self.assertEqual([option['person_id'] for option in data['others']], [undeclared.pk])

    def test_already_cast_person_is_excluded(self):
        """Someone already holding this (Song, Role) assignment is never re-offered."""
        membership = MembershipFactory(semester=self.semester)
        SongRoleAssignmentFactory(song=self.song, role=self.role, person=membership.person)

        data = self._get()

        offered = [option['person_id'] for option in [*data['declared'], *data['others']]]
        self.assertNotIn(membership.person.pk, offered)

    def test_a_candidate_with_no_conflicts_carries_an_empty_summary(self):
        """Every option carries a `conflicts` list, empty in the common case."""
        MembershipFactory(semester=self.semester)

        data = self._get()

        self.assertEqual(data['others'][0]['conflicts'], [])

    def test_a_conflicted_candidate_carries_the_rehearsal_date_and_reason(self):
        """The admin-only summary names the future Rehearsal and its reason (ADR-0005 admin surface)."""
        membership = MembershipFactory(semester=self.semester)
        ConflictFactory(
            person=membership.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT,
            reason='a synthetic reason string',
        )

        entry = self._get()['others'][0]['conflicts'][0]

        self.assertEqual(
            set(entry.keys()), {'rehearsal_id', 'date', 'is_full_conflict', 'reason'},
        )
        self.assertEqual(entry['date'], self.rehearsal.date.isoformat())
        self.assertEqual(entry['reason'], 'a synthetic reason string')

    def test_an_unknown_role_is_404(self):
        """A `role_id` naming no Role 404s rather than rendering an empty picker."""
        response = self.client.get(reverse('api-song-cast-picker', args=[self.song.pk, 999_999]))

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewTests(TestCase):
    """`POST /api/songs/<pk>/cast/preview/` — the write envelope, echoed values and blocked Buffers."""

    def setUp(self):
        """Log an admin in against a Semester whose Song already carries a removable cast member."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()
        SongRoleRequirementFactory(song=self.song, role=self.role, count=1)
        self.removable = SongRoleAssignmentFactory(song=self.song, role=self.role)
        self.membership = MembershipFactory(semester=self.semester)
        self.song.refresh_from_db()

    def _body(self, **overrides):
        """Build a well-formed Preview/Save request body for this Song."""
        body = {
            'song_updated_at': self.song.updated_at.isoformat(),
            'removed_assignment_ids': [],
            'added_entries': [],
        }
        body.update(overrides)
        return body

    def test_valid_preview_returns_fallout_and_echoes_values(self):
        """A well-formed Buffer previews `ok: true`, with a serialized Fallout and the normalized Buffer echoed back."""
        _, envelope = _post_json(self, _preview_url(self.song), self._body(
            added_entries=[{'role_id': self.role.pk, 'person_id': self.membership.person.pk}],
        ))

        self.assertTrue(envelope['ok'])
        self.assertEqual(
            set(envelope['fallout'].keys()),
            {'is_blocked', 'block_message', 'is_stale', 'pending_adds', 'pending_removals', 'loud', 'quiet'},
        )
        self.assertEqual(
            set(envelope['values'].keys()),
            {'song_id', 'song_updated_at', 'removed_assignment_ids', 'added_entries'},
        )

    def test_preview_carries_the_shared_context_envelope(self):
        """Every `/api/` response wears `context`, this one included (issue #326)."""
        _, envelope = _post_json(self, _preview_url(self.song), self._body())

        self.assertIn('context', envelope)

    def test_a_missing_song_updated_at_is_ok_false_not_a_400(self):
        """A body with no staleness stamp is a rejected Buffer (200, `ok: false`), never a hard 4xx."""
        response, envelope = _post_json(self, _preview_url(self.song), {'added_entries': []})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])

    def test_an_undecodable_body_is_a_400(self):
        """A body that isn't JSON at all is the one hard 400 this surface answers (issue #326)."""
        response = self.client.post(_preview_url(self.song), data='not json', content_type='application/json')

        self.assertEqual(response.status_code, 400)

    def test_a_requirement_less_role_is_reported_as_a_blocked_fallout(self):
        """A Requirement-less add previews as `is_blocked`, not as an exception (ADR-0015)."""
        unrequired_role = RoleFactory()

        _, envelope = _post_json(self, _preview_url(self.song), self._body(
            added_entries=[{'role_id': unrequired_role.pk, 'person_id': self.membership.person.pk}],
        ))

        self.assertTrue(envelope['fallout']['is_blocked'])
        self.assertTrue(envelope['fallout']['block_message'])


@override_settings(SECURE_SSL_REDIRECT=False)
class SaveTests(TestCase):
    """`POST /api/songs/<pk>/cast/save/` — the real, committing write."""

    def setUp(self):
        """Log an admin in against a Semester whose Song already carries a removable cast member."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()
        SongRoleRequirementFactory(song=self.song, role=self.role, count=1)
        self.removable = SongRoleAssignmentFactory(song=self.song, role=self.role)
        self.membership = MembershipFactory(semester=self.semester)
        self.song.refresh_from_db()

    def _body(self, **overrides):
        """Build a well-formed Save request body for this Song."""
        body = {
            'song_updated_at': self.song.updated_at.isoformat(),
            'removed_assignment_ids': [],
            'added_entries': [],
        }
        body.update(overrides)
        return body

    def test_valid_save_persists_and_does_not_echo_values(self):
        """A valid Save removes the old assignment, creates the new one, and answers with `values: null`."""
        _, envelope = _post_json(self, _save_url(self.song), self._body(
            removed_assignment_ids=[self.removable.pk],
            added_entries=[{'role_id': self.role.pk, 'person_id': self.membership.person.pk}],
        ))

        self.assertTrue(envelope['ok'])
        self.assertIsNone(envelope['values'])
        self.assertFalse(SongRoleAssignment.objects.filter(pk=self.removable.pk).exists())
        self.assertTrue(
            SongRoleAssignment.objects.filter(
                song=self.song, role=self.role, person=self.membership.person,
            ).exists()
        )

    def test_a_saved_cast_reaches_every_rehearsal_and_the_concert(self):
        """One Save writes one semester-wide row, not a per-Rehearsal copy (ADR-0019)."""
        RehearsalFactory(semester=self.semester)
        RehearsalFactory(semester=self.semester)

        _post_json(self, _save_url(self.song), self._body(
            added_entries=[{'role_id': self.role.pk, 'person_id': self.membership.person.pk}],
        ))

        self.assertEqual(
            SongRoleAssignment.objects.filter(
                song=self.song, role=self.role, person=self.membership.person,
            ).count(),
            1,
        )

    def test_a_stale_stamp_is_ok_false_and_writes_nothing(self):
        """A Buffer built before someone else's save is reported inline, never as a hard 4xx (ADR 0008)."""
        stale = (self.song.updated_at - timedelta(days=1)).isoformat()

        response, envelope = _post_json(self, _save_url(self.song), self._body(
            song_updated_at=stale, removed_assignment_ids=[self.removable.pk],
        ))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(SongRoleAssignment.objects.filter(pk=self.removable.pk).exists())

    def test_a_requirement_less_role_is_ok_false_and_writes_nothing(self):
        """A Requirement-less add is rejected inline and rolls back the rest of the Buffer (ADR-0015)."""
        unrequired_role = RoleFactory()

        response, envelope = _post_json(self, _save_url(self.song), self._body(
            removed_assignment_ids=[self.removable.pk],
            added_entries=[{'role_id': unrequired_role.pk, 'person_id': self.membership.person.pk}],
        ))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(SongRoleAssignment.objects.filter(pk=self.removable.pk).exists())

    def test_saving_advances_the_songs_stamp_so_a_replayed_body_is_refused(self):
        """The same body posted twice is refused the second time — the stamp moved (ADR-0019)."""
        body = self._body(added_entries=[{'role_id': self.role.pk, 'person_id': self.membership.person.pk}])

        _post_json(self, _save_url(self.song), body)
        _, envelope = _post_json(self, _save_url(self.song), body)

        self.assertFalse(envelope['ok'])
