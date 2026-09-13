"""Read-only diagnostic for issue #443: find SongRoleAssignment/Backup rows with no backing SongRoleRequirement.

Issues #439/#440 gate new `SongRoleAssignment`/`Backup` writes on a
matching `SongRoleRequirement` existing for that (song, role) pair, but a
row saved before that gate landed could still violate it. This command
never writes anything — it only counts. Output is deliberately limited to
row counts and numeric `Semester` ids, never a Song/Role/Person name or
email, because this is meant to be safe to run in a public CI log (see
`.github/workflows/diagnose-role-requirement-orphans.yml`) against a real
database, and this repo's privacy constraint (CONTRIBUTING.md) still
applies to anything a real run of this command could print.
"""

from django.core.management.base import BaseCommand

from scheduling.models import Backup, SongRoleAssignment, song_role_requirement_exists


class Command(BaseCommand):
    """`manage.py diagnose_role_requirement_orphans`: report orphaned assignment/backup rows, per Semester."""

    help = (
        'Read-only report of SongRoleAssignment/Backup rows with no backing SongRoleRequirement '
        '(the invariant issues #439/#440 introduced). Writes nothing; prints only counts and Semester ids.'
    )

    def handle(self, *args, **options):
        """Print a per-Semester breakdown of orphaned SongRoleAssignment and Backup rows.

        Reuses `scheduling.models.song_role_requirement_exists()` — the
        same predicate `SongRoleAssignment.clean()`/`Backup.clean()` use —
        rather than re-deriving the check, so this reports exactly what
        the app itself would now refuse to (re-)save.
        """
        assignment_total, assignment_orphans_by_semester = self._orphans_by_semester(
            SongRoleAssignment.objects.select_related('song'),
            song_id_of=lambda a: a.song_id,
            semester_id_of=lambda a: a.song.semester_id,
            role_id_of=lambda a: a.role_id,
        )
        backup_total, backup_orphans_by_semester = self._orphans_by_semester(
            Backup.objects.select_related('rehearsal_song__song', 'rehearsal_song__rehearsal'),
            song_id_of=lambda b: b.rehearsal_song.song_id,
            semester_id_of=lambda b: b.rehearsal_song.rehearsal.semester_id,
            role_id_of=lambda b: b.role_id,
        )

        self.stdout.write(f'SongRoleAssignment: {assignment_total} total, '
                           f'{sum(assignment_orphans_by_semester.values())} orphaned')
        for semester_id, count in sorted(assignment_orphans_by_semester.items()):
            self.stdout.write(f'  semester_id={semester_id}: {count} orphaned SongRoleAssignment row(s)')

        self.stdout.write(f'Backup: {backup_total} total, {sum(backup_orphans_by_semester.values())} orphaned')
        for semester_id, count in sorted(backup_orphans_by_semester.items()):
            self.stdout.write(f'  semester_id={semester_id}: {count} orphaned Backup row(s)')

        if not assignment_orphans_by_semester and not backup_orphans_by_semester:
            self.stdout.write(self.style.SUCCESS('No orphaned rows found in either model.'))
        else:
            self.stdout.write(self.style.WARNING(
                'Orphaned rows found — see the semester_id(s) above. Inspect those Semesters '
                '(by id, in the Django admin) before deciding whether to delete or backfill them.'
            ))

    @staticmethod
    def _orphans_by_semester(queryset, *, song_id_of, semester_id_of, role_id_of):
        """Return (total row count, {semester_id: orphan count}) for `queryset` against the shared Requirement gate."""
        total = 0
        orphans_by_semester: dict[int, int] = {}
        for obj in queryset:
            total += 1
            if not song_role_requirement_exists(song_id_of(obj), role_id_of(obj)):
                semester_id = semester_id_of(obj)
                orphans_by_semester[semester_id] = orphans_by_semester.get(semester_id, 0) + 1
        return total, orphans_by_semester
