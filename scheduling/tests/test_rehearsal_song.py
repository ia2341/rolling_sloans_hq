"""RehearsalSong: timed song slots on a Rehearsal, and the Dress Rehearsal's live derivation (issue #37)."""

from datetime import time

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from scheduling.factories import (
    RehearsalFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.models import RehearsalSong


class RehearsalSongOrderUniquenessTests(TestCase):
    def test_duplicate_order_on_same_rehearsal_is_rejected(self):
        """A second RehearsalSong with the same (rehearsal, order) pair raises IntegrityError."""
        rehearsal = RehearsalFactory()
        RehearsalSongFactory(rehearsal=rehearsal, order=1)

        with self.assertRaises(IntegrityError), transaction.atomic():
            RehearsalSongFactory(rehearsal=rehearsal, order=1)

    def test_same_order_on_different_rehearsals_is_allowed(self):
        """The same order value is fine across two different Rehearsals."""
        first = RehearsalFactory()
        second = RehearsalFactory()

        RehearsalSongFactory(rehearsal=first, order=1)
        RehearsalSongFactory(rehearsal=second, order=1)

        self.assertEqual(RehearsalSong.objects.count(), 2)


class RehearsalSongComputedTimesTests(TestCase):
    def test_first_song_starts_at_rehearsal_start_time(self):
        """The first RehearsalSong (order=1) starts exactly at the Rehearsal's start_time."""
        semester = SemesterFactory(default_rehearsal_duration_minutes=90, default_song_slot_count=5)
        rehearsal = RehearsalFactory(semester=semester, start_time=time(18, 0))

        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, order=1, slot_count=1)

        self.assertEqual(rehearsal_song.start_time, time(18, 0))
        self.assertEqual(rehearsal_song.end_time, time(18, 18))

    def test_later_song_starts_after_prior_slot_counts(self):
        """A second RehearsalSong starts after the first's slot_count worth of slot-minutes."""
        semester = SemesterFactory(default_rehearsal_duration_minutes=90, default_song_slot_count=5)
        rehearsal = RehearsalFactory(semester=semester, start_time=time(18, 0))
        RehearsalSongFactory(rehearsal=rehearsal, order=1, slot_count=2)

        second = RehearsalSongFactory(rehearsal=rehearsal, order=2, slot_count=1)

        self.assertEqual(second.start_time, time(18, 36))
        self.assertEqual(second.end_time, time(18, 54))

    def test_slot_count_greater_than_one_does_not_overrun_the_rehearsal_window(self):
        """A slot_count > 1 row's computed end_time stays within the Rehearsal's fixed start/end window."""
        semester = SemesterFactory(default_rehearsal_duration_minutes=90, default_song_slot_count=5)
        rehearsal = RehearsalFactory(semester=semester, start_time=time(18, 0))

        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, order=1, slot_count=3)

        self.assertEqual(rehearsal_song.start_time, rehearsal.start_time)
        self.assertLessEqual(rehearsal_song.end_time, rehearsal.end_time)
        self.assertEqual(rehearsal_song.end_time, time(18, 54))

    def test_editing_slot_count_recomputes_end_time(self):
        """Changing slot_count and re-saving recomputes end_time, not just at creation."""
        semester = SemesterFactory(default_rehearsal_duration_minutes=90, default_song_slot_count=5)
        rehearsal = RehearsalFactory(semester=semester, start_time=time(18, 0))
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, order=1, slot_count=1)

        rehearsal_song.slot_count = 2
        rehearsal_song.save()

        reloaded = RehearsalSong.objects.get(pk=rehearsal_song.pk)
        self.assertEqual(reloaded.end_time, time(18, 36))


class RehearsalSongDressRehearsalRejectionTests(TestCase):
    def test_cannot_be_saved_against_a_dress_rehearsal(self):
        """Attempting to save a RehearsalSong against a Dress Rehearsal raises instead of persisting."""
        dress_rehearsal = RehearsalFactory(is_full_setlist=True)

        with self.assertRaises(ValueError):
            RehearsalSongFactory(rehearsal=dress_rehearsal, order=1)

    def test_clean_reports_it_as_a_validation_error(self):
        """clean() surfaces the same rejection as a normal ValidationError, for admin-form use."""
        dress_rehearsal = RehearsalFactory(is_full_setlist=True)
        song = SongFactory(semester=dress_rehearsal.semester)
        rehearsal_song = RehearsalSong(rehearsal=dress_rehearsal, song=song, order=1, slot_count=1)

        with self.assertRaises(ValidationError):
            rehearsal_song.clean()


class DressRehearsalLiveDerivationTests(TestCase):
    def test_returns_setlist_in_position_order_with_no_persisted_rows(self):
        """A Dress Rehearsal's derived songs are the Semester's setlist in position order, with zero RehearsalSong rows."""
        semester = SemesterFactory()
        third = SongFactory(semester=semester, position=3)
        first = SongFactory(semester=semester, position=1)
        second = SongFactory(semester=semester, position=2)
        dress_rehearsal = RehearsalFactory(semester=semester, is_full_setlist=True)

        songs = list(dress_rehearsal.dress_rehearsal_songs)

        self.assertEqual(songs, [first, second, third])
        self.assertEqual(RehearsalSong.objects.filter(rehearsal=dress_rehearsal).count(), 0)

    def test_setlist_change_after_scheduling_changes_the_query_with_no_write_to_rehearsal(self):
        """Adding/reordering a Song in the setlist changes what's returned, with no write to the Rehearsal itself."""
        semester = SemesterFactory()
        only_song = SongFactory(semester=semester, position=1)
        dress_rehearsal = RehearsalFactory(semester=semester, is_full_setlist=True)
        original_updated_fields = (dress_rehearsal.date, dress_rehearsal.start_time, dress_rehearsal.end_time)

        self.assertEqual(list(dress_rehearsal.dress_rehearsal_songs), [only_song])

        new_song = SongFactory(semester=semester, position=0)

        reloaded = dress_rehearsal.__class__.objects.get(pk=dress_rehearsal.pk)
        self.assertEqual(list(reloaded.dress_rehearsal_songs), [new_song, only_song])
        self.assertEqual(
            (reloaded.date, reloaded.start_time, reloaded.end_time),
            original_updated_fields,
        )


class RehearsalSongFieldTests(TestCase):
    def test_created_with_all_fields(self):
        """A RehearsalSong is created with its rehearsal, song, order, and slot_count."""
        rehearsal = RehearsalFactory()
        song = SongFactory(semester=rehearsal.semester)

        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1, slot_count=2)

        reloaded = RehearsalSong.objects.get(pk=rehearsal_song.pk)
        self.assertEqual(reloaded.rehearsal, rehearsal)
        self.assertEqual(reloaded.song, song)
        self.assertEqual(reloaded.order, 1)
        self.assertEqual(reloaded.slot_count, 2)
        self.assertIsNotNone(reloaded.start_time)
        self.assertIsNotNone(reloaded.end_time)
