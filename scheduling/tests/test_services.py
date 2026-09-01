"""Shared scheduling service functions (issue #92, issue #95)."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    MembershipRoleFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.services import assignment_matrix_for, song_rehearsal_progress


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


class AssignmentMatrixForTests(TestCase):
    def test_rows_ordered_by_song_position_with_start_times(self):
        """Rows are the Rehearsal's Songs in Song.position order, each carrying its RehearsalSong start_time."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        semester = rehearsal.semester
        second_song = SongFactory(semester=semester, position=2)
        first_song = SongFactory(semester=semester, position=1)
        second_rs = RehearsalSongFactory(song=second_song, rehearsal=rehearsal, order=1)
        first_rs = RehearsalSongFactory(song=first_song, rehearsal=rehearsal, order=2)

        matrix = assignment_matrix_for(rehearsal)

        self.assertEqual([row.song for row in matrix.rows], [first_song, second_song])
        self.assertEqual(matrix.rows[0].start_time, first_rs.start_time)
        self.assertEqual(matrix.rows[1].start_time, second_rs.start_time)

    def test_dress_rehearsal_rows_come_from_live_setlist_with_no_start_time(self):
        """The Dress Rehearsal's rows are the live setlist (no RehearsalSong rows), so start_time is None."""
        rehearsal = RehearsalFactory(is_full_setlist=True)
        song = SongFactory(semester=rehearsal.semester, position=1)

        matrix = assignment_matrix_for(rehearsal)

        self.assertEqual([row.song for row in matrix.rows], [song])
        self.assertIsNone(matrix.rows[0].start_time)

    def test_columns_are_roles_with_a_requirement_on_any_matrix_song(self):
        """Columns are every Role with a SongRoleRequirement on one of the Rehearsal's Songs, ordered by name."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        song = SongFactory(semester=rehearsal.semester, position=1)
        RehearsalSongFactory(song=song, rehearsal=rehearsal, order=1)
        singer = RoleFactory(name='Singer')
        guitarist = RoleFactory(name='Guitarist')
        SongRoleRequirementFactory(song=song, role=singer, count=2)
        SongRoleRequirementFactory(song=song, role=guitarist, count=1)
        RoleFactory(name='Drummer')  # no requirement on this Song — not a column

        matrix = assignment_matrix_for(rehearsal)

        self.assertEqual(matrix.roles, [guitarist, singer])

    def test_cell_lists_assignments_with_role_mismatch_flag(self):
        """A cell lists every SongRoleAssignment for its (Song, Role) pair, carrying is_role_mismatch."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        song = SongFactory(semester=rehearsal.semester, position=1)
        RehearsalSongFactory(song=song, rehearsal=rehearsal, order=1)
        role = RoleFactory()
        SongRoleRequirementFactory(song=song, role=role, count=1)
        person = PersonFactory()
        membership = MembershipFactory(person=person, semester=rehearsal.semester)
        MembershipRoleFactory(membership=membership, role=role)
        matched = SongRoleAssignmentFactory(song=song, role=role, person=person)
        mismatched_person = PersonFactory()
        MembershipFactory(person=mismatched_person, semester=rehearsal.semester)
        mismatched = SongRoleAssignmentFactory(song=song, role=role, person=mismatched_person)

        matrix = assignment_matrix_for(rehearsal)

        [cell] = matrix.rows[0].cells
        self.assertCountEqual(cell.assignments, [matched, mismatched])
        by_person = {assignment.person: assignment.is_role_mismatch for assignment in cell.assignments}
        self.assertFalse(by_person[person])
        self.assertTrue(by_person[mismatched_person])

    def test_empty_cell_for_song_role_pair_with_no_assignment(self):
        """A (Song, Role) column pair with no SongRoleAssignment yields an empty cell, not a missing one."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        song = SongFactory(semester=rehearsal.semester, position=1)
        RehearsalSongFactory(song=song, rehearsal=rehearsal, order=1)
        role = RoleFactory()
        SongRoleRequirementFactory(song=song, role=role, count=1)

        matrix = assignment_matrix_for(rehearsal)

        [cell] = matrix.rows[0].cells
        self.assertEqual(cell.assignments, [])
