"""preview_rehearsal_edits(): the ADR-0008 real-write-then-rollback wrapper writes nothing (issue #219)."""

from datetime import time, timedelta

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from scheduling.factories import RehearsalFactory, SemesterFactory
from scheduling.models import Rehearsal
from scheduling.services import (
    RehearsalEditBuffer,
    RehearsalEditRow,
    preview_rehearsal_edits,
)

TOMORROW = timezone.localdate() + timedelta(days=1)
NEXT_WEEK = timezone.localdate() + timedelta(days=7)


class PreviewRehearsalEditsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Semester with one existing future Rehearsal."""
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, date=TOMORROW, start_time=time(18, 0))

    def _preview(self, buffer):
        """Call preview_rehearsal_edits() inside a transaction the test itself rolls back, per its docstring's requirement."""
        with transaction.atomic():
            preview_rehearsal_edits(buffer, viewing_semester=self.semester)
            transaction.set_rollback(True)

    def test_writes_nothing_for_a_buffer_with_a_creation_and_a_mutation_together(self):
        """A preview of a new row plus an edited existing row leaves every Rehearsal row and the Semester stamp untouched."""
        count_before = Rehearsal.objects.count()
        stamp_before = self.semester.updated_at
        buffer = RehearsalEditBuffer(
            semester_id=self.semester.pk,
            semester_updated_at=self.semester.updated_at,
            rows=[
                RehearsalEditRow(
                    rehearsal_id=None, date=NEXT_WEEK, start_time=time(19, 0), end_time=time(21, 0),
                    is_full_setlist=False, setup_grace_minutes=None, teardown_grace_minutes=None,
                    arrival_buffer_minutes=None, departure_buffer_minutes=None,
                ),
                RehearsalEditRow(
                    rehearsal_id=self.rehearsal.pk, date=TOMORROW, start_time=time(20, 0), end_time=time(22, 0),
                    is_full_setlist=False, setup_grace_minutes=None, teardown_grace_minutes=None,
                    arrival_buffer_minutes=None, departure_buffer_minutes=None,
                ),
            ],
        )

        self._preview(buffer)

        self.assertEqual(Rehearsal.objects.count(), count_before)
        self.rehearsal.refresh_from_db()
        self.assertEqual(self.rehearsal.start_time, time(18, 0))
        self.semester.refresh_from_db()
        self.assertEqual(self.semester.updated_at, stamp_before)
