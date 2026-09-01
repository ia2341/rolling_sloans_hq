"""Shared scheduling service functions (issue #92)."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from scheduling.factories import RehearsalFactory, RehearsalSongFactory, SongFactory
from scheduling.services import song_rehearsal_progress


class SongRehearsalProgressTests(TestCase):
    def setUp(self):
        """Build a Song and a past/future date to attach RehearsalSong rows to."""
        self.song = SongFactory()
        today = timezone.localdate()
        self.past_date = today - timedelta(days=1)
        self.future_date = today + timedelta(days=1)

    def _rehearsal_song(self, date):
        """Build a RehearsalSong for self.song on a Rehearsal dated `date`."""
        rehearsal = RehearsalFactory(semester=self.song.semester, date=date)
        return RehearsalSongFactory(song=self.song, rehearsal=rehearsal)

    def test_no_rehearsal_songs_yields_all_zero(self):
        """A Song with no RehearsalSong rows yields completed=remaining=total=0."""
        progress = song_rehearsal_progress(self.song)

        self.assertEqual(progress.completed, 0)
        self.assertEqual(progress.remaining, 0)
        self.assertEqual(progress.total, 0)

    def test_all_past_rehearsals_count_as_completed(self):
        """RehearsalSong rows whose Rehearsal date is entirely in the past all count as completed."""
        self._rehearsal_song(self.past_date)
        self._rehearsal_song(self.past_date - timedelta(days=1))

        progress = song_rehearsal_progress(self.song)

        self.assertEqual(progress.completed, 2)
        self.assertEqual(progress.remaining, 0)
        self.assertEqual(progress.total, 2)

    def test_all_future_rehearsals_count_as_remaining(self):
        """RehearsalSong rows whose Rehearsal date is today or later all count as remaining."""
        self._rehearsal_song(self.future_date)
        self._rehearsal_song(timezone.localdate())

        progress = song_rehearsal_progress(self.song)

        self.assertEqual(progress.completed, 0)
        self.assertEqual(progress.remaining, 2)
        self.assertEqual(progress.total, 2)

    def test_mixed_past_and_future_rehearsals_split_correctly(self):
        """A mix of past and future/current-day Rehearsals splits into completed vs remaining."""
        self._rehearsal_song(self.past_date)
        self._rehearsal_song(self.future_date)
        self._rehearsal_song(self.future_date + timedelta(days=1))

        progress = song_rehearsal_progress(self.song)

        self.assertEqual(progress.completed, 1)
        self.assertEqual(progress.remaining, 2)
        self.assertEqual(progress.total, 3)

    def test_scoped_to_the_given_song_only(self):
        """RehearsalSong rows for a different Song are not counted."""
        other_song = SongFactory(semester=self.song.semester)
        self._rehearsal_song(self.past_date)
        other_rehearsal = RehearsalFactory(semester=self.song.semester, date=self.past_date)
        RehearsalSongFactory(song=other_song, rehearsal=other_rehearsal, order=99)

        progress = song_rehearsal_progress(self.song)

        self.assertEqual(progress.total, 1)
