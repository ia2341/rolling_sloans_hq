"""reorder_songs(), song_deletion_summaries() and delete_songs_with_recordings(): the setlist edit grid's service seams (issue #179).

The Django views that used to exercise these through an HTTP round trip
(the setlist edit grid's reorder/add/delete-with-recording-cascade
gestures) were deleted by issue #341's cutover to the React SPA; the
`admin_client`/`member_client`/`select` helpers this module used to define
moved to `api_test_helpers.py`, which the surviving `/api/` test modules
now import instead. What's left here is the service layer itself, called
directly rather than through any view — the guarantee these three
functions make is unchanged by which HTTP layer calls them.
"""

from unittest.mock import patch

from botocore.exceptions import ClientError, EndpointConnectionError
from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import (
    RecordingFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.models import RehearsalSong, Song
from scheduling.services import (
    delete_songs_with_recordings,
    reorder_songs,
    song_deletion_summaries,
)


class ReorderSongsServiceTests(TestCase):
    def test_renumbers_survivors_to_a_contiguous_sequence_in_the_given_order(self):
        """reorder_songs() assigns 1..N following ordered_song_ids, regardless of prior positions."""
        semester = SemesterFactory()
        first = SongFactory(semester=semester, position=1)
        second = SongFactory(semester=semester, position=2)
        third = SongFactory(semester=semester, position=3)

        reorder_songs(semester, [third.pk, first.pk, second.pk])

        third.refresh_from_db()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(third.position, 1)
        self.assertEqual(first.position, 2)
        self.assertEqual(second.position, 3)

    def test_handles_a_deletion_in_the_middle_leaving_a_contiguous_sequence(self):
        """A shorter ordered_song_ids list (a mid-list deletion) still yields 1..N with no gap."""
        semester = SemesterFactory()
        first = SongFactory(semester=semester, position=1)
        middle = SongFactory(semester=semester, position=2)
        third = SongFactory(semester=semester, position=3)
        middle.delete()

        reorder_songs(semester, [first.pk, third.pk])

        first.refresh_from_db()
        third.refresh_from_db()
        self.assertEqual(first.position, 1)
        self.assertEqual(third.position, 2)


class SongDeletionSummariesServiceTests(TestCase):
    def test_counts_recordings_and_distinct_uploaders_per_song(self):
        """Each summary carries its Song's recording count and distinct-uploader count."""
        song = SongFactory()
        rehearsal_song = RehearsalSongFactory(song=song)
        uploader_a = PersonFactory()
        uploader_b = PersonFactory()
        RecordingFactory(rehearsal_song=rehearsal_song, uploaded_by=uploader_a)
        RecordingFactory(rehearsal_song=rehearsal_song, uploaded_by=uploader_a)
        RecordingFactory(rehearsal_song=rehearsal_song, uploaded_by=uploader_b)
        untouched = SongFactory(semester=song.semester)

        summaries = {s.song.pk: s for s in song_deletion_summaries([song, untouched])}

        self.assertEqual(summaries[song.pk].recording_count, 3)
        self.assertEqual(summaries[song.pk].uploader_count, 2)
        self.assertEqual(summaries[untouched.pk].recording_count, 0)
        self.assertEqual(summaries[untouched.pk].uploader_count, 0)


class DeleteSongsWithRecordingsServiceTests(TestCase):
    @patch('scheduling.services._recording_storage')
    def test_deletes_the_songs_and_their_rehearsal_song_and_recording_cascade(self, recording_storage):
        """Deleting a Song cascades to its RehearsalSongs and Recordings, per the existing FK cascade."""
        song = SongFactory()
        rehearsal_song = RehearsalSongFactory(song=song)
        recording = RecordingFactory(rehearsal_song=rehearsal_song)

        with self.captureOnCommitCallbacks(execute=True):
            delete_songs_with_recordings([song])

        self.assertFalse(Song.objects.filter(pk=song.pk).exists())
        self.assertFalse(RehearsalSong.objects.filter(pk=rehearsal_song.pk).exists())
        self.assertFalse(type(recording).objects.filter(pk=recording.pk).exists())

    @patch('scheduling.services._recording_storage')
    def test_deletes_every_recording_object_from_storage_on_commit(self, recording_storage):
        """Every doomed Song's Recordings' object keys are requested for deletion, collected before the cascade."""
        client = recording_storage.return_value.connection.meta.client
        song = SongFactory()
        rehearsal_song = RehearsalSongFactory(song=song)
        RecordingFactory(rehearsal_song=rehearsal_song, file='recordings/one.mp3')
        RecordingFactory(rehearsal_song=rehearsal_song, file='recordings/two.mp3')

        with self.captureOnCommitCallbacks(execute=True):
            delete_songs_with_recordings([song])

        deleted_keys = {call.kwargs['Key'] for call in client.delete_object.call_args_list}
        self.assertEqual(deleted_keys, {'recordings/one.mp3', 'recordings/two.mp3'})

    @patch('scheduling.services._recording_storage')
    def test_storage_deletion_is_registered_on_commit_not_inline(self, recording_storage):
        """A rolled-back deletion (callbacks never fired) touches no storage object."""
        client = recording_storage.return_value.connection.meta.client
        song = SongFactory()
        RecordingFactory(rehearsal_song__song=song, file='recordings/never-fired.mp3')

        with self.captureOnCommitCallbacks(execute=False):
            delete_songs_with_recordings([song])

        client.delete_object.assert_not_called()

    @patch('scheduling.services._recording_storage')
    def test_a_storage_failure_is_logged_and_does_not_raise(self, recording_storage):
        """A storage backend that raises is caught, logged, and never bubbles up or blocks the deletion."""
        client = recording_storage.return_value.connection.meta.client
        client.delete_object.side_effect = ClientError(
            {'Error': {'Code': '500', 'Message': 'Internal Error'}}, 'DeleteObject'
        )
        song = SongFactory()
        RecordingFactory(rehearsal_song__song=song, file='recordings/flaky.mp3')

        with self.assertLogs('scheduling.services', level='ERROR'), self.captureOnCommitCallbacks(execute=True):
            delete_songs_with_recordings([song])

        self.assertFalse(Song.objects.filter(pk=song.pk).exists())

    @patch('scheduling.services._recording_storage')
    def test_a_connection_level_storage_failure_is_also_caught(self, recording_storage):
        """A non-ClientError BotoCoreError (e.g. a network outage) is caught too, not just ClientError."""
        client = recording_storage.return_value.connection.meta.client
        client.delete_object.side_effect = EndpointConnectionError(endpoint_url='https://r2.example')
        song = SongFactory()
        RecordingFactory(rehearsal_song__song=song, file='recordings/unreachable.mp3')

        with self.assertLogs('scheduling.services', level='ERROR'), self.captureOnCommitCallbacks(execute=True):
            delete_songs_with_recordings([song])

        self.assertFalse(Song.objects.filter(pk=song.pk).exists())

    @patch('scheduling.services._recording_storage')
    def test_no_storage_call_when_the_songs_have_no_recordings(self, recording_storage):
        """A Song with no Recordings triggers no on_commit storage work at all."""
        song = SongFactory()

        with self.captureOnCommitCallbacks(execute=True):
            delete_songs_with_recordings([song])

        recording_storage.return_value.connection.meta.client.delete_object.assert_not_called()

    def test_an_empty_list_does_nothing(self):
        """Calling with no Songs is a no-op: no query, no on_commit registration."""
        delete_songs_with_recordings([])
