"""The 0018 migration: a pre-existing zero-count SongRoleRequirement must not block the incoming check constraint."""

from datetime import timedelta

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class DeleteZeroCountRequirementsMigrationTests(TransactionTestCase):
    """Migrates the real schema forward across 0018, the way it will run in production."""

    migrate_from = ('scheduling', '0017_semester_updated_at')
    migrate_to = ('scheduling', '0018_alter_songrolerequirement_count_and_more')

    def setUp(self):
        """Roll the scheduling app's schema back to just before the count constraint lands."""
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])

    def tearDown(self):
        """Leave the test database on its latest migration state for other tests."""
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([executor.loader.graph.leaf_nodes('scheduling')[0]])

    def test_migration_applies_over_a_pre_existing_zero_count_row(self):
        """A zero-count row present before 0017 is gone after it, and the constraint is in force."""
        old_apps = self.executor.loader.project_state(self.migrate_from).apps
        Song = old_apps.get_model('scheduling', 'Song')
        Role = old_apps.get_model('scheduling', 'Role')
        Semester = old_apps.get_model('scheduling', 'Semester')
        SongRoleRequirement = old_apps.get_model('scheduling', 'SongRoleRequirement')

        semester = Semester.objects.create(
            name='Test Semester',
            default_rehearsal_duration_minutes=90,
            default_setup_grace_minutes=10,
            default_teardown_grace_minutes=10,
            default_song_slot_count=1,
            default_arrival_buffer_minutes=5,
            default_departure_buffer_minutes=5,
        )
        song = Song.objects.create(
            semester=semester,
            title='Test Song',
            artist='Test Artist',
            length=timedelta(minutes=3),
            position=1,
        )
        role = Role.objects.create(name='Singer')
        zero_count_requirement = SongRoleRequirement.objects.create(song=song, role=role, count=0)

        self.executor.loader.build_graph()
        self.executor.migrate([self.migrate_to])

        new_apps = self.executor.loader.project_state(self.migrate_to).apps
        NewSongRoleRequirement = new_apps.get_model('scheduling', 'SongRoleRequirement')
        self.assertFalse(NewSongRoleRequirement.objects.filter(pk=zero_count_requirement.pk).exists())

        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO scheduling_songrolerequirement (song_id, role_id, count) VALUES (%s, %s, 0)',
                [song.pk, role.pk],
            )
