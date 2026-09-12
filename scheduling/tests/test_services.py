"""Shared scheduling service functions (issue #92, issue #95, issue #98, issue #99)."""

from datetime import date, time, timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    BackupFactory,
    ConflictFactory,
    ConflictWindowFactory,
    MembershipFactory,
    PersonRoleFactory,
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import Conflict, ConflictWindow, MembershipRole
from scheduling.services import (
    AssignmentMatrixEntryKind,
    SongRehearsalProgress,
    active_roles_for,
    assignable_roster_for,
    assignment_grid_is_editable,
    assignment_matrix_for,
    assignment_picker_for,
    attendance_suggestion_for,
    breaks_for,
    cast_line_for,
    cast_lines_for_semester,
    conflict_history_for,
    declare_conflict,
    fill_status_for,
    future_rehearsals_for,
    future_scheduling_footprint_for,
    performers_for,
    recording_count_for,
    recording_counts_for_semester,
    rehearsal_schedule_for,
    rehearsed_at_for,
    role_codes_for,
    setlist_total_running_time,
    song_rehearsal_progress,
    songs_with_progress_for,
    timeline_for,
)


class SongRehearsalProgressTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Song and a past/future date to attach RehearsalSong rows to."""
        cls.song = SongFactory()
        today = timezone.localdate()
        cls.past_date = today - timedelta(days=1)
        cls.future_date = today + timedelta(days=1)

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
        other_rehearsal = RehearsalFactory(semester=self.song.semester, date=self.future_date)
        RehearsalSongFactory(song=other_song, rehearsal=other_rehearsal, order=99)

        progress = song_rehearsal_progress(self.song)

        self.assertEqual(progress.total, 1)


class PerformersForTests(TestCase):
    def test_no_assignments_yields_empty_list(self):
        """A Song with no SongRoleAssignments yields an empty performers list."""
        song = SongFactory()

        performers = performers_for(song)

        self.assertEqual(performers, [])

    def test_dedupes_a_person_appearing_under_multiple_roles(self):
        """A Person assigned to two Roles on the same Song appears once, listing both Roles."""
        song = SongFactory()
        person = PersonFactory()
        singer = RoleFactory(name='Singer')
        guitarist = RoleFactory(name='Guitarist')
        SongRoleAssignmentFactory(song=song, person=person, role=singer)
        SongRoleAssignmentFactory(song=song, person=person, role=guitarist)

        performers = performers_for(song)

        self.assertEqual(len(performers), 1)
        self.assertEqual(performers[0].person, person)
        self.assertCountEqual(performers[0].roles, [singer, guitarist])

    def test_distinct_people_each_get_their_own_entry(self):
        """Two different People assigned to the same Song each get their own SongPerformer entry."""
        song = SongFactory()
        role = RoleFactory()
        first_person = SongRoleAssignmentFactory(song=song, role=role).person
        second_person = SongRoleAssignmentFactory(song=song, role=role).person

        performers = performers_for(song)

        self.assertCountEqual(
            [performer.person for performer in performers], [first_person, second_person],
        )

    def test_scoped_to_the_given_song_only(self):
        """SongRoleAssignments for a different Song are not included."""
        song = SongFactory()
        other_song = SongFactory(semester=song.semester)
        SongRoleAssignmentFactory(song=other_song)

        performers = performers_for(song)

        self.assertEqual(performers, [])

    def test_a_backup_only_person_is_excluded(self):
        """A Person who is only a Backup on the Song's slot, with no SongRoleAssignment, is not a performer (ADR-0007 §5).

        The Setlist reports who plays the Song at the concert, so folding a
        one-evening Backup into it would misreport that fact — unlike the
        three attendance reads, performers_for() is deliberately not routed
        through the widened slot-membership helper (issue #175).
        """
        song = SongFactory()
        rehearsal_song = RehearsalSongFactory(song=song, rehearsal=RehearsalFactory(semester=song.semester))
        BackupFactory(rehearsal_song=rehearsal_song, role=RoleFactory())

        performers = performers_for(song)

        self.assertEqual(performers, [])


class FillStatusForTests(TestCase):
    def test_no_requirements_yields_empty_list(self):
        """A Song with no SongRoleRequirements returns an empty result, not an error."""
        song = SongFactory()

        statuses = fill_status_for(song)

        self.assertEqual(statuses, [])

    def test_role_under_target_is_flagged_understaffed(self):
        """A Role with fewer assignments than its target is flagged is_understaffed."""
        song = SongFactory()
        role = RoleFactory(name='Singer')
        SongRoleRequirementFactory(song=song, role=role, count=3)
        SongRoleAssignmentFactory(song=song, role=role)

        [status] = fill_status_for(song)

        self.assertEqual(status.target, 3)
        self.assertEqual(status.actual, 1)
        self.assertTrue(status.is_understaffed)

    def test_role_exactly_at_target_is_not_flagged(self):
        """A Role with assignments equal to its target is not flagged understaffed."""
        song = SongFactory()
        role = RoleFactory()
        SongRoleRequirementFactory(song=song, role=role, count=2)
        SongRoleAssignmentFactory(song=song, role=role)
        SongRoleAssignmentFactory(song=song, role=role)

        [status] = fill_status_for(song)

        self.assertEqual(status.actual, 2)
        self.assertFalse(status.is_understaffed)

    def test_role_over_target_is_not_flagged(self):
        """A Role with more assignments than its target is not flagged understaffed (a target is never a cap)."""
        song = SongFactory()
        role = RoleFactory()
        SongRoleRequirementFactory(song=song, role=role, count=1)
        SongRoleAssignmentFactory(song=song, role=role)
        SongRoleAssignmentFactory(song=song, role=role)

        [status] = fill_status_for(song)

        self.assertEqual(status.actual, 2)
        self.assertFalse(status.is_understaffed)

    def test_requirement_on_a_retired_role_is_present_and_flagged(self):
        """A Requirement naming a retired Role is included, flagged is_retired_role, never filtered out."""
        song = SongFactory()
        retired_role = RoleFactory(is_active=False)
        SongRoleRequirementFactory(song=song, role=retired_role, count=1)

        [status] = fill_status_for(song)

        self.assertEqual(status.role, retired_role)
        self.assertTrue(status.is_retired_role)

    def test_scoped_to_the_given_song_only(self):
        """A Requirement on a different Song is not included."""
        song = SongFactory()
        other_song = SongFactory(semester=song.semester)
        SongRoleRequirementFactory(song=other_song)

        statuses = fill_status_for(song)

        self.assertEqual(statuses, [])


class RecordingCountForTests(TestCase):
    def test_no_recordings_yields_zero(self):
        """A Song with no Recordings yields a count of 0, not an error."""
        song = SongFactory()

        self.assertEqual(recording_count_for(song), 0)

    def test_counts_recordings_across_every_rehearsal_song_slot(self):
        """Recordings across multiple RehearsalSong slots for the Song all count."""
        song = SongFactory()
        first_slot = RehearsalSongFactory(
            song=song, rehearsal=RehearsalFactory(semester=song.semester, date=date(2026, 9, 16)),
        )
        second_slot = RehearsalSongFactory(
            song=song, rehearsal=RehearsalFactory(semester=song.semester, date=date(2026, 9, 23)),
        )
        RecordingFactory(rehearsal_song=first_slot)
        RecordingFactory(rehearsal_song=first_slot)
        RecordingFactory(rehearsal_song=second_slot)

        self.assertEqual(recording_count_for(song), 3)

    def test_scoped_to_the_given_song_only(self):
        """Recordings on a different Song's RehearsalSong slots are not counted."""
        song = SongFactory()
        other_song = SongFactory(semester=song.semester)
        other_slot = RehearsalSongFactory(song=other_song, rehearsal=RehearsalFactory(semester=song.semester))
        RecordingFactory(rehearsal_song=other_slot)

        self.assertEqual(recording_count_for(song), 0)


class RecordingCountsForSemesterTests(TestCase):
    def test_matches_recording_count_for_per_song(self):
        """The bulk result for each Song matches what recording_count_for() would compute for it directly (issue #394)."""
        semester = SemesterFactory()
        recorded_song = SongFactory(semester=semester)
        quiet_song = SongFactory(semester=semester)
        slot = RehearsalSongFactory(song=recorded_song, rehearsal=RehearsalFactory(semester=semester))
        RecordingFactory(rehearsal_song=slot)
        RecordingFactory(rehearsal_song=slot)

        counts = recording_counts_for_semester(semester)

        self.assertEqual(counts.get(recorded_song.pk, 0), recording_count_for(recorded_song))
        self.assertEqual(counts.get(quiet_song.pk, 0), recording_count_for(quiet_song))

    def test_a_song_with_no_recordings_is_absent_from_the_map(self):
        """A Song with zero Recordings has no key in the result — callers use .get(song_id, 0) (issue #394)."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)

        counts = recording_counts_for_semester(semester)

        self.assertNotIn(song.pk, counts)


class SongsWithProgressForTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Semester and a Person to query songs_with_progress_for with."""
        cls.semester = SemesterFactory()
        cls.person = PersonFactory()
        cls.role = RoleFactory()

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

    def test_a_song_with_no_rehearsal_songs_gets_zero_progress(self):
        """A Song with no RehearsalSong rows at all still gets a progress of 0/0/0, not a KeyError (issue #394)."""
        song = SongFactory(semester=self.semester)

        [returned_song] = songs_with_progress_for(self.semester, self.person)

        self.assertEqual(returned_song, song)
        self.assertEqual(returned_song.progress, SongRehearsalProgress(completed=0, remaining=0, total=0))

    def test_query_count_does_not_scale_with_song_count(self):
        """Annotating every Song with its progress costs the same query count regardless of how many Songs the Semester has (issue #394).

        Guards against re-introducing a per-Song query (e.g. calling
        `song_rehearsal_progress()` in a loop over Songs) — the regression
        this ticket fixes, which made Home's song-progress table scale
        with the Semester's Song count instead of staying flat.
        """
        def _build_song(position):
            song = SongFactory(semester=self.semester, position=position)
            rehearsal = RehearsalFactory(
                semester=self.semester, date=timezone.localdate() - timedelta(days=position),
            )
            RehearsalSongFactory(song=song, rehearsal=rehearsal, order=1)
            return song

        _build_song(1)
        _build_song(2)
        with CaptureQueriesContext(connection) as few:
            songs_with_progress_for(self.semester, self.person)

        for position in range(3, 9):
            _build_song(position)
        with CaptureQueriesContext(connection) as many:
            songs_with_progress_for(self.semester, self.person)

        self.assertEqual(len(few.captured_queries), len(many.captured_queries))


class BreaksForTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Person and a 5-slot Rehearsal (18:00 start, 18-minute slots) to attach RehearsalSong rows to."""
        cls.person = PersonFactory()
        cls.role = RoleFactory()
        cls.rehearsal = RehearsalFactory(is_full_setlist=False)

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


class TimelineForTests(TestCase):
    """`timeline_for()`: the "You at this rehearsal" picture (issue #331)."""

    @classmethod
    def setUpTestData(cls):
        """Build a Person and a Role to attach RehearsalSong rows to."""
        cls.person = PersonFactory()
        cls.role = RoleFactory()

    def _slot(self, rehearsal, order, *, assign=False):
        """Build a RehearsalSong at `order` in `rehearsal`, optionally assigning self.person to its Song."""
        song = SongFactory(semester=rehearsal.semester)
        if assign:
            SongRoleAssignmentFactory(song=song, role=self.role, person=self.person)
        return RehearsalSongFactory(rehearsal=rehearsal, song=song, order=order)

    def test_viewer_on_no_slots(self):
        """A viewer on none of the Rehearsal's slots gets every slot flagged False and no viewer start/end."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        self._slot(rehearsal, 1)
        self._slot(rehearsal, 2)

        timeline = timeline_for(rehearsal, self.person)

        self.assertEqual(len(timeline.slots), 2)
        self.assertTrue(all(not slot.is_viewer for slot in timeline.slots))
        self.assertEqual(timeline.viewer_song_count, 0)
        self.assertEqual(timeline.total_song_count, 2)
        self.assertIsNone(timeline.viewer_start_time)
        self.assertIsNone(timeline.viewer_end_time)
        self.assertEqual(timeline.window_start, rehearsal.start_time)
        self.assertEqual(timeline.window_end, rehearsal.end_time)
        self.assertFalse(timeline.is_dress_rehearsal)

    def test_viewer_on_first_and_last_slot_only(self):
        """Assigned to both the first and last slot means full-window attendance (matching attendance_suggestion_for)."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        self._slot(rehearsal, 1, assign=True)
        self._slot(rehearsal, 2)
        self._slot(rehearsal, 3, assign=True)

        timeline = timeline_for(rehearsal, self.person)

        self.assertEqual([slot.is_viewer for slot in timeline.slots], [True, False, True])
        self.assertEqual(timeline.viewer_song_count, 2)
        self.assertEqual(timeline.total_song_count, 3)
        self.assertEqual(timeline.viewer_start_time, rehearsal.start_time)
        self.assertEqual(timeline.viewer_end_time, rehearsal.end_time)

    def test_viewer_start_end_include_arrival_and_departure_buffer(self):
        """Assigned to a middle slot only (not first/last) shifts start/end by the Rehearsal's arrival/departure buffer.

        Guards against timeline_for() re-diverging from
        attendance_suggestion_for() (issue: UI overhaul round 2, item 1 —
        the Home/Schedule timeline previously showed the raw slot boundary
        with no buffer at all).
        """
        rehearsal = RehearsalFactory(
            is_full_setlist=False, arrival_buffer_minutes=15, departure_buffer_minutes=10,
        )
        self._slot(rehearsal, 1)
        middle = self._slot(rehearsal, 2, assign=True)
        self._slot(rehearsal, 3)

        timeline = timeline_for(rehearsal, self.person)
        suggestion = attendance_suggestion_for(rehearsal, self.person)

        self.assertEqual(timeline.viewer_start_time, suggestion.arrival_time)
        self.assertEqual(timeline.viewer_end_time, suggestion.departure_time)
        self.assertLess(timeline.viewer_start_time, middle.start_time)
        self.assertGreater(timeline.viewer_end_time, middle.end_time)

    def test_dress_rehearsal_degenerates_to_the_whole_window_and_setlist(self):
        """The Dress Rehearsal has no RehearsalSong rows: the picture is the whole window, for every viewer (ADR-0006)."""
        dress_rehearsal = RehearsalFactory(is_full_setlist=True)
        SongFactory(semester=dress_rehearsal.semester)
        SongFactory(semester=dress_rehearsal.semester)

        timeline = timeline_for(dress_rehearsal, self.person)

        self.assertEqual(timeline.slots, [])
        self.assertEqual(timeline.viewer_song_count, 2)
        self.assertEqual(timeline.total_song_count, 2)
        self.assertEqual(timeline.viewer_start_time, dress_rehearsal.start_time)
        self.assertEqual(timeline.viewer_end_time, dress_rehearsal.end_time)
        self.assertTrue(timeline.is_dress_rehearsal)


class AssignmentMatrixForTests(TestCase):
    def test_rows_ordered_by_rehearsal_song_order_with_start_times(self):
        """Rows are the Rehearsal's Songs in RehearsalSong.order (Running Order), each carrying its start_time.

        Deliberately not Song.position (the Setlist's concert position):
        the Running Order can be dealt/shuffled independently of it
        (CLAUDE.md), and this grid must agree with `timeline_for()`'s slot
        picture — rendered on Home and Schedule from the same
        RehearsalSong.order — about which position a Song is in.
        """
        rehearsal = RehearsalFactory(is_full_setlist=False)
        semester = rehearsal.semester
        second_song = SongFactory(semester=semester, position=1)
        first_song = SongFactory(semester=semester, position=2)
        second_rs = RehearsalSongFactory(song=second_song, rehearsal=rehearsal, order=2)
        first_rs = RehearsalSongFactory(song=first_song, rehearsal=rehearsal, order=1)

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

    def test_a_song_role_assignment_always_implies_a_column(self):
        """A SongRoleAssignment is a column, since issue #439 gates it on a matching SongRoleRequirement existing.

        Unlike the gate #151/#186 removed (and #213 restored), issue #439
        reverses course again: a Role is only ever assignable once its
        Requirement exists, so `SongRoleAssignmentFactory()`'s
        auto-created Requirement (see its docstring) is what actually
        makes this Role a column here, not the Assignment on its own.
        """
        rehearsal = RehearsalFactory(is_full_setlist=False)
        song = SongFactory(semester=rehearsal.semester, position=1)
        RehearsalSongFactory(song=song, rehearsal=rehearsal, order=1)
        role = RoleFactory(name='Bassist')
        SongRoleAssignmentFactory(song=song, role=role)

        matrix = assignment_matrix_for(rehearsal)

        self.assertEqual(matrix.roles, [role])
        [cell] = matrix.rows[0].cells
        self.assertEqual(cell.role, role)
        self.assertEqual(len(cell.entries), 1)

    def test_role_with_neither_requirement_nor_assignment_is_not_a_column(self):
        """A Role carrying no Requirement and no Assignment on the Rehearsal's Songs is not a column."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        song = SongFactory(semester=rehearsal.semester, position=1)
        RehearsalSongFactory(song=song, rehearsal=rehearsal, order=1)
        RoleFactory(name='Drummer')

        matrix = assignment_matrix_for(rehearsal)

        self.assertEqual(matrix.roles, [])

    def test_cell_lists_entries_with_role_mismatch_flag(self):
        """A cell lists an entry per SongRoleAssignment for its (Song, Role) pair, carrying is_role_mismatch."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        song = SongFactory(semester=rehearsal.semester, position=1)
        RehearsalSongFactory(song=song, rehearsal=rehearsal, order=1)
        role = RoleFactory()
        SongRoleRequirementFactory(song=song, role=role, count=1)
        person = PersonFactory()
        MembershipFactory(person=person, semester=rehearsal.semester)
        PersonRoleFactory(person=person, role=role)
        matched = SongRoleAssignmentFactory(song=song, role=role, person=person)
        mismatched_person = PersonFactory()
        MembershipFactory(person=mismatched_person, semester=rehearsal.semester)
        mismatched = SongRoleAssignmentFactory(song=song, role=role, person=mismatched_person)

        matrix = assignment_matrix_for(rehearsal)

        [cell] = matrix.rows[0].cells
        self.assertCountEqual([entry.person for entry in cell.entries], [person, mismatched_person])
        self.assertCountEqual([entry.id for entry in cell.entries], [matched.pk, mismatched.pk])
        self.assertTrue(all(entry.kind == AssignmentMatrixEntryKind.ASSIGNMENT for entry in cell.entries))
        by_person = {entry.person: entry.is_role_mismatch for entry in cell.entries}
        self.assertFalse(by_person[person])
        self.assertTrue(by_person[mismatched_person])

    def test_entries_ordered_by_person_name(self):
        """A cell's entries are ordered by Person.name, matching the grid's display order (issue #208)."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        song = SongFactory(semester=rehearsal.semester, position=1)
        RehearsalSongFactory(song=song, rehearsal=rehearsal, order=1)
        role = RoleFactory()
        SongRoleRequirementFactory(song=song, role=role, count=2)
        zed = PersonFactory(name='Zed')
        anna = PersonFactory(name='Anna')
        SongRoleAssignmentFactory(song=song, role=role, person=zed)
        SongRoleAssignmentFactory(song=song, role=role, person=anna)

        matrix = assignment_matrix_for(rehearsal)

        [cell] = matrix.rows[0].cells
        self.assertEqual([entry.person for entry in cell.entries], [anna, zed])

    def test_empty_cell_for_song_role_pair_with_no_assignment(self):
        """A (Song, Role) column pair with no SongRoleAssignment yields an empty cell, not a missing one."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        song = SongFactory(semester=rehearsal.semester, position=1)
        RehearsalSongFactory(song=song, rehearsal=rehearsal, order=1)
        role = RoleFactory()
        SongRoleRequirementFactory(song=song, role=role, count=1)

        matrix = assignment_matrix_for(rehearsal)

        [cell] = matrix.rows[0].cells
        self.assertEqual(cell.entries, [])


class AssignmentGridIsEditableTests(TestCase):
    def test_future_rehearsal_is_editable(self):
        """A Rehearsal dated after today offers edit mode."""
        rehearsal = RehearsalFactory(is_full_setlist=False, date=timezone.localdate() + timedelta(days=1))

        self.assertTrue(assignment_grid_is_editable(rehearsal))

    def test_todays_rehearsal_is_editable(self):
        """A Rehearsal dated today stays editable all day (whole days, not instants)."""
        rehearsal = RehearsalFactory(is_full_setlist=False, date=timezone.localdate())

        self.assertTrue(assignment_grid_is_editable(rehearsal))

    def test_past_rehearsal_is_not_editable(self):
        """A Rehearsal dated before today offers no edit mode — its Backups describe an evening that already happened."""
        rehearsal = RehearsalFactory(is_full_setlist=False, date=timezone.localdate() - timedelta(days=1))

        self.assertFalse(assignment_grid_is_editable(rehearsal))

    def test_the_dress_rehearsal_is_never_editable_whatever_its_date(self):
        """The old ADR-0009 backstop is gone (ADR-0019) and the Dress Rehearsal is excluded outright, future-dated or not.

        The old direction of this exclusion (`is_full_setlist **or** a
        future date`) is what's retired; the Dress Rehearsal has no
        RehearsalSong to edit at all (ADR-0003), which
        `_editable_rehearsal_or_404()` enforces on the endpoints. This
        predicate says the same thing, because it is also what
        `_serialize_rehearsal_detail()` puts on the wire as
        `can_edit_assignments` — an API that promised an edit its own
        endpoints 404'd would mislead any client trusting that field
        alone (PR #502 review).
        """
        past_dress = RehearsalFactory(is_full_setlist=True, date=timezone.localdate() - timedelta(days=30))
        future_dress = RehearsalFactory(is_full_setlist=True, date=timezone.localdate() + timedelta(days=30))

        self.assertFalse(assignment_grid_is_editable(past_dress))
        self.assertFalse(assignment_grid_is_editable(future_dress))


class AssignmentPickerForTests(TestCase):
    def test_declared_members_listed_before_others(self):
        """A rostered Member who declared the Role lands in `declared`; every other rostered Member lands in `others` (issue #211)."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        role = RoleFactory()
        declarer = PersonFactory(name='Ada')
        MembershipFactory(person=declarer, semester=semester)
        PersonRoleFactory(person=declarer, role=role)
        non_declarer = PersonFactory(name='Bea')
        MembershipFactory(person=non_declarer, semester=semester)

        result = assignment_picker_for(song, role, semester)

        self.assertEqual([option.person for option in result.declared], [declarer])
        self.assertTrue(result.declared[0].has_declared_role)
        self.assertEqual([option.person for option in result.others], [non_declarer])
        self.assertFalse(result.others[0].has_declared_role)

    def test_declared_role_persists_across_semesters(self):
        """A PersonRole declared once lands a Person in `declared` for every Semester they're rostered in (ADR-0014, issue #380)."""
        first_semester = SemesterFactory()
        second_semester = SemesterFactory()
        role = RoleFactory()
        person = PersonFactory(name='Ada')
        PersonRoleFactory(person=person, role=role)
        MembershipFactory(person=person, semester=first_semester)
        MembershipFactory(person=person, semester=second_semester)
        first_song = SongFactory(semester=first_semester)
        second_song = SongFactory(semester=second_semester)

        first_result = assignment_picker_for(first_song, role, first_semester)
        second_result = assignment_picker_for(second_song, role, second_semester)

        self.assertEqual([option.person for option in first_result.declared], [person])
        self.assertEqual([option.person for option in second_result.declared], [person])

    def test_a_membership_role_alone_no_longer_counts_as_declared(self):
        """A legacy `MembershipRole` row with no matching `PersonRole` no longer lands a Person in `declared` (issue #380)."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        role = RoleFactory()
        person = PersonFactory(name='Ada')
        membership = MembershipFactory(person=person, semester=semester)
        MembershipRole.objects.create(membership=membership, role=role)

        result = assignment_picker_for(song, role, semester)

        self.assertEqual(result.declared, [])
        self.assertEqual([option.person for option in result.others], [person])

    def test_options_ordered_by_person_name_within_each_group(self):
        """Within `declared` and within `others`, options are ordered by Person.name."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        role = RoleFactory()
        zed = PersonFactory(name='Zed')
        anna = PersonFactory(name='Anna')
        MembershipFactory(person=zed, semester=semester)
        MembershipFactory(person=anna, semester=semester)

        result = assignment_picker_for(song, role, semester)

        self.assertEqual([option.person for option in result.others], [anna, zed])

    def test_non_rostered_person_is_never_offered(self):
        """A Person with no Membership in the Semester is offered nowhere in the picker."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        role = RoleFactory()
        PersonFactory(name='Outsider')  # no Membership in `semester`

        result = assignment_picker_for(song, role, semester)

        self.assertEqual(result.declared, [])
        self.assertEqual(result.others, [])

    def test_a_rostered_person_from_a_different_semester_is_not_offered(self):
        """A Membership in a different Semester doesn't make a Person eligible for this one."""
        semester = SemesterFactory()
        other_semester = SemesterFactory()
        song = SongFactory(semester=semester)
        role = RoleFactory()
        MembershipFactory(semester=other_semester)

        result = assignment_picker_for(song, role, semester)

        self.assertEqual(result.declared, [])
        self.assertEqual(result.others, [])

    def test_already_assigned_person_is_excluded(self):
        """A Person already holding this exact (Song, Role) assignment is not re-offered — re-adding them would only invite a duplicate."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        role = RoleFactory()
        person = PersonFactory()
        MembershipFactory(person=person, semester=semester)
        SongRoleAssignmentFactory(song=song, role=role, person=person)

        result = assignment_picker_for(song, role, semester)

        self.assertEqual(result.declared, [])
        self.assertEqual(result.others, [])

    def test_assignment_on_a_different_role_does_not_exclude_the_person(self):
        """A Person already assigned to this Song under a different Role is still offered for this cell's Role."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        role = RoleFactory()
        other_role = RoleFactory()
        person = PersonFactory()
        MembershipFactory(person=person, semester=semester)
        SongRoleAssignmentFactory(song=song, role=other_role, person=person)

        result = assignment_picker_for(song, role, semester)

        self.assertEqual([option.person for option in result.others], [person])


class AssignableRosterForTests(TestCase):
    """`assignable_roster_for()` (issue #399): the picker's roster+declared-Roles source, embedded once per Rehearsal detail so the "+" picker needs no per-cell fetch."""

    def test_returns_every_rostered_person_with_their_declared_role_ids(self):
        """Each entry carries the Person and the pk set of every Role they've declared (ADR-0014, person-level)."""
        semester = SemesterFactory()
        guitar = RoleFactory()
        vocals = RoleFactory()
        person = PersonFactory(name='Ada')
        MembershipFactory(person=person, semester=semester)
        PersonRoleFactory(person=person, role=guitar)
        PersonRoleFactory(person=person, role=vocals)

        result = assignable_roster_for(semester)

        self.assertEqual([entry.person for entry in result], [person])
        self.assertEqual(result[0].declared_role_ids, frozenset({guitar.pk, vocals.pk}))

    def test_a_rostered_person_with_no_declared_role_gets_an_empty_set(self):
        """A rostered Person who has declared no Role gets an empty `declared_role_ids`, not a missing entry."""
        semester = SemesterFactory()
        person = PersonFactory(name='Bea')
        MembershipFactory(person=person, semester=semester)

        result = assignable_roster_for(semester)

        self.assertEqual(result[0].declared_role_ids, frozenset())

    def test_a_non_rostered_person_is_excluded(self):
        """A Person with no Membership in the Semester is offered nowhere in the picker."""
        semester = SemesterFactory()
        PersonFactory(name='Outsider')  # no Membership in `semester`

        result = assignable_roster_for(semester)

        self.assertEqual(result, [])

    def test_a_membership_in_a_different_semester_is_excluded(self):
        """A Membership in a different Semester doesn't make a Person eligible for this one."""
        semester = SemesterFactory()
        other_semester = SemesterFactory()
        MembershipFactory(semester=other_semester)

        result = assignable_roster_for(semester)

        self.assertEqual(result, [])

    def test_declared_role_persists_across_semesters(self):
        """A PersonRole declared once shows up in `declared_role_ids` for every Semester the Person is rostered in (ADR-0014, issue #380)."""
        first_semester = SemesterFactory()
        second_semester = SemesterFactory()
        role = RoleFactory()
        person = PersonFactory(name='Ada')
        PersonRoleFactory(person=person, role=role)
        MembershipFactory(person=person, semester=first_semester)
        MembershipFactory(person=person, semester=second_semester)

        first_result = assignable_roster_for(first_semester)
        second_result = assignable_roster_for(second_semester)

        self.assertEqual(first_result[0].declared_role_ids, frozenset({role.pk}))
        self.assertEqual(second_result[0].declared_role_ids, frozenset({role.pk}))

    def test_ordered_by_person_name(self):
        """Entries come back ordered by `Person.name`, independent of Membership creation order."""
        semester = SemesterFactory()
        zed = PersonFactory(name='Zed')
        anna = PersonFactory(name='Anna')
        MembershipFactory(person=zed, semester=semester)
        MembershipFactory(person=anna, semester=semester)

        result = assignable_roster_for(semester)

        self.assertEqual([entry.person for entry in result], [anna, zed])


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

    def test_dress_rehearsal_is_excluded(self):
        """Dress Rehearsal attendance is mandatory (ADR-0006), so it never appears in the declarable list."""
        semester = SemesterFactory()
        today = timezone.localdate()
        ordinary = RehearsalFactory(semester=semester, date=today + timedelta(days=1))
        RehearsalFactory(semester=semester, date=today + timedelta(days=2), is_full_setlist=True)

        result = future_rehearsals_for(semester)

        self.assertEqual(result, [ordinary])


class DeclareConflictTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Person and a Rehearsal with a known time span for every test."""
        cls.person = PersonFactory()
        cls.rehearsal = RehearsalFactory(start_time=time(18, 0), end_time=time(19, 30))

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

    def test_resubmitting_edits_the_existing_conflict_instead_of_creating_a_second_one(self):
        """A second declare_conflict call against the same (person, rehearsal) edits the row in place (issue #99)."""
        first = declare_conflict(
            person=self.person, rehearsal=self.rehearsal, declaration_type='full_absence', reason='Sick.',
        )

        second = declare_conflict(
            person=self.person, rehearsal=self.rehearsal, declaration_type='late_arrival', declared_time=time(18, 30),
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Conflict.objects.filter(person=self.person, rehearsal=self.rehearsal).count(), 1)
        self.assertEqual(second.type, Conflict.PARTIAL)

    def test_editing_from_late_arrival_to_early_departure_replaces_the_window(self):
        """Editing a partial Conflict to the other partial shape drops the stale window and adds the new one."""
        declare_conflict(
            person=self.person, rehearsal=self.rehearsal, declaration_type='late_arrival', declared_time=time(18, 30),
        )

        conflict = declare_conflict(
            person=self.person, rehearsal=self.rehearsal, declaration_type='early_departure', declared_time=time(19, 0),
        )

        windows = list(ConflictWindow.objects.filter(conflict=conflict))
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].unavailable_start, time(19, 0))
        self.assertEqual(windows[0].unavailable_end, time(19, 30))

    def test_dress_rehearsal_is_rejected(self):
        """Dress Rehearsal attendance is mandatory (ADR-0006), so no declaration against it is accepted."""
        dress_rehearsal = RehearsalFactory(is_full_setlist=True)

        with self.assertRaises(ValueError):
            declare_conflict(
                person=self.person, rehearsal=dress_rehearsal, declaration_type='full_absence',
            )

        self.assertFalse(Conflict.objects.filter(rehearsal=dress_rehearsal).exists())

    def test_editing_from_partial_to_full_absence_clears_the_window(self):
        """Editing a partial Conflict to full_absence leaves no ConflictWindow behind."""
        declare_conflict(
            person=self.person, rehearsal=self.rehearsal, declaration_type='late_arrival', declared_time=time(18, 30),
        )

        conflict = declare_conflict(person=self.person, rehearsal=self.rehearsal, declaration_type='full_absence')

        self.assertEqual(conflict.type, Conflict.FULL_CONFLICT)
        self.assertFalse(ConflictWindow.objects.filter(conflict=conflict).exists())


class ConflictHistoryForTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Semester and a Person to view History for."""
        cls.semester = SemesterFactory()
        cls.person = PersonFactory()

    def test_only_includes_rehearsals_with_a_submitted_conflict(self):
        """A Rehearsal with no Conflict for this Person is not in History; one with a Conflict is."""
        RehearsalFactory(semester=self.semester, date=date(2026, 9, 16))
        declared = RehearsalFactory(semester=self.semester, date=date(2026, 9, 23))
        ConflictFactory(person=self.person, rehearsal=declared, type=Conflict.FULL_CONFLICT)

        rows = conflict_history_for(self.semester, self.person)

        self.assertEqual([row.rehearsal for row in rows], [declared])

    def test_another_persons_conflict_is_not_included(self):
        """A Conflict declared by a different Person for the same Rehearsal is not in this Person's History."""
        other_person = PersonFactory()
        rehearsal = RehearsalFactory(semester=self.semester)
        ConflictFactory(person=other_person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)

        rows = conflict_history_for(self.semester, self.person)

        self.assertEqual(rows, [])

    def test_full_conflict_derives_full_absence_label_with_no_declared_time(self):
        """A FULL_CONFLICT Conflict derives the full_absence type and label, with no declared_time."""
        rehearsal = RehearsalFactory(semester=self.semester)
        ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)

        [row] = conflict_history_for(self.semester, self.person)

        self.assertEqual(row.declaration_type, 'full_absence')
        self.assertEqual(row.type_label, 'Full absence')
        self.assertIsNone(row.declared_time)

    def test_window_touching_start_time_derives_late_arrival(self):
        """A ConflictWindow starting at the Rehearsal's start_time derives late_arrival, with declared_time=window end."""
        rehearsal = RehearsalFactory(semester=self.semester, start_time=time(18, 0), end_time=time(19, 30))
        conflict = ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))

        [row] = conflict_history_for(self.semester, self.person)

        self.assertEqual(row.declaration_type, 'late_arrival')
        self.assertEqual(row.type_label, 'Late arrival')
        self.assertEqual(row.declared_time, time(18, 30))

    def test_window_touching_end_time_derives_early_departure(self):
        """A ConflictWindow ending at the Rehearsal's end_time derives early_departure, with declared_time=window start."""
        rehearsal = RehearsalFactory(semester=self.semester, start_time=time(18, 0), end_time=time(19, 30))
        conflict = ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(19, 0), unavailable_end=time(19, 30))

        [row] = conflict_history_for(self.semester, self.person)

        self.assertEqual(row.declaration_type, 'early_departure')
        self.assertEqual(row.type_label, 'Early departure')
        self.assertEqual(row.declared_time, time(19, 0))

    def test_partial_conflict_with_no_window_derives_none_instead_of_crashing(self):
        """A PARTIAL Conflict with zero ConflictWindow rows (e.g. admin-created) derives (None, None), not an AttributeError."""
        rehearsal = RehearsalFactory(semester=self.semester, start_time=time(18, 0), end_time=time(19, 30))
        ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.PARTIAL)

        [row] = conflict_history_for(self.semester, self.person)

        self.assertIsNone(row.declaration_type)
        self.assertEqual(row.type_label, 'Partial (custom)')
        self.assertIsNone(row.declared_time)

    def test_window_touching_neither_boundary_derives_none_instead_of_mislabeling(self):
        """A ConflictWindow anchored at neither the Rehearsal's start nor end derives (None, None), not a guessed label."""
        rehearsal = RehearsalFactory(semester=self.semester, start_time=time(18, 0), end_time=time(19, 30))
        conflict = ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 30), unavailable_end=time(19, 0))

        [row] = conflict_history_for(self.semester, self.person)

        self.assertIsNone(row.declaration_type)
        self.assertEqual(row.type_label, 'Partial (custom)')
        self.assertIsNone(row.declared_time)

    def test_scoped_to_the_given_semester(self):
        """A Conflict on a Rehearsal from a different Semester is not included."""
        other_rehearsal = RehearsalFactory()
        ConflictFactory(person=self.person, rehearsal=other_rehearsal, type=Conflict.FULL_CONFLICT)

        rows = conflict_history_for(self.semester, self.person)

        self.assertEqual(rows, [])

    def test_past_and_future_rehearsals_are_flagged_accordingly(self):
        """A past Rehearsal's row has is_future=False; a future one's has is_future=True."""
        today = timezone.localdate()
        past = RehearsalFactory(semester=self.semester, date=today - timedelta(days=1))
        future = RehearsalFactory(semester=self.semester, date=today + timedelta(days=1))
        ConflictFactory(person=self.person, rehearsal=past, type=Conflict.FULL_CONFLICT)
        ConflictFactory(person=self.person, rehearsal=future, type=Conflict.FULL_CONFLICT)

        rows = conflict_history_for(self.semester, self.person)

        by_rehearsal = {row.rehearsal: row.is_future for row in rows}
        self.assertFalse(by_rehearsal[past])
        self.assertTrue(by_rehearsal[future])

    def test_rows_ordered_by_date(self):
        """History rows are ordered by Rehearsal date (issue #214: one Rehearsal per date per Semester, so date alone orders them)."""
        today = timezone.localdate()
        later = RehearsalFactory(semester=self.semester, date=today + timedelta(days=1), start_time=time(17, 0))
        earlier = RehearsalFactory(semester=self.semester, date=today, start_time=time(19, 0))
        ConflictFactory(person=self.person, rehearsal=later, type=Conflict.FULL_CONFLICT)
        ConflictFactory(person=self.person, rehearsal=earlier, type=Conflict.FULL_CONFLICT)

        rows = conflict_history_for(self.semester, self.person)

        self.assertEqual([row.rehearsal for row in rows], [earlier, later])


class RehearsalScheduleForTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Semester and a Person to view its schedule."""
        cls.semester = SemesterFactory()
        cls.person = PersonFactory()

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

    def test_rows_ordered_by_date(self):
        """Rows within each split are ordered by date (issue #214: one Rehearsal per date per Semester, so date alone orders them)."""
        today = timezone.localdate()
        later = RehearsalFactory(semester=self.semester, date=today + timedelta(days=2), start_time=time(17, 0))
        earlier = RehearsalFactory(semester=self.semester, date=today + timedelta(days=1), start_time=time(19, 0))

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

    def test_row_carries_the_running_order_and_your_songs(self):
        """Each row's `songs`/`your_rehearsal_songs` match what `assignment_matrix_for()`/`slots_for_person()` would have reported, per-Rehearsal (issue #394)."""
        rehearsal = RehearsalFactory(semester=self.semester, date=timezone.localdate() + timedelta(days=1))
        assigned_song = SongFactory(semester=self.semester, position=1)
        other_song = SongFactory(semester=self.semester, position=2)
        RehearsalSongFactory(song=assigned_song, rehearsal=rehearsal, order=1)
        RehearsalSongFactory(song=other_song, rehearsal=rehearsal, order=2)
        SongRoleAssignmentFactory(song=assigned_song, person=self.person)

        schedule = rehearsal_schedule_for(self.semester, self.person)

        row = schedule.future[0]
        self.assertEqual([song.pk for song in row.songs], [assigned_song.pk, other_song.pk])
        self.assertEqual([rs.song_id for rs in row.your_rehearsal_songs], [assigned_song.pk])

    def test_attendance_suggestion_matches_the_single_rehearsal_derivation_needed_at_one_end(self):
        """A row's batched `attendance_suggestion` matches `attendance_suggestion_for()`'s own per-Rehearsal computation when the Person is needed at only one end (issue #394).

        Guards the bulk derivation in `_regular_attendance_suggestion_from_slots()`
        against drifting from `_regular_rehearsal_attendance_suggestion()`/
        `Rehearsal.attendance_for()`, which callers outside the All-rehearsals
        list (e.g. `timeline_for()`) still use directly.
        """
        rehearsal = RehearsalFactory(semester=self.semester, date=timezone.localdate() + timedelta(days=1))
        first_song = SongFactory(semester=self.semester, position=1)
        second_song = SongFactory(semester=self.semester, position=2)
        RehearsalSongFactory(song=first_song, rehearsal=rehearsal, order=1)
        RehearsalSongFactory(song=second_song, rehearsal=rehearsal, order=2)
        SongRoleAssignmentFactory(song=second_song, person=self.person)  # needed at the end only, not the start

        schedule = rehearsal_schedule_for(self.semester, self.person)

        row = schedule.future[0]
        self.assertEqual(row.attendance_suggestion, attendance_suggestion_for(rehearsal, self.person))

    def test_attendance_suggestion_matches_the_single_rehearsal_derivation_needed_at_both_ends(self):
        """The batched suggestion also matches the single-Rehearsal derivation when the Person is needed for the whole window (issue #394)."""
        rehearsal = RehearsalFactory(semester=self.semester, date=timezone.localdate() + timedelta(days=1))
        first_song = SongFactory(semester=self.semester, position=1)
        second_song = SongFactory(semester=self.semester, position=2)
        RehearsalSongFactory(song=first_song, rehearsal=rehearsal, order=1)
        RehearsalSongFactory(song=second_song, rehearsal=rehearsal, order=2)
        SongRoleAssignmentFactory(song=first_song, person=self.person)
        SongRoleAssignmentFactory(song=second_song, person=self.person)

        schedule = rehearsal_schedule_for(self.semester, self.person)

        row = schedule.future[0]
        suggestion = row.attendance_suggestion
        self.assertEqual(suggestion, attendance_suggestion_for(rehearsal, self.person))
        self.assertEqual(suggestion.arrival_time, rehearsal.start_time)
        self.assertEqual(suggestion.departure_time, rehearsal.end_time)

    def test_query_count_does_not_scale_with_rehearsal_count(self):
        """Building the schedule for a Semester with many Rehearsals costs the same query count as one with few (issue #394).

        Guards against re-introducing a per-Rehearsal query (e.g. calling
        `assignment_matrix_for()`/`slots_for_person()` in a loop over
        Rehearsals) — the regression this ticket fixes, which made the
        All-rehearsals list's cost scale with the Semester's Rehearsal
        count instead of staying flat.
        """
        def _build_rehearsal(day_offset):
            rehearsal = RehearsalFactory(
                semester=self.semester, date=timezone.localdate() + timedelta(days=day_offset),
            )
            song = SongFactory(semester=self.semester, position=day_offset)
            RehearsalSongFactory(song=song, rehearsal=rehearsal, order=1)
            SongRoleAssignmentFactory(song=song, person=self.person)
            return rehearsal

        _build_rehearsal(1)
        _build_rehearsal(2)
        with CaptureQueriesContext(connection) as few:
            rehearsal_schedule_for(self.semester, self.person)

        for offset in range(3, 9):
            _build_rehearsal(offset)
        with CaptureQueriesContext(connection) as many:
            rehearsal_schedule_for(self.semester, self.person)

        self.assertEqual(len(few.captured_queries), len(many.captured_queries))


class ActiveRolesForTests(TestCase):
    def test_only_active_roles_in_name_order(self):
        """Returns only is_active Roles, ordered by name, regardless of creation order."""
        RoleFactory(name='Zither', is_active=False)
        drummer = RoleFactory(name='Drummer')
        bassist = RoleFactory(name='Bassist')
        semester = SemesterFactory()

        roles = active_roles_for(semester)

        self.assertEqual(roles, [bassist, drummer])


class RoleCodesForTests(TestCase):
    def test_multi_word_name_codes_by_initials(self):
        """A multi-word Role name codes to the uppercased initials of its first three words."""
        role = RoleFactory(name='Lead Guitar')

        codes = role_codes_for([role])

        self.assertEqual(codes[role.id], 'LG')

    def test_single_word_name_codes_to_first_three_letters(self):
        """A single-word Role name codes to its first three letters, uppercased."""
        role = RoleFactory(name='Drummer')

        codes = role_codes_for([role])

        self.assertEqual(codes[role.id], 'DRU')

    def test_colliding_codes_fall_back_to_the_full_name(self):
        """Two Roles whose derived codes collide both fall back to their full names, so the code stays unambiguous."""
        first = RoleFactory(name='Bass Guitar')
        second = RoleFactory(name='Backing Guitar')

        codes = role_codes_for([first, second])

        self.assertEqual(codes[first.id], 'Bass Guitar')
        self.assertEqual(codes[second.id], 'Backing Guitar')


class CastLineForTests(TestCase):
    def test_includes_an_empty_entry_for_an_unfilled_role(self):
        """A Role in the given role set with nobody assigned still gets an entry, with an empty performers list."""
        song = SongFactory()
        singer = RoleFactory(name='Singer')
        drummer = RoleFactory(name='Drummer')
        codes = role_codes_for([drummer, singer])

        entries = cast_line_for(song, [drummer, singer], codes)

        self.assertEqual([entry.role for entry in entries], [drummer, singer])
        self.assertEqual(entries[0].performers, [])
        self.assertEqual(entries[1].performers, [])

    def test_shape_is_constant_regardless_of_the_songs_own_requirements(self):
        """The entries follow the given role set, not the Song's own SongRoleRequirements."""
        song = SongFactory()
        singer = RoleFactory(name='Singer')
        drummer = RoleFactory(name='Drummer')
        SongRoleRequirementFactory(song=song, role=singer)  # Song only requests Singer
        codes = role_codes_for([drummer, singer])

        entries = cast_line_for(song, [drummer, singer], codes)

        self.assertEqual(len(entries), 2)

    def test_a_filled_role_carries_its_performer_and_mismatch_flag(self):
        """A filled Role's entry carries the assigned Person and their is_role_mismatch flag for that Role (ADR-0002)."""
        song = SongFactory()
        role = RoleFactory(name='Bassist')
        person = PersonFactory()
        SongRoleAssignmentFactory(song=song, role=role, person=person)
        codes = role_codes_for([role])

        entries = cast_line_for(song, [role], codes)

        self.assertEqual(len(entries[0].performers), 1)
        self.assertEqual(entries[0].performers[0].person, person)
        self.assertTrue(entries[0].performers[0].is_role_mismatch)

    def test_a_backup_only_person_is_excluded(self):
        """A Backup-only Person (no SongRoleAssignment) does not appear in the cast line (ADR-0007)."""
        song = SongFactory()
        role = RoleFactory()
        rehearsal_song = RehearsalSongFactory(song=song, rehearsal=RehearsalFactory(semester=song.semester))
        BackupFactory(rehearsal_song=rehearsal_song, role=role)
        codes = role_codes_for([role])

        entries = cast_line_for(song, [role], codes)

        self.assertEqual(entries[0].performers, [])


class CastLinesForSemesterTests(TestCase):
    def test_matches_cast_line_for_per_song(self):
        """Every Song's bulk cast line matches what cast_line_for() would compute for it directly (issue #394)."""
        semester = SemesterFactory()
        singer = RoleFactory(name='Singer')
        drummer = RoleFactory(name='Drummer')
        first_song = SongFactory(semester=semester)
        second_song = SongFactory(semester=semester)
        person = PersonFactory()
        SongRoleAssignmentFactory(song=first_song, role=singer, person=person)
        SongRoleAssignmentFactory(song=second_song, role=drummer, person=PersonFactory())
        codes = role_codes_for([drummer, singer])

        cast_lines = cast_lines_for_semester(semester, [drummer, singer], codes)

        self.assertEqual(cast_lines[first_song.pk], cast_line_for(first_song, [drummer, singer], codes))
        self.assertEqual(cast_lines[second_song.pk], cast_line_for(second_song, [drummer, singer], codes))

    def test_a_song_with_no_assignments_gets_every_role_empty(self):
        """A Song with no SongRoleAssignments still gets an entry per Role, each with an empty performers list (issue #394)."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        role = RoleFactory()
        codes = role_codes_for([role])

        cast_lines = cast_lines_for_semester(semester, [role], codes)

        self.assertEqual(cast_lines[song.pk][0].performers, [])

    def test_query_count_does_not_scale_with_song_count(self):
        """Building cast lines for every Song in the Semester costs the same query count regardless of Song count (issue #394).

        Guards against re-introducing a per-Song query (e.g. calling
        `cast_line_for()`/`performers_for()` in a loop over Songs) — the
        regression this ticket fixes, which made the Setlist's cost scale
        with the Semester's Song count instead of staying flat.
        """
        semester = SemesterFactory()
        role = RoleFactory()
        codes = role_codes_for([role])

        def _build_song():
            song = SongFactory(semester=semester)
            SongRoleAssignmentFactory(song=song, role=role, person=PersonFactory())
            return song

        _build_song()
        _build_song()
        with CaptureQueriesContext(connection) as few:
            cast_lines_for_semester(semester, [role], codes)

        for _ in range(6):
            _build_song()
        with CaptureQueriesContext(connection) as many:
            cast_lines_for_semester(semester, [role], codes)

        self.assertEqual(len(few.captured_queries), len(many.captured_queries))


class SetlistTotalRunningTimeForTests(TestCase):
    def test_empty_setlist_returns_zero(self):
        """A Semester with no Songs returns "0:00", not an error."""
        semester = SemesterFactory()

        self.assertEqual(setlist_total_running_time(semester), '0:00')

    def test_sums_every_songs_length(self):
        """Sums every Song's length in the Semester, formatted as a display string."""
        semester = SemesterFactory()
        SongFactory(semester=semester, length=timedelta(minutes=3, seconds=30))
        SongFactory(semester=semester, length=timedelta(minutes=4, seconds=15))

        self.assertEqual(setlist_total_running_time(semester), '7:45')

    def test_scoped_to_the_given_semester_only(self):
        """A Song in a different Semester is not summed in."""
        semester = SemesterFactory()
        SongFactory(semester=semester, length=timedelta(minutes=3))
        SongFactory(length=timedelta(minutes=10))  # different semester

        self.assertEqual(setlist_total_running_time(semester), '3:00')


class RehearsedAtForTests(TestCase):
    def test_includes_each_scheduled_slot_with_its_times(self):
        """Each RehearsalSong slot the Song is scheduled at appears with the Rehearsal and its slot times."""
        song = SongFactory()
        rehearsal = RehearsalFactory(semester=song.semester)
        rehearsal_song = RehearsalSongFactory(song=song, rehearsal=rehearsal, order=1)

        rows = rehearsed_at_for(song)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].rehearsal, rehearsal)
        self.assertFalse(rows[0].is_dress_rehearsal)
        self.assertEqual(rows[0].start_time, rehearsal_song.start_time)
        self.assertEqual(rows[0].end_time, rehearsal_song.end_time)

    def test_appends_the_dress_rehearsal_as_a_live_whole_setlist_row(self):
        """The Semester's Dress Rehearsal is appended with no slot time, even though it carries no RehearsalSong row (ADR-0003)."""
        song = SongFactory()
        dress_rehearsal = RehearsalFactory(semester=song.semester, is_full_setlist=True)

        rows = rehearsed_at_for(song)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].rehearsal, dress_rehearsal)
        self.assertTrue(rows[0].is_dress_rehearsal)
        self.assertIsNone(rows[0].start_time)
        self.assertIsNone(rows[0].end_time)

    def test_no_dress_rehearsal_yields_only_scheduled_slots(self):
        """A Semester with no Dress Rehearsal yields only the Song's scheduled slots, no extra row."""
        song = SongFactory()
        RehearsalSongFactory(song=song, rehearsal=RehearsalFactory(semester=song.semester), order=1)

        rows = rehearsed_at_for(song)

        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].is_dress_rehearsal)


class FutureSchedulingFootprintForTests(TestCase):
    """`future_scheduling_footprint_for()` (issue #468, ADR-0017): the Deactivate confirmation dialog's dependency."""

    def test_empty_for_a_person_with_no_future_facing_state(self):
        """A Person with only a Membership in the excluded (viewing) Semester and nothing else gets three empty lists."""
        person = PersonFactory()
        viewing_semester = SemesterFactory()
        MembershipFactory(person=person, semester=viewing_semester)

        footprint = future_scheduling_footprint_for(person, excluding_semester=viewing_semester)

        self.assertEqual(footprint.future_memberships, [])
        self.assertEqual(footprint.future_role_assignments, [])
        self.assertEqual(footprint.future_rehearsal_appearances, [])

    def test_future_memberships_exclude_the_viewing_semester(self):
        """A Membership in the viewing Semester is excluded; Memberships in other Semesters are listed by name."""
        person = PersonFactory()
        viewing_semester = SemesterFactory(name='Viewing Semester')
        other_semester = SemesterFactory(name='Other Semester')
        MembershipFactory(person=person, semester=viewing_semester)
        MembershipFactory(person=person, semester=other_semester)

        footprint = future_scheduling_footprint_for(person, excluding_semester=viewing_semester)

        self.assertEqual(len(footprint.future_memberships), 1)
        self.assertEqual(footprint.future_memberships[0].semester_id, other_semester.pk)
        self.assertEqual(footprint.future_memberships[0].semester_name, 'Other Semester')

    def test_future_role_assignments_exclude_the_viewing_semesters_songs(self):
        """A SongRoleAssignment on the viewing Semester's own Song is excluded; one on another Semester's Song is listed."""
        person = PersonFactory()
        viewing_semester = SemesterFactory()
        other_semester = SemesterFactory(name='Other Semester')
        viewing_song = SongFactory(semester=viewing_semester, title='Viewing Song')
        other_song = SongFactory(semester=other_semester, title='Other Song')
        role = RoleFactory(name='Guitar')
        SongRoleAssignmentFactory(song=viewing_song, person=person, role=RoleFactory(name='Bass'))
        SongRoleAssignmentFactory(song=other_song, person=person, role=role)

        footprint = future_scheduling_footprint_for(person, excluding_semester=viewing_semester)

        self.assertEqual(len(footprint.future_role_assignments), 1)
        row = footprint.future_role_assignments[0]
        self.assertEqual(row.semester_id, other_semester.pk)
        self.assertEqual(row.song_id, other_song.pk)
        self.assertEqual(row.song_title, 'Other Song')
        self.assertEqual(row.role_name, 'Guitar')

    def test_future_rehearsal_appearances_include_the_viewing_semesters_own_future_rehearsals(self):
        """Unlike Memberships/Assignments, a future-dated Rehearsal in the viewing Semester itself is still included."""
        person = PersonFactory()
        viewing_semester = SemesterFactory()
        today = timezone.localdate()
        song = SongFactory(semester=viewing_semester, title='Upcoming Song')
        role = RoleFactory(name='Drums')
        SongRoleAssignmentFactory(song=song, person=person, role=role)
        rehearsal = RehearsalFactory(semester=viewing_semester, date=today + timedelta(days=3))
        RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)

        footprint = future_scheduling_footprint_for(person, excluding_semester=viewing_semester)

        self.assertEqual(len(footprint.future_rehearsal_appearances), 1)
        row = footprint.future_rehearsal_appearances[0]
        self.assertEqual(row.rehearsal_id, rehearsal.pk)
        self.assertEqual(row.semester_id, viewing_semester.pk)
        self.assertEqual(row.date, rehearsal.date)
        self.assertEqual(row.song_id, song.pk)
        self.assertEqual(row.role_name, 'Drums')
        self.assertEqual(row.kind, 'assignment')

    def test_a_past_rehearsal_appearance_is_excluded(self):
        """A RehearsalSong on a past-dated Rehearsal is never counted as a future appearance."""
        person = PersonFactory()
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        SongRoleAssignmentFactory(song=song, person=person, role=RoleFactory())
        past_rehearsal = RehearsalFactory(semester=semester, date=timezone.localdate() - timedelta(days=1))
        RehearsalSongFactory(rehearsal=past_rehearsal, song=song, order=1)

        footprint = future_scheduling_footprint_for(person, excluding_semester=None)

        self.assertEqual(footprint.future_rehearsal_appearances, [])

    def test_a_future_backup_appearance_is_included_with_kind_backup(self):
        """A Backup row on a future Rehearsal names `person` regardless of whether they hold the underlying Song's Standing Assignment."""
        person = PersonFactory()
        semester = SemesterFactory()
        song = SongFactory(semester=semester, title='Backed-up Song')
        role = RoleFactory(name='Keys')
        rehearsal = RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=1))
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        BackupFactory(rehearsal_song=rehearsal_song, person=person, role=role)

        footprint = future_scheduling_footprint_for(person, excluding_semester=None)

        self.assertEqual(len(footprint.future_rehearsal_appearances), 1)
        row = footprint.future_rehearsal_appearances[0]
        self.assertEqual(row.kind, 'backup')
        self.assertEqual(row.role_name, 'Keys')
        self.assertEqual(row.song_id, song.pk)

    def test_excluding_semester_none_includes_every_membership_and_assignment(self):
        """With no viewing Semester (`excluding_semester=None`), nothing is excluded from Memberships or Assignments."""
        person = PersonFactory()
        semester = SemesterFactory()
        MembershipFactory(person=person, semester=semester)
        SongRoleAssignmentFactory(song=SongFactory(semester=semester), person=person, role=RoleFactory())

        footprint = future_scheduling_footprint_for(person, excluding_semester=None)

        self.assertEqual(len(footprint.future_memberships), 1)
        self.assertEqual(len(footprint.future_role_assignments), 1)

    def test_spans_multiple_other_semesters(self):
        """Future-facing state accumulates correctly across more than one other Semester."""
        person = PersonFactory()
        viewing_semester = SemesterFactory()
        semester_a = SemesterFactory(name='Semester A')
        semester_b = SemesterFactory(name='Semester B')
        MembershipFactory(person=person, semester=semester_a)
        MembershipFactory(person=person, semester=semester_b)
        SongRoleAssignmentFactory(song=SongFactory(semester=semester_a), person=person, role=RoleFactory())
        SongRoleAssignmentFactory(song=SongFactory(semester=semester_b), person=person, role=RoleFactory())

        footprint = future_scheduling_footprint_for(person, excluding_semester=viewing_semester)

        self.assertEqual(len(footprint.future_memberships), 2)
        self.assertEqual(len(footprint.future_role_assignments), 2)
        self.assertEqual(
            {row.semester_id for row in footprint.future_memberships}, {semester_a.pk, semester_b.pk},
        )

    def test_a_semester_whose_every_rehearsal_is_past_is_excluded_from_memberships_and_assignments(self):
        """A genuinely concluded Semester — one whose only Rehearsals are already past — is never reported as a future commitment."""
        person = PersonFactory()
        concluded_semester = SemesterFactory(name='Concluded Semester')
        RehearsalFactory(semester=concluded_semester, date=timezone.localdate() - timedelta(days=30))
        MembershipFactory(person=person, semester=concluded_semester)
        SongRoleAssignmentFactory(song=SongFactory(semester=concluded_semester), person=person, role=RoleFactory())

        footprint = future_scheduling_footprint_for(person, excluding_semester=None)

        self.assertEqual(footprint.future_memberships, [])
        self.assertEqual(footprint.future_role_assignments, [])

    def test_a_semester_with_a_future_rehearsal_is_not_treated_as_concluded(self):
        """A Semester with at least one future-dated Rehearsal (alongside past ones) still counts as a live commitment."""
        person = PersonFactory()
        semester = SemesterFactory(name='Still Live Semester')
        RehearsalFactory(semester=semester, date=timezone.localdate() - timedelta(days=30))
        RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=30))
        MembershipFactory(person=person, semester=semester)

        footprint = future_scheduling_footprint_for(person, excluding_semester=None)

        self.assertEqual(len(footprint.future_memberships), 1)
        self.assertEqual(footprint.future_memberships[0].semester_id, semester.pk)

    def test_a_semester_with_no_rehearsals_at_all_is_not_treated_as_concluded(self):
        """A brand-new Semester with no Rehearsals scheduled yet has no evidence it's over, so it still counts as future."""
        person = PersonFactory()
        semester = SemesterFactory(name='Not Yet Scheduled Semester')
        MembershipFactory(person=person, semester=semester)

        footprint = future_scheduling_footprint_for(person, excluding_semester=None)

        self.assertEqual(len(footprint.future_memberships), 1)
        self.assertEqual(footprint.future_memberships[0].semester_id, semester.pk)

    def test_a_future_dress_rehearsal_is_synthesized_as_an_appearance_for_every_standing_assignment(self):
        """ADR-0003: the Dress Rehearsal carries no RehearsalSong row, so it's synthesized from each Standing Assignment in its Semester."""
        person = PersonFactory()
        semester = SemesterFactory()
        song = SongFactory(semester=semester, title='Dress Rehearsal Song')
        role = RoleFactory(name='Bass')
        SongRoleAssignmentFactory(song=song, person=person, role=role)
        dress_rehearsal = RehearsalFactory(
            semester=semester, date=timezone.localdate() + timedelta(days=7), is_full_setlist=True,
        )

        footprint = future_scheduling_footprint_for(person, excluding_semester=None)

        self.assertEqual(len(footprint.future_rehearsal_appearances), 1)
        row = footprint.future_rehearsal_appearances[0]
        self.assertEqual(row.rehearsal_id, dress_rehearsal.pk)
        self.assertEqual(row.song_id, song.pk)
        self.assertEqual(row.role_name, 'Bass')
        self.assertEqual(row.kind, 'assignment')
        self.assertTrue(row.is_dress_rehearsal)

    def test_a_past_dress_rehearsal_is_not_synthesized(self):
        """A Dress Rehearsal dated in the past never contributes an appearance, same as any other past Rehearsal."""
        person = PersonFactory()
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        SongRoleAssignmentFactory(song=song, person=person, role=RoleFactory())
        RehearsalFactory(semester=semester, date=timezone.localdate() - timedelta(days=7), is_full_setlist=True)

        footprint = future_scheduling_footprint_for(person, excluding_semester=None)

        self.assertEqual(footprint.future_rehearsal_appearances, [])

    def test_ordinary_rehearsal_song_appearances_are_not_flagged_as_dress_rehearsal(self):
        """A normal `RehearsalSong`-derived appearance (not the Dress Rehearsal) reports `is_dress_rehearsal=False`."""
        person = PersonFactory()
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        SongRoleAssignmentFactory(song=song, person=person, role=RoleFactory())
        rehearsal = RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=2))
        RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)

        footprint = future_scheduling_footprint_for(person, excluding_semester=None)

        self.assertEqual(len(footprint.future_rehearsal_appearances), 1)
        self.assertFalse(footprint.future_rehearsal_appearances[0].is_dress_rehearsal)
