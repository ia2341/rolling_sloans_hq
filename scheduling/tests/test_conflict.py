"""Conflict: a Person's declared unavailability for a Rehearsal (issue #48)."""

from datetime import date, time

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import ConflictFactory, RehearsalFactory
from scheduling.models import Conflict


class ConflictUniquenessTests(TestCase):
    def test_duplicate_person_rehearsal_pair_is_rejected(self):
        """A second Conflict row for the same (person, rehearsal) pair raises IntegrityError.

        One row per member per Rehearsal, edited in place, never
        append-only versioned.
        """
        person = PersonFactory()
        rehearsal = RehearsalFactory()
        ConflictFactory(person=person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)

        with self.assertRaises(IntegrityError), transaction.atomic():
            ConflictFactory(person=person, rehearsal=rehearsal, type=Conflict.PARTIAL)

    def test_same_person_can_have_conflicts_on_different_rehearsals(self):
        """A Person can hold independent Conflict rows across distinct Rehearsals."""
        person = PersonFactory()
        first = RehearsalFactory()
        second = RehearsalFactory()

        ConflictFactory(person=person, rehearsal=first)
        ConflictFactory(person=person, rehearsal=second)

        self.assertEqual(Conflict.objects.filter(person=person).count(), 2)

    def test_same_rehearsal_can_have_conflicts_from_different_people(self):
        """A Rehearsal can hold independent Conflict rows from distinct People."""
        rehearsal = RehearsalFactory()

        ConflictFactory(rehearsal=rehearsal)
        ConflictFactory(rehearsal=rehearsal)

        self.assertEqual(Conflict.objects.filter(rehearsal=rehearsal).count(), 2)

    def test_existing_conflict_can_be_edited_in_place(self):
        """Updating an existing Conflict's type does not create a second row."""
        conflict = ConflictFactory(type=Conflict.FULL_CONFLICT)

        conflict.type = Conflict.PARTIAL
        conflict.save()

        self.assertEqual(Conflict.objects.filter(person=conflict.person, rehearsal=conflict.rehearsal).count(), 1)
        reloaded = Conflict.objects.get(pk=conflict.pk)
        self.assertEqual(reloaded.type, Conflict.PARTIAL)


class ConflictImplicitAvailabilityTests(TestCase):
    def test_no_row_is_distinguishable_from_an_explicit_row(self):
        """A (person, rehearsal) pair with no Conflict row is distinct from one with an explicit row.

        Application code determines availability by checking whether a row
        exists at all, not by reading a status value off a row that's
        always present — a Rehearsal a member has never submitted anything
        for is implicitly fully available by the absence of a row.
        """
        person = PersonFactory()
        rehearsal_with_no_conflict = RehearsalFactory()
        rehearsal_with_conflict = RehearsalFactory()
        ConflictFactory(person=person, rehearsal=rehearsal_with_conflict, type=Conflict.FULL_CONFLICT)

        assumed_available = not Conflict.objects.filter(person=person, rehearsal=rehearsal_with_no_conflict).exists()
        has_explicit_conflict = Conflict.objects.filter(person=person, rehearsal=rehearsal_with_conflict).exists()

        self.assertTrue(assumed_available)
        self.assertTrue(has_explicit_conflict)

    def test_deleting_a_conflict_returns_the_pair_to_implicit_availability(self):
        """Deleting a Conflict row removes any explicit status, reverting to implicit full availability."""
        conflict = ConflictFactory()
        person, rehearsal = conflict.person, conflict.rehearsal

        conflict.delete()

        self.assertFalse(Conflict.objects.filter(person=person, rehearsal=rehearsal).exists())


class ConflictNoDeadlineOrEditLockTests(TestCase):
    def test_conflict_can_be_created_and_edited_after_rehearsal_start_time(self):
        """Nothing on Conflict blocks creating or editing a row relative to the Rehearsal's start time."""
        past_rehearsal = RehearsalFactory(date=date(2020, 1, 1), start_time=time(18, 0))

        conflict = ConflictFactory(rehearsal=past_rehearsal, type=Conflict.FULL_CONFLICT)
        conflict.type = Conflict.PARTIAL
        conflict.save()

        reloaded = Conflict.objects.get(pk=conflict.pk)
        self.assertEqual(reloaded.type, Conflict.PARTIAL)


class ConflictFieldTests(TestCase):
    def test_created_with_all_fields(self):
        """A Conflict is created with its Person, Rehearsal, and type, plus timestamps."""
        person = PersonFactory()
        rehearsal = RehearsalFactory()

        conflict = ConflictFactory(person=person, rehearsal=rehearsal, type=Conflict.PARTIAL)

        reloaded = Conflict.objects.get(pk=conflict.pk)
        self.assertEqual(reloaded.person, person)
        self.assertEqual(reloaded.rehearsal, rehearsal)
        self.assertEqual(reloaded.type, Conflict.PARTIAL)
        self.assertIsNotNone(reloaded.created_at)
        self.assertIsNotNone(reloaded.updated_at)

    def test_reason_is_optional(self):
        """A Conflict can be created without a reason, defaulting to an empty string."""
        conflict = ConflictFactory()

        self.assertEqual(conflict.reason, '')

    def test_reason_is_saved(self):
        """A Conflict's reason text is persisted and reloadable."""
        conflict = ConflictFactory(reason='Out of town for a wedding.')

        reloaded = Conflict.objects.get(pk=conflict.pk)
        self.assertEqual(reloaded.reason, 'Out of town for a wedding.')


class ConflictDressRehearsalTests(TestCase):
    """Dress Rehearsal attendance is mandatory, so no Conflict may point at one (ADR-0006)."""

    @classmethod
    def setUpTestData(cls):
        """Build a Person and a Dress Rehearsal for every test."""
        cls.person = PersonFactory()
        cls.dress_rehearsal = RehearsalFactory(is_full_setlist=True)

    def test_clean_rejects_a_conflict_on_the_dress_rehearsal(self):
        """clean() raises a ValidationError so a ModelForm surfaces it as a field error, not a 500."""
        conflict = Conflict(
            person=self.person, rehearsal=self.dress_rehearsal, type=Conflict.FULL_CONFLICT,
        )

        with self.assertRaises(ValidationError) as raised:
            conflict.clean()

        self.assertIn('rehearsal', raised.exception.message_dict)

    def test_save_rejects_a_conflict_on_the_dress_rehearsal(self):
        """save() raises for every write path, including .objects.create() and the Django admin."""
        with self.assertRaises(ValueError):
            Conflict.objects.create(
                person=self.person, rehearsal=self.dress_rehearsal, type=Conflict.FULL_CONFLICT,
            )

        self.assertFalse(Conflict.objects.filter(rehearsal=self.dress_rehearsal).exists())

    def test_an_ordinary_rehearsal_is_still_accepted(self):
        """A Conflict on a non-Dress Rehearsal passes both clean() and save() untouched."""
        rehearsal = RehearsalFactory(is_full_setlist=False)

        conflict = Conflict(person=self.person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)
        conflict.clean()
        conflict.save()

        self.assertTrue(Conflict.objects.filter(pk=conflict.pk).exists())
