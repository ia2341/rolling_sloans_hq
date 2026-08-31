"""ConflictWindow: disjoint unavailable time ranges within a partial Conflict (issue #49)."""

from datetime import time

from django.core.exceptions import ValidationError
from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import (
    ConflictFactory,
    ConflictWindowFactory,
    RehearsalFactory,
)
from scheduling.models import Conflict, ConflictWindow


class ConflictWindowMultipleWindowsTests(TestCase):
    def test_partial_conflict_can_have_multiple_windows(self):
        """A partial Conflict can hold several disjoint ConflictWindow rows (e.g. 6-7pm and 8:30-9pm)."""
        rehearsal = RehearsalFactory(start_time=time(18, 0), end_time=time(21, 0))
        conflict = ConflictFactory(rehearsal=rehearsal, type=Conflict.PARTIAL)

        first = ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 0), unavailable_end=time(19, 0))
        second = ConflictWindowFactory(conflict=conflict, unavailable_start=time(20, 30), unavailable_end=time(21, 0))

        windows = ConflictWindow.objects.filter(conflict=conflict)
        self.assertEqual(windows.count(), 2)
        self.assertIn(first, windows)
        self.assertIn(second, windows)


class ConflictWindowFullConflictTests(TestCase):
    def test_full_conflict_has_no_windows(self):
        """A full_conflict Conflict has no associated ConflictWindow rows in normal use."""
        conflict = ConflictFactory(type=Conflict.FULL_CONFLICT)

        self.assertFalse(ConflictWindow.objects.filter(conflict=conflict).exists())


class ConflictWindowTypeFlipClearingTests(TestCase):
    def test_flipping_type_to_full_conflict_deletes_existing_windows(self):
        """Updating an existing Conflict's type from partial to full_conflict clears its stale windows."""
        conflict = ConflictFactory(type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=conflict)
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(19, 0), unavailable_end=time(19, 15))
        self.assertEqual(ConflictWindow.objects.filter(conflict=conflict).count(), 2)

        conflict.type = Conflict.FULL_CONFLICT
        conflict.save()

        self.assertFalse(ConflictWindow.objects.filter(conflict=conflict).exists())

    def test_saving_partial_conflict_without_type_change_does_not_delete_windows(self):
        """Re-saving a partial Conflict with type unchanged leaves its windows intact."""
        conflict = ConflictFactory(type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=conflict)

        conflict.save()

        self.assertEqual(ConflictWindow.objects.filter(conflict=conflict).count(), 1)


class ConflictWindowValidationTests(TestCase):
    def test_window_outside_rehearsal_span_is_rejected(self):
        """A window whose start or end falls outside the parent Rehearsal's time span fails validation."""
        rehearsal = RehearsalFactory(start_time=time(18, 0), end_time=time(19, 30))
        conflict = ConflictFactory(rehearsal=rehearsal, type=Conflict.PARTIAL)
        window = ConflictWindow(conflict=conflict, unavailable_start=time(17, 0), unavailable_end=time(18, 30))

        with self.assertRaises(ValidationError):
            window.full_clean()

    def test_window_within_rehearsal_span_is_valid(self):
        """A window whose start and end fall within the parent Rehearsal's time span passes validation."""
        rehearsal = RehearsalFactory(start_time=time(18, 0), end_time=time(19, 30))
        conflict = ConflictFactory(rehearsal=rehearsal, type=Conflict.PARTIAL)
        window = ConflictWindow(conflict=conflict, unavailable_start=time(18, 15), unavailable_end=time(18, 45))

        window.full_clean(exclude=['id'])


class ConflictAggregationTests(TestCase):
    def test_rehearsal_conflicts_with_windows_are_returned_via_select_and_prefetch(self):
        """Several members' mixed full/partial Conflicts for one Rehearsal come back with windows correctly attached.

        Exercises the standard select/prefetch query
        Conflict.objects.filter(rehearsal=X).select_related('person').prefetch_related('conflictwindow_set')
        an admin would use to pull all conflicts for a Rehearsal, per issue #49.
        """
        rehearsal = RehearsalFactory(start_time=time(18, 0), end_time=time(21, 0))
        full_conflict_person = PersonFactory()
        partial_conflict_person = PersonFactory()
        no_conflict_person = PersonFactory()

        ConflictFactory(person=full_conflict_person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)
        partial = ConflictFactory(person=partial_conflict_person, rehearsal=rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=partial, unavailable_start=time(18, 0), unavailable_end=time(19, 0))
        ConflictWindowFactory(conflict=partial, unavailable_start=time(20, 30), unavailable_end=time(21, 0))
        other_rehearsal_conflict = ConflictFactory(rehearsal=RehearsalFactory(), type=Conflict.FULL_CONFLICT)

        conflicts = Conflict.objects.filter(rehearsal=rehearsal).select_related('person').prefetch_related(
            'conflictwindow_set',
        )

        self.assertEqual(conflicts.count(), 2)
        by_person = {conflict.person_id: conflict for conflict in conflicts}
        self.assertNotIn(no_conflict_person.id, by_person)
        self.assertNotIn(other_rehearsal_conflict.person_id, by_person)

        full = by_person[full_conflict_person.id]
        self.assertEqual(list(full.conflictwindow_set.all()), [])

        partial_reloaded = by_person[partial_conflict_person.id]
        windows = list(partial_reloaded.conflictwindow_set.all())
        self.assertEqual(len(windows), 2)
        self.assertEqual(
            {(w.unavailable_start, w.unavailable_end) for w in windows},
            {(time(18, 0), time(19, 0)), (time(20, 30), time(21, 0))},
        )
