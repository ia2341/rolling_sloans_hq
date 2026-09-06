"""semester_deletion_summary() and delete_semester(): the hard-delete cascade and its Recordings' storage objects (issue #171, ADR 0011).

The Django views that used to exercise `delete_semester()` through an
HTTP round trip were deleted by issue #341's cutover to the React SPA
(their surviving behavioural coverage lives in `test_semester_api.py`'s
`DeleteApiTests`/`DeletionSummaryApiTests`), but neither of those touches
the cascade's row-by-row detail or the R2 on_commit/storage-failure
handling this module pins directly against the service function — so
these two classes were kept rather than deleted with the rest of that
file.
"""

from unittest.mock import patch

from botocore.exceptions import ClientError, EndpointConnectionError
from django.test import TestCase

from identity.factories import PersonFactory
from identity.models import Person
from scheduling.factories import (
    ConflictFactory,
    MembershipFactory,
    MembershipRoleFactory,
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.models import (
    Conflict,
    Membership,
    MembershipRole,
    Recording,
    Rehearsal,
    RehearsalSong,
    Semester,
    Song,
)
from scheduling.services import (
    LiveSemesterDeletionError,
    delete_semester,
    get_live_semester,
    semester_deletion_summary,
)


class SemesterDeletionSummaryTests(TestCase):
    def test_counts_members_songs_rehearsals_and_recordings(self):
        """The summary counts exactly the rows scoped to the target Semester."""
        semester = SemesterFactory(draft=True)
        MembershipFactory.create_batch(2, semester=semester)
        SongFactory.create_batch(3, semester=semester)
        rehearsal = RehearsalFactory(semester=semester)
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal)
        RecordingFactory.create_batch(4, rehearsal_song=rehearsal_song)
        # A second Semester's rows must not leak into the count.
        other = SemesterFactory(draft=True)
        MembershipFactory(semester=other)

        summary = semester_deletion_summary(semester)

        self.assertEqual(summary.member_count, 2)
        self.assertEqual(summary.song_count, 3)
        self.assertEqual(summary.rehearsal_count, 1)
        self.assertEqual(summary.recording_count, 4)


class DeleteSemesterServiceTests(TestCase):
    @patch('scheduling.services._recording_storage')
    def test_refuses_to_delete_the_live_semester(self, recording_storage):
        """delete_semester() itself refuses the Live Semester, independent of any view."""
        live = SemesterFactory()
        self.assertEqual(get_live_semester(), live)

        with self.assertRaises(LiveSemesterDeletionError):
            delete_semester(live)

        self.assertTrue(Semester.objects.filter(pk=live.pk).exists())
        recording_storage.return_value.connection.meta.client.delete_object.assert_not_called()

    @patch('scheduling.services._recording_storage')
    def test_deletes_a_draft_semester_and_its_cascade(self, recording_storage):
        """Deleting a never-published draft removes it and every row scoped to it, but no Person."""
        draft = SemesterFactory(draft=True)
        person = PersonFactory()
        membership = MembershipFactory(semester=draft, person=person)
        MembershipRoleFactory(membership=membership)
        song = SongFactory(semester=draft)
        rehearsal = RehearsalFactory(semester=draft)
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, song=song)
        RecordingFactory(rehearsal_song=rehearsal_song)
        ConflictFactory(rehearsal=rehearsal, person=person)

        with self.captureOnCommitCallbacks(execute=True):
            delete_semester(draft)

        self.assertFalse(Semester.objects.filter(pk=draft.pk).exists())
        self.assertFalse(Membership.objects.filter(semester_id=draft.pk).exists())
        self.assertFalse(MembershipRole.objects.filter(membership__semester_id=draft.pk).exists())
        self.assertFalse(Song.objects.filter(semester_id=draft.pk).exists())
        self.assertFalse(Rehearsal.objects.filter(semester_id=draft.pk).exists())
        self.assertFalse(RehearsalSong.objects.filter(rehearsal__semester_id=draft.pk).exists())
        self.assertFalse(Conflict.objects.filter(rehearsal__semester_id=draft.pk).exists())
        self.assertFalse(Recording.objects.filter(rehearsal_song=rehearsal_song).exists())
        self.assertTrue(Person.objects.filter(pk=person.pk).exists())

    @patch('scheduling.services._recording_storage')
    def test_deletes_every_recording_object_from_storage_on_commit(self, recording_storage):
        """Every Recording's object key belonging to the Semester is requested for deletion after commit."""
        client = recording_storage.return_value.connection.meta.client
        draft = SemesterFactory(draft=True)
        rehearsal_song = RehearsalSongFactory(rehearsal__semester=draft)
        RecordingFactory(rehearsal_song=rehearsal_song, file='recordings/one.mp3')
        RecordingFactory(rehearsal_song=rehearsal_song, file='recordings/two.mp3')

        with self.captureOnCommitCallbacks(execute=True):
            delete_semester(draft)

        deleted_keys = {call.kwargs['Key'] for call in client.delete_object.call_args_list}
        self.assertEqual(deleted_keys, {'recordings/one.mp3', 'recordings/two.mp3'})

    @patch('scheduling.services._recording_storage')
    def test_storage_deletion_is_registered_on_commit_not_inline(self, recording_storage):
        """A rolled-back deletion (callbacks never fired) touches no storage object."""
        client = recording_storage.return_value.connection.meta.client
        draft = SemesterFactory(draft=True)
        RecordingFactory(rehearsal_song__rehearsal__semester=draft, file='recordings/never-fired.mp3')

        with self.captureOnCommitCallbacks(execute=False):
            delete_semester(draft)

        client.delete_object.assert_not_called()

    @patch('scheduling.services._recording_storage')
    def test_a_storage_failure_is_logged_and_does_not_raise(self, recording_storage):
        """A storage backend that raises is caught, logged, and never bubbles up or blocks the deletion."""
        client = recording_storage.return_value.connection.meta.client
        client.delete_object.side_effect = ClientError(
            {'Error': {'Code': '500', 'Message': 'Internal Error'}}, 'DeleteObject'
        )
        draft = SemesterFactory(draft=True)
        RecordingFactory(rehearsal_song__rehearsal__semester=draft, file='recordings/flaky.mp3')

        with self.assertLogs('scheduling.services', level='ERROR'), self.captureOnCommitCallbacks(execute=True):
            delete_semester(draft)

        # The Semester row deletion already committed; the storage failure changes nothing about that.
        self.assertFalse(Semester.objects.filter(pk=draft.pk).exists())

    @patch('scheduling.services._recording_storage')
    def test_a_connection_level_storage_failure_is_also_caught(self, recording_storage):
        """A non-ClientError BotoCoreError (e.g. a network outage) is caught too, not just ClientError."""
        client = recording_storage.return_value.connection.meta.client
        client.delete_object.side_effect = EndpointConnectionError(endpoint_url='https://r2.example')
        draft = SemesterFactory(draft=True)
        RecordingFactory(rehearsal_song__rehearsal__semester=draft, file='recordings/unreachable.mp3')

        with self.assertLogs('scheduling.services', level='ERROR'), self.captureOnCommitCallbacks(execute=True):
            delete_semester(draft)

        self.assertFalse(Semester.objects.filter(pk=draft.pk).exists())

    @patch('scheduling.services._recording_storage')
    def test_no_storage_call_when_the_semester_has_no_recordings(self, recording_storage):
        """A Semester with no Recordings triggers no on_commit storage work at all."""
        draft = SemesterFactory(draft=True)

        with self.captureOnCommitCallbacks(execute=True):
            delete_semester(draft)

        recording_storage.return_value.connection.meta.client.delete_object.assert_not_called()
