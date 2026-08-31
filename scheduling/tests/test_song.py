"""Song: setlist entries with a per-semester concert-order position (issue #32)."""

from datetime import timedelta

from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from scheduling.factories import SemesterFactory, SongFactory
from scheduling.models import Song


class SongPositionUniquenessTests(TestCase):
    def test_two_songs_in_same_semester_can_have_different_positions(self):
        """Two Songs in the same Semester with distinct positions save without error."""
        semester = SemesterFactory()

        SongFactory(semester=semester, position=1)
        SongFactory(semester=semester, position=2)

        self.assertEqual(Song.objects.filter(semester=semester).count(), 2)

    def test_duplicate_position_within_same_semester_is_rejected(self):
        """A second Song at the same position in the same Semester raises IntegrityError.

        The constraint is DEFERRED (see SongReorderingTests), so it isn't
        checked until commit; `connection.check_constraints()` forces that
        check immediately within the test's wrapping transaction.
        """
        semester = SemesterFactory()
        SongFactory(semester=semester, position=1)

        with self.assertRaises(IntegrityError), transaction.atomic():
            SongFactory(semester=semester, position=1)
            connection.check_constraints()

    def test_same_position_in_different_semesters_is_allowed(self):
        """The same position value is fine across two different Semesters."""
        first_semester = SemesterFactory()
        second_semester = SemesterFactory()

        SongFactory(semester=first_semester, position=1)
        SongFactory(semester=second_semester, position=1)

        self.assertEqual(Song.objects.filter(position=1).count(), 2)


class SongReorderingTests(TestCase):
    def test_directly_swapping_two_adjacent_positions_updates_rows_in_place(self):
        """Swapping two Songs' positions in one transaction works despite the unique constraint.

        The (semester, position) constraint is DEFERRED, so the transient
        collision from writing the new positions in either order is only
        checked — and passes — at commit, letting a real reorder UI swap two
        adjacent songs directly rather than needing a free position to stage
        through.
        """
        semester = SemesterFactory()
        first = SongFactory(semester=semester, position=1)
        second = SongFactory(semester=semester, position=2)
        first_pk, second_pk = first.pk, second.pk

        with transaction.atomic():
            first.position = 2
            first.save(update_fields=['position'])
            second.position = 1
            second.save(update_fields=['position'])

        reloaded_first = Song.objects.get(pk=first_pk)
        reloaded_second = Song.objects.get(pk=second_pk)
        self.assertEqual(reloaded_first.position, 2)
        self.assertEqual(reloaded_second.position, 1)
        self.assertEqual(Song.objects.filter(semester=semester).count(), 2)


class SongCrossSemesterTests(TestCase):
    def test_same_title_in_two_semesters_is_two_distinct_rows(self):
        """A song replayed in a later semester is a brand-new row, not a shared reference (ADR-0001)."""
        first_semester = SemesterFactory()
        second_semester = SemesterFactory()

        first_song = SongFactory(semester=first_semester, title='Song A', position=1)
        second_song = SongFactory(semester=second_semester, title='Song A', position=1)

        self.assertNotEqual(first_song.pk, second_song.pk)
        self.assertEqual(Song.objects.filter(title='Song A').count(), 2)

        # No relational field on Song points back to another Song at all —
        # not just that one hypothetical field name is absent.
        self_referential_fields = [
            field for field in Song._meta.get_fields()
            if field.is_relation and field.related_model is Song
        ]
        self.assertEqual(self_referential_fields, [])


class SongFieldTests(TestCase):
    def test_created_with_all_fields(self):
        """A Song is created with title, artist, length, notes, position, and its Semester."""
        semester = SemesterFactory()

        song = SongFactory(
            semester=semester,
            title='Song A',
            artist='Artist A',
            length=timedelta(minutes=4, seconds=15),
            notes='Bridge needs a key change',
            position=1,
        )

        reloaded = Song.objects.get(pk=song.pk)
        self.assertEqual(reloaded.semester, semester)
        self.assertEqual(reloaded.title, 'Song A')
        self.assertEqual(reloaded.artist, 'Artist A')
        self.assertEqual(reloaded.length, timedelta(minutes=4, seconds=15))
        self.assertEqual(reloaded.notes, 'Bridge needs a key change')
        self.assertEqual(reloaded.position, 1)
