"""`conflict_feasibility_for()`: the joint feasibility check and standing-overlap advisory (issue #194)."""

from datetime import time

from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import (
    BackupFactory,
    ConflictFactory,
    ConflictWindowFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Conflict
from scheduling.services import (
    FEASIBILITY_ROW_CEILING,
    FEASIBLE,
    INFEASIBLE,
    NOT_APPLICABLE,
    conflict_feasibility_for,
)


def _by_conflict_id(rows):
    """Index a conflict_feasibility_for() result by conflict_id for easy per-row assertions."""
    return {row.conflict_id: row for row in rows}


class FullConflictIsAlwaysNotApplicableTests(TestCase):
    def test_full_conflict_is_not_applicable_regardless_of_approval(self):
        """A full-absence Conflict is always NOT_APPLICABLE, whether or not it's in the approved set."""
        rehearsal = RehearsalFactory(is_full_setlist=False, start_time=time(18, 0), end_time=time(20, 0))
        conflict = ConflictFactory(rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)

        unapproved = _by_conflict_id(conflict_feasibility_for(rehearsal, approved_conflict_ids=set()))
        approved = _by_conflict_id(conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict.pk}))

        self.assertEqual(unapproved[conflict.pk].verdict, NOT_APPLICABLE)
        self.assertTrue(unapproved[conflict.pk].checked)
        self.assertEqual(approved[conflict.pk].verdict, NOT_APPLICABLE)


class NoAssignedSongsIsAlwaysFeasibleTests(TestCase):
    def test_partial_conflict_with_no_assigned_songs_is_feasible(self):
        """A partial Conflict held by somebody with no assigned Songs that evening is feasible: nothing to place."""
        semester = SemesterFactory(default_song_slot_count=1)
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(19, 0))
        song = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1, slot_count=1)
        conflict = ConflictFactory(rehearsal=rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))

        rows = _by_conflict_id(conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict.pk}))

        self.assertEqual(rows[conflict.pk].verdict, FEASIBLE)
        self.assertTrue(rows[conflict.pk].checked)


class SwapResolvesAConflictTests(TestCase):
    def test_a_partial_conflict_a_swap_resolves_is_feasible(self):
        """One person only free for the second slot: swapping their Song into it resolves the Conflict -- feasible."""
        semester = SemesterFactory(default_song_slot_count=2)
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(19, 0))
        song_a = SongFactory(semester=semester)
        song_b = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=rehearsal, song=song_a, order=1, slot_count=1)
        RehearsalSongFactory(rehearsal=rehearsal, song=song_b, order=2, slot_count=1)
        person = PersonFactory()
        SongRoleAssignmentFactory(song=song_a, person=person)
        conflict = ConflictFactory(person=person, rehearsal=rehearsal, type=Conflict.PARTIAL)
        # Two 30-minute slots: 18:00-18:30 and 18:30-19:00. Unavailable for the first slot only --
        # moving song_a (currently first) into the second slot resolves it.
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))

        rows = _by_conflict_id(conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict.pk}))

        self.assertEqual(rows[conflict.pk].verdict, FEASIBLE)

    def test_a_partial_conflict_no_ordering_resolves_is_infeasible(self):
        """A person assigned to every Song in the Rehearsal can't be moved out of their Window by any ordering."""
        semester = SemesterFactory(default_song_slot_count=2)
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(19, 0))
        song_a = SongFactory(semester=semester)
        song_b = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=rehearsal, song=song_a, order=1, slot_count=1)
        RehearsalSongFactory(rehearsal=rehearsal, song=song_b, order=2, slot_count=1)
        person = PersonFactory()
        SongRoleAssignmentFactory(song=song_a, person=person)
        SongRoleAssignmentFactory(song=song_b, person=person)
        conflict = ConflictFactory(person=person, rehearsal=rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))

        rows = _by_conflict_id(conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict.pk}))

        self.assertEqual(rows[conflict.pk].verdict, INFEASIBLE)


class JointFeasibilityTests(TestCase):
    def _build_two_conflicting_people(self, status_one=Conflict.PENDING, status_two=Conflict.PENDING):
        """Build a Rehearsal where each of two people, alone, can be scheduled around, but not together.

        Both hold the same Window (the first of two 30-minute slots), each
        assigned to a different Song -- satisfying one (by putting their
        Song second) always puts the other's Song first, in the Window.
        """
        semester = SemesterFactory(default_song_slot_count=2)
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(19, 0))
        song_a = SongFactory(semester=semester)
        song_b = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=rehearsal, song=song_a, order=1, slot_count=1)
        RehearsalSongFactory(rehearsal=rehearsal, song=song_b, order=2, slot_count=1)
        person_one = PersonFactory()
        person_two = PersonFactory()
        SongRoleAssignmentFactory(song=song_a, person=person_one)
        SongRoleAssignmentFactory(song=song_b, person=person_two)
        conflict_one = ConflictFactory(person=person_one, rehearsal=rehearsal, type=Conflict.PARTIAL, status=status_one)
        ConflictWindowFactory(conflict=conflict_one, unavailable_start=time(18, 0), unavailable_end=time(18, 30))
        conflict_two = ConflictFactory(person=person_two, rehearsal=rehearsal, type=Conflict.PARTIAL, status=status_two)
        ConflictWindowFactory(conflict=conflict_two, unavailable_start=time(18, 0), unavailable_end=time(18, 30))
        return rehearsal, conflict_one, conflict_two

    def test_two_individually_feasible_conflicts_can_be_jointly_infeasible(self):
        """The case the joint design exists for: each Conflict alone is solvable, but not together."""
        rehearsal, conflict_one, conflict_two = self._build_two_conflicting_people()

        alone_one = _by_conflict_id(conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict_one.pk}))
        alone_two = _by_conflict_id(conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict_two.pk}))
        joint = _by_conflict_id(
            conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict_one.pk, conflict_two.pk}),
        )

        self.assertEqual(alone_one[conflict_one.pk].verdict, FEASIBLE)
        self.assertEqual(alone_two[conflict_two.pk].verdict, FEASIBLE)
        self.assertEqual(joint[conflict_one.pk].verdict, INFEASIBLE)
        self.assertEqual(joint[conflict_two.pk].verdict, INFEASIBLE)

    def test_only_approved_conflicts_join_the_set(self):
        """A rejected Conflict constrains nothing: excluded from approved_conflict_ids, it doesn't break the other row."""
        rehearsal, _rejected_conflict, conflict_two = self._build_two_conflicting_people(status_one=Conflict.REJECTED)

        rows = _by_conflict_id(conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict_two.pk}))

        self.assertEqual(rows[conflict_two.pk].verdict, FEASIBLE)


class FullConflictInTheApprovedSetTests(TestCase):
    def test_a_full_conflict_in_the_approved_set_adds_no_constraint_to_another_rows_search(self):
        """A full Conflict named in approved_conflict_ids is ignored by the search, not a KeyError."""
        semester = SemesterFactory(default_song_slot_count=2)
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(19, 0))
        song_a = SongFactory(semester=semester)
        song_b = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=rehearsal, song=song_a, order=1, slot_count=1)
        RehearsalSongFactory(rehearsal=rehearsal, song=song_b, order=2, slot_count=1)
        person = PersonFactory()
        SongRoleAssignmentFactory(song=song_a, person=person)
        partial_conflict = ConflictFactory(person=person, rehearsal=rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=partial_conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))
        full_conflict = ConflictFactory(rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)

        rows = _by_conflict_id(
            conflict_feasibility_for(rehearsal, approved_conflict_ids={partial_conflict.pk, full_conflict.pk}),
        )

        self.assertEqual(rows[partial_conflict.pk].verdict, FEASIBLE)
        self.assertEqual(rows[full_conflict.pk].verdict, NOT_APPLICABLE)


class HeterogeneousSlotCountTests(TestCase):
    def test_gets_the_right_answer_with_mixed_slot_counts(self):
        """A Rehearsal with different slot_count rows per song is handled correctly -- fixed-column matching would not be."""
        semester = SemesterFactory(default_song_slot_count=4)
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(20, 0))
        long_song = SongFactory(semester=semester)
        short_song = SongFactory(semester=semester)
        other_song = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=rehearsal, song=long_song, order=1, slot_count=2)
        RehearsalSongFactory(rehearsal=rehearsal, song=short_song, order=2, slot_count=1)
        RehearsalSongFactory(rehearsal=rehearsal, song=other_song, order=3, slot_count=1)
        person = PersonFactory()
        SongRoleAssignmentFactory(song=short_song, person=person)
        conflict = ConflictFactory(person=person, rehearsal=rehearsal, type=Conflict.PARTIAL)
        # Four 30-minute slots: 18:00-20:00. short_song lands at 19:00-19:30 only when long_song
        # (2 slots) precedes it -- an ordering with short_song earlier avoids this Window entirely.
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(19, 0), unavailable_end=time(19, 30))

        rows = _by_conflict_id(conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict.pk}))

        self.assertEqual(rows[conflict.pk].verdict, FEASIBLE)


class RowCountCeilingTests(TestCase):
    def test_beyond_the_ceiling_the_row_is_not_checked(self):
        """A Rehearsal with more RehearsalSong rows than the ceiling reports its partial Conflicts as not checked."""
        row_count = FEASIBILITY_ROW_CEILING + 1
        semester = SemesterFactory(default_song_slot_count=row_count)
        rehearsal = RehearsalFactory(
            semester=semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(22, 0),
        )
        songs = [SongFactory(semester=semester) for _ in range(row_count)]
        for index, song in enumerate(songs, start=1):
            RehearsalSongFactory(rehearsal=rehearsal, song=song, order=index, slot_count=1)
        person = PersonFactory()
        SongRoleAssignmentFactory(song=songs[0], person=person)
        conflict = ConflictFactory(person=person, rehearsal=rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))

        rows = _by_conflict_id(conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict.pk}))

        self.assertFalse(rows[conflict.pk].checked)
        self.assertIsNone(rows[conflict.pk].verdict)

    def test_a_conflict_with_no_assigned_songs_stays_feasible_even_beyond_the_ceiling(self):
        """No search is needed for an empty assignment set, so the ceiling never turns it into 'not checked'."""
        row_count = FEASIBILITY_ROW_CEILING + 1
        semester = SemesterFactory(default_song_slot_count=row_count)
        rehearsal = RehearsalFactory(
            semester=semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(22, 0),
        )
        songs = [SongFactory(semester=semester) for _ in range(row_count)]
        for index, song in enumerate(songs, start=1):
            RehearsalSongFactory(rehearsal=rehearsal, song=song, order=index, slot_count=1)
        conflict = ConflictFactory(rehearsal=rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))

        rows = _by_conflict_id(conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict.pk}))

        self.assertTrue(rows[conflict.pk].checked)
        self.assertEqual(rows[conflict.pk].verdict, FEASIBLE)


class StandingOverlapAdvisoryTests(TestCase):
    def test_fires_for_an_approved_person_still_assigned_into_their_window(self):
        """An approved partial Conflict whose person is still assigned into their saved Window gets the advisory."""
        semester = SemesterFactory(default_song_slot_count=1)
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(18, 30))
        song = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1, slot_count=1)
        person = PersonFactory()
        SongRoleAssignmentFactory(song=song, person=person)
        conflict = ConflictFactory(person=person, rehearsal=rehearsal, type=Conflict.PARTIAL, status=Conflict.APPROVED)
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))

        rows = _by_conflict_id(conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict.pk}))

        self.assertTrue(rows[conflict.pk].has_standing_overlap)

    def test_silent_once_a_backup_covers_that_role_on_that_song(self):
        """The advisory falls silent once a Backup covers the assigned Role on that Song at that Rehearsal."""
        semester = SemesterFactory(default_song_slot_count=1)
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(18, 30))
        song = SongFactory(semester=semester)
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1, slot_count=1)
        role = RoleFactory()
        person = PersonFactory()
        SongRoleAssignmentFactory(song=song, person=person, role=role)
        conflict = ConflictFactory(person=person, rehearsal=rehearsal, type=Conflict.PARTIAL, status=Conflict.APPROVED)
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))
        BackupFactory(rehearsal_song=rehearsal_song, role=role, person=PersonFactory())

        rows = _by_conflict_id(conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict.pk}))

        self.assertFalse(rows[conflict.pk].has_standing_overlap)

    def test_advisory_never_fires_for_a_non_approved_row(self):
        """A pending Conflict's own row never carries the advisory, even with a real standing overlap."""
        semester = SemesterFactory(default_song_slot_count=1)
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(18, 30))
        song = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1, slot_count=1)
        person = PersonFactory()
        SongRoleAssignmentFactory(song=song, person=person)
        conflict = ConflictFactory(person=person, rehearsal=rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))

        rows = _by_conflict_id(conflict_feasibility_for(rehearsal, approved_conflict_ids=set()))

        self.assertFalse(rows[conflict.pk].has_standing_overlap)

    def test_advisory_computed_against_saved_order_not_a_candidate_one(self):
        """The advisory reads the saved RehearsalSong times, not a hypothetical reordering the search might find."""
        semester = SemesterFactory(default_song_slot_count=2)
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(19, 0))
        song_a = SongFactory(semester=semester)
        song_b = SongFactory(semester=semester)
        # Saved order puts song_a (the person's song) in the unavailable first slot, even though swapping
        # would resolve it -- the advisory must still fire, since it never proposes the swap.
        RehearsalSongFactory(rehearsal=rehearsal, song=song_a, order=1, slot_count=1)
        RehearsalSongFactory(rehearsal=rehearsal, song=song_b, order=2, slot_count=1)
        person = PersonFactory()
        SongRoleAssignmentFactory(song=song_a, person=person)
        conflict = ConflictFactory(person=person, rehearsal=rehearsal, type=Conflict.PARTIAL, status=Conflict.APPROVED)
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))

        rows = _by_conflict_id(conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict.pk}))

        self.assertEqual(rows[conflict.pk].verdict, FEASIBLE)
        self.assertTrue(rows[conflict.pk].has_standing_overlap)


class OneImplementationSharedByBothAnswersTests(TestCase):
    def test_verdict_and_advisory_agree_on_what_overlap_means(self):
        """A Window that touches a slot's boundary without overlapping it is not flagged by either answer."""
        semester = SemesterFactory(default_song_slot_count=2)
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(19, 0))
        song_a = SongFactory(semester=semester)
        song_b = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=rehearsal, song=song_a, order=1, slot_count=1)
        RehearsalSongFactory(rehearsal=rehearsal, song=song_b, order=2, slot_count=1)
        person = PersonFactory()
        # song_b's slot is 18:30-19:00; a Window ending exactly at 18:30 (song_b's start) doesn't overlap it.
        SongRoleAssignmentFactory(song=song_b, person=person)
        conflict = ConflictFactory(person=person, rehearsal=rehearsal, type=Conflict.PARTIAL, status=Conflict.APPROVED)
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))

        rows = _by_conflict_id(conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict.pk}))

        self.assertEqual(rows[conflict.pk].verdict, FEASIBLE)
        self.assertFalse(rows[conflict.pk].has_standing_overlap)
