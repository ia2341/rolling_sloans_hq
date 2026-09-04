"""deal_running_orders() and shuffle_rehearsal_running_order(): the balanced dealer (issue #223)."""

from collections import Counter
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from scheduling.factories import (
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.models import RehearsalSong
from scheduling.services import (
    EmptySetlistError,
    NoEligibleRehearsalsError,
    deal_running_orders,
    shuffle_rehearsal_running_order,
)


def _future_rehearsal(semester, **kwargs):
    """Build a Rehearsal dated safely in the future for `semester` (non-Dress unless is_full_setlist is passed)."""
    kwargs.setdefault('date', timezone.localdate() + timedelta(days=kwargs.pop('days_out', 7)))
    kwargs.setdefault('is_full_setlist', False)
    return RehearsalFactory(semester=semester, **kwargs)


class DealRunningOrdersTests(TestCase):
    def test_refuses_an_empty_setlist(self):
        """An empty setlist is refused, naming the reason, rather than silently doing nothing."""
        semester = SemesterFactory()
        _future_rehearsal(semester, days_out=1)

        with self.assertRaises(EmptySetlistError):
            deal_running_orders(semester)

    def test_refuses_no_eligible_rehearsals(self):
        """No eligible Rehearsal is refused, naming the reason."""
        semester = SemesterFactory()
        SongFactory(semester=semester)

        with self.assertRaises(NoEligibleRehearsalsError):
            deal_running_orders(semester)

    def test_ignores_a_dress_rehearsal_and_a_past_rehearsal(self):
        """A Dress Rehearsal and a past-dated Rehearsal are never eligible, so they never appear in the deal."""
        semester = SemesterFactory()
        SongFactory(semester=semester)
        dress = _future_rehearsal(semester, days_out=2, is_full_setlist=True)
        past = RehearsalFactory(semester=semester, date=timezone.localdate() - timedelta(days=1))
        future = _future_rehearsal(semester, days_out=3)

        deal = deal_running_orders(semester)

        dealt_ids = {dealt.rehearsal_id for dealt in deal.rehearsals}
        self.assertNotIn(dress.pk, dealt_ids)
        self.assertNotIn(past.pk, dealt_ids)
        self.assertIn(future.pk, dealt_ids)

    def test_writes_nothing(self):
        """A deal creates no RehearsalSong row and touches no existing one."""
        semester = SemesterFactory()
        for _ in range(3):
            SongFactory(semester=semester)
        for day in range(3):
            _future_rehearsal(semester, days_out=day + 1)

        deal_running_orders(semester)

        self.assertEqual(RehearsalSong.objects.count(), 0)

    def test_every_dealt_row_has_slot_count_one(self):
        """Every freshly dealt row (no rehearsal_song_id) carries slot_count=1."""
        semester = SemesterFactory()
        for _ in range(4):
            SongFactory(semester=semester)
        for day in range(2):
            _future_rehearsal(semester, days_out=day + 1)

        deal = deal_running_orders(semester)

        for dealt_rehearsal in deal.rehearsals:
            for row in dealt_rehearsal.rows:
                if row.rehearsal_song_id is None:
                    self.assertEqual(row.slot_count, 1)

    def test_rehearsal_receives_min_of_slot_count_and_setlist_size(self):
        """A Rehearsal's dealt row count is min(default_song_slot_count, setlist size)."""
        semester = SemesterFactory(default_song_slot_count=5)
        for _ in range(3):
            SongFactory(semester=semester)
        rehearsal = _future_rehearsal(semester, days_out=1)

        deal = deal_running_orders(semester)

        dealt = next(d for d in deal.rehearsals if d.rehearsal_id == rehearsal.pk)
        self.assertEqual(len(dealt.rows), 3)

    def test_no_song_dealt_twice_into_one_rehearsal(self):
        """No Rehearsal's dealt rows repeat a Song."""
        semester = SemesterFactory(default_song_slot_count=6)
        songs = [SongFactory(semester=semester) for _ in range(6)]
        for day in range(4):
            _future_rehearsal(semester, days_out=day + 1)

        deal = deal_running_orders(semester)

        for dealt_rehearsal in deal.rehearsals:
            song_ids = [row.song_id for row in dealt_rehearsal.rows]
            self.assertEqual(len(song_ids), len(set(song_ids)))
        self.assertTrue(all(song.pk for song in songs))

    def test_short_setlist_leaves_trailing_slots_empty_rather_than_repeating(self):
        """A setlist smaller than the slot budget deals fewer rows rather than repeating a Song."""
        semester = SemesterFactory(default_song_slot_count=5)
        SongFactory(semester=semester)
        SongFactory(semester=semester)
        rehearsal = _future_rehearsal(semester, days_out=1)

        deal = deal_running_orders(semester)

        dealt = next(d for d in deal.rehearsals if d.rehearsal_id == rehearsal.pk)
        self.assertEqual(len(dealt.rows), 2)

    def test_appearance_counts_are_balanced_within_one(self):
        """Across the whole term, no Song's total appearance count differs from another's by more than one."""
        semester = SemesterFactory(default_song_slot_count=2)
        songs = [SongFactory(semester=semester) for _ in range(5)]
        for day in range(7):
            _future_rehearsal(semester, days_out=day + 1)

        deal = deal_running_orders(semester)

        counts = Counter()
        for dealt_rehearsal in deal.rehearsals:
            for row in dealt_rehearsal.rows:
                counts[row.song_id] += 1
        for song in songs:
            counts.setdefault(song.pk, 0)
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)

    def test_randomizes_which_songs_land_where_over_repeated_runs(self):
        """Repeated deals of the same setlist/Rehearsals produce more than one distinct arrangement."""
        semester = SemesterFactory(default_song_slot_count=3)
        for _ in range(5):
            SongFactory(semester=semester)
        rehearsal = _future_rehearsal(semester, days_out=1)

        arrangements = set()
        for _ in range(20):
            deal = deal_running_orders(semester)
            dealt = next(d for d in deal.rehearsals if d.rehearsal_id == rehearsal.pk)
            arrangements.add(tuple(row.song_id for row in dealt.rows))

        self.assertGreater(len(arrangements), 1)

    def test_recording_bearing_row_is_pinned_at_its_exact_order_and_slot_count(self):
        """A RehearsalSong with a Recording keeps its identity, order and slot_count in every dealt run."""
        semester = SemesterFactory(default_song_slot_count=4)
        for _ in range(5):
            SongFactory(semester=semester)
        rehearsal = _future_rehearsal(semester, days_out=1)
        pinned = RehearsalSongFactory(rehearsal=rehearsal, order=2, slot_count=2)
        RecordingFactory(rehearsal_song=pinned)

        for _ in range(10):
            deal = deal_running_orders(semester)
            dealt = next(d for d in deal.rehearsals if d.rehearsal_id == rehearsal.pk)
            pinned_index = next(i for i, row in enumerate(dealt.rows) if row.rehearsal_song_id == pinned.pk)
            pinned_row = dealt.rows[pinned_index]
            self.assertEqual(pinned_index, 1)  # order=2 is 1-indexed -> DOM index 1
            self.assertEqual(pinned_row.song_id, pinned.song_id)
            self.assertEqual(pinned_row.slot_count, 2)
            other_song_ids = [row.song_id for i, row in enumerate(dealt.rows) if i != pinned_index]
            self.assertNotIn(pinned.song_id, other_song_ids)

    def test_pinned_row_counts_toward_its_songs_balance(self):
        """A pinned Song's existing appearance counts toward the term-wide ±1 balance, not on top of it."""
        semester = SemesterFactory(default_song_slot_count=1)
        pinned_song = SongFactory(semester=semester)
        other_song = SongFactory(semester=semester)
        pinned_rehearsal = _future_rehearsal(semester, days_out=1)
        pinned = RehearsalSongFactory(rehearsal=pinned_rehearsal, song=pinned_song, order=1, slot_count=1)
        RecordingFactory(rehearsal_song=pinned)
        for day in range(2, 5):
            _future_rehearsal(semester, days_out=day)

        deal = deal_running_orders(semester)

        counts = Counter({pinned_song.pk: 1, other_song.pk: 0})
        for dealt_rehearsal in deal.rehearsals:
            for row in dealt_rehearsal.rows:
                if row.rehearsal_song_id is None:
                    counts[row.song_id] += 1
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)

    def test_hand_raised_slot_count_is_pinned_even_without_a_recording(self):
        """A row with no Recording but a hand-raised slot_count is left untouched, exactly like a pinned Recording row."""
        semester = SemesterFactory(default_song_slot_count=4)
        songs = [SongFactory(semester=semester) for _ in range(5)]
        rehearsal = _future_rehearsal(semester, days_out=1)
        raised = RehearsalSongFactory(rehearsal=rehearsal, song=songs[0], order=3, slot_count=2)

        for _ in range(10):
            deal = deal_running_orders(semester)
            dealt = next(d for d in deal.rehearsals if d.rehearsal_id == rehearsal.pk)
            pinned_index = next(i for i, row in enumerate(dealt.rows) if row.rehearsal_song_id == raised.pk)
            pinned_row = dealt.rows[pinned_index]
            self.assertEqual(pinned_index, 2)  # order=3 is 1-indexed -> DOM index 2
            self.assertEqual(pinned_row.song_id, raised.song_id)
            self.assertEqual(pinned_row.slot_count, 2)


class ShuffleRehearsalRunningOrderTests(TestCase):
    def test_empty_rehearsal_returns_no_rows(self):
        """A Rehearsal with no Running Order rows returns an empty list -- a no-op, not a refusal."""
        rehearsal = RehearsalFactory()

        self.assertEqual(shuffle_rehearsal_running_order(rehearsal), [])

    def test_writes_nothing(self):
        """Shuffling touches no RehearsalSong row."""
        rehearsal = RehearsalFactory()
        for i in range(4):
            RehearsalSongFactory(rehearsal=rehearsal, order=i + 1)
        before = list(RehearsalSong.objects.filter(rehearsal=rehearsal).order_by('order').values('pk', 'order', 'song_id'))

        shuffle_rehearsal_running_order(rehearsal)

        after = list(RehearsalSong.objects.filter(rehearsal=rehearsal).order_by('order').values('pk', 'order', 'song_id'))
        self.assertEqual(before, after)

    def test_returns_the_same_songs_reordered(self):
        """The shuffled result is a permutation of the Rehearsal's own existing rows -- nothing added or removed."""
        rehearsal = RehearsalFactory()
        rehearsal_songs = [RehearsalSongFactory(rehearsal=rehearsal, order=i + 1) for i in range(5)]

        rows = shuffle_rehearsal_running_order(rehearsal)

        self.assertEqual({row.rehearsal_song_id for row in rows}, {rs.pk for rs in rehearsal_songs})
        self.assertEqual(len(rows), len(rehearsal_songs))

    def test_randomizes_order_over_repeated_runs(self):
        """Repeated shuffles of the same Rehearsal produce more than one distinct order."""
        rehearsal = RehearsalFactory()
        for i in range(5):
            RehearsalSongFactory(rehearsal=rehearsal, order=i + 1)

        arrangements = {tuple(row.rehearsal_song_id for row in shuffle_rehearsal_running_order(rehearsal)) for _ in range(20)}

        self.assertGreater(len(arrangements), 1)

    def test_recording_bearing_row_stays_at_its_own_order(self):
        """A Recording-bearing row never moves, across repeated shuffles."""
        rehearsal = RehearsalFactory()
        rehearsal_songs = [RehearsalSongFactory(rehearsal=rehearsal, order=i + 1) for i in range(5)]
        pinned = rehearsal_songs[2]
        RecordingFactory(rehearsal_song=pinned)

        for _ in range(10):
            rows = shuffle_rehearsal_running_order(rehearsal)
            pinned_index = next(i for i, row in enumerate(rows) if row.rehearsal_song_id == pinned.pk)
            self.assertEqual(pinned_index, 2)

    def test_hand_raised_slot_count_row_stays_at_its_own_order_without_a_recording(self):
        """A row with no Recording but a hand-raised slot_count never moves, across repeated shuffles."""
        semester = SemesterFactory(default_song_slot_count=6)
        rehearsal = RehearsalFactory(semester=semester)
        rehearsal_songs = [
            RehearsalSongFactory(rehearsal=rehearsal, song=SongFactory(semester=semester), order=i + 1)
            for i in range(5)
        ]
        raised = rehearsal_songs[3]
        raised.slot_count = 2
        raised.save()

        for _ in range(10):
            rows = shuffle_rehearsal_running_order(rehearsal)
            pinned_index = next(i for i, row in enumerate(rows) if row.rehearsal_song_id == raised.pk)
            self.assertEqual(pinned_index, 3)
