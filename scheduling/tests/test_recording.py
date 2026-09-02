"""Recording metadata and relationships (issue #50)."""

from django.core.exceptions import ValidationError
from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import RehearsalFactory, RehearsalSongFactory, SongFactory
from scheduling.models import Recording


class RecordingMetadataTests(TestCase):
    def test_persists_required_upload_metadata_and_optional_note(self):
        """A Recording keeps its RehearsalSong, uploader, upload metadata, and an optional note."""
        rehearsal_song = RehearsalSongFactory()
        uploader = PersonFactory()

        recording = Recording.objects.create(
            rehearsal_song=rehearsal_song,
            uploaded_by=uploader,
            file='recordings/2026-fall/take-1.m4a',
            content_type='audio/mp4',
            file_size=1_024,
        )

        reloaded = Recording.objects.get(pk=recording.pk)
        self.assertEqual(reloaded.rehearsal_song, rehearsal_song)
        self.assertEqual(reloaded.uploaded_by, uploader)
        self.assertEqual(reloaded.file.name, 'recordings/2026-fall/take-1.m4a')
        self.assertEqual(reloaded.content_type, 'audio/mp4')
        self.assertEqual(reloaded.file_size, 1_024)
        self.assertEqual(reloaded.note, '')
        self.assertIsNotNone(reloaded.uploaded_at)

    def test_requires_its_relationships_and_upload_metadata(self):
        """A Recording cannot validate without its RehearsalSong, uploader, or required metadata."""
        recording = Recording()

        with self.assertRaises(ValidationError) as raised:
            recording.full_clean()

        self.assertEqual(
            set(raised.exception.message_dict),
            {'rehearsal_song', 'uploaded_by', 'file', 'content_type', 'file_size'},
        )


class RecordingRelationshipTests(TestCase):
    def test_multiple_takes_resolve_by_song_and_rehearsal_through_rehearsal_song(self):
        """Multiple takes share a RehearsalSong and are found through its Song and Rehearsal."""
        rehearsal = RehearsalFactory()
        song = SongFactory(semester=rehearsal.semester)
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        uploader = PersonFactory()
        first_take = Recording.objects.create(
            rehearsal_song=rehearsal_song,
            uploaded_by=uploader,
            file='recordings/take-1.m4a',
            content_type='audio/mp4',
            file_size=1_024,
            note='First take',
        )
        second_take = Recording.objects.create(
            rehearsal_song=rehearsal_song,
            uploaded_by=uploader,
            file='recordings/take-2.m4a',
            content_type='audio/mp4',
            file_size=2_048,
            note='Second take',
        )

        recordings_for_song = Recording.objects.filter(rehearsal_song__song=song)
        recordings_for_rehearsal = Recording.objects.filter(rehearsal_song__rehearsal=rehearsal)
        field_names = {field.name for field in Recording._meta.fields}

        self.assertCountEqual(recordings_for_song, [first_take, second_take])
        self.assertCountEqual(recordings_for_rehearsal, [first_take, second_take])
        self.assertNotIn('song', field_names)
        self.assertNotIn('rehearsal', field_names)
