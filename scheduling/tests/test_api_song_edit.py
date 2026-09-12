"""`/api/songs/<pk>/edit/{preview,save}/`: the Song page's two Buffers in one transaction (PR #502 review).

The Song page stages a Requirements Buffer and a cast Buffer behind one
Save popup (issue #499). Posting them to their own endpoints made two
independently committed transactions, so a Requirements save that
succeeded followed by a cast save that failed left a partial Song behind
— and made the preview disagree with the save, because each preview
request rolled back before the next began. These endpoints are the fix;
the per-surface endpoints stay for the Setlist's cast-only popover.
"""

import json
from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse

from scheduling.factories import (
    MembershipFactory,
    PersonRoleFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import SongRoleAssignment, SongRoleRequirement
from scheduling.tests.api_test_helpers import admin_client, member_client, select


def _preview_url(song):
    """Return the combined Song-edit Preview endpoint for `song`."""
    return reverse('api-song-edit-preview', args=[song.pk])


def _save_url(song):
    """Return the combined Song-edit Save endpoint for `song`."""
    return reverse('api-song-edit-save', args=[song.pk])


def _post_json(test_case, url, body):
    """POST `body` as a JSON request body and return `(response, parsed envelope)`."""
    response = test_case.client.post(url, data=json.dumps(body), content_type='application/json')
    return response, json.loads(response.content)


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessControlTests(TestCase):
    """Both endpoints gate like every other `AdminApiView`/`AdminPreviewApiView`."""

    def setUp(self):
        """Build a Semester with one Song so both endpoints have something to resolve against."""
        self.semester = SemesterFactory()
        self.song = SongFactory(semester=self.semester, position=1)

    def test_anonymous_preview_post_is_401(self):
        """An anonymous POST to Preview answers the documented JSON 401, never a redirect."""
        response = self.client.post(_preview_url(self.song), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_anonymous_save_post_is_401(self):
        """An anonymous POST to Save answers the documented JSON 401, never a redirect."""
        response = self.client.post(_save_url(self.song), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)

    def test_member_save_post_is_403(self):
        """A logged-in non-admin is refused the combined Save — editing a Song is admin-only."""
        member_client(self)
        select(self, self.semester)

        response = self.client.post(_save_url(self.song), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
class CombinedSongEditTests(TestCase):
    def setUp(self):
        """Build a Semester with one Song, one already-required Role, and a rostered Person who declares both Roles."""
        self.semester = SemesterFactory()
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()
        self.new_role = RoleFactory()
        SongRoleRequirementFactory(song=self.song, role=self.role, count=1)
        self.person = MembershipFactory(semester=self.semester).person
        PersonRoleFactory(person=self.person, role=self.role)
        PersonRoleFactory(person=self.person, role=self.new_role)
        self.song.refresh_from_db()
        self.semester.refresh_from_db()
        admin_client(self)
        select(self, self.semester)

    def _body(self, *, entries=None, removed_assignment_ids=(), added_entries=(), song_updated_at=None):
        """Build the combined wire body: the flat union of the Requirements and cast Buffer shapes."""
        if entries is None:
            entries = [{'role_id': self.role.pk, 'count': 1}]
        return {
            'semester_id': self.semester.pk,
            'semester_updated_at': self.semester.updated_at.isoformat(),
            'entries': entries,
            'song_updated_at': (song_updated_at or self.song.updated_at).isoformat(),
            'removed_assignment_ids': list(removed_assignment_ids),
            'added_entries': list(added_entries),
        }

    def test_save_commits_both_halves(self):
        """One request writes the Requirement change and the cast change together."""
        body = self._body(
            entries=[{'role_id': self.role.pk, 'count': 1}, {'role_id': self.new_role.pk, 'count': 1}],
            added_entries=[{'role_id': self.role.pk, 'person_id': self.person.pk}],
        )

        response, envelope = _post_json(self, _save_url(self.song), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertTrue(SongRoleRequirement.objects.filter(song=self.song, role=self.new_role).exists())
        self.assertTrue(
            SongRoleAssignment.objects.filter(song=self.song, role=self.role, person=self.person).exists()
        )

    def test_a_requirement_added_in_this_session_is_immediately_castable(self):
        """Casting onto a Role whose Requirement the same body adds works — Requirements apply first (ADR 0015)."""
        body = self._body(
            entries=[{'role_id': self.role.pk, 'count': 1}, {'role_id': self.new_role.pk, 'count': 1}],
            added_entries=[{'role_id': self.new_role.pk, 'person_id': self.person.pk}],
        )

        response, envelope = _post_json(self, _save_url(self.song), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertTrue(
            SongRoleAssignment.objects.filter(song=self.song, role=self.new_role, person=self.person).exists()
        )

    def test_preview_reports_a_session_added_requirement_as_castable_too(self):
        """Preview runs both halves in one rolled-back transaction, so it agrees with the Save above."""
        body = self._body(
            entries=[{'role_id': self.role.pk, 'count': 1}, {'role_id': self.new_role.pk, 'count': 1}],
            added_entries=[{'role_id': self.new_role.pk, 'person_id': self.person.pk}],
        )

        response, envelope = _post_json(self, _preview_url(self.song), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertFalse(envelope['fallout']['cast']['is_blocked'])
        self.assertEqual(
            [change['person_name'] for change in envelope['fallout']['cast']['pending_adds']],
            [self.person.name],
        )

    def test_preview_writes_nothing(self):
        """Preview's writes are rolled back — neither half survives the request (ADR 0008)."""
        body = self._body(
            entries=[{'role_id': self.role.pk, 'count': 1}, {'role_id': self.new_role.pk, 'count': 1}],
            added_entries=[{'role_id': self.new_role.pk, 'person_id': self.person.pk}],
        )

        _post_json(self, _preview_url(self.song), body)

        self.assertFalse(SongRoleRequirement.objects.filter(song=self.song, role=self.new_role).exists())
        self.assertFalse(SongRoleAssignment.objects.filter(song=self.song, person=self.person).exists())

    def test_a_failing_cast_half_rolls_back_the_requirements_half(self):
        """A stale cast stamp refuses the whole save — the Requirement change never commits on its own.

        The partial-save regression this endpoint exists to close: as two
        requests, the Requirements change committed and only the cast
        change was refused.
        """
        stale_stamp = self.song.updated_at - timedelta(days=1)
        body = self._body(
            entries=[{'role_id': self.role.pk, 'count': 1}, {'role_id': self.new_role.pk, 'count': 1}],
            added_entries=[{'role_id': self.role.pk, 'person_id': self.person.pk}],
            song_updated_at=stale_stamp,
        )

        response, envelope = _post_json(self, _save_url(self.song), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertFalse(SongRoleRequirement.objects.filter(song=self.song, role=self.new_role).exists())

    def test_a_session_with_no_cast_change_reports_a_null_cast_half(self):
        """An empty cast Buffer is skipped outright, so its stamp can never refuse a Requirements-only save."""
        body = self._body(entries=[{'role_id': self.role.pk, 'count': 2}])

        response, envelope = _post_json(self, _preview_url(self.song), body)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(envelope['fallout']['cast'])

    def test_a_wrong_semester_id_is_the_shared_409(self):
        """A body naming another Semester is refused before either half runs."""
        other = SemesterFactory()
        body = self._body()
        body['semester_id'] = other.pk

        response, _ = _post_json(self, _save_url(self.song), body)

        self.assertEqual(response.status_code, 409)

    def test_a_song_from_another_semester_is_404(self):
        """A Song outside the viewing Semester isn't found at all (ADR 0001)."""
        other_song = SongFactory(semester=SemesterFactory(), position=1)

        response = self.client.post(
            _save_url(other_song), data=json.dumps(self._body()), content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)
