"""Shared scheduling service functions (issue #92, issue #95, issue #98)."""

from datetime import time, timedelta

from django.test import TestCase
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    MembershipRoleFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import Conflict, ConflictWindow
from scheduling.services import (
    assignment_matrix_for,
    breaks_for,
    declare_conflict,
    future_rehearsals_for,
    rehearsal_schedule_for,
    song_rehearsal_progress,
    songs_with_progress_for,
)


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


class BreaksForTests(TestCase):
    def setUp(self):
        """Build a Person and a 5-slot Rehearsal (18:00 start, 18-minute slots) to attach RehearsalSong rows to."""
        self.person = PersonFactory()
        self.role = RoleFactory()
        self.rehearsal = RehearsalFactory(is_full_setlist=False)

    def _assigned_slot(self, order):
        """Build a RehearsalSong at `order` in self.rehearsal, with self.person assigned to its Song."""
        song = SongFactory(semester=self.rehearsal.semester)
        SongRoleAssignmentFactory(song=song, role=self.role, person=self.person)
        return RehearsalSongFactory(rehearsal=self.rehearsal, song=song, order=order)

    def _unassigned_slot(self, order):
        """Build a RehearsalSong at `order` in self.rehearsal, with no assignment for self.person."""
        song = SongFactory(semester=self.rehearsal.semester)
        return RehearsalSongFactory(rehearsal=self.rehearsal, song=song, order=order)

    def test_zero_assignments_yields_no_breaks(self):
        """A Person with no assigned slots at the Rehearsal gets an empty list, not a break."""
        self._unassigned_slot(1)

        self.assertEqual(breaks_for(self.rehearsal, self.person), [])

    def test_back_to_back_assigned_slots_yield_no_breaks(self):
        """Consecutive assigned slots with no intervening unassigned slot yield no breaks."""
        self._assigned_slot(1)
        self._assigned_slot(2)

        self.assertEqual(breaks_for(self.rehearsal, self.person), [])

    def test_full_window_attendance_yields_no_breaks(self):
        """A Person assigned to every slot in the Rehearsal has no gaps at all."""
        for order in range(1, 6):
            self._assigned_slot(order)

        self.assertEqual(breaks_for(self.rehearsal, self.person), [])

    def test_unassigned_slot_between_two_assigned_slots_is_a_break(self):
        """A gap opens between one assigned slot's end_time and the next assigned slot's start_time."""
        first = self._assigned_slot(1)
        middle = self._unassigned_slot(2)
        last = self._assigned_slot(3)

        [gap] = breaks_for(self.rehearsal, self.person)

        self.assertEqual(gap.start_time, first.end_time)
        self.assertEqual(gap.end_time, last.start_time)
        self.assertEqual(first.end_time, middle.start_time)
        self.assertEqual(middle.end_time, last.start_time)

    def test_dress_rehearsal_yields_no_breaks(self):
        """The Dress Rehearsal has no persisted RehearsalSong rows, so it always yields an empty list (ADR-0003)."""
        dress_rehearsal = RehearsalFactory(is_full_setlist=True)
        song = SongFactory(semester=dress_rehearsal.semester)
        SongRoleAssignmentFactory(song=song, role=self.role, person=self.person)

        self.assertEqual(breaks_for(dress_rehearsal, self.person), [])


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


class FutureRehearsalsForTests(TestCase):
    def test_returns_only_todays_and_future_rehearsals_in_date_order(self):
        """Rehearsals dated before today are excluded; today's and later ones come back in date order."""
        semester = SemesterFactory()
        today = timezone.localdate()
        yesterday = RehearsalFactory(semester=semester, date=today - timedelta(days=1))
        later = RehearsalFactory(semester=semester, date=today + timedelta(days=2))
        todays = RehearsalFactory(semester=semester, date=today)

        result = future_rehearsals_for(semester)

        self.assertNotIn(yesterday, result)
        self.assertEqual(result, [todays, later])

    def test_scoped_to_the_given_semester(self):
        """A Rehearsal belonging to a different Semester is never included."""
        semester = SemesterFactory()
        other_semester = SemesterFactory()
        RehearsalFactory(semester=other_semester, date=timezone.localdate() + timedelta(days=1))

        result = future_rehearsals_for(semester)

        self.assertEqual(result, [])


class DeclareConflictTests(TestCase):
    def setUp(self):
        """Build a Person and a Rehearsal with a known time span for every test."""
        self.person = PersonFactory()
        self.rehearsal = RehearsalFactory(start_time=time(18, 0), end_time=time(19, 30))

    def test_full_absence_creates_full_conflict_with_no_window(self):
        """full_absence creates a FULL_CONFLICT Conflict and no ConflictWindow."""
        conflict = declare_conflict(
            person=self.person, rehearsal=self.rehearsal, declaration_type='full_absence', reason='Sick.',
        )

        self.assertEqual(conflict.type, Conflict.FULL_CONFLICT)
        self.assertEqual(conflict.reason, 'Sick.')
        self.assertFalse(ConflictWindow.objects.filter(conflict=conflict).exists())

    def test_late_arrival_creates_partial_conflict_with_window_from_rehearsal_start(self):
        """late_arrival creates a PARTIAL Conflict with one window from the Rehearsal's start_time to declared_time."""
        conflict = declare_conflict(
            person=self.person, rehearsal=self.rehearsal, declaration_type='late_arrival', declared_time=time(18, 30),
        )

        self.assertEqual(conflict.type, Conflict.PARTIAL)
        window = ConflictWindow.objects.get(conflict=conflict)
        self.assertEqual(window.unavailable_start, time(18, 0))
        self.assertEqual(window.unavailable_end, time(18, 30))

    def test_early_departure_creates_partial_conflict_with_window_to_rehearsal_end(self):
        """early_departure creates a PARTIAL Conflict with one window from declared_time to the Rehearsal's end_time."""
        conflict = declare_conflict(
            person=self.person, rehearsal=self.rehearsal, declaration_type='early_departure', declared_time=time(19, 0),
        )

        self.assertEqual(conflict.type, Conflict.PARTIAL)
        window = ConflictWindow.objects.get(conflict=conflict)
        self.assertEqual(window.unavailable_start, time(19, 0))
        self.assertEqual(window.unavailable_end, time(19, 30))

    def test_unknown_declaration_type_raises(self):
        """An unrecognized declaration_type raises rather than silently creating anything."""
        with self.assertRaises(ValueError):
            declare_conflict(person=self.person, rehearsal=self.rehearsal, declaration_type='not-a-real-type')

        self.assertFalse(Conflict.objects.filter(person=self.person, rehearsal=self.rehearsal).exists())


class RehearsalScheduleForTests(TestCase):
    def setUp(self):
        """Build a Semester and a Person to view its schedule."""
        self.semester = SemesterFactory()
        self.person = PersonFactory()

    def test_splits_past_and_future_rehearsals_by_date(self):
        """A Rehearsal dated before today is past; one dated today or later is future."""
        today = timezone.localdate()
        past = RehearsalFactory(semester=self.semester, date=today - timedelta(days=1))
        today_rehearsal = RehearsalFactory(semester=self.semester, date=today)
        future = RehearsalFactory(semester=self.semester, date=today + timedelta(days=1))

        schedule = rehearsal_schedule_for(self.semester, self.person)

        self.assertEqual([row.rehearsal for row in schedule.past], [past])
        self.assertEqual(
            [row.rehearsal for row in schedule.future], [today_rehearsal, future],
        )

    def test_rows_ordered_by_date_then_start_time(self):
        """Rows within each split are ordered by date, then start_time."""
        today = timezone.localdate()
        later = RehearsalFactory(semester=self.semester, date=today + timedelta(days=1), start_time=time(19, 0))
        earlier = RehearsalFactory(semester=self.semester, date=today + timedelta(days=1), start_time=time(17, 0))

        schedule = rehearsal_schedule_for(self.semester, self.person)

        self.assertEqual([row.rehearsal for row in schedule.future], [earlier, later])

    def test_row_carries_persons_attendance_suggestion(self):
        """Each row carries the viewing Person's attendance_suggestion_for that Rehearsal, or None if not needed."""
        rehearsal = RehearsalFactory(semester=self.semester, date=timezone.localdate() + timedelta(days=1))
        song = SongFactory(semester=self.semester, position=1)
        RehearsalSongFactory(song=song, rehearsal=rehearsal, order=1)
        SongRoleAssignmentFactory(song=song, person=self.person)
        not_needed = RehearsalFactory(semester=self.semester, date=timezone.localdate() + timedelta(days=2))

        schedule = rehearsal_schedule_for(self.semester, self.person)

        by_rehearsal = {row.rehearsal: row.attendance_suggestion for row in schedule.future}
        self.assertIsNotNone(by_rehearsal[rehearsal])
        self.assertIsNone(by_rehearsal[not_needed])

    def test_scoped_to_the_given_semester_only(self):
        """A Rehearsal in a different Semester is not included."""
        RehearsalFactory()  # different semester

        schedule = rehearsal_schedule_for(self.semester, self.person)

        self.assertEqual(schedule.past, [])
        self.assertEqual(schedule.future, [])
