"""apply_setlist_edits(): the batch write, the deletion cascade, reorder, and the two staleness checks (issue #321)."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase

from scheduling.factories import (
    RecordingFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.models import RehearsalSong, Song
from scheduling.services import (
    SetlistEditBuffer,
    SetlistEditRow,
    StaleSetlistSemesterError,
    WrongViewingSemesterError,
    apply_setlist_edits,
)


class ApplySetlistEditsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Semester with two Songs to submit Buffers against."""
        cls.semester = SemesterFactory()
        cls.first = SongFactory(semester=cls.semester, position=1, title='First', artist='Artist A')
        cls.second = SongFactory(semester=cls.semester, position=2, title='Second', artist='Artist B')

    def _row(self, song=None, **overrides):
        """Build one SetlistEditRow, defaulting every field from `song` (or blank, for a new row)."""
        defaults = {
            'song_id': song.pk if song else None,
            'title': song.title if song else '',
            'artist': song.artist if song else '',
            'length': song.length if song else timedelta(minutes=3),
            'notes': song.notes if song else '',
        }
        defaults.update(overrides)
        return SetlistEditRow(**defaults)

    def _buffer(self, rows, deleted_song_ids=(), semester=None, updated_at=None):
        """Build a SetlistEditBuffer against self.semester unless overridden."""
        semester = semester or self.semester
        return SetlistEditBuffer(
            semester_id=semester.pk,
            semester_updated_at=updated_at if updated_at is not None else semester.updated_at,
            rows=list(rows),
            deleted_song_ids=frozenset(deleted_song_ids),
        )

    def test_edits_an_existing_song(self):
        """A Buffer row naming an existing Song's id saves the edited fields onto it."""
        buffer = self._buffer([
            self._row(self.first, title='New Title', artist='New Artist'),
            self._row(self.second),
        ])

        apply_setlist_edits(buffer, viewing_semester=self.semester)

        self.first.refresh_from_db()
        self.assertEqual(self.first.title, 'New Title')
        self.assertEqual(self.first.artist, 'New Artist')

    def test_adds_a_brand_new_song(self):
        """A Buffer row with no song_id creates a new Song on the Semester."""
        buffer = self._buffer([
            self._row(self.first), self._row(self.second),
            self._row(title='Brand New', artist='New Artist', length=timedelta(minutes=2, seconds=30), notes=''),
        ])

        apply_setlist_edits(buffer, viewing_semester=self.semester)

        added = Song.objects.get(title='Brand New')
        self.assertEqual(added.semester, self.semester)
        self.assertEqual(added.position, 3)

    @patch('scheduling.services._recording_storage')
    def test_deletes_a_song_and_its_recordings(self, recording_storage):
        """A Song named in deleted_song_ids is hard-deleted along with its Recordings."""
        rehearsal_song = RehearsalSongFactory(song=self.first)
        recording = RecordingFactory(rehearsal_song=rehearsal_song)
        buffer = self._buffer([self._row(self.second)], deleted_song_ids={self.first.pk})

        with self.captureOnCommitCallbacks(execute=True):
            apply_setlist_edits(buffer, viewing_semester=self.semester)

        self.assertFalse(Song.objects.filter(pk=self.first.pk).exists())
        self.assertFalse(type(recording).objects.filter(pk=recording.pk).exists())
        self.assertFalse(RehearsalSong.objects.filter(pk=rehearsal_song.pk).exists())

    def test_reorders_survivors_after_a_deletion_to_a_contiguous_sequence(self):
        """Surviving rows are renumbered 1..N in the Buffer's row order after a deletion."""
        third = SongFactory(semester=self.semester, position=3, title='Third')
        buffer = self._buffer([self._row(third), self._row(self.first)], deleted_song_ids={self.second.pk})

        apply_setlist_edits(buffer, viewing_semester=self.semester)

        third.refresh_from_db()
        self.first.refresh_from_db()
        self.assertEqual(third.position, 1)
        self.assertEqual(self.first.position, 2)
        self.assertFalse(Song.objects.filter(pk=self.second.pk).exists())

    def test_swapping_two_songs_positions_does_not_collide(self):
        """Reordering two existing rows to swap their positions succeeds, exercising the deferred unique constraint."""
        buffer = self._buffer([self._row(self.second), self._row(self.first)])

        apply_setlist_edits(buffer, viewing_semester=self.semester)

        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.second.position, 1)
        self.assertEqual(self.first.position, 2)

    def test_bumps_the_semesters_updated_at(self):
        """A successful apply advances the Semester's optimistic-concurrency stamp."""
        original_updated_at = self.semester.updated_at
        buffer = self._buffer([self._row(self.first), self._row(self.second)])

        apply_setlist_edits(buffer, viewing_semester=self.semester)

        self.semester.refresh_from_db()
        self.assertGreater(self.semester.updated_at, original_updated_at)

    def test_wrong_semester_raises_and_writes_nothing(self):
        """A Buffer whose semester_id doesn't match viewing_semester raises WrongViewingSemesterError before any write."""
        other_semester = SemesterFactory()
        buffer = self._buffer([self._row(self.first), self._row(self.second)], semester=other_semester)

        with self.assertRaises(WrongViewingSemesterError):
            apply_setlist_edits(buffer, viewing_semester=self.semester)

        self.first.refresh_from_db()
        self.assertEqual(self.first.title, 'First')

    def test_stale_stamp_raises_and_writes_nothing(self):
        """A Buffer carrying an older Semester stamp than the current one is rejected, writing nothing."""
        stale_stamp = self.semester.updated_at
        self.semester.updated_at = stale_stamp + timedelta(seconds=1)
        self.semester.save(update_fields=['updated_at'])
        buffer = self._buffer(
            [self._row(self.first, title='Should Not Save'), self._row(self.second)], updated_at=stale_stamp,
        )

        with self.assertRaises(StaleSetlistSemesterError):
            apply_setlist_edits(buffer, viewing_semester=self.semester)

        self.first.refresh_from_db()
        self.assertEqual(self.first.title, 'First')
