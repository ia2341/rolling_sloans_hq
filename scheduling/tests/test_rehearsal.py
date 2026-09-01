"""Rehearsal: dated/timed events defaulted from their Semester's timing fields (issue #36)."""

from datetime import time

from django.test import TestCase

from scheduling.factories import RehearsalFactory, SemesterFactory
from scheduling.models import Rehearsal


class RehearsalDefaultsFromSemesterTests(TestCase):
    def test_inherits_grace_periods_from_semester_at_creation(self):
        """A new Rehearsal's grace periods default to its Semester's, when left unset."""
        semester = SemesterFactory(default_setup_grace_minutes=20, default_teardown_grace_minutes=10)

        rehearsal = RehearsalFactory(semester=semester)

        reloaded = Rehearsal.objects.get(pk=rehearsal.pk)
        self.assertEqual(reloaded.setup_grace_minutes, 20)
        self.assertEqual(reloaded.teardown_grace_minutes, 10)

    def test_inherits_arrival_departure_buffers_from_semester_at_creation(self):
        """A new Rehearsal's arrival/departure buffers default to its Semester's, when left unset."""
        semester = SemesterFactory(default_arrival_buffer_minutes=10, default_departure_buffer_minutes=5)

        rehearsal = RehearsalFactory(semester=semester)

        reloaded = Rehearsal.objects.get(pk=rehearsal.pk)
        self.assertEqual(reloaded.arrival_buffer_minutes, 10)
        self.assertEqual(reloaded.departure_buffer_minutes, 5)

    def test_end_time_defaults_to_start_time_plus_semester_duration(self):
        """A new Rehearsal's end_time, left unset, is derived from the Semester's default duration."""
        semester = SemesterFactory(default_rehearsal_duration_minutes=90)

        rehearsal = RehearsalFactory(semester=semester, start_time=time(18, 0))

        reloaded = Rehearsal.objects.get(pk=rehearsal.pk)
        self.assertEqual(reloaded.end_time, time(19, 30))

    def test_end_time_crossing_midnight_raises_instead_of_wrapping_silently(self):
        """If the Semester's default duration would carry end_time past midnight, creation fails loud."""
        semester = SemesterFactory(default_rehearsal_duration_minutes=90)

        with self.assertRaises(ValueError):
            RehearsalFactory(semester=semester, start_time=time(23, 30))

    def test_explicit_values_at_creation_are_not_overridden_by_semester_defaults(self):
        """Values passed explicitly at creation win over the Semester's defaults."""
        semester = SemesterFactory(default_setup_grace_minutes=20, default_teardown_grace_minutes=10)

        rehearsal = RehearsalFactory(
            semester=semester,
            setup_grace_minutes=5,
            teardown_grace_minutes=5,
            arrival_buffer_minutes=15,
            departure_buffer_minutes=15,
            end_time=time(20, 0),
        )

        reloaded = Rehearsal.objects.get(pk=rehearsal.pk)
        self.assertEqual(reloaded.setup_grace_minutes, 5)
        self.assertEqual(reloaded.teardown_grace_minutes, 5)
        self.assertEqual(reloaded.arrival_buffer_minutes, 15)
        self.assertEqual(reloaded.departure_buffer_minutes, 15)
        self.assertEqual(reloaded.end_time, time(20, 0))


class RehearsalEditingIndependenceTests(TestCase):
    def test_editing_grace_periods_does_not_change_semester_defaults(self):
        """Editing a Rehearsal's grace periods afterward leaves the Semester's defaults untouched."""
        semester = SemesterFactory(default_setup_grace_minutes=20, default_teardown_grace_minutes=10)
        rehearsal = RehearsalFactory(semester=semester)

        rehearsal.setup_grace_minutes = 45
        rehearsal.teardown_grace_minutes = 45
        rehearsal.save()

        reloaded_semester = semester.__class__.objects.get(pk=semester.pk)
        self.assertEqual(reloaded_semester.default_setup_grace_minutes, 20)
        self.assertEqual(reloaded_semester.default_teardown_grace_minutes, 10)

    def test_editing_one_rehearsal_does_not_change_another(self):
        """Editing one Rehearsal's grace periods leaves a sibling Rehearsal in the same Semester untouched."""
        semester = SemesterFactory(default_setup_grace_minutes=20, default_teardown_grace_minutes=10)
        edited = RehearsalFactory(semester=semester)
        other = RehearsalFactory(semester=semester)

        edited.setup_grace_minutes = 45
        edited.teardown_grace_minutes = 45
        edited.save()

        reloaded_other = Rehearsal.objects.get(pk=other.pk)
        self.assertEqual(reloaded_other.setup_grace_minutes, 20)
        self.assertEqual(reloaded_other.teardown_grace_minutes, 10)

    def test_editing_arrival_departure_buffers_does_not_change_semester_defaults(self):
        """Editing a Rehearsal's arrival/departure buffers afterward leaves the Semester's defaults untouched."""
        semester = SemesterFactory(default_arrival_buffer_minutes=10, default_departure_buffer_minutes=5)
        rehearsal = RehearsalFactory(semester=semester)

        rehearsal.arrival_buffer_minutes = 30
        rehearsal.departure_buffer_minutes = 30
        rehearsal.save()

        reloaded_semester = semester.__class__.objects.get(pk=semester.pk)
        self.assertEqual(reloaded_semester.default_arrival_buffer_minutes, 10)
        self.assertEqual(reloaded_semester.default_departure_buffer_minutes, 5)

    def test_editing_one_rehearsal_does_not_change_another_arrival_departure_buffers(self):
        """Editing one Rehearsal's arrival/departure buffers leaves a sibling Rehearsal in the same Semester untouched."""
        semester = SemesterFactory(default_arrival_buffer_minutes=10, default_departure_buffer_minutes=5)
        edited = RehearsalFactory(semester=semester)
        other = RehearsalFactory(semester=semester)

        edited.arrival_buffer_minutes = 30
        edited.departure_buffer_minutes = 30
        edited.save()

        reloaded_other = Rehearsal.objects.get(pk=other.pk)
        self.assertEqual(reloaded_other.arrival_buffer_minutes, 10)
        self.assertEqual(reloaded_other.departure_buffer_minutes, 5)


class RehearsalIsFullSetlistTests(TestCase):
    def test_defaults_to_false(self):
        """A newly created Rehearsal is not the Dress Rehearsal by default."""
        rehearsal = RehearsalFactory()

        self.assertFalse(rehearsal.is_full_setlist)

    def test_can_be_toggled(self):
        """is_full_setlist can be flipped on and back off after creation."""
        rehearsal = RehearsalFactory(is_full_setlist=False)

        rehearsal.is_full_setlist = True
        rehearsal.save()
        reloaded = Rehearsal.objects.get(pk=rehearsal.pk)
        self.assertTrue(reloaded.is_full_setlist)

        reloaded.is_full_setlist = False
        reloaded.save()
        self.assertFalse(Rehearsal.objects.get(pk=rehearsal.pk).is_full_setlist)


class RehearsalFieldTests(TestCase):
    def test_created_with_all_fields(self):
        """A Rehearsal is created with its semester, date, start/end times, and grace periods."""
        semester = SemesterFactory()

        rehearsal = RehearsalFactory(
            semester=semester,
            date='2026-09-15',
            start_time=time(19, 0),
            end_time=time(21, 0),
            setup_grace_minutes=15,
            teardown_grace_minutes=15,
            arrival_buffer_minutes=10,
            departure_buffer_minutes=10,
            is_full_setlist=True,
        )

        reloaded = Rehearsal.objects.get(pk=rehearsal.pk)
        self.assertEqual(reloaded.semester, semester)
        self.assertEqual(str(reloaded.date), '2026-09-15')
        self.assertEqual(reloaded.start_time, time(19, 0))
        self.assertEqual(reloaded.end_time, time(21, 0))
        self.assertEqual(reloaded.setup_grace_minutes, 15)
        self.assertEqual(reloaded.teardown_grace_minutes, 15)
        self.assertEqual(reloaded.arrival_buffer_minutes, 10)
        self.assertEqual(reloaded.departure_buffer_minutes, 10)
        self.assertTrue(reloaded.is_full_setlist)
