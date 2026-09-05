"""`services.spotify_import_candidates_for()`: server-side duplicate detection for the + Add sheet (issue #335)."""

from datetime import timedelta

from django.test import TestCase

from scheduling.factories import SemesterFactory, SongFactory
from scheduling.services import spotify_import_candidates_for
from scheduling.spotify import ImportedSong


class SpotifyImportCandidatesForTests(TestCase):
    """A candidate's title is compared case-insensitively against the viewing Semester's saved Songs."""

    def test_flags_a_case_insensitive_title_match_as_already_in_setlist(self):
        """A candidate whose title matches an existing Song's, differing only by case, is flagged."""
        semester = SemesterFactory()
        SongFactory(semester=semester, title='Wonderwall')
        songs = [ImportedSong(title='wonderwall', artist='Oasis', length=timedelta(minutes=4), position=1)]

        candidates = spotify_import_candidates_for(semester, songs)

        self.assertTrue(candidates[0].already_in_setlist)

    def test_does_not_flag_a_title_absent_from_the_setlist(self):
        """A candidate with no matching title in `semester` is not flagged."""
        semester = SemesterFactory()
        SongFactory(semester=semester, title='Wonderwall')
        songs = [ImportedSong(title='Brand New Track', artist='Faux Static', length=timedelta(minutes=4), position=1)]

        candidates = spotify_import_candidates_for(semester, songs)

        self.assertFalse(candidates[0].already_in_setlist)

    def test_does_not_flag_a_match_from_a_different_semester(self):
        """A title matching a Song in a *different* Semester is never flagged (ADR 0001: Songs never carry across terms)."""
        other_semester = SemesterFactory()
        SongFactory(semester=other_semester, title='Wonderwall')
        this_semester = SemesterFactory()
        songs = [ImportedSong(title='Wonderwall', artist='Oasis', length=timedelta(minutes=4), position=1)]

        candidates = spotify_import_candidates_for(this_semester, songs)

        self.assertFalse(candidates[0].already_in_setlist)

    def test_none_semester_flags_nothing(self):
        """No published/selected Semester flags no candidate as a duplicate."""
        songs = [ImportedSong(title='Wonderwall', artist='Oasis', length=timedelta(minutes=4), position=1)]

        candidates = spotify_import_candidates_for(None, songs)

        self.assertFalse(candidates[0].already_in_setlist)
