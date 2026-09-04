"""delete_rehearsals_with_recordings(): the whole-Rehearsal hard-delete cascade and its storage cleanup (issue #221)."""

from unittest.mock import patch

from botocore.exceptions import ClientError, EndpointConnectionError
from django.test import TestCase

from scheduling.factories import (
    ConflictFactory,
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
)
from scheduling.models import Conflict, Recording, Rehearsal, RehearsalSong
from scheduling.services import delete_rehearsals_with_recordings


class DeleteRehearsalsWithRecordingsServiceTests(TestCase):
    @patch('scheduling.services._recording_storage')
    def test_deletes_the_rehearsal_and_its_rehearsal_song_recording_and_conflict_cascade(self, recording_storage):
        """Deleting a Rehearsal cascades to its RehearsalSongs, Recordings and Conflicts, per the existing FK cascade."""
        rehearsal = RehearsalFactory()
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal)
        recording = RecordingFactory(rehearsal_song=rehearsal_song)
        conflict = ConflictFactory(rehearsal=rehearsal)

        with self.captureOnCommitCallbacks(execute=True):
            delete_rehearsals_with_recordings([rehearsal])

        self.assertFalse(Rehearsal.objects.filter(pk=rehearsal.pk).exists())
        self.assertFalse(RehearsalSong.objects.filter(pk=rehearsal_song.pk).exists())
        self.assertFalse(Recording.objects.filter(pk=recording.pk).exists())
        self.assertFalse(Conflict.objects.filter(pk=conflict.pk).exists())

    @patch('scheduling.services._recording_storage')
    def test_deletes_every_recording_object_from_storage_on_commit(self, recording_storage):
        """Every doomed Rehearsal's Recordings' object keys are requested for deletion, collected before the cascade."""
        client = recording_storage.return_value.connection.meta.client
        rehearsal = RehearsalFactory()
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal)
        RecordingFactory(rehearsal_song=rehearsal_song, file='recordings/one.mp3')
        RecordingFactory(rehearsal_song=rehearsal_song, file='recordings/two.mp3')

        with self.captureOnCommitCallbacks(execute=True):
            delete_rehearsals_with_recordings([rehearsal])

        deleted_keys = {call.kwargs['Key'] for call in client.delete_object.call_args_list}
        self.assertEqual(deleted_keys, {'recordings/one.mp3', 'recordings/two.mp3'})

    @patch('scheduling.services._recording_storage')
    def test_storage_deletion_is_registered_on_commit_not_inline(self, recording_storage):
        """A rolled-back deletion (callbacks never fired) touches no storage object."""
        client = recording_storage.return_value.connection.meta.client
        rehearsal = RehearsalFactory()
        RecordingFactory(rehearsal_song__rehearsal=rehearsal, file='recordings/never-fired.mp3')

        with self.captureOnCommitCallbacks(execute=False):
            delete_rehearsals_with_recordings([rehearsal])

        client.delete_object.assert_not_called()

    @patch('scheduling.services._recording_storage')
    def test_a_storage_failure_is_logged_and_does_not_raise(self, recording_storage):
        """A storage backend that raises is caught, logged, and never bubbles up or blocks the deletion."""
        client = recording_storage.return_value.connection.meta.client
        client.delete_object.side_effect = ClientError(
            {'Error': {'Code': '500', 'Message': 'Internal Error'}}, 'DeleteObject'
        )
        rehearsal = RehearsalFactory()
        RecordingFactory(rehearsal_song__rehearsal=rehearsal, file='recordings/flaky.mp3')

        with self.assertLogs('scheduling.services', level='ERROR'), self.captureOnCommitCallbacks(execute=True):
            delete_rehearsals_with_recordings([rehearsal])

        self.assertFalse(Rehearsal.objects.filter(pk=rehearsal.pk).exists())

    @patch('scheduling.services._recording_storage')
    def test_a_connection_level_storage_failure_is_also_caught(self, recording_storage):
        """A non-ClientError BotoCoreError (e.g. a network outage) is caught too, not just ClientError."""
        client = recording_storage.return_value.connection.meta.client
        client.delete_object.side_effect = EndpointConnectionError(endpoint_url='https://r2.example')
        rehearsal = RehearsalFactory()
        RecordingFactory(rehearsal_song__rehearsal=rehearsal, file='recordings/unreachable.mp3')

        with self.assertLogs('scheduling.services', level='ERROR'), self.captureOnCommitCallbacks(execute=True):
            delete_rehearsals_with_recordings([rehearsal])

        self.assertFalse(Rehearsal.objects.filter(pk=rehearsal.pk).exists())

    @patch('scheduling.services._recording_storage')
    def test_no_storage_call_when_the_rehearsal_has_no_recordings(self, recording_storage):
        """A Rehearsal with no Recordings triggers no on_commit storage work at all."""
        rehearsal = RehearsalFactory()

        with self.captureOnCommitCallbacks(execute=True):
            delete_rehearsals_with_recordings([rehearsal])

        recording_storage.return_value.connection.meta.client.delete_object.assert_not_called()

    def test_an_empty_list_does_nothing(self):
        """Calling with no Rehearsals is a no-op: no query, no on_commit registration."""
        delete_rehearsals_with_recordings([])
