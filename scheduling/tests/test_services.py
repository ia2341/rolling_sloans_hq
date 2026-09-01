"""Shared scheduling service functions (issue #92)."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.services import song_rehearsal_progress, songs_with_progress_for


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


class SongsWithProgressForTests(TestCase):
    def setUp(self):
        """Build a Semester and a Person to query songs_with_progress_for with."""
        self.semester = SemesterFactory()
        self.person = PersonFactory()
        self.role = RoleFactory()

    def test_returns_songs_in_position_order_scoped_to_the_semester(self):
        """Only the given Semester's Songs are returned, in position order."""
        other_semester = SemesterFactory()
        SongFactory(semester=other_semester)
        second_song = SongFactory(semester=self.semester, position=2)
        first_song = SongFactory(semester=self.semester, position=1)

        songs = songs_with_progress_for(self.semester, self.person)

        self.assertEqual(songs, [first_song, second_song])

    def test_annotates_each_song_with_its_rehearsal_progress(self):
        """Each returned Song carries the same progress song_rehearsal_progress would compute for it directly."""
        song = SongFactory(semester=self.semester)
        rehearsal = RehearsalFactory(semester=self.semester, date=timezone.localdate() - timedelta(days=1))
        RehearsalSongFactory(song=song, rehearsal=rehearsal)

        [returned_song] = songs_with_progress_for(self.semester, self.person)

        self.assertEqual(returned_song.progress, song_rehearsal_progress(song))

    def test_marks_has_assignment_only_for_the_given_persons_own_songs(self):
        """has_assignment is True only for Songs where `person` has any SongRoleAssignment, regardless of other Persons'."""
        my_song = SongFactory(semester=self.semester, position=1)
        other_song = SongFactory(semester=self.semester, position=2)
        SongRoleAssignmentFactory(song=my_song, role=self.role, person=self.person)
        SongRoleAssignmentFactory(song=other_song, role=self.role, person=PersonFactory())

        songs = songs_with_progress_for(self.semester, self.person)

        songs_by_pk = {song.pk: song for song in songs}
        self.assertTrue(songs_by_pk[my_song.pk].has_assignment)
        self.assertFalse(songs_by_pk[other_song.pk].has_assignment)
