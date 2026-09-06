"""`/api/songs/<pk>/requirements/preview/` and `.../save/`: the Requirements editor surface over HTTP (issue #339, ADR 0008)."""

import json

from django.test import TestCase, override_settings
from django.urls import reverse

from scheduling.factories import (
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import SongRoleRequirement
from scheduling.tests.api_test_helpers import (
    admin_client,
    member_client,
    select,
)
from scheduling.tests.preview_helpers import assert_preview_writes_nothing


def _preview_url(song):
    """Return the Requirements Preview `/api/` endpoint's URL for `song`."""
    return reverse('api-song-requirements-preview', args=[song.pk])


def _save_url(song):
    """Return the Requirements Save `/api/` endpoint's URL for `song`."""
    return reverse('api-song-requirements-save', args=[song.pk])


def _post_json(test_case, url, body):
    """POST `body` (a dict) as a JSON request body and return the parsed response envelope."""
    response = test_case.client.post(url, data=json.dumps(body), content_type='application/json')
    return response, json.loads(response.content)


def _valid_body(semester, entries=None):
    """Build a well-formed `/api/songs/<pk>/requirements/{preview,save}/` request body for `semester`."""
    return {
        'semester_id': semester.pk,
        'semester_updated_at': semester.updated_at.isoformat(),
        'entries': entries if entries is not None else [],
    }


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessControlTests(TestCase):
    """Both endpoints gate identically to every other AdminApiView/AdminPreviewApiView."""

    def setUp(self):
        """Build a Song so a POST has something to resolve against."""
        self.semester = SemesterFactory()
        self.song = SongFactory(semester=self.semester)

    def test_anonymous_preview_post_is_401(self):
        """An anonymous POST to Preview answers the documented JSON 401, never a redirect."""
        response = self.client.post(_preview_url(self.song), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_anonymous_save_post_is_401(self):
        """An anonymous POST to Save answers the documented JSON 401, never a redirect."""
        response = self.client.post(_save_url(self.song), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_non_admin_preview_post_is_403(self):
        """A logged-in non-admin's POST to Preview is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.post(_preview_url(self.song), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def test_non_admin_save_post_is_403(self):
        """A logged-in non-admin's POST to Save is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.post(_save_url(self.song), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def test_preview_get_is_not_allowed(self):
        """A GET to Preview is rejected -- it is POST-only."""
        admin_client(self)

        response = self.client.get(_preview_url(self.song))

        self.assertEqual(response.status_code, 405)

    def test_save_get_is_not_allowed(self):
        """A GET to Save is rejected -- it is POST-only."""
        admin_client(self)

        response = self.client.get(_save_url(self.song))

        self.assertEqual(response.status_code, 405)


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewValidBufferTests(TestCase):
    """A valid Buffer's Preview renders Fallout, echoes `values`, and writes nothing."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one Song and two Roles (one to edit, one to add)."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester)
        self.existing_role = RoleFactory(name='Bass')
        self.new_role = RoleFactory(name='Drums')
        self.requirement = SongRoleRequirementFactory(song=self.song, role=self.existing_role, count=1)

    def test_valid_buffer_previews_ok_with_fallout_and_echoed_values_and_writes_nothing(self):
        """A mixed add+edit Buffer previews `ok: true` and writes nothing (issue #228's acceptance criteria)."""
        body = _valid_body(self.semester, entries=[
            {'role_id': self.existing_role.pk, 'count': 2},
            {'role_id': self.new_role.pk, 'count': 1},
        ])

        response = assert_preview_writes_nothing(
            self, _preview_url(self.song), models_to_check=[SongRoleRequirement], semester=self.semester,
            json_body=body,
        )
        envelope = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertIn('context', envelope)
        self.assertIsNotNone(envelope['fallout'])
        self.assertEqual(len(envelope['fallout']['pending_edits']), 1)
        self.assertEqual(envelope['fallout']['pending_edits'][0]['role_name'], 'Bass')
        self.assertEqual(len(envelope['fallout']['pending_adds']), 1)
        self.assertEqual(envelope['fallout']['pending_adds'][0]['role_name'], 'Drums')
        self.assertIsNotNone(envelope['values'])
        self.assertEqual(envelope['errors'], {})
        self.assertEqual(envelope['non_field_errors'], [])

    def test_a_removal_previews_and_writes_nothing(self):
        """A Buffer that would delete the only Requirement previews the removal and writes nothing."""
        body = _valid_body(self.semester, entries=[])

        response = assert_preview_writes_nothing(
            self, _preview_url(self.song), models_to_check=[SongRoleRequirement], semester=self.semester,
            json_body=body,
        )
        envelope = json.loads(response.content)

        self.assertTrue(envelope['ok'])
        self.assertEqual(len(envelope['fallout']['pending_removals']), 1)
        self.assertEqual(envelope['fallout']['pending_removals'][0]['role_name'], 'Bass')


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewInvalidBufferTests(TestCase):
    """A malformed Buffer previews `ok: false` with per-row errors, and still echoes every submitted value."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one Song and one Role."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester)
        self.role = RoleFactory()

    def test_count_below_one_previews_ok_false_with_a_row_error(self):
        """A row with count 0 previews HTTP 200, `ok: false`, with a per-row count error, and echoes the raw values."""
        body = _valid_body(self.semester, entries=[{'role_id': self.role.pk, 'count': 0}])

        response, envelope = _post_json(self, _preview_url(self.song), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertIn('context', envelope)
        self.assertIsNone(envelope['fallout'])
        row_key = f'role-{self.role.pk}'
        self.assertIn(row_key, envelope['errors'])
        self.assertIn('count', envelope['errors'][row_key])
        self.assertIsNotNone(envelope['values'])

    def test_unknown_role_previews_ok_false(self):
        """A role_id naming no Role previews `ok: false` with a per-row error."""
        body = _valid_body(self.semester, entries=[{'role_id': 999999, 'count': 1}])

        response, envelope = _post_json(self, _preview_url(self.song), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertIn('role-999999', envelope['errors'])

    def test_duplicate_role_previews_ok_false(self):
        """Two entries naming the same Role is a per-row Validation Error, not silent last-write-wins."""
        body = _valid_body(self.semester, entries=[
            {'role_id': self.role.pk, 'count': 1},
            {'role_id': self.role.pk, 'count': 2},
        ])

        response, envelope = _post_json(self, _preview_url(self.song), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])


@override_settings(SECURE_SSL_REDIRECT=False)
class WrongSemesterTests(TestCase):
    """A `semester_id` that doesn't match the viewing Semester hard-fails on both endpoints."""

    def setUp(self):
        """Log in a synthetic admin viewing one Semester, with a second Semester the Buffer will wrongly claim."""
        admin_client(self)
        self.viewing_semester = SemesterFactory()
        self.other_semester = SemesterFactory()
        select(self, self.viewing_semester)
        self.song = SongFactory(semester=self.viewing_semester)

    def test_wrong_semester_id_previews_a_4xx(self):
        """Preview answers a wrong semester_id with a 4xx, not a 200 Validation Error."""
        body = _valid_body(self.other_semester)

        response, envelope = _post_json(self, _preview_url(self.song), body)

        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.assertEqual(envelope['error'], 'wrong_semester')

    def test_wrong_semester_id_save_is_a_4xx(self):
        """Save answers a wrong semester_id with a 4xx, not a 200 Validation Error."""
        body = _valid_body(self.other_semester)

        response, envelope = _post_json(self, _save_url(self.song), body)

        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.assertEqual(envelope['error'], 'wrong_semester')


@override_settings(SECURE_SSL_REDIRECT=False)
class StaleSemesterTests(TestCase):
    """A stale `semester_updated_at` is reported, never refused (ADR 0008), differently on Preview vs. Save."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one Song, and build a stamp a year behind reality."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester)
        self.role = RoleFactory()
        self.stale_stamp = self.semester.updated_at.replace(year=self.semester.updated_at.year - 1)

    def _stale_body(self):
        """Build a well-formed Buffer body whose semester_updated_at is the stale (year-behind) stamp."""
        return {
            'semester_id': self.semester.pk,
            'semester_updated_at': self.stale_stamp.isoformat(),
            'entries': [{'role_id': self.role.pk, 'count': 1}],
        }

    def test_stale_preview_reports_is_stale_true_with_fallout_still_computed(self):
        """Preview against a stale stamp still computes Fallout and reports is_stale: true, ok: true."""
        response, envelope = _post_json(self, _preview_url(self.song), self._stale_body())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertIsNotNone(envelope['fallout'])
        self.assertTrue(envelope['fallout']['is_stale'])

    def test_stale_save_is_refused_without_corrupting_data(self):
        """Save against a stale stamp reports ok: false (not a hard 4xx) and creates no Requirement."""
        response, envelope = _post_json(self, _save_url(self.song), self._stale_body())

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        self.assertFalse(SongRoleRequirement.objects.filter(song=self.song, role=self.role).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class SaveCommitsTests(TestCase):
    """A valid Save actually persists the Buffer, and never echoes `values`."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one Song and one Role."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester)
        self.role = RoleFactory()

    def test_valid_save_creates_the_requirement_and_does_not_echo_values(self):
        """A valid Save actually creates the Requirement in the database and answers with values: null."""
        body = _valid_body(self.semester, entries=[{'role_id': self.role.pk, 'count': 2}])

        response, envelope = _post_json(self, _save_url(self.song), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertIsNone(envelope['values'])
        self.assertIn('context', envelope)
        requirement = SongRoleRequirement.objects.get(song=self.song, role=self.role)
        self.assertEqual(requirement.count, 2)

    def test_invalid_save_does_not_echo_values(self):
        """An invalid Save's failure response also omits values (unlike Preview, which echoes on failure)."""
        body = _valid_body(self.semester, entries=[{'role_id': self.role.pk, 'count': 0}])

        response, envelope = _post_json(self, _save_url(self.song), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertIsNone(envelope['values'])


@override_settings(SECURE_SSL_REDIRECT=False)
class StructuralTests(TestCase):
    """The positive replacement for the deleted `NoPreviewEndpointTests` (issue #339 reverses that decision)."""

    def test_the_preview_route_resolves(self):
        """The Song-requirements preview route resolves under the `api-` namespace."""
        song = SongFactory()
        self.assertTrue(reverse('api-song-requirements-preview', args=[song.pk]))

    def test_preview_song_role_requirements_exists_and_is_callable(self):
        """services.preview_song_role_requirements exists and is callable."""
        import scheduling.services as services_module

        self.assertTrue(hasattr(services_module, 'preview_song_role_requirements'))
        self.assertTrue(callable(services_module.preview_song_role_requirements))
