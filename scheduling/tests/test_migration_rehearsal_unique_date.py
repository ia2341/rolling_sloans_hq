"""The 0020 migration: pre-existing duplicate Rehearsals must block the incoming UniqueConstraint(semester, date)."""

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class RehearsalUniqueDatePerSemesterMigrationTests(TransactionTestCase):
    """Migrates the real schema forward across 0020, the way it will run in production."""

    migrate_from = ('scheduling', '0019_alter_songrolerequirement_count_and_more')
    migrate_to = ('scheduling', '0020_rehearsal_unique_date_per_semester')

    def setUp(self):
        """Roll the scheduling app's schema back to just before the date constraint lands."""
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])

    def tearDown(self):
        """Leave the test database on its latest migration state for other tests."""
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([executor.loader.graph.leaf_nodes('scheduling')[0]])

    def _old_models(self):
        """Return (Semester, Rehearsal) as they existed just before migration 0020."""
        old_apps = self.executor.loader.project_state(self.migrate_from).apps
        return old_apps.get_model('scheduling', 'Semester'), old_apps.get_model('scheduling', 'Rehearsal')

    def _create_semester(self, Semester):
        """Create a minimal Semester through the historical model."""
        return Semester.objects.create(
            name='Test Semester',
            default_rehearsal_duration_minutes=90,
            default_setup_grace_minutes=10,
            default_teardown_grace_minutes=10,
            default_song_slot_count=1,
            default_arrival_buffer_minutes=5,
            default_departure_buffer_minutes=5,
        )

    def test_migration_refuses_to_apply_over_pre_existing_duplicate_dates(self):
        """Two Rehearsals sharing (semester, date) block the migration instead of being silently resolved."""
        Semester, Rehearsal = self._old_models()
        semester = self._create_semester(Semester)
        Rehearsal.objects.create(semester=semester, date='2026-09-16', start_time='19:00:00', end_time='21:00:00')
        duplicate = Rehearsal.objects.create(
            semester=semester, date='2026-09-16', start_time='19:30:00', end_time='21:30:00',
        )

        self.executor.loader.build_graph()
        with self.assertRaises(RuntimeError) as raised:
            self.executor.migrate([self.migrate_to])
        self.assertIn('2026-09-16', str(raised.exception))

        # Clear the fixture so tearDown's migrate-to-leaf doesn't hit the same guard.
        duplicate.delete()

    def test_migration_applies_cleanly_with_no_duplicate_dates(self):
        """Distinct dates within a Semester don't block the migration, and the constraint is in force after."""
        Semester, Rehearsal = self._old_models()
        semester = self._create_semester(Semester)
        Rehearsal.objects.create(semester=semester, date='2026-09-16', start_time='19:00:00', end_time='21:00:00')
        Rehearsal.objects.create(semester=semester, date='2026-09-20', start_time='19:00:00', end_time='21:00:00')

        self.executor.loader.build_graph()
        self.executor.migrate([self.migrate_to])

        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO scheduling_rehearsal (semester_id, date, start_time, end_time, is_full_setlist) '
                "VALUES (%s, '2026-09-16', '20:00:00', '22:00:00', false)",
                [semester.pk],
            )
