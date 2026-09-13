"""Tests for the `diagnose_role_requirement_orphans` read-only management command (issue #443)."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import (
    BackupFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Backup, SongRoleAssignment


class DiagnoseRoleRequirementOrphansTests(TestCase):
    """Verifies the command finds orphaned rows per Semester and writes nothing.

    `SongRoleAssignmentFactory`/`BackupFactory` both auto-create a matching
    `SongRoleRequirement` (issue #439/#440's gate runs on every `save()`),
    so an orphaned row can only be built the way a real legacy row would
    have gotten here: via `bulk_create()`, which bypasses `save()` entirely.
    """

    def test_reports_no_orphans_on_clean_data(self):
        """A normally-created (gated) assignment and backup report zero orphans."""
        SongRoleAssignmentFactory()
        BackupFactory()

        out = StringIO()
        call_command('diagnose_role_requirement_orphans', stdout=out)

        self.assertIn('0 orphaned', out.getvalue())
        self.assertIn('No orphaned rows found', out.getvalue())

    def test_finds_orphaned_assignment_and_reports_its_semester_id(self):
        """An assignment with no backing Requirement is counted under its Song's Semester id."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        role = RoleFactory()
        person = PersonFactory()
        SongRoleAssignment.objects.bulk_create([
            SongRoleAssignment(song=song, role=role, person=person),
        ])

        out = StringIO()
        call_command('diagnose_role_requirement_orphans', stdout=out)

        self.assertIn('SongRoleAssignment: 1 total, 1 orphaned', out.getvalue())
        self.assertIn(f'semester_id={semester.pk}: 1 orphaned SongRoleAssignment row(s)', out.getvalue())
        self.assertNotIn(song.title, out.getvalue())
        self.assertNotIn(person.email, out.getvalue())

    def test_finds_orphaned_backup_and_reports_its_semester_id(self):
        """A Backup with no backing Requirement is counted under its RehearsalSong's Semester id."""
        rehearsal_song = RehearsalSongFactory()
        semester = rehearsal_song.rehearsal.semester
        role = RoleFactory()
        person = PersonFactory()
        Backup.objects.bulk_create([
            Backup(rehearsal_song=rehearsal_song, role=role, person=person),
        ])

        out = StringIO()
        call_command('diagnose_role_requirement_orphans', stdout=out)

        self.assertIn('Backup: 1 total, 1 orphaned', out.getvalue())
        self.assertIn(f'semester_id={semester.pk}: 1 orphaned Backup row(s)', out.getvalue())
