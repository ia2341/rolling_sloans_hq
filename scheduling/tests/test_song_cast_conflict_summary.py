"""song_cast_conflict_summary_for(): the per-Song, future-Rehearsal availability check ADR-0019 replaces ADR-0009's premise with (issue #499)."""

from datetime import time, timedelta

from django.test import TestCase
from django.utils import timezone

from scheduling.factories import (
    ConflictFactory,
    ConflictWindowFactory,
    MembershipFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import Conflict
from scheduling.services import (
    song_cast_conflict_summaries_for,
    song_cast_conflict_summary_for,
)


class SongCastConflictSummaryTests(TestCase):
    def setUp(self):
        """Build a Semester with one Song on one future Rehearsal's Running Order, and one rostered candidate."""
        self.semester = SemesterFactory()
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()
        SongRoleRequirementFactory(song=self.song, role=self.role, count=1)
        self.rehearsal = RehearsalFactory(
            semester=self.semester,
            is_full_setlist=False,
            start_time=time(18, 0),
            date=timezone.localdate() + timedelta(days=7),
        )
        self.rehearsal_song = RehearsalSongFactory(
            rehearsal=self.rehearsal, song=self.song, order=1, slot_count=1,
        )
        self.person = MembershipFactory(semester=self.semester).person

    def test_a_person_with_no_conflicts_gets_an_empty_summary(self):
        """The common case: nothing declared anywhere returns no entries at all."""
        self.assertEqual(song_cast_conflict_summary_for(self.song, self.person, self.semester), [])

    def test_a_full_conflict_produces_one_entry_for_that_rehearsal(self):
        """A full Conflict at a future Rehearsal of this Song is reported, flagged `is_full_conflict`."""
        ConflictFactory(person=self.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)

        entries = song_cast_conflict_summary_for(self.song, self.person, self.semester)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].rehearsal_id, self.rehearsal.pk)
        self.assertEqual(entries[0].date, self.rehearsal.date)
        self.assertTrue(entries[0].is_full_conflict)

    def test_an_entry_carries_the_conflicts_reason_for_its_admin_only_caller(self):
        """The reason is carried through — the picker that renders it is an AdminApiView (ADR-0005)."""
        ConflictFactory(
            person=self.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT,
            reason='a synthetic reason string',
        )

        entries = song_cast_conflict_summary_for(self.song, self.person, self.semester)

        self.assertEqual(entries[0].reason, 'a synthetic reason string')

    def test_a_conflict_window_overlapping_the_slot_is_reported(self):
        """A partial Conflict whose Window overlaps this Song's slot is reported, not flagged as a full Conflict."""
        conflict = ConflictFactory(person=self.person, rehearsal=self.rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(
            conflict=conflict,
            unavailable_start=self.rehearsal_song.start_time,
            unavailable_end=self.rehearsal_song.end_time,
        )

        entries = song_cast_conflict_summary_for(self.song, self.person, self.semester)

        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0].is_full_conflict)

    def test_a_conflict_window_outside_the_slot_is_not_reported(self):
        """A partial Conflict whose Window misses this Song's slot entirely raises nothing — the same overlap test the per-Rehearsal check uses."""
        conflict = ConflictFactory(person=self.person, rehearsal=self.rehearsal, type=Conflict.PARTIAL)
        assert self.rehearsal_song.end_time < self.rehearsal.end_time
        ConflictWindowFactory(
            conflict=conflict,
            unavailable_start=self.rehearsal_song.end_time,
            unavailable_end=self.rehearsal.end_time,
        )

        self.assertEqual(song_cast_conflict_summary_for(self.song, self.person, self.semester), [])

    def test_a_partial_conflict_with_no_windows_is_not_reported(self):
        """A partial Conflict carrying no Window at all overlaps nothing, so it raises no entry."""
        ConflictFactory(person=self.person, rehearsal=self.rehearsal, type=Conflict.PARTIAL)

        self.assertEqual(song_cast_conflict_summary_for(self.song, self.person, self.semester), [])

    def test_a_past_rehearsal_is_excluded(self):
        """Only future Rehearsals count — a past evening's availability can't inform a new cast decision."""
        past_rehearsal = RehearsalFactory(
            semester=self.semester, is_full_setlist=False, date=timezone.localdate() - timedelta(days=7),
        )
        RehearsalSongFactory(rehearsal=past_rehearsal, song=self.song, order=1, slot_count=1)
        ConflictFactory(person=self.person, rehearsal=past_rehearsal, type=Conflict.FULL_CONFLICT)

        self.assertEqual(song_cast_conflict_summary_for(self.song, self.person, self.semester), [])

    def test_a_conflict_at_a_rehearsal_this_song_is_not_on_is_excluded(self):
        """The summary is scoped to this Song's own slots, not to the person's whole calendar."""
        other_rehearsal = RehearsalFactory(
            semester=self.semester, is_full_setlist=False, date=timezone.localdate() + timedelta(days=14),
        )
        ConflictFactory(person=self.person, rehearsal=other_rehearsal, type=Conflict.FULL_CONFLICT)

        self.assertEqual(song_cast_conflict_summary_for(self.song, self.person, self.semester), [])

    def test_several_future_rehearsals_are_reported_in_date_order(self):
        """A Song rehearsed twice more yields one entry per conflicted evening, oldest first."""
        later = RehearsalFactory(
            semester=self.semester, is_full_setlist=False, date=timezone.localdate() + timedelta(days=21),
        )
        RehearsalSongFactory(rehearsal=later, song=self.song, order=1, slot_count=1)
        ConflictFactory(person=self.person, rehearsal=later, type=Conflict.FULL_CONFLICT)
        ConflictFactory(person=self.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)

        entries = song_cast_conflict_summary_for(self.song, self.person, self.semester)

        self.assertEqual([entry.date for entry in entries], [self.rehearsal.date, later.date])

    def test_another_persons_conflict_is_never_reported(self):
        """The summary answers about one candidate only."""
        someone_else = MembershipFactory(semester=self.semester).person
        ConflictFactory(person=someone_else, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)

        self.assertEqual(song_cast_conflict_summary_for(self.song, self.person, self.semester), [])

    def test_a_song_with_no_future_rehearsal_slots_returns_empty(self):
        """A Song not on any future Running Order has nothing to check against."""
        other_song = SongFactory(semester=self.semester, position=2)
        ConflictFactory(person=self.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)

        self.assertEqual(song_cast_conflict_summary_for(other_song, self.person, self.semester), [])


class SongCastConflictSummariesForTests(TestCase):
    """The batched sibling the cast picker calls, so N candidates cost a fixed number of queries (PR #502 review)."""

    def setUp(self):
        """Build a Semester with one Song on one future Rehearsal's Running Order, and three rostered candidates."""
        self.semester = SemesterFactory()
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()
        SongRoleRequirementFactory(song=self.song, role=self.role, count=1)
        self.rehearsal = RehearsalFactory(
            semester=self.semester,
            is_full_setlist=False,
            start_time=time(18, 0),
            date=timezone.localdate() + timedelta(days=7),
        )
        RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song, order=1, slot_count=1)
        self.people = [MembershipFactory(semester=self.semester).person for _ in range(3)]

    def test_every_person_asked_about_gets_a_key(self):
        """A candidate with nothing declared maps to `[]`, so a caller never distinguishes "none" from "not asked"."""
        summaries = song_cast_conflict_summaries_for(self.song, self.people, self.semester)

        self.assertEqual(set(summaries), {person.pk for person in self.people})
        self.assertEqual(list(summaries.values()), [[], [], []])

    def test_each_persons_entries_match_the_single_person_answer(self):
        """The batch and the one-person wrapper can't disagree — the wrapper delegates to this function."""
        ConflictFactory(person=self.people[0], rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)

        summaries = song_cast_conflict_summaries_for(self.song, self.people, self.semester)

        for person in self.people:
            self.assertEqual(
                summaries[person.pk], song_cast_conflict_summary_for(self.song, person, self.semester),
            )

    def test_query_count_does_not_grow_with_the_candidate_count(self):
        """Three candidates cost the same queries as one — the point of batching (PR #502 review)."""
        for person in self.people:
            ConflictFactory(person=person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)

        with self.assertNumQueries(3):
            song_cast_conflict_summaries_for(self.song, self.people, self.semester)
        with self.assertNumQueries(3):
            song_cast_conflict_summaries_for(self.song, self.people[:1], self.semester)
