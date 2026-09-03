"""Rehearsal: dated/timed events defaulted from their Semester's timing fields (issue #36)."""

from datetime import date, time

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from scheduling.factories import ConflictFactory, RehearsalFactory, SemesterFactory
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


class RehearsalFullSetlistFlipWithConflictsTests(TestCase):
    """A Rehearsal members have declared Conflicts against can't become the Dress Rehearsal (issue #150, ADR-0006)."""

    def test_flip_on_is_blocked_when_conflicts_have_been_declared(self):
        """save() refuses the flip and names the count, so no write path can create Conflicts ADR-0006 forbids."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        ConflictFactory(rehearsal=rehearsal)
        ConflictFactory(rehearsal=rehearsal)

        rehearsal.is_full_setlist = True
        with self.assertRaises(ValueError) as raised:
            rehearsal.save()

        self.assertIn('2', str(raised.exception))
        self.assertFalse(Rehearsal.objects.get(pk=rehearsal.pk).is_full_setlist)

    def test_clean_reports_the_blocked_flip_as_a_field_error_naming_the_count(self):
        """clean() surfaces the blocked flip as an is_full_setlist error naming the count, not a 500."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        ConflictFactory(rehearsal=rehearsal)

        rehearsal.is_full_setlist = True
        with self.assertRaises(ValidationError) as raised:
            rehearsal.clean()

        self.assertIn('1', raised.exception.message_dict['is_full_setlist'][0])

    def test_the_blocked_flip_message_names_no_member_and_no_reason(self):
        """The message carries only a count — never who declared, or why (ADR-0005)."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        conflict = ConflictFactory(rehearsal=rehearsal, reason='Out of town for a wedding.')

        rehearsal.is_full_setlist = True
        with self.assertRaises(ValidationError) as raised:
            rehearsal.clean()

        message = raised.exception.message_dict['is_full_setlist'][0]
        self.assertNotIn(conflict.reason, message)
        self.assertNotIn(conflict.person.email, message)

    def test_flip_on_is_free_for_a_rehearsal_with_no_conflicts_of_its_own(self):
        """A Rehearsal nobody has declared against still becomes the Dress Rehearsal, whatever siblings carry."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        ConflictFactory()  # a Conflict against some other Rehearsal doesn't block this one

        rehearsal.is_full_setlist = True
        rehearsal.clean()
        rehearsal.save()

        self.assertTrue(Rehearsal.objects.get(pk=rehearsal.pk).is_full_setlist)

    def test_flip_back_off_stays_allowed(self):
        """Turning the Dress Rehearsal back into an ordinary Rehearsal is never blocked."""
        rehearsal = RehearsalFactory(is_full_setlist=True)

        rehearsal.is_full_setlist = False
        rehearsal.clean()
        rehearsal.save()

        self.assertFalse(Rehearsal.objects.get(pk=rehearsal.pk).is_full_setlist)

    def test_unrelated_edits_are_unaffected_by_existing_conflicts(self):
        """A Rehearsal with Conflicts still saves ordinary edits, so long as is_full_setlist stays false."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        ConflictFactory(rehearsal=rehearsal)

        rehearsal.setup_grace_minutes = 45
        rehearsal.save()

        self.assertEqual(Rehearsal.objects.get(pk=rehearsal.pk).setup_grace_minutes, 45)


class RehearsalCleanWithMissingRequiredFieldsTests(TestCase):
    def test_full_clean_with_blank_semester_raises_validation_error_not_500(self):
        """full_clean() on a Rehearsal with no semester surfaces a normal field error, not a DoesNotExist crash."""
        rehearsal = Rehearsal(date='2026-09-15', start_time=time(19, 0))

        with self.assertRaises(ValidationError) as ctx:
            rehearsal.full_clean()
        self.assertIn('semester', ctx.exception.message_dict)

    def test_full_clean_with_blank_date_raises_validation_error_not_500(self):
        """full_clean() on a Rehearsal with no date surfaces a normal field error, not a TypeError crash."""
        semester = SemesterFactory()
        rehearsal = Rehearsal(semester=semester, start_time=time(19, 0))

        with self.assertRaises(ValidationError) as ctx:
            rehearsal.full_clean()
        self.assertIn('date', ctx.exception.message_dict)


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


class RehearsalUniqueDatePerSemesterTests(TestCase):
    """One Rehearsal per evening per Semester (issue #214): the constraint rehearsal generation depends on."""

    def test_a_second_rehearsal_on_the_same_date_in_the_same_semester_raises(self):
        """Saving a second Rehearsal on a date a Semester already has one raises IntegrityError."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=date(2026, 9, 16))

        with self.assertRaises(IntegrityError):
            RehearsalFactory(semester=semester, date=date(2026, 9, 16))

    def test_the_same_date_in_a_different_semester_is_allowed(self):
        """The same calendar date is fine across two different Semesters."""
        first_semester = SemesterFactory()
        second_semester = SemesterFactory()

        RehearsalFactory(semester=first_semester, date=date(2026, 9, 16))
        RehearsalFactory(semester=second_semester, date=date(2026, 9, 16))

        self.assertEqual(Rehearsal.objects.filter(date=date(2026, 9, 16)).count(), 2)

    def test_a_different_date_in_the_same_semester_is_allowed(self):
        """A Semester can hold several Rehearsals as long as each falls on its own date."""
        semester = SemesterFactory()

        RehearsalFactory(semester=semester, date=date(2026, 9, 16))
        RehearsalFactory(semester=semester, date=date(2026, 9, 20))

        self.assertEqual(Rehearsal.objects.filter(semester=semester).count(), 2)
