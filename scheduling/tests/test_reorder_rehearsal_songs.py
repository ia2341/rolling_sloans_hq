"""reorder_rehearsal_songs(): the Running Order renumber-and-re-derive seam (issue #215)."""

from datetime import time

from django.test import TestCase

from scheduling.factories import RehearsalFactory, RehearsalSongFactory, SemesterFactory
from scheduling.models import RehearsalSong
from scheduling.services import reorder_rehearsal_songs


class ReorderRehearsalSongsServiceTests(TestCase):
    def test_renumbers_survivors_to_a_contiguous_sequence_in_the_given_order(self):
        """reorder_rehearsal_songs() assigns 1..N following the given id order, regardless of prior order values."""
        rehearsal = RehearsalFactory()
        first = RehearsalSongFactory(rehearsal=rehearsal, order=1)
        second = RehearsalSongFactory(rehearsal=rehearsal, order=2)
        third = RehearsalSongFactory(rehearsal=rehearsal, order=3)

        reorder_rehearsal_songs(rehearsal, [third.pk, first.pk, second.pk])

        third.refresh_from_db()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(third.order, 1)
        self.assertEqual(first.order, 2)
        self.assertEqual(second.order, 3)

    def test_handles_a_deletion_in_the_middle_leaving_a_contiguous_sequence(self):
        """A shorter ordered id list (a mid-list deletion) still yields 1..N with no gap."""
        rehearsal = RehearsalFactory()
        first = RehearsalSongFactory(rehearsal=rehearsal, order=1)
        middle = RehearsalSongFactory(rehearsal=rehearsal, order=2)
        third = RehearsalSongFactory(rehearsal=rehearsal, order=3)
        middle.delete()

        reorder_rehearsal_songs(rehearsal, [first.pk, third.pk])

        first.refresh_from_db()
        third.refresh_from_db()
        self.assertEqual(first.order, 1)
        self.assertEqual(third.order, 2)

    def test_reordering_re_derives_times_for_the_new_sequence(self):
        """Swapping two rows' order re-derives both rows' persisted start_time/end_time for their new slots."""
        semester = SemesterFactory(default_rehearsal_duration_minutes=90, default_song_slot_count=5)
        rehearsal = RehearsalFactory(semester=semester, start_time=time(18, 0))
        first = RehearsalSongFactory(rehearsal=rehearsal, order=1, slot_count=2)
        second = RehearsalSongFactory(rehearsal=rehearsal, order=2, slot_count=1)

        reorder_rehearsal_songs(rehearsal, [second.pk, first.pk])

        second.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(second.order, 1)
        self.assertEqual(second.start_time, time(18, 15))
        self.assertEqual(second.end_time, time(18, 27))
        self.assertEqual(first.order, 2)
        self.assertEqual(first.start_time, time(18, 27))
        self.assertEqual(first.end_time, time(18, 51))

    def test_an_identity_reorder_re_derives_times_without_touching_order(self):
        """Passing the current order back re-derives times (e.g. after a Rehearsal window move) but leaves order put."""
        semester = SemesterFactory(default_rehearsal_duration_minutes=90, default_song_slot_count=5)
        rehearsal = RehearsalFactory(semester=semester, start_time=time(18, 0))
        first = RehearsalSongFactory(rehearsal=rehearsal, order=1, slot_count=1)
        second = RehearsalSongFactory(rehearsal=rehearsal, order=2, slot_count=1)

        rehearsal.start_time = time(19, 0)
        rehearsal.end_time = time(20, 30)
        rehearsal.save()
        reorder_rehearsal_songs(rehearsal, [first.pk, second.pk])

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.order, 1)
        self.assertEqual(second.order, 2)
        self.assertEqual(first.start_time, time(19, 15))
        self.assertEqual(second.start_time, time(19, 27))

    def test_a_full_reversal_does_not_collide_with_the_rehearsal_order_uniqueness_constraint(self):
        """Reversing every row (the case most likely to collide mid-run) succeeds without an IntegrityError."""
        rehearsal = RehearsalFactory()
        songs = [RehearsalSongFactory(rehearsal=rehearsal, order=n) for n in range(1, 5)]

        reorder_rehearsal_songs(rehearsal, [song.pk for song in reversed(songs)])

        orders = list(
            RehearsalSong.objects.filter(rehearsal=rehearsal).order_by('order').values_list('pk', flat=True)
        )
        self.assertEqual(orders, [song.pk for song in reversed(songs)])
