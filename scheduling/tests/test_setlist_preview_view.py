"""SetlistPreviewView: the Setlist edit surface's first Preview (issue #321, ADR 0008)."""

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from scheduling.factories import (
    RecordingFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.models import Recording, RehearsalSong, Song
from scheduling.tests.preview_helpers import assert_preview_writes_nothing
from scheduling.tests.test_setlist_reorder_add_delete import (
    admin_client,
    build_post_data,
    member_client,
    select,
)

PASSWORD = 'a-strong-test-password-123'


def _preview_url():
    """Return the Setlist Preview endpoint's URL."""
    return reverse('scheduling:setlist-edit-preview')


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewAccessControlTests(TestCase):
    def setUp(self):
        """Build a Semester so the preview route has something to resolve against."""
        self.semester = SemesterFactory()

    def test_anonymous_post_redirects_to_login(self):
        """An anonymous POST to the Preview endpoint redirects to login rather than running anything."""
        response = self.client.post(_preview_url(), {})

        self.assertRedirects(response, f"{reverse('identity:login')}?next={_preview_url()}")

    def test_non_admin_post_is_forbidden(self):
        """A logged-in non-admin's POST to the Preview endpoint is rejected with 403."""
        member_client(self)

        response = self.client.post(_preview_url(), {})

        self.assertEqual(response.status_code, 403)

    def test_get_is_not_allowed(self):
        """A GET to the Preview endpoint is rejected with 405 -- it is POST-only."""
        admin_client(self)

        response = self.client.get(_preview_url())

        self.assertEqual(response.status_code, 405)


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewRenderingTests(TestCase):
    def setUp(self):
        """Log in a synthetic admin Person against a Semester with three Songs."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.first = SongFactory(semester=self.semester, position=1, title='First', artist='Artist A')
        self.second = SongFactory(semester=self.semester, position=2, title='Second', artist='Artist B')

    def test_a_mixed_buffer_renders_fallout_and_pending_changes_and_writes_nothing(self):
        """A Preview POST with an edit, an add and a deletion together renders Fallout, writing nothing."""
        payload = build_post_data(self.semester, [
            {'song': self.first, 'title': 'First Edited'},
            {'song': self.second, 'deleted': True},
            {'title': 'Brand New Song', 'artist': 'New Artist', 'length': '3:15'},
        ])

        response = assert_preview_writes_nothing(
            self, _preview_url(), payload,
            models_to_check=[Song], semester=self.semester,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="setlist-fallout"')
        self.assertContains(response, 'Edit')
        self.assertContains(response, 'First Edited')
        self.assertContains(response, 'Brand New Song')
        self.assertContains(response, 'Delete Second')

    def test_invalid_formset_renders_validation_error_not_fallout(self):
        """A structurally invalid Buffer (a malformed length) renders a Validation Error banner, and writes nothing."""
        payload = build_post_data(self.semester, [{'song': self.first, 'length': 'not-a-length'}])

        response = assert_preview_writes_nothing(
            self, _preview_url(), payload,
            models_to_check=[Song], semester=self.semester,
        )

        self.assertContains(response, 'id="setlist-fallout-validation-error"')
        self.assertNotContains(response, 'id="setlist-fallout-pending"')

    def test_a_malformed_song_order_renders_validation_error_not_fallout(self):
        """A `song_order` that drops a surviving prefix is reported as a Validation Error, and writes nothing."""
        payload = build_post_data(self.semester, [{'song': self.first}, {'song': self.second}])
        payload['song_order'] = ['song-0']

        response = assert_preview_writes_nothing(
            self, _preview_url(), payload,
            models_to_check=[Song], semester=self.semester,
        )

        self.assertContains(response, 'id="setlist-fallout-validation-error"')

    def test_stale_stamp_renders_preview_with_a_banner_not_an_error_page(self):
        """A stale Semester.updated_at renders the Preview with a stale banner rather than refusing it."""
        stale_stamp = self.semester.updated_at.replace(year=self.semester.updated_at.year - 1)
        payload = build_post_data(self.semester, [{'song': self.first}, {'song': self.second}], stamp=stale_stamp.isoformat())

        response = assert_preview_writes_nothing(
            self, _preview_url(), payload,
            models_to_check=[Song], semester=self.semester,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="setlist-fallout-stale-banner"')
        self.assertContains(response, 'id="setlist-fallout-pending"')

    def test_no_semester_is_handled_gracefully(self):
        """With no viewing Semester at all, the Preview endpoint returns a response rather than crashing."""
        self.semester.delete()
        payload = build_post_data(self.semester, [])
        del payload['semester_updated_at']

        response = self.client.post(_preview_url(), payload)

        self.assertLess(response.status_code, 500)

    @patch('scheduling.services._recording_storage')
    def test_a_deletion_with_recordings_and_a_running_order_reports_a_loud_line(self, recording_storage):
        """Deleting a Song with Recordings and a Running Order row reports both counts as a loud Fallout line."""
        rehearsal_song = RehearsalSongFactory(song=self.first)
        RecordingFactory(rehearsal_song=rehearsal_song)
        payload = build_post_data(self.semester, [{'song': self.first, 'deleted': True}, {'song': self.second}])

        response = assert_preview_writes_nothing(
            self, _preview_url(), payload,
            models_to_check=[Song, Recording, RehearsalSong], semester=self.semester,
        )

        self.assertContains(response, 'id="setlist-fallout-loud"')
        self.assertContains(response, 'recording')
        self.assertContains(response, 'Running Order')

    def test_a_pure_reorder_reports_a_quiet_note_about_running_order(self):
        """Reordering the setlist with no other change reports a quiet note that Running Order is untouched."""
        payload = build_post_data(self.semester, [{'song': self.second}, {'song': self.first}])

        response = assert_preview_writes_nothing(
            self, _preview_url(), payload,
            models_to_check=[Song], semester=self.semester,
        )

        self.assertContains(response, 'id="setlist-fallout-quiet"')
        self.assertContains(response, 'concert position only')

    def test_an_unchanged_buffer_reports_no_pending_changes(self):
        """A Preview POST that changes nothing reports an empty pending-changes list."""
        payload = build_post_data(self.semester, [{'song': self.first}, {'song': self.second}])

        response = assert_preview_writes_nothing(
            self, _preview_url(), payload,
            models_to_check=[Song], semester=self.semester,
        )

        self.assertContains(response, 'No pending changes.')
