"""The 0014 data migration clearing Conflicts that predate ADR-0006's mandatory-attendance rule."""

from importlib import import_module

from django.apps import apps
from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import RehearsalFactory
from scheduling.models import Conflict, ConflictWindow

# The migration module's name starts with a digit, so it can't be imported by name.
delete_dress_rehearsal_conflicts = import_module(
    'scheduling.migrations.0014_delete_dress_rehearsal_conflicts',
).delete_dress_rehearsal_conflicts


class DeleteDressRehearsalConflictsTests(TestCase):
    """Exercises the migration's own function; Conflict.save() now refuses to build the fixture."""

    def _legacy_conflict(self, rehearsal):
        """Insert a Conflict for a fresh Person on `rehearsal`, bypassing the save() guard as a pre-ADR-0006 row would."""
        conflict = Conflict(person=PersonFactory(), rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)
        [conflict] = Conflict.objects.bulk_create([conflict])
        return conflict

    def test_deletes_dress_rehearsal_conflicts_and_their_windows(self):
        """A Conflict on a Dress Rehearsal goes, and its ConflictWindows cascade away with it."""
        dress_rehearsal = RehearsalFactory(is_full_setlist=True)
        conflict = self._legacy_conflict(dress_rehearsal)
        ConflictWindow.objects.bulk_create([
            ConflictWindow(
                conflict=conflict,
                unavailable_start=dress_rehearsal.start_time,
                unavailable_end=dress_rehearsal.end_time,
            ),
        ])

        delete_dress_rehearsal_conflicts(apps, None)

        self.assertFalse(Conflict.objects.filter(pk=conflict.pk).exists())
        self.assertFalse(ConflictWindow.objects.filter(conflict_id=conflict.pk).exists())

    def test_leaves_ordinary_rehearsal_conflicts_alone(self):
        """A Conflict on a non-Dress Rehearsal is untouched."""
        conflict = self._legacy_conflict(RehearsalFactory(is_full_setlist=False))

        delete_dress_rehearsal_conflicts(apps, None)

        self.assertTrue(Conflict.objects.filter(pk=conflict.pk).exists())
