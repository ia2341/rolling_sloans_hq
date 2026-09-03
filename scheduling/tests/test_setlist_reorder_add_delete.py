"""The setlist edit grid's reorder, add and delete-with-recording-cascade gestures (issue #179)."""

from unittest.mock import patch

from botocore.exceptions import ClientError, EndpointConnectionError
from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import (
    RecordingFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.fields import format_song_length
from scheduling.models import RehearsalSong, Song
from scheduling.services import (
    VIEWING_SEMESTER_SESSION_KEY,
    delete_songs_with_recordings,
    reorder_songs,
    song_deletion_summaries,
)

PASSWORD = 'a-strong-test-password-123'


def admin_client(test_case):
    """Log a synthetic admin Person into `test_case`'s client and return that Person."""
    person = PersonFactory(password=PASSWORD, is_admin=True)
    test_case.client.login(username=person.email, password=PASSWORD)
    return person


def member_client(test_case):
    """Log a synthetic non-admin Person into `test_case`'s client and return that Person."""
    person = PersonFactory(password=PASSWORD)
    test_case.client.login(username=person.email, password=PASSWORD)
    return person


def select(test_case, semester):
    """Record `semester` as the client's session selection, mirroring `services.set_viewing_semester`."""
    session = test_case.client.session
    session[VIEWING_SEMESTER_SESSION_KEY] = semester.pk
    session.save()


def build_post_data(semester, rows, stamp=None, extra=None):
    """Build POST data for the setlist edit grid's save, mirroring what its JS submits (issue #179).

    `rows` lists the buffer in submitted (visual) order. Each entry is
    either `{'song': existing_song, ...field overrides, 'deleted': bool}`
    for an existing row, or a plain dict of field values (no 'song' key)
    for a brand-new row. Existing rows always occupy the low formset slots
    (`INITIAL_FORMS`) and new rows the slots after — mirroring the grid's
    JS, which never renames an existing row's slot on drag — while
    `song_order` carries the actual submitted (visual) order, in `rows`'
    given order, independent of slot index.
    """
    existing_rows = [row for row in rows if row.get('song') is not None]
    new_rows = [row for row in rows if row.get('song') is None]
    data = {
        'song-TOTAL_FORMS': str(len(existing_rows) + len(new_rows)),
        'song-INITIAL_FORMS': str(len(existing_rows)),
        'song-MIN_NUM_FORMS': '0',
        'song-MAX_NUM_FORMS': '1000',
    }
    for index, row in enumerate(existing_rows):
        prefix = f'song-{index}'
        song = row['song']
        data[f'{prefix}-id'] = str(song.pk)
        data[f'{prefix}-title'] = row.get('title', song.title)
        data[f'{prefix}-artist'] = row.get('artist', song.artist)
        data[f'{prefix}-length'] = row.get('length', format_song_length(song.length))
        data[f'{prefix}-notes'] = row.get('notes', song.notes)
        if row.get('deleted'):
            data[f'{prefix}-DELETE'] = 'on'
        row['_prefix'] = prefix
    for offset, row in enumerate(new_rows):
        prefix = f'song-{len(existing_rows) + offset}'
        data[f'{prefix}-id'] = ''
        data[f'{prefix}-title'] = row.get('title', '')
        data[f'{prefix}-artist'] = row.get('artist', '')
        data[f'{prefix}-length'] = row.get('length', '')
        data[f'{prefix}-notes'] = row.get('notes', '')
        if row.get('deleted'):
            data[f'{prefix}-DELETE'] = 'on'
        row['_prefix'] = prefix
    data['song_order'] = [row['_prefix'] for row in rows]
    data['semester_updated_at'] = stamp or semester.updated_at.isoformat()
    if extra:
        data.update(extra)
    return data


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


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistDeleteConfirmAccessTests(TestCase):
    def test_redirects_anonymous_users_to_login(self):
        """An anonymous POST to the confirm-delete endpoint redirects to the login page."""
        url = reverse('scheduling:setlist-edit-confirm-delete')

        response = self.client.post(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_is_forbidden_for_a_non_admin(self):
        """A logged-in non-admin's POST to the confirm-delete endpoint returns 403."""
        member_client(self)

        response = self.client.post(reverse('scheduling:setlist-edit-confirm-delete'))

        self.assertEqual(response.status_code, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistDeleteConfirmViewTests(TestCase):
    def test_names_each_requested_songs_recording_and_uploader_counts(self):
        """The confirmation fragment names each Song's title, recording count and distinct-uploader count."""
        semester = SemesterFactory()
        with_recordings = SongFactory(semester=semester, title='Song With Takes')
        rehearsal_song = RehearsalSongFactory(song=with_recordings)
        uploader = PersonFactory()
        RecordingFactory.create_batch(4, rehearsal_song=rehearsal_song, uploaded_by=uploader)
        RecordingFactory(rehearsal_song=rehearsal_song, uploaded_by=PersonFactory())
        RecordingFactory(rehearsal_song=rehearsal_song, uploaded_by=PersonFactory())
        without_recordings = SongFactory(semester=semester, title='Song With No Takes')
        admin_client(self)
        select(self, semester)

        response = self.client.post(
            reverse('scheduling:setlist-edit-confirm-delete'),
            {'song_id': [str(with_recordings.pk), str(without_recordings.pk)]},
        )

        self.assertContains(response, 'Song With Takes')
        self.assertContains(response, '6 recordings')
        self.assertContains(response, '3 members')
        self.assertContains(response, 'Song With No Takes')
        self.assertContains(response, 'no recordings')

    def test_ignores_a_song_id_outside_the_viewing_semester(self):
        """A song_id naming another Semester's Song is silently dropped, not a data leak across Semesters."""
        semester = SemesterFactory(draft=True)
        other_semester_song = SongFactory()
        admin_client(self)
        select(self, semester)

        response = self.client.post(
            reverse('scheduling:setlist-edit-confirm-delete'), {'song_id': [str(other_semester_song.pk)]},
        )

        self.assertNotContains(response, other_semester_song.title)


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistEditReorderTests(TestCase):
    def test_a_reordered_save_renumbers_songs_to_match_the_submitted_visual_order(self):
        """Dragging the last Song to the top and saving renumbers every Song to match, contiguously."""
        semester = SemesterFactory()
        first = SongFactory(semester=semester, position=1, title='First')
        second = SongFactory(semester=semester, position=2, title='Second')
        third = SongFactory(semester=semester, position=3, title='Third')
        admin_client(self)
        # Visual order: third, first, second -- but formset slots stay in original (factory) order.
        data = build_post_data(semester, [{'song': third}, {'song': first}, {'song': second}])

        response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertRedirects(response, reverse('scheduling:setlist'))
        third.refresh_from_db()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(third.position, 1)
        self.assertEqual(first.position, 2)
        self.assertEqual(second.position, 3)

    def test_move_up_and_move_down_controls_produce_the_same_reordering_as_drag(self):
        """A save whose visual order came from the move-up/down buttons reorders identically to a drag."""
        semester = SemesterFactory()
        first = SongFactory(semester=semester, position=1, title='First')
        second = SongFactory(semester=semester, position=2, title='Second')
        admin_client(self)
        data = build_post_data(semester, [{'song': second}, {'song': first}])

        self.client.post(reverse('scheduling:setlist-edit'), data)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(second.position, 1)
        self.assertEqual(first.position, 2)


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistEditAddTests(TestCase):
    def test_a_new_row_is_created_and_takes_its_submitted_position(self):
        """A brand-new (no id) row in the buffer is created as a Song at its submitted position."""
        semester = SemesterFactory()
        existing = SongFactory(semester=semester, position=1, title='Existing')
        admin_client(self)
        data = build_post_data(semester, [
            {'song': existing},
            {'title': 'Brand New Song', 'artist': 'New Artist', 'length': '3:00'},
        ])

        response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertRedirects(response, reverse('scheduling:setlist'))
        new_song = Song.objects.get(title='Brand New Song')
        self.assertEqual(new_song.semester, semester)
        self.assertEqual(new_song.position, 2)
        existing.refresh_from_db()
        self.assertEqual(existing.position, 1)

    def test_adding_is_repeatable_in_one_save(self):
        """Multiple new rows in one buffer are all created in one Save, not one round trip each."""
        semester = SemesterFactory()
        admin_client(self)
        data = build_post_data(semester, [
            {'title': 'Song A', 'artist': 'Artist A', 'length': '2:00'},
            {'title': 'Song B', 'artist': 'Artist B', 'length': '2:30'},
        ])

        self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertEqual(Song.objects.filter(semester=semester).count(), 2)
        positions = set(Song.objects.filter(semester=semester).values_list('position', flat=True))
        self.assertEqual(positions, {1, 2})

    def test_an_untouched_added_row_is_silently_dropped_not_saved(self):
        """An added-but-never-filled-in row (all blank) is dropped rather than crashing the save."""
        semester = SemesterFactory()
        existing = SongFactory(semester=semester, position=1, title='Existing')
        admin_client(self)
        data = build_post_data(semester, [{'song': existing}, {}])

        response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertRedirects(response, reverse('scheduling:setlist'))
        self.assertEqual(Song.objects.filter(semester=semester).count(), 1)


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistEditDeleteTests(TestCase):
    @patch('scheduling.services._recording_storage')
    def test_a_song_marked_deleted_is_removed_and_survivors_close_up_contiguously(self, recording_storage):
        """A struck row is gone after Save and the remaining Songs are renumbered with no gap."""
        semester = SemesterFactory()
        first = SongFactory(semester=semester, position=1, title='First')
        doomed = SongFactory(semester=semester, position=2, title='Doomed')
        third = SongFactory(semester=semester, position=3, title='Third')
        admin_client(self)
        data = build_post_data(semester, [
            {'song': first}, {'song': doomed, 'deleted': True}, {'song': third},
        ])

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertRedirects(response, reverse('scheduling:setlist'))
        self.assertFalse(Song.objects.filter(pk=doomed.pk).exists())
        first.refresh_from_db()
        third.refresh_from_db()
        self.assertEqual(first.position, 1)
        self.assertEqual(third.position, 2)

    @patch('scheduling.services._recording_storage')
    def test_a_song_with_recordings_can_be_deleted_and_its_recordings_are_gone(self, recording_storage):
        """Deleting a Song with Recordings succeeds; the Song and its Recordings are gone afterwards."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester, position=1, title='Has Takes')
        rehearsal_song = RehearsalSongFactory(song=song)
        recording = RecordingFactory(rehearsal_song=rehearsal_song)
        admin_client(self)
        select(self, semester)
        data = build_post_data(semester, [{'song': song, 'deleted': True}])

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertRedirects(response, reverse('scheduling:setlist'))
        self.assertFalse(Song.objects.filter(pk=song.pk).exists())
        self.assertFalse(type(recording).objects.filter(pk=recording.pk).exists())

    @patch('scheduling.services._recording_storage')
    def test_storage_deletion_for_a_saved_deletion_is_registered_on_commit(self, recording_storage):
        """A Save that deletes a Song requests its Recordings' storage objects only after the transaction commits."""
        client = recording_storage.return_value.connection.meta.client
        semester = SemesterFactory()
        song = SongFactory(semester=semester, position=1)
        rehearsal_song = RehearsalSongFactory(song=song)
        RecordingFactory(rehearsal_song=rehearsal_song, file='recordings/doomed.mp3')
        admin_client(self)
        select(self, semester)
        data = build_post_data(semester, [{'song': song, 'deleted': True}])

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('scheduling:setlist-edit'), data)

        client.delete_object.assert_called_once_with(Bucket=recording_storage.return_value.bucket_name, Key='recordings/doomed.mp3')

    @patch('scheduling.services._recording_storage')
    def test_a_storage_failure_on_save_is_logged_and_does_not_break_the_save(self, recording_storage):
        """A storage backend that raises during a Save's deletion is logged, never raised, and the Save still succeeds."""
        client = recording_storage.return_value.connection.meta.client
        client.delete_object.side_effect = ClientError(
            {'Error': {'Code': '500', 'Message': 'Internal Error'}}, 'DeleteObject'
        )
        semester = SemesterFactory()
        song = SongFactory(semester=semester, position=1)
        RecordingFactory(rehearsal_song__song=song, file='recordings/flaky.mp3')
        admin_client(self)
        select(self, semester)
        data = build_post_data(semester, [{'song': song, 'deleted': True}])

        with self.assertLogs('scheduling.services', level='ERROR'), self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertRedirects(response, reverse('scheduling:setlist'))
        self.assertFalse(Song.objects.filter(pk=song.pk).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistEditMixedBufferTests(TestCase):
    @patch('scheduling.services._recording_storage')
    def test_a_mixed_buffer_produces_exactly_the_intended_rows_contiguously_numbered(self, recording_storage):
        """One Save with a reorder, an edit, an added row and a deletion together produces exactly the right rows."""
        semester = SemesterFactory()
        keep_first = SongFactory(semester=semester, position=1, title='Keep First')
        to_delete = SongFactory(semester=semester, position=2, title='To Delete')
        keep_second = SongFactory(semester=semester, position=3, title='Keep Second')
        admin_client(self)
        # Visual order after the edit: keep_second (edited), keep_first, to_delete (struck), new row.
        data = build_post_data(semester, [
            {'song': keep_second, 'title': 'Keep Second Edited'},
            {'song': keep_first},
            {'song': to_delete, 'deleted': True},
            {'title': 'Added Song', 'artist': 'Added Artist', 'length': '3:15'},
        ])

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertRedirects(response, reverse('scheduling:setlist'))
        self.assertFalse(Song.objects.filter(pk=to_delete.pk).exists())
        keep_second.refresh_from_db()
        keep_first.refresh_from_db()
        added = Song.objects.get(title='Added Song')
        self.assertEqual(keep_second.title, 'Keep Second Edited')
        self.assertEqual(keep_second.position, 1)
        self.assertEqual(keep_first.position, 2)
        self.assertEqual(added.position, 3)
        self.assertEqual(Song.objects.filter(semester=semester).count(), 3)

    def test_a_stale_stamp_on_a_mixed_buffer_writes_nothing(self):
        """A mixed buffer submitted with a stale stamp is rejected wholesale, like a plain edit-only save."""
        from datetime import timedelta

        from django.utils import timezone

        semester = SemesterFactory()
        song = SongFactory(semester=semester, position=1, title='Original')
        stale_stamp = semester.updated_at.isoformat()
        semester.updated_at = timezone.now() + timedelta(seconds=1)
        semester.save(update_fields=['updated_at'])
        admin_client(self)
        data = build_post_data(
            semester,
            [{'song': song, 'deleted': True}, {'title': 'New Song', 'artist': 'New Artist', 'length': '2:00'}],
            stamp=stale_stamp,
        )

        response = self.client.post(reverse('scheduling:setlist-edit'), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'reload and reapply')
        self.assertTrue(Song.objects.filter(pk=song.pk).exists())
        self.assertFalse(Song.objects.filter(title='New Song').exists())
