"""The `/manage/conflicts/<rehearsal_id>/` adjudication table: one Save Changes per Rehearsal (issue #192)."""

from datetime import time

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from faker import Faker

from identity.factories import PersonFactory
from scheduling import services
from scheduling.factories import ConflictFactory, RehearsalFactory, SemesterFactory
from scheduling.models import Conflict, RehearsalSong, SongRoleAssignment
from scheduling.services import (
    AdjudicationBuffer,
    AdjudicationEntry,
    StaleAdjudicationSemesterError,
    UnknownConflictError,
    WrongAdjudicationSemesterError,
    apply_adjudications,
    conflict_adjudication_rows_for,
)

fake = Faker()
PASSWORD = 'a-strong-test-password-123'


class ConflictAdjudicationRowsForTests(TestCase):
    """`conflict_adjudication_rows_for()`: the read backing the table's rows."""

    @classmethod
    def setUpTestData(cls):
        """Build a Rehearsal with a full-absence and a late-arrival Conflict."""
        cls.rehearsal = RehearsalFactory(is_full_setlist=False, start_time=time(18, 0), end_time=time(20, 0))
        cls.absence_person = PersonFactory()
        cls.absence = ConflictFactory(
            person=cls.absence_person,
            rehearsal=cls.rehearsal,
            type=Conflict.FULL_CONFLICT,
            reason=fake.sentence(),
        )
        cls.late_person = PersonFactory()
        cls.late = services.declare_conflict(
            cls.late_person,
            cls.rehearsal,
            services.CONFLICT_LATE_ARRIVAL,
            declared_time=time(18, 30),
            reason=fake.sentence(),
        )

    def test_returns_one_row_per_conflict_on_the_rehearsal(self):
        """Every Conflict on the Rehearsal gets exactly one row."""
        rows = conflict_adjudication_rows_for(self.rehearsal)

        self.assertEqual({row.conflict.pk for row in rows}, {self.absence.pk, self.late.pk})

    def test_a_row_carries_person_declaration_reason_and_status(self):
        """Each row surfaces the person, declaration type label, declared time, reason and status."""
        rows = conflict_adjudication_rows_for(self.rehearsal)
        by_pk = {row.conflict.pk: row for row in rows}

        absence_row = by_pk[self.absence.pk]
        self.assertEqual(absence_row.person, self.absence_person)
        self.assertEqual(absence_row.type_label, 'Full absence')
        self.assertIsNone(absence_row.declared_time)
        self.assertEqual(absence_row.reason, self.absence.reason)
        self.assertEqual(absence_row.status, Conflict.PENDING)

        late_row = by_pk[self.late.pk]
        self.assertEqual(late_row.type_label, 'Late arrival')
        self.assertEqual(late_row.declared_time, time(18, 30))

    def test_excludes_conflicts_on_other_rehearsals(self):
        """A Conflict declared against a different Rehearsal never appears."""
        other_rehearsal = RehearsalFactory(is_full_setlist=False)
        ConflictFactory(rehearsal=other_rehearsal)

        rows = conflict_adjudication_rows_for(self.rehearsal)

        self.assertEqual({row.conflict.pk for row in rows}, {self.absence.pk, self.late.pk})

    def test_a_rehearsal_with_no_conflicts_returns_no_rows(self):
        """A conflict-free Rehearsal returns an empty list rather than raising."""
        empty_rehearsal = RehearsalFactory(is_full_setlist=False)

        rows = conflict_adjudication_rows_for(empty_rehearsal)

        self.assertEqual(rows, [])


class ApplyAdjudicationsTests(TestCase):
    """`apply_adjudications()`: the atomic, stamp-guarded batch write."""

    @classmethod
    def setUpTestData(cls):
        """Build a Semester with one Rehearsal carrying two pending Conflicts."""
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, is_full_setlist=False)
        cls.first = ConflictFactory(rehearsal=cls.rehearsal, status=Conflict.PENDING)
        cls.second = ConflictFactory(rehearsal=cls.rehearsal, status=Conflict.PENDING)

    def _buffer(self, entries, semester=None, semester_updated_at=None):
        """Build an AdjudicationBuffer for `self.rehearsal`, defaulting to the current Semester stamp."""
        semester = semester or self.semester
        return AdjudicationBuffer(
            rehearsal_id=self.rehearsal.pk,
            semester_id=semester.pk,
            semester_updated_at=semester_updated_at or semester.updated_at,
            entries=entries,
        )

    def test_writes_status_and_note_for_every_entry(self):
        """A save with the current stamp writes every entry's status and note."""
        note = fake.sentence()
        buffer = self._buffer([
            AdjudicationEntry(conflict_id=self.first.pk, status=Conflict.APPROVED, note=note),
            AdjudicationEntry(conflict_id=self.second.pk, status=Conflict.REJECTED, note=''),
        ])

        apply_adjudications(buffer, viewing_semester=self.semester)

        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.first.status, Conflict.APPROVED)
        self.assertEqual(self.first.adjudication_note, note)
        self.assertEqual(self.second.status, Conflict.REJECTED)
        self.assertEqual(self.second.adjudication_note, '')

    def test_flips_an_already_approved_row_back_to_rejected(self):
        """A row already decided can be flipped in either direction."""
        self.first.status = Conflict.APPROVED
        self.first.save()
        buffer = self._buffer([AdjudicationEntry(conflict_id=self.first.pk, status=Conflict.REJECTED, note='')])

        apply_adjudications(buffer, viewing_semester=self.semester)

        self.first.refresh_from_db()
        self.assertEqual(self.first.status, Conflict.REJECTED)

    def test_advances_the_semester_stamp(self):
        """A successful save bumps Semester.updated_at, so a subsequent stale save is rejected."""
        original_stamp = self.semester.updated_at
        buffer = self._buffer([AdjudicationEntry(conflict_id=self.first.pk, status=Conflict.APPROVED, note='')])

        apply_adjudications(buffer, viewing_semester=self.semester)

        self.semester.refresh_from_db()
        self.assertGreater(self.semester.updated_at, original_stamp)

    def test_touches_no_rehearsal_song_order_role_assignment_or_backup(self):
        """Approving a Conflict changes nothing but its own status and note (issue #192's boundary)."""
        buffer = self._buffer([AdjudicationEntry(conflict_id=self.first.pk, status=Conflict.APPROVED, note='')])
        rehearsal_song_count = RehearsalSong.objects.count()
        assignment_count = SongRoleAssignment.objects.count()

        apply_adjudications(buffer, viewing_semester=self.semester)

        self.assertEqual(RehearsalSong.objects.count(), rehearsal_song_count)
        self.assertEqual(SongRoleAssignment.objects.count(), assignment_count)

    def test_a_conflict_id_belonging_to_another_rehearsal_is_rejected_and_writes_nothing(self):
        """A Conflict id outside this Rehearsal raises and neither row is written."""
        other_rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)
        foreign = ConflictFactory(rehearsal=other_rehearsal, status=Conflict.PENDING)
        buffer = self._buffer([
            AdjudicationEntry(conflict_id=self.first.pk, status=Conflict.APPROVED, note=''),
            AdjudicationEntry(conflict_id=foreign.pk, status=Conflict.APPROVED, note=''),
        ])

        with self.assertRaises(UnknownConflictError):
            apply_adjudications(buffer, viewing_semester=self.semester)

        self.first.refresh_from_db()
        foreign.refresh_from_db()
        self.assertEqual(self.first.status, Conflict.PENDING)
        self.assertEqual(foreign.status, Conflict.PENDING)

    def test_a_semester_id_mismatch_is_rejected_and_writes_nothing(self):
        """A buffer naming a Semester other than the viewing one raises and writes nothing."""
        other_semester = SemesterFactory()
        buffer = self._buffer(
            [AdjudicationEntry(conflict_id=self.first.pk, status=Conflict.APPROVED, note='')],
            semester=other_semester,
        )

        with self.assertRaises(WrongAdjudicationSemesterError):
            apply_adjudications(buffer, viewing_semester=self.semester)

        self.first.refresh_from_db()
        self.assertEqual(self.first.status, Conflict.PENDING)

    def test_a_stale_stamp_is_hard_rejected_and_writes_nothing(self):
        """A buffer carrying an outdated Semester.updated_at raises and neither row is written."""
        stale_stamp = self.semester.updated_at
        self.semester.updated_at = timezone.now()
        self.semester.save(update_fields=['updated_at'])
        buffer = self._buffer(
            [AdjudicationEntry(conflict_id=self.first.pk, status=Conflict.APPROVED, note='')],
            semester_updated_at=stale_stamp,
        )

        with self.assertRaises(StaleAdjudicationSemesterError):
            apply_adjudications(buffer, viewing_semester=self.semester)

        self.first.refresh_from_db()
        self.assertEqual(self.first.status, Conflict.PENDING)

    def test_no_semester_row_lock_is_taken(self):
        """apply_adjudications() renumbers no positions, so it must not lock the Semester row."""
        import inspect

        source = inspect.getsource(apply_adjudications)

        self.assertNotIn('select_for_update', source)
        self.assertNotIn('_lock_semester', source)


@override_settings(SECURE_SSL_REDIRECT=False)
class ConflictAdjudicationDetailViewSaveTests(TestCase):
    """POST to `/manage/conflicts/<rehearsal_id>/`: the table's one Save Changes."""

    @classmethod
    def setUpTestData(cls):
        """Build an admin, a live Semester, a Rehearsal and two pending Conflicts."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, is_full_setlist=False)
        cls.first = ConflictFactory(rehearsal=cls.rehearsal, status=Conflict.PENDING)
        cls.second = ConflictFactory(rehearsal=cls.rehearsal, status=Conflict.PENDING)

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def _post(self, forms, stamp=None):
        """POST the adjudication formset: `forms` is a list of (conflict, status, note) tuples."""
        data = {
            'adjudication-TOTAL_FORMS': str(len(forms)),
            'adjudication-INITIAL_FORMS': str(len(forms)),
            'adjudication-MIN_NUM_FORMS': '0',
            'adjudication-MAX_NUM_FORMS': '1000',
            'semester_id': str(self.semester.pk),
            'semester_updated_at': (stamp or self.semester.updated_at).isoformat(),
        }
        for index, (conflict, status, note) in enumerate(forms):
            data[f'adjudication-{index}-conflict_id'] = str(conflict.pk)
            data[f'adjudication-{index}-status'] = status
            data[f'adjudication-{index}-note'] = note
        return self.client.post(
            reverse('scheduling:manage-conflicts-detail', args=[self.rehearsal.pk]), data,
        )

    def test_get_renders_every_conflict_with_person_type_time_reason_and_status(self):
        """A GET lists both Conflicts with their identifying detail."""
        response = self.client.get(reverse('scheduling:manage-conflicts-detail', args=[self.rehearsal.pk]))

        self.assertEqual(response.status_code, 200)
        triples = response.context['triples']
        self.assertEqual({triple[0].conflict.pk for triple in triples}, {self.first.pk, self.second.pk})

    def test_save_commits_both_rows_in_one_request(self):
        """A single Save Changes decides every row on the Rehearsal."""
        note = fake.sentence()
        response = self._post([
            (self.first, Conflict.APPROVED, note),
            (self.second, Conflict.REJECTED, ''),
        ])

        self.assertEqual(response.status_code, 302)
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.first.status, Conflict.APPROVED)
        self.assertEqual(self.first.adjudication_note, note)
        self.assertEqual(self.second.status, Conflict.REJECTED)

    def test_flipping_an_already_decided_row_both_directions_is_allowed(self):
        """An approved row can be flipped to rejected, and a rejected row to approved, in one save."""
        self.first.status = Conflict.APPROVED
        self.first.save()
        self.second.status = Conflict.REJECTED
        self.second.save()

        self._post([
            (self.first, Conflict.REJECTED, ''),
            (self.second, Conflict.APPROVED, ''),
        ])

        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.first.status, Conflict.REJECTED)
        self.assertEqual(self.second.status, Conflict.APPROVED)

    def test_note_is_optional_on_approval_and_rejection_alike(self):
        """Neither verdict requires a note to save successfully."""
        response = self._post([
            (self.first, Conflict.APPROVED, ''),
            (self.second, Conflict.REJECTED, ''),
        ])

        self.assertEqual(response.status_code, 302)

    def test_leaving_without_saving_writes_nothing(self):
        """A bare GET performs no write — the two Conflicts stay pending."""
        self.client.get(reverse('scheduling:manage-conflicts-detail', args=[self.rehearsal.pk]))

        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.first.status, Conflict.PENDING)
        self.assertEqual(self.second.status, Conflict.PENDING)

    def test_an_over_long_note_blocks_the_whole_save_and_preserves_the_buffer(self):
        """A too-long note on one row writes nothing, for either row, and re-renders with the submitted values."""
        too_long_note = 'x' * 256
        response = self._post([
            (self.first, Conflict.APPROVED, too_long_note),
            (self.second, Conflict.REJECTED, ''),
        ])

        self.assertEqual(response.status_code, 200)
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.first.status, Conflict.PENDING)
        self.assertEqual(self.second.status, Conflict.PENDING)
        self.assertContains(response, too_long_note)

    def test_a_conflict_id_from_another_rehearsal_is_rejected_and_writes_nothing(self):
        """A tampered conflict_id pointing outside this Rehearsal is rejected and nothing is written."""
        other_rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)
        foreign = ConflictFactory(rehearsal=other_rehearsal, status=Conflict.PENDING)

        response = self._post([
            (self.first, Conflict.APPROVED, ''),
            (foreign, Conflict.APPROVED, ''),
        ])

        self.assertEqual(response.status_code, 200)
        self.first.refresh_from_db()
        foreign.refresh_from_db()
        self.assertEqual(self.first.status, Conflict.PENDING)
        self.assertEqual(foreign.status, Conflict.PENDING)

    def test_a_stale_stamp_is_rejected_with_a_reload_and_reapply_message(self):
        """A save against a superseded Semester stamp is hard-rejected and says so."""
        stale_stamp = self.semester.updated_at
        self.semester.updated_at = timezone.now()
        self.semester.save(update_fields=['updated_at'])

        response = self._post(
            [(self.first, Conflict.APPROVED, ''), (self.second, Conflict.REJECTED, '')], stamp=stale_stamp,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'reload and reapply')
        self.first.refresh_from_db()
        self.assertEqual(self.first.status, Conflict.PENDING)

    def test_a_semester_id_mismatch_is_rejected_with_nothing_written(self):
        """A tampered semester_id field is rejected and writes nothing."""
        other_semester = SemesterFactory(draft=True)

        data = {
            'adjudication-TOTAL_FORMS': '2',
            'adjudication-INITIAL_FORMS': '2',
            'adjudication-MIN_NUM_FORMS': '0',
            'adjudication-MAX_NUM_FORMS': '1000',
            'semester_id': str(other_semester.pk),
            'semester_updated_at': self.semester.updated_at.isoformat(),
            'adjudication-0-conflict_id': str(self.first.pk),
            'adjudication-0-status': Conflict.APPROVED,
            'adjudication-0-note': '',
            'adjudication-1-conflict_id': str(self.second.pk),
            'adjudication-1-status': Conflict.REJECTED,
            'adjudication-1-note': '',
        }
        response = self.client.post(
            reverse('scheduling:manage-conflicts-detail', args=[self.rehearsal.pk]), data,
        )

        self.assertEqual(response.status_code, 200)
        self.first.refresh_from_db()
        self.assertEqual(self.first.status, Conflict.PENDING)

    def test_no_email_is_sent_on_save(self):
        """Adjudicating Conflicts triggers no external side effect."""
        from django.core import mail

        self._post([(self.first, Conflict.APPROVED, '')])

        self.assertEqual(len(mail.outbox), 0)

    def test_adjudication_note_never_leaks_into_the_admin_index_or_read_service(self):
        """conflict_adjudication_index_for() (the /manage/conflicts/ index) carries no adjudication_note (ADR 0005)."""
        note = 'a private admin-only note'
        self._post([(self.first, Conflict.APPROVED, note), (self.second, Conflict.REJECTED, '')])

        response = self.client.get(reverse('scheduling:manage-conflicts'))

        self.assertNotContains(response, note)


@override_settings(SECURE_SSL_REDIRECT=False)
class NonAdminAndAnonymousSaveAccessTests(TestCase):
    """Access control on the save path mirrors the already-tested GET path (issue #191's mixin)."""

    @classmethod
    def setUpTestData(cls):
        """Build a Rehearsal with one Conflict."""
        cls.rehearsal = RehearsalFactory(is_full_setlist=False)
        cls.conflict = ConflictFactory(rehearsal=cls.rehearsal, status=Conflict.PENDING)

    def test_post_is_forbidden_for_a_non_admin(self):
        """A logged-in non-admin's POST returns 403."""
        member = PersonFactory(password=PASSWORD, is_admin=False)
        self.client.login(username=member.email, password=PASSWORD)

        response = self.client.post(reverse('scheduling:manage-conflicts-detail', args=[self.rehearsal.pk]), {})

        self.assertEqual(response.status_code, 403)
