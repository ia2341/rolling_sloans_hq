"""Rehearsal.attendance_for: derived arrival/departure need for a Person (issue #38)."""

from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import (
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)


class RehearsalAttendanceForTests(TestCase):
    def setUp(self):
        """Build a Rehearsal with three ordered RehearsalSong rows and an unassigned Person."""
        self.rehearsal = RehearsalFactory()
        self.role = RoleFactory()
        self.first_song = SongFactory(semester=self.rehearsal.semester)
        self.middle_song = SongFactory(semester=self.rehearsal.semester)
        self.last_song = SongFactory(semester=self.rehearsal.semester)
        RehearsalSongFactory(rehearsal=self.rehearsal, song=self.first_song, order=1)
        RehearsalSongFactory(rehearsal=self.rehearsal, song=self.middle_song, order=2)
        RehearsalSongFactory(rehearsal=self.rehearsal, song=self.last_song, order=3)
        self.person = PersonFactory()

    def test_assigned_only_to_first_song_is_needed_from_start_only(self):
        """A Person assigned only to the first RehearsalSong is needed from the start, not until the end."""
        SongRoleAssignmentFactory(song=self.first_song, role=self.role, person=self.person)

        attendance = self.rehearsal.attendance_for(self.person)

        self.assertTrue(attendance.needed_from_start)
        self.assertFalse(attendance.needed_until_end)

    def test_assigned_only_to_last_song_is_needed_until_end_only(self):
        """A Person assigned only to the last RehearsalSong is needed until the end, not from the start."""
        SongRoleAssignmentFactory(song=self.last_song, role=self.role, person=self.person)

        attendance = self.rehearsal.attendance_for(self.person)

        self.assertFalse(attendance.needed_from_start)
        self.assertTrue(attendance.needed_until_end)

    def test_assigned_to_first_and_last_song_is_needed_for_the_whole_rehearsal(self):
        """A Person assigned to both the first and last RehearsalSong is needed for the entire window."""
        SongRoleAssignmentFactory(song=self.first_song, role=self.role, person=self.person)
        SongRoleAssignmentFactory(song=self.last_song, role=self.role, person=self.person)

        attendance = self.rehearsal.attendance_for(self.person)

        self.assertTrue(attendance.needed_from_start)
        self.assertTrue(attendance.needed_until_end)

    def test_assigned_to_neither_first_nor_last_song_is_not_needed_at_either_end(self):
        """A Person assigned only to a middle RehearsalSong is needed at neither the start nor the end."""
        SongRoleAssignmentFactory(song=self.middle_song, role=self.role, person=self.person)

        attendance = self.rehearsal.attendance_for(self.person)

        self.assertFalse(attendance.needed_from_start)
        self.assertFalse(attendance.needed_until_end)

    def test_person_with_no_rehearsal_song_rows_is_not_needed_at_either_end(self):
        """A Rehearsal with no RehearsalSong rows yet reports neither end as needed for anyone."""
        empty_rehearsal = RehearsalFactory()

        attendance = empty_rehearsal.attendance_for(self.person)

        self.assertFalse(attendance.needed_from_start)
        self.assertFalse(attendance.needed_until_end)


class DressRehearsalAttendanceForTests(TestCase):
    def setUp(self):
        """Build a Dress Rehearsal (is_full_setlist=True) whose songs come live from the setlist."""
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=True)
        self.role = RoleFactory()
        self.first_song = SongFactory(semester=self.semester, position=1)
        self.middle_song = SongFactory(semester=self.semester, position=2)
        self.last_song = SongFactory(semester=self.semester, position=3)
        self.person = PersonFactory()

    def test_assigned_only_to_first_setlist_song_is_needed_from_start_only(self):
        """A Person assigned only to the setlist's first Song is needed from the start, not until the end."""
        SongRoleAssignmentFactory(song=self.first_song, role=self.role, person=self.person)

        attendance = self.rehearsal.attendance_for(self.person)

        self.assertTrue(attendance.needed_from_start)
        self.assertFalse(attendance.needed_until_end)

    def test_assigned_only_to_last_setlist_song_is_needed_until_end_only(self):
        """A Person assigned only to the setlist's last Song is needed until the end, not from the start."""
        SongRoleAssignmentFactory(song=self.last_song, role=self.role, person=self.person)

        attendance = self.rehearsal.attendance_for(self.person)

        self.assertFalse(attendance.needed_from_start)
        self.assertTrue(attendance.needed_until_end)

    def test_assigned_to_neither_first_nor_last_setlist_song_is_not_needed_at_either_end(self):
        """A Person assigned only to a middle setlist Song is needed at neither the start nor the end."""
        SongRoleAssignmentFactory(song=self.middle_song, role=self.role, person=self.person)

        attendance = self.rehearsal.attendance_for(self.person)

        self.assertFalse(attendance.needed_from_start)
        self.assertFalse(attendance.needed_until_end)

    def test_empty_setlist_is_not_needed_at_either_end(self):
        """A Dress Rehearsal for a Semester with no Songs yet reports neither end as needed for anyone."""
        empty_semester = SemesterFactory()
        empty_rehearsal = RehearsalFactory(semester=empty_semester, is_full_setlist=True)

        attendance = empty_rehearsal.attendance_for(self.person)

        self.assertFalse(attendance.needed_from_start)
        self.assertFalse(attendance.needed_until_end)
