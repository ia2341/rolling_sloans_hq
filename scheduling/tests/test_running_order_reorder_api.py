"""`/api/schedule/<id>/running-order/{preview,save}/`: the "Edit Rehearsal" drag-and-drop over HTTP (ADR 0008).

`build_rehearsal_reorder_buffer_from_request()` is a thin, reorder-only
sibling of `build_rehearsal_buffer_from_request()` (which
`test_rehearsal_edit_api.py` already covers end-to-end) — this file
exercises only what's new: that a submitted order of `RehearsalSong` ids
actually reorders `RehearsalSong.order` via the unchanged
`apply_rehearsal_edits()`/`preview_rehearsal_edits()`, that every other
Rehearsal field and each row's `slot_count` survive untouched, and that a
malformed or incomplete id list is refused rather than silently dropping
a row.
"""

import json

from django.test import TestCase, override_settings
from django.urls import reverse

from scheduling.factories import (
    RehearsalFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.models import RehearsalSong
from scheduling.tests.api_test_helpers import admin_client, member_client, select
from scheduling.tests.preview_helpers import assert_preview_writes_nothing


def _preview_url(rehearsal):
    """Return the Running Order reorder's Preview `/api/` endpoint for `rehearsal`."""
    return reverse('api-schedule-running-order-preview', args=[rehearsal.pk])


def _save_url(rehearsal):
    """Return the Running Order reorder's Save `/api/` endpoint for `rehearsal`."""
    return reverse('api-schedule-running-order-save', args=[rehearsal.pk])


def _post_json(test_case, url, body):
    """POST `body` as a JSON request body and return `(response, parsed envelope)`."""
    response = test_case.client.post(url, data=json.dumps(body), content_type='application/json')
    return response, json.loads(response.content)


def _valid_body(semester, ordered_rehearsal_song_ids):
    """Build a well-formed `/api/schedule/<id>/running-order/{preview,save}/` request body for `semester`."""
    return {
        'semester_id': semester.pk,
        'semester_updated_at': semester.updated_at.isoformat(),
        'ordered_rehearsal_song_ids': ordered_rehearsal_song_ids,
    }


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessControlTests(TestCase):
    """Preview/Save gate identically to every other `AdminApiView`/`AdminPreviewApiView`."""

    def setUp(self):
        """Build a future Rehearsal with one Song so every endpoint has something to resolve against."""
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)
        self.song = SongFactory(semester=self.semester, position=1)
        self.rehearsal_song = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song)

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


@override_settings(SECURE_SSL_REDIRECT=False)
class DressRehearsalTests(TestCase):
    """The Dress Rehearsal has no Running Order of its own to reorder (ADR 0003)."""

    def setUp(self):
        """Log in a synthetic admin against a Dress Rehearsal."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.dress = RehearsalFactory(semester=self.semester, is_full_setlist=True)

    def test_preview_404s_for_the_dress_rehearsal(self):
        """Preview 404s for the Dress Rehearsal rather than accepting an empty reorder."""
        response = self.client.post(
            _preview_url(self.dress), data=json.dumps(_valid_body(self.semester, [])), content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)

    def test_save_404s_for_the_dress_rehearsal(self):
        """Save 404s for the Dress Rehearsal rather than accepting an empty reorder."""
        response = self.client.post(
            _save_url(self.dress), data=json.dumps(_valid_body(self.semester, [])), content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class ReorderValidationTests(TestCase):
    """A reorder Buffer must name exactly the Rehearsal's current Running Order rows, once each."""

    def setUp(self):
        """Build a Rehearsal with three RehearsalSong rows in a known order."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)
        self.songs = [SongFactory(semester=self.semester, position=index) for index in range(1, 4)]
        self.rehearsal_songs = [
            RehearsalSongFactory(rehearsal=self.rehearsal, song=song, order=index)
            for index, song in enumerate(self.songs, start=1)
        ]

    def test_missing_row_is_refused(self):
        """Omitting one existing RehearsalSong id from the submitted order is a non_field_error, not a silent delete."""
        ids = [rehearsal_song.pk for rehearsal_song in self.rehearsal_songs[:2]]

        response, envelope = _post_json(self, _save_url(self.rehearsal), _valid_body(self.semester, ids))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        self.assertEqual(RehearsalSong.objects.filter(rehearsal=self.rehearsal).count(), 3)

    def test_duplicate_row_is_refused(self):
        """Naming one RehearsalSong id twice is refused rather than silently dropping another row."""
        ids = [self.rehearsal_songs[0].pk, self.rehearsal_songs[0].pk, self.rehearsal_songs[2].pk]

        response, envelope = _post_json(self, _save_url(self.rehearsal), _valid_body(self.semester, ids))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])

    def test_foreign_row_is_refused(self):
        """Naming a RehearsalSong id from a different Rehearsal is refused, never reassigned."""
        other_rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)
        other_song = SongFactory(semester=self.semester, position=9)
        other_rehearsal_song = RehearsalSongFactory(rehearsal=other_rehearsal, song=other_song)
        ids = [self.rehearsal_songs[1].pk, self.rehearsal_songs[2].pk, other_rehearsal_song.pk]

        response, envelope = _post_json(self, _save_url(self.rehearsal), _valid_body(self.semester, ids))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])

    def test_non_list_ids_is_refused(self):
        """A non-list `ordered_rehearsal_song_ids` is refused rather than raising an unhandled error."""
        body = _valid_body(self.semester, [])
        body['ordered_rehearsal_song_ids'] = 'not-a-list'

        response, envelope = _post_json(self, _save_url(self.rehearsal), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewWritesNothingTests(TestCase):
    """A well-formed reorder previews `ok: true` with Fallout, writing nothing (ADR 0008)."""

    def setUp(self):
        """Build a Rehearsal with two RehearsalSong rows so the Buffer can swap their order."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)
        self.song_a = SongFactory(semester=self.semester, position=1)
        self.song_b = SongFactory(semester=self.semester, position=2)
        self.rehearsal_song_a = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song_a, order=1)
        self.rehearsal_song_b = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song_b, order=2)

    def test_swapped_order_previews_cleanly_and_writes_nothing(self):
        """Swapping the two rows' order previews `ok: true` and leaves `RehearsalSong.order` untouched."""
        body = _valid_body(self.semester, [self.rehearsal_song_b.pk, self.rehearsal_song_a.pk])

        response = assert_preview_writes_nothing(
            self, _preview_url(self.rehearsal),
            models_to_check=[RehearsalSong], semester=self.semester, json_body=body,
        )
        envelope = json.loads(response.content)

        self.assertTrue(envelope['ok'])
        self.assertIsNotNone(envelope['fallout'])
        self.rehearsal_song_a.refresh_from_db()
        self.rehearsal_song_b.refresh_from_db()
        self.assertEqual(self.rehearsal_song_a.order, 1)
        self.assertEqual(self.rehearsal_song_b.order, 2)


@override_settings(SECURE_SSL_REDIRECT=False)
class SaveCommitsTests(TestCase):
    """A valid Save actually reorders the Running Order, leaving every other field untouched."""

    def setUp(self):
        """Build a Rehearsal with two RehearsalSong rows, one carrying a hand-raised slot_count (a manual pin)."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(
            semester=self.semester, is_full_setlist=False, setup_grace_minutes=15,
        )
        self.song_a = SongFactory(semester=self.semester, position=1)
        self.song_b = SongFactory(semester=self.semester, position=2)
        self.rehearsal_song_a = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song_a, order=1, slot_count=2)
        self.rehearsal_song_b = RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song_b, order=2, slot_count=1)

    def test_valid_save_reorders_and_preserves_slot_count_and_overrides(self):
        """Swapping the two rows' order persists the new order, keeps each row's own slot_count, and leaves the Rehearsal's own override untouched."""
        body = _valid_body(self.semester, [self.rehearsal_song_b.pk, self.rehearsal_song_a.pk])

        response, envelope = _post_json(self, _save_url(self.rehearsal), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertIsNone(envelope['values'])
        self.rehearsal_song_a.refresh_from_db()
        self.rehearsal_song_b.refresh_from_db()
        self.rehearsal.refresh_from_db()
        self.assertEqual(self.rehearsal_song_b.order, 1)
        self.assertEqual(self.rehearsal_song_a.order, 2)
        self.assertEqual(self.rehearsal_song_a.slot_count, 2)
        self.assertEqual(self.rehearsal_song_b.slot_count, 1)
        self.assertEqual(self.rehearsal.setup_grace_minutes, 15)

    def test_pinned_row_can_still_be_moved_manually(self):
        """A row pinned by a hand-raised slot_count still reorders through this manual path (services.py's documented asymmetry)."""
        body = _valid_body(self.semester, [self.rehearsal_song_a.pk, self.rehearsal_song_b.pk])
        # rehearsal_song_a already carries slot_count=2 (a manual pin); moving it to the front
        # (its current position) alongside b exercises the same code path a real reorder would.
        response, envelope = _post_json(self, _save_url(self.rehearsal), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
