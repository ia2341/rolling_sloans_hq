"""Member recording upload self-service: /me/recordings/ + /me/recordings/presign/ (issue #61)."""

import json
from unittest.mock import patch

from botocore.exceptions import ClientError
from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import (
    RecordingFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.models import Recording

PASSWORD = 'a-strong-test-password-123'


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAccessTests(TestCase):
    def test_recordings_redirects_anonymous_users_to_login(self):
        """An anonymous GET to /me/recordings/ redirects to the login page."""
        url = reverse('scheduling:recordings')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_presign_rejects_anonymous_requests(self):
        """An anonymous POST to /me/recordings/presign/ is rejected rather than reserving an upload slot."""
        url = reverse('scheduling:recordings-presign')

        response = self.client.post(url, data='{}', content_type='application/json')

        self.assertNotEqual(response.status_code, 200)

    def test_delete_redirects_anonymous_users_to_login(self):
        """An anonymous POST to a Recording's delete URL redirects to the login page rather than deleting it."""
        recording = RecordingFactory()
        url = reverse('scheduling:recordings-delete', args=[recording.pk])

        response = self.client.post(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")
        self.assertTrue(Recording.objects.filter(pk=recording.pk).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class RecordingUploadViewGetTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_shows_no_active_semester_message_when_none_exists(self):
        """With no current Semester, the picker's queryset is empty rather than erroring."""
        response = self.client.get(reverse('scheduling:recordings'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['form'].fields['rehearsal_song'].queryset), [])
        self.assertContains(response, 'No songs have been scheduled into a rehearsal yet')

    def test_song_with_no_scheduled_slots_shows_a_message_naming_that_song(self):
        """`?song=<id>` for a Song with no RehearsalSong rows yet blames that Song, not the whole Semester."""
        semester = SemesterFactory()
        song_with_no_slots = SongFactory(semester=semester, title='Only Unscheduled Song')

        response = self.client.get(reverse('scheduling:recordings'), {'song': song_with_no_slots.pk})

        self.assertContains(response, 'Only Unscheduled Song')
        self.assertContains(response, "hasn't been scheduled into a rehearsal yet")
        self.assertNotContains(response, 'No songs have been scheduled into a rehearsal yet')

    def test_unscheduled_song_message_does_not_claim_the_semester_has_no_scheduled_songs(self):
        """With other Songs already scheduled, `?song=<unscheduled id>` must not claim none are (issue #121)."""
        semester = SemesterFactory()
        RehearsalSongFactory(rehearsal__semester=semester, song__semester=semester)
        song_with_no_slots = SongFactory(semester=semester, title='Skipped Number')

        response = self.client.get(reverse('scheduling:recordings'), {'song': song_with_no_slots.pk})

        self.assertNotContains(response, 'No songs have been scheduled into a rehearsal yet')
        self.assertContains(response, 'Skipped Number')
        self.assertContains(response, "hasn't been scheduled into a rehearsal yet")

    def test_unknown_song_param_falls_back_to_a_song_scoped_message(self):
        """A `?song=<id>` matching no current-Semester Song still scopes the message to that song, not the Semester."""
        semester = SemesterFactory()
        RehearsalSongFactory(rehearsal__semester=semester, song__semester=semester)

        response = self.client.get(reverse('scheduling:recordings'), {'song': 99_999})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'No songs have been scheduled into a rehearsal yet')
        self.assertContains(response, "hasn't been scheduled into a rehearsal yet")

    def test_semester_wide_empty_state_message_when_no_song_param_is_given(self):
        """Without `?song=`, an empty dropdown keeps the Semester-wide wording (issue #119, no regression)."""
        SemesterFactory()

        response = self.client.get(reverse('scheduling:recordings'))

        self.assertContains(response, 'No songs have been scheduled into a rehearsal yet')

    def test_no_empty_state_message_when_rehearsal_songs_are_available(self):
        """The empty-state message is absent once the current Semester has scheduled RehearsalSong rows."""
        semester = SemesterFactory()
        RehearsalSongFactory(rehearsal__semester=semester, song__semester=semester)

        response = self.client.get(reverse('scheduling:recordings'))

        self.assertNotContains(response, 'No songs have been scheduled into a rehearsal yet')

    def test_offers_only_the_current_semesters_rehearsal_songs(self):
        """The RehearsalSong picker is scoped to the current Semester, per get_current_semester()."""
        older_semester = SemesterFactory()
        current_semester = SemesterFactory()
        older_rehearsal_song = RehearsalSongFactory(rehearsal__semester=older_semester, song__semester=older_semester)
        current_rehearsal_song = RehearsalSongFactory(
            rehearsal__semester=current_semester, song__semester=current_semester,
        )

        response = self.client.get(reverse('scheduling:recordings'))

        choices = list(response.context['form'].fields['rehearsal_song'].queryset)
        self.assertIn(current_rehearsal_song, choices)
        self.assertNotIn(older_rehearsal_song, choices)

    def test_song_param_restricts_dropdown_to_that_songs_slots(self):
        """`?song=<id>` (issue #102) limits the picker to that Song's own RehearsalSong rows, not the whole Semester."""
        semester = SemesterFactory()
        target_song = SongFactory(semester=semester)
        other_song = SongFactory(semester=semester)
        target_rehearsal_song = RehearsalSongFactory(rehearsal__semester=semester, song=target_song)
        other_rehearsal_song = RehearsalSongFactory(rehearsal__semester=semester, song=other_song)

        response = self.client.get(reverse('scheduling:recordings'), {'song': target_song.pk})

        choices = list(response.context['form'].fields['rehearsal_song'].queryset)
        self.assertEqual(choices, [target_rehearsal_song])
        self.assertNotIn(other_rehearsal_song, choices)

    def test_omitting_song_param_returns_the_full_unfiltered_semester_dropdown(self):
        """Without `?song=`, every current-Semester RehearsalSong is offered, across all Songs (no regression)."""
        semester = SemesterFactory()
        first_rehearsal_song = RehearsalSongFactory(rehearsal__semester=semester, song__semester=semester)
        second_rehearsal_song = RehearsalSongFactory(rehearsal__semester=semester, song__semester=semester)

        response = self.client.get(reverse('scheduling:recordings'))

        choices = list(response.context['form'].fields['rehearsal_song'].queryset)
        self.assertIn(first_rehearsal_song, choices)
        self.assertIn(second_rehearsal_song, choices)

    def test_song_with_no_scheduled_slots_renders_an_empty_dropdown_without_erroring(self):
        """A Song with zero RehearsalSong rows yet renders a normal empty dropdown, not an error (issue #102)."""
        semester = SemesterFactory()
        song_with_no_slots = SongFactory(semester=semester)

        response = self.client.get(reverse('scheduling:recordings'), {'song': song_with_no_slots.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['form'].fields['rehearsal_song'].queryset), [])

    def test_non_numeric_song_param_returns_404(self):
        """A malformed `?song=` value 404s rather than raising a 500 from an invalid queryset lookup."""
        SemesterFactory()

        response = self.client.get(reverse('scheduling:recordings'), {'song': 'not-a-number'})

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class RecordingUploadViewPostTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person and create a current-Semester RehearsalSong before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.rehearsal_song = RehearsalSongFactory(rehearsal__semester=self.semester, song__semester=self.semester)

    @patch('scheduling.services._recording_storage')
    def test_confirm_creates_a_recording_owned_by_the_requesting_user(self, recording_storage):
        """A valid confirm POST creates a Recording scoped to the right RehearsalSong and uploader, then redirects."""
        storage = recording_storage.return_value
        storage.connection.meta.client.head_object.return_value = {
            'ContentType': 'audio/mpeg', 'ContentLength': 2_048,
        }

        response = self.client.post(reverse('scheduling:recordings'), data={
            'rehearsal_song': self.rehearsal_song.pk,
            'object_key': 'recordings/take-one.mp3',
            'note': 'First take',
        })

        self.assertRedirects(response, reverse('scheduling:recordings'))
        recording = Recording.objects.get()
        self.assertEqual(recording.rehearsal_song, self.rehearsal_song)
        self.assertEqual(recording.uploaded_by, self.person)
        self.assertEqual(recording.note, 'First take')

    def test_confirm_rejects_a_rehearsal_song_outside_the_song_param_scope(self):
        """A `?song=<id>` confirm POST rejects a RehearsalSong choice for a different Song (issue #102)."""
        other_song_rehearsal_song = RehearsalSongFactory(rehearsal__semester=self.semester, song__semester=self.semester)

        response = self.client.post(
            f"{reverse('scheduling:recordings')}?song={self.rehearsal_song.song_id}",
            data={
                'rehearsal_song': other_song_rehearsal_song.pk,
                'object_key': 'recordings/take-one.mp3',
                'note': '',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(Recording.objects.exists())

    @patch('scheduling.services._recording_storage')
    def test_confirm_surfaces_a_missing_upload_as_a_form_error_without_creating_a_recording(
        self, recording_storage
    ):
        """An object_key that was never actually uploaded to R2 re-renders the form instead of creating a Recording."""
        storage = recording_storage.return_value
        storage.connection.meta.client.head_object.side_effect = ClientError(
            {'Error': {'Code': '404', 'Message': 'Not Found'}}, 'HeadObject',
        )

        response = self.client.post(reverse('scheduling:recordings'), data={
            'rehearsal_song': self.rehearsal_song.pk,
            'object_key': 'recordings/never-uploaded.mp3',
            'note': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(Recording.objects.exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class RecordingPresignViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    @patch('scheduling.services._recording_storage')
    def test_valid_parameters_return_an_upload_reservation(self, recording_storage):
        """A supported content type and in-range size return 200 with the upload_url/fields/object_key."""
        storage = recording_storage.return_value
        storage.connection.meta.client.generate_presigned_post.return_value = {
            'url': 'https://r2.example/upload-bucket',
            'fields': {'key': 'recordings/whatever.mp3', 'Content-Type': 'audio/mpeg'},
        }

        response = self.client.post(
            reverse('scheduling:recordings-presign'),
            data=json.dumps({'content_type': 'audio/mpeg', 'file_size': 1_024}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['upload_url'], 'https://r2.example/upload-bucket')
        self.assertTrue(body['object_key'].startswith('recordings/'))
        self.assertEqual(body['fields'], {'key': 'recordings/whatever.mp3', 'Content-Type': 'audio/mpeg'})

    @patch('scheduling.services._recording_storage')
    def test_disallowed_extension_returns_a_4xx_without_contacting_r2(self, recording_storage):
        """An unsupported content type is rejected before the real R2 client is ever touched."""
        storage = recording_storage.return_value

        response = self.client.post(
            reverse('scheduling:recordings-presign'),
            data=json.dumps({'content_type': 'video/quicktime', 'file_size': 1_024}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        storage.connection.meta.client.generate_presigned_post.assert_not_called()

    @patch('scheduling.services._recording_storage')
    def test_oversized_file_returns_a_4xx_without_contacting_r2(self, recording_storage):
        """A file_size beyond the recording-upload limit is rejected before the real R2 client is ever touched."""
        storage = recording_storage.return_value

        response = self.client.post(
            reverse('scheduling:recordings-presign'),
            data=json.dumps({'content_type': 'audio/mpeg', 'file_size': 51 * 1024 * 1024}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        storage.connection.meta.client.generate_presigned_post.assert_not_called()

    def test_malformed_json_body_returns_a_4xx(self):
        """A body that isn't valid JSON is rejected with a 4xx rather than a 500."""
        response = self.client.post(
            reverse('scheduling:recordings-presign'), data='not json', content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)


@override_settings(SECURE_SSL_REDIRECT=False)
class RecordingDeleteViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_deletes_the_requesting_users_own_recording_and_redirects_to_the_song_detail_page(self):
        """A member deleting their own Recording removes it and redirects back to its Song's detail page."""
        rehearsal_song = RehearsalSongFactory()
        recording = RecordingFactory(rehearsal_song=rehearsal_song, uploaded_by=self.person)

        response = self.client.post(reverse('scheduling:recordings-delete', args=[recording.pk]))

        self.assertRedirects(response, reverse('scheduling:song-detail', args=[rehearsal_song.song_id]))
        self.assertFalse(Recording.objects.filter(pk=recording.pk).exists())

    def test_rejects_deletion_of_another_members_recording(self):
        """A member cannot delete a Recording they did not upload; the row survives and the request 404s."""
        other_recording = RecordingFactory()

        response = self.client.post(reverse('scheduling:recordings-delete', args=[other_recording.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Recording.objects.filter(pk=other_recording.pk).exists())

    def test_unknown_recording_returns_404(self):
        """A delete POST for a nonexistent Recording id 404s."""
        response = self.client.post(reverse('scheduling:recordings-delete', args=[999999]))

        self.assertEqual(response.status_code, 404)
