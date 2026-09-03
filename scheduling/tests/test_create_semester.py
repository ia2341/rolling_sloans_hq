"""`create_semester()`, the one new service seam Semester setup adds (issue #200)."""

from django.test import TestCase

from scheduling.factories import SemesterFactory
from scheduling.models import Semester
from scheduling.services import InvalidSemesterNameError, create_semester

TIMING_DEFAULTS = {
    'default_rehearsal_duration_minutes': 240,
    'default_setup_grace_minutes': 10,
    'default_teardown_grace_minutes': 10,
    'default_song_slot_count': 6,
    'default_arrival_buffer_minutes': 5,
    'default_departure_buffer_minutes': 5,
}


class CreateSemesterTests(TestCase):
    def test_creates_a_draft_with_the_given_timing_defaults(self):
        """A fresh Semester is created with `published_at` null and every timing default applied."""
        semester = create_semester(name='Fall 2026', **TIMING_DEFAULTS)

        semester.refresh_from_db()
        self.assertIsNone(semester.published_at)
        self.assertEqual(semester.name, 'Fall 2026')
        for field, value in TIMING_DEFAULTS.items():
            self.assertEqual(getattr(semester, field), value)

    def test_leaves_prior_semesters_unchanged(self):
        """Creating a new Semester touches no row belonging to an existing one."""
        prior = SemesterFactory(name='Spring 2026')
        prior_updated_at = prior.updated_at

        create_semester(name='Fall 2026', **TIMING_DEFAULTS)

        prior.refresh_from_db()
        self.assertEqual(prior.updated_at, prior_updated_at)

    def test_rejects_a_blank_name(self):
        """A blank or whitespace-only name raises without writing a row."""
        with self.assertRaises(InvalidSemesterNameError):
            create_semester(name='   ', **TIMING_DEFAULTS)

        self.assertEqual(Semester.objects.count(), 0)

    def test_rejects_a_duplicate_name_case_insensitively(self):
        """A name matching an existing Semester (any case) raises without writing a row."""
        SemesterFactory(name='Fall 2026')

        with self.assertRaises(InvalidSemesterNameError):
            create_semester(name='fall 2026', **TIMING_DEFAULTS)

        self.assertEqual(Semester.objects.count(), 1)
