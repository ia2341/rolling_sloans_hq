"""Conflict adjudication: the status/note pair, its reset on edit, and the reads it must not reach (issue #189)."""

from datetime import time, timedelta
from importlib import import_module

from django.test import TestCase
from django.utils import timezone
from faker import Faker

from identity.factories import PersonFactory
from scheduling import services
from scheduling.factories import (
    ConflictFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Conflict

fake = Faker()

# The migration module's name starts with a digit, so it can't be imported by name.
_migration = import_module('scheduling.migrations.0018_conflict_adjudication')


class ConflictAdjudicationFieldTests(TestCase):
    """The two new fields exist, default to an undecided verdict, and carry no provenance."""

    def test_a_freshly_built_conflict_is_pending_with_an_empty_note(self):
        """A Conflict created without adjudication starts pending and unannotated."""
        conflict = ConflictFactory()

        self.assertEqual(conflict.status, Conflict.PENDING)
        self.assertEqual(conflict.adjudication_note, '')

    def test_status_accepts_each_of_the_three_verdicts(self):
        """pending, approved and rejected all round-trip through the database."""
        for status in (Conflict.PENDING, Conflict.APPROVED, Conflict.REJECTED):
            with self.subTest(status=status):
                conflict = ConflictFactory(status=status)

                conflict.refresh_from_db()

                self.assertEqual(conflict.status, status)

    def test_an_adjudication_note_is_offered_on_an_approval_as_readily_as_on_a_rejection(self):
        """A note saves alongside either verdict — it is not a rejection-only field."""
        for status in (Conflict.APPROVED, Conflict.REJECTED):
            with self.subTest(status=status):
                note = fake.sentence()
                conflict = ConflictFactory(status=status, adjudication_note=note)

                conflict.refresh_from_db()

                self.assertEqual(conflict.adjudication_note, note)

    def test_the_note_is_never_required(self):
        """adjudication_note is blank-able, so an admin may decide without writing anything."""
        field = Conflict._meta.get_field('adjudication_note')

        self.assertTrue(field.blank)
        self.assertFalse(field.null)

    def test_no_provenance_field_is_added(self):
        """Nothing records who adjudicated, when, or what the prior verdict was (issue #189, deliberate)."""
        field_names = {field.name for field in Conflict._meta.get_fields()}

        self.assertEqual(
            field_names & {'adjudicated_at', 'adjudicated_by', 'adjudication_history', 'previous_status'},
            set(),
        )


class ConflictAdjudicationMigrationTests(TestCase):
    """0016 backfills every pre-existing Conflict to pending with an empty note."""

    def test_the_migration_adds_both_fields_with_an_undecided_default(self):
        """Each AddField carries the default that rewrites existing rows: pending, and an empty note."""
        defaults = {
            operation.name: operation.field.get_default()
            for operation in _migration.Migration.operations
            if operation.model_name == 'conflict'
        }

        self.assertEqual(defaults, {'status': Conflict.PENDING, 'adjudication_note': ''})

    def test_the_migration_adds_no_provenance_field(self):
        """0016 touches only the two fields issue #189 specifies."""
        added = {operation.name for operation in _migration.Migration.operations}

        self.assertEqual(added, {'status', 'adjudication_note'})


class DeclareConflictResetsAdjudicationTests(TestCase):
    """Every path through declare_conflict() returns the row to pending with an empty note."""

    @classmethod
    def setUpTestData(cls):
        """Build a Person and a declarable (non-Dress) Rehearsal."""
        cls.person = PersonFactory()
        cls.rehearsal = RehearsalFactory(is_full_setlist=False)

    def _adjudicate(self, conflict, status=Conflict.APPROVED):
        """Stamp `conflict` with `status` and a synthesized note, as an admin's decision would."""
        conflict.status = status
        conflict.adjudication_note = fake.sentence()
        conflict.save()
        return conflict

    def test_a_fresh_declaration_starts_pending_with_an_empty_note(self):
        """A first-time declaration is undecided, not silently approved."""
        conflict = services.declare_conflict(
            self.person, self.rehearsal, services.CONFLICT_FULL_ABSENCE, reason=fake.sentence(),
        )

        self.assertEqual(conflict.status, Conflict.PENDING)
        self.assertEqual(conflict.adjudication_note, '')

    def test_editing_an_approved_conflict_returns_it_to_pending_and_clears_the_note(self):
        """An approval never survives the member moving the declaration it blessed."""
        conflict = services.declare_conflict(self.person, self.rehearsal, services.CONFLICT_FULL_ABSENCE)
        self._adjudicate(conflict)

        edited = services.declare_conflict(
            self.person, self.rehearsal, services.CONFLICT_FULL_ABSENCE, reason=fake.sentence(),
        )

        self.assertEqual(edited.pk, conflict.pk)
        self.assertEqual(edited.status, Conflict.PENDING)
        self.assertEqual(edited.adjudication_note, '')

    def test_editing_a_rejected_conflict_also_returns_it_to_pending(self):
        """A rejection is reset too — the reset is about staleness, not about which verdict was reached."""
        conflict = services.declare_conflict(self.person, self.rehearsal, services.CONFLICT_FULL_ABSENCE)
        self._adjudicate(conflict, status=Conflict.REJECTED)

        edited = services.declare_conflict(self.person, self.rehearsal, services.CONFLICT_FULL_ABSENCE)

        self.assertEqual(edited.status, Conflict.PENDING)
        self.assertEqual(edited.adjudication_note, '')

    def test_changing_declaration_type_resets_the_adjudication(self):
        """A full absence re-declared as a late arrival comes back pending and unannotated."""
        conflict = services.declare_conflict(self.person, self.rehearsal, services.CONFLICT_FULL_ABSENCE)
        self._adjudicate(conflict)

        edited = services.declare_conflict(
            self.person,
            self.rehearsal,
            services.CONFLICT_LATE_ARRIVAL,
            declared_time=time(18, 30),
        )

        self.assertEqual(edited.status, Conflict.PENDING)
        self.assertEqual(edited.adjudication_note, '')

    def test_changing_between_two_partial_declaration_types_resets_the_adjudication(self):
        """A late arrival re-declared as an early departure is undecided again."""
        conflict = services.declare_conflict(
            self.person, self.rehearsal, services.CONFLICT_LATE_ARRIVAL, declared_time=time(18, 30),
        )
        self._adjudicate(conflict)

        edited = services.declare_conflict(
            self.person, self.rehearsal, services.CONFLICT_EARLY_DEPARTURE, declared_time=time(19, 0),
        )

        self.assertEqual(edited.status, Conflict.PENDING)
        self.assertEqual(edited.adjudication_note, '')

    def test_deleting_and_redeclaring_starts_pending_with_an_empty_note(self):
        """A delete-and-redeclare cannot smuggle an old verdict back onto the new row."""
        conflict = services.declare_conflict(self.person, self.rehearsal, services.CONFLICT_FULL_ABSENCE)
        self._adjudicate(conflict)
        conflict.delete()

        redeclared = services.declare_conflict(self.person, self.rehearsal, services.CONFLICT_FULL_ABSENCE)

        self.assertEqual(redeclared.status, Conflict.PENDING)
        self.assertEqual(redeclared.adjudication_note, '')

    def test_the_reset_is_persisted_not_only_set_on_the_returned_instance(self):
        """Re-reading the row from the database shows the reset, so every caller sees it."""
        conflict = services.declare_conflict(self.person, self.rehearsal, services.CONFLICT_FULL_ABSENCE)
        self._adjudicate(conflict)

        services.declare_conflict(self.person, self.rehearsal, services.CONFLICT_FULL_ABSENCE)

        conflict.refresh_from_db()
        self.assertEqual(conflict.status, Conflict.PENDING)
        self.assertEqual(conflict.adjudication_note, '')


class AdjudicationDoesNotReachTheAttendanceReadsTests(TestCase):
    """status governs neither "are you needed" nor "when should you come" (issue #189's boundary).

    An approved absence un-assigns nobody, a rejected one constrains
    nothing, and a pending one is not a silent approval — so each of these
    five reads must return an identical answer under all three verdicts.
    These are regression tests: they exist to stop a future contributor
    helpfully wiring approval into attendance.
    """

    @classmethod
    def setUpTestData(cls):
        """Build a future Rehearsal with three slots, a Person assigned to the first, and a Conflict for them."""
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(
            semester=cls.semester,
            date=timezone.localdate() + timedelta(days=7),
            is_full_setlist=False,
        )
        cls.role = RoleFactory()
        cls.first_song = SongFactory(semester=cls.semester)
        cls.middle_song = SongFactory(semester=cls.semester)
        cls.last_song = SongFactory(semester=cls.semester)
        RehearsalSongFactory(rehearsal=cls.rehearsal, song=cls.first_song, order=1)
        RehearsalSongFactory(rehearsal=cls.rehearsal, song=cls.middle_song, order=2)
        RehearsalSongFactory(rehearsal=cls.rehearsal, song=cls.last_song, order=3)
        cls.person = PersonFactory()
        SongRoleAssignmentFactory(song=cls.first_song, role=cls.role, person=cls.person)
        SongRoleAssignmentFactory(song=cls.last_song, role=cls.role, person=cls.person)
        cls.conflict = ConflictFactory(
            person=cls.person, rehearsal=cls.rehearsal, type=Conflict.FULL_CONFLICT, reason=fake.sentence(),
        )

    def _under_each_status(self, read):
        """Return `read()`'s answer under pending, approved and rejected, as a dict keyed by status."""
        answers = {}
        for status in (Conflict.PENDING, Conflict.APPROVED, Conflict.REJECTED):
            self.conflict.status = status
            self.conflict.adjudication_note = '' if status == Conflict.PENDING else fake.sentence()
            self.conflict.save()
            answers[status] = read()
        return answers

    def _assert_identical_under_each_status(self, read):
        """Assert `read()` returns the same answer whether the Conflict is pending, approved or rejected."""
        answers = self._under_each_status(read)

        self.assertEqual(answers[Conflict.APPROVED], answers[Conflict.PENDING])
        self.assertEqual(answers[Conflict.REJECTED], answers[Conflict.PENDING])

    def test_attendance_for_ignores_the_verdict(self):
        """Rehearsal.attendance_for reports the same start/end need under every verdict."""
        self._assert_identical_under_each_status(lambda: self.rehearsal.attendance_for(self.person))

    def test_attendance_suggestion_for_ignores_the_verdict(self):
        """attendance_suggestion_for returns the same arrival/departure window under every verdict."""
        self._assert_identical_under_each_status(
            lambda: services.attendance_suggestion_for(self.rehearsal, self.person),
        )

    def test_next_attended_rehearsal_for_ignores_the_verdict(self):
        """next_attended_rehearsal_for lands on the same Rehearsal under every verdict."""
        self._assert_identical_under_each_status(
            lambda: services.next_attended_rehearsal_for(self.person, self.semester),
        )

    def test_breaks_for_ignores_the_verdict(self):
        """breaks_for reports the same idle gaps under every verdict."""
        self._assert_identical_under_each_status(lambda: services.breaks_for(self.rehearsal, self.person))

    def test_performers_for_ignores_the_verdict(self):
        """performers_for lists the same people under every verdict."""
        self._assert_identical_under_each_status(lambda: services.performers_for(self.first_song))

    def test_an_approved_full_absence_still_leaves_the_person_needed(self):
        """The boundary spelled out concretely: approval does not un-assign the approved absentee."""
        self.conflict.status = Conflict.APPROVED
        self.conflict.save()

        attendance = self.rehearsal.attendance_for(self.person)

        self.assertTrue(attendance.needed_from_start)
        self.assertTrue(attendance.needed_until_end)
