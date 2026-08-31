"""Private recording-storage services (issue #51)."""

from unittest.mock import patch

from botocore.exceptions import ClientError
from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import RecordingFactory, RehearsalSongFactory
from scheduling.models import Recording
from scheduling.services import (
    MAX_RECORDING_FILE_SIZE,
    RecordingUploadError,
    confirm_recording_upload,
    create_recording_playback_url,
    reserve_recording_upload,
)


class RecordingUploadReservationTests(TestCase):
    """Tests for reserving direct-to-R2 upload slots."""

    @patch('scheduling.services._recording_storage')
    def test_rejects_unsupported_content_types_and_oversized_files(self, recording_storage):
        """Reservation rejects invalid client metadata before it contacts R2."""
        storage = recording_storage.return_value

        with self.assertRaises(RecordingUploadError):
            reserve_recording_upload('video/quicktime', 1)
        with self.assertRaises(RecordingUploadError):
            reserve_recording_upload('audio/mp4', MAX_RECORDING_FILE_SIZE + 1)

        storage.connection.meta.client.generate_presigned_post.assert_not_called()

    @patch('scheduling.services._recording_storage')
    def test_reserves_a_private_audio_upload_with_a_size_and_type_enforced_post_policy(
        self, recording_storage
    ):
        """Reservation returns an opaque object key and R2's signed POST policy, which itself
        caps the upload to the claimed content type and MAX_RECORDING_FILE_SIZE."""
        storage = recording_storage.return_value
        client = storage.connection.meta.client
        client.generate_presigned_post.return_value = {
            'url': 'https://r2.example/upload-bucket',
            'fields': {'key': 'recordings/whatever.m4a', 'Content-Type': 'audio/mp4'},
        }

        reservation = reserve_recording_upload('audio/mp4', 1_024)

        self.assertTrue(reservation.object_key.startswith('recordings/'))
        self.assertEqual(reservation.upload_url, 'https://r2.example/upload-bucket')
        self.assertEqual(reservation.fields, {'key': 'recordings/whatever.m4a', 'Content-Type': 'audio/mp4'})
        client.generate_presigned_post.assert_called_once_with(
            Bucket=storage.bucket_name,
            Key=reservation.object_key,
            Fields={'Content-Type': 'audio/mp4'},
            Conditions=[
                {'Content-Type': 'audio/mp4'},
                ['content-length-range', 1, MAX_RECORDING_FILE_SIZE],
            ],
            ExpiresIn=900,
        )


class RecordingUploadConfirmationTests(TestCase):
    """Tests for validating uploaded R2 objects before recording them."""

    @patch('scheduling.services._recording_storage')
    def test_persists_metadata_from_the_uploaded_object_not_client_claims(self, recording_storage):
        """Confirmation trusts R2's HEAD response for the newly persisted Recording metadata."""
        storage = recording_storage.return_value
        rehearsal_song = RehearsalSongFactory()
        uploader = PersonFactory()
        client = storage.connection.meta.client
        client.head_object.return_value = {'ContentType': 'audio/mpeg', 'ContentLength': 2_048}

        recording = confirm_recording_upload(
            rehearsal_song,
            uploader,
            'recordings/take.mp3',
            note='Final take',
        )

        self.assertEqual(recording.rehearsal_song, rehearsal_song)
        self.assertEqual(recording.uploaded_by, uploader)
        self.assertEqual(recording.file.name, 'recordings/take.mp3')
        self.assertEqual(recording.content_type, 'audio/mpeg')
        self.assertEqual(recording.file_size, 2_048)
        self.assertEqual(recording.note, 'Final take')
        client.head_object.assert_called_once_with(
            Bucket=storage.bucket_name,
            Key='recordings/take.mp3',
        )

    @patch('scheduling.services._recording_storage')
    def test_rejects_invalid_uploaded_objects_without_persisting_a_recording(self, recording_storage):
        """Confirmation rejects a non-audio or oversized R2 object before creating a Recording."""
        storage = recording_storage.return_value
        rehearsal_song = RehearsalSongFactory()
        uploader = PersonFactory()
        storage.connection.meta.client.head_object.return_value = {
            'ContentType': 'video/mp4',
            'ContentLength': MAX_RECORDING_FILE_SIZE + 1,
        }

        with self.assertRaises(RecordingUploadError):
            confirm_recording_upload(rehearsal_song, uploader, 'recordings/bad-file.mp4')

        self.assertFalse(Recording.objects.exists())

    @patch('scheduling.services._recording_storage')
    def test_rejects_an_object_key_that_was_never_uploaded(self, recording_storage):
        """Confirmation surfaces a missing R2 object as a RecordingUploadError, not a raw ClientError."""
        storage = recording_storage.return_value
        rehearsal_song = RehearsalSongFactory()
        uploader = PersonFactory()
        storage.connection.meta.client.head_object.side_effect = ClientError(
            {'Error': {'Code': '404', 'Message': 'Not Found'}}, 'HeadObject'
        )

        with self.assertRaises(RecordingUploadError):
            confirm_recording_upload(rehearsal_song, uploader, 'recordings/never-uploaded.mp3')

        self.assertFalse(Recording.objects.exists())

    @patch('scheduling.services._recording_storage')
    def test_rejects_confirming_the_same_object_key_twice(self, recording_storage):
        """Confirmation refuses to create a second Recording for an already-confirmed object key."""
        storage = recording_storage.return_value
        RecordingFactory(file='recordings/already-confirmed.mp3')
        storage.connection.meta.client.head_object.return_value = {
            'ContentType': 'audio/mpeg',
            'ContentLength': 2_048,
        }

        with self.assertRaises(RecordingUploadError):
            confirm_recording_upload(
                RehearsalSongFactory(),
                PersonFactory(),
                'recordings/already-confirmed.mp3',
            )

        self.assertEqual(Recording.objects.count(), 1)
        storage.connection.meta.client.head_object.assert_not_called()

    @patch('scheduling.services.Recording.objects.filter')
    @patch('scheduling.services._recording_storage')
    def test_rejects_a_concurrent_confirmation_that_slips_past_the_exists_check(
        self, recording_storage, filter_mock
    ):
        """The database's unique constraint on file, not just the exists() pre-check, guards against races."""
        storage = recording_storage.return_value
        storage.connection.meta.client.head_object.return_value = {
            'ContentType': 'audio/mpeg',
            'ContentLength': 2_048,
        }
        filter_mock.return_value.exists.return_value = False
        RecordingFactory(file='recordings/racing-confirm.mp3')

        with self.assertRaises(RecordingUploadError):
            confirm_recording_upload(
                RehearsalSongFactory(),
                PersonFactory(),
                'recordings/racing-confirm.mp3',
            )

        self.assertEqual(Recording.objects.count(), 1)


class RecordingPlaybackTests(TestCase):
    """Tests for issuing ephemeral private playback URLs."""

    @patch('scheduling.services._recording_storage')
    def test_generates_a_new_signed_get_url_for_every_playback_request(self, recording_storage):
        """Playback delegates every request to R2 instead of returning a permanent cached URL."""
        storage = recording_storage.return_value
        recording = RecordingFactory(file='recordings/take.m4a')
        client = storage.connection.meta.client
        client.generate_presigned_url.side_effect = [
            'https://r2.example/playback-one',
            'https://r2.example/playback-two',
        ]

        first_url = create_recording_playback_url(recording)
        second_url = create_recording_playback_url(recording)

        self.assertEqual(first_url, 'https://r2.example/playback-one')
        self.assertEqual(second_url, 'https://r2.example/playback-two')
        self.assertEqual(client.generate_presigned_url.call_count, 2)
        client.generate_presigned_url.assert_called_with(
            'get_object',
            Params={'Bucket': storage.bucket_name, 'Key': 'recordings/take.m4a'},
            ExpiresIn=900,
            HttpMethod='GET',
        )
