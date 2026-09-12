"""preview_rehearsal_backups(): Fallout tiering computed by running the real apply and rolling it back (issue #212, ADR 0008, ADR 0019).

Every case that staged a `SongRoleAssignment` removal or add moved to
`test_preview_song_cast_edits.py` when ADR-0019 moved casting off this
surface. The loud/quiet tiers still *read* the standing cast — a Backup is
only judged against who it stands beside — so those assertions stay, now
set up with `SongRoleAssignmentFactory` rather than by buffering an edit.
"""

from datetime import time, timedelta

from django.db import transaction
from django.test import TestCase

from scheduling.factories import (
    BackupFactory,
    ConflictFactory,
    ConflictWindowFactory,
    MembershipFactory,
    PersonRoleFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import Backup, Conflict
from scheduling.services import (
    AssignmentEditBuffer,
    apply_rehearsal_backups,
    preview_rehearsal_backups,
)


class PreviewRehearsalBackupsTests(TestCase):
    def setUp(self):
        """Build a Semester with a future Rehearsal holding one Song/Role slot."""
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False, start_time=time(18, 0))
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory(name='Singer')
        SongRoleRequirementFactory(song=self.song, role=self.role, count=1)
        self.rehearsal_song = RehearsalSongFactory(
            rehearsal=self.rehearsal, song=self.song, order=1, slot_count=1,
        )

    def _buffer(self, removed_backup_ids=(), added_backup_entries=(), semester=None, updated_at=None):
        """Build a Backup-only AssignmentEditBuffer against self.semester unless overridden."""
        semester = semester or self.semester
        return AssignmentEditBuffer(
            semester_id=semester.pk,
            semester_updated_at=updated_at if updated_at is not None else semester.updated_at,
            removed_backup_ids=frozenset(removed_backup_ids),
            added_backup_entries=frozenset(added_backup_entries),
        )

    def _preview(self, buffer):
        """Call preview_rehearsal_backups() inside a transaction the test itself rolls back, per its docstring's requirement."""
        with transaction.atomic():
            fallout = preview_rehearsal_backups(buffer, rehearsal=self.rehearsal, viewing_semester=self.semester)
            transaction.set_rollback(True)
        return fallout

    def test_writes_nothing(self):
        """A preview of a Backup add leaves every row count and the Semester stamp untouched."""
        membership = MembershipFactory(semester=self.semester)
        backup_count_before = Backup.objects.count()
        stamp_before = self.semester.updated_at

        self._preview(self._buffer(
            added_backup_entries=[(self.rehearsal_song.pk, self.role.pk, membership.person.pk, None)],
        ))

        self.assertEqual(Backup.objects.count(), backup_count_before)
        self.semester.refresh_from_db()
        self.assertEqual(self.semester.updated_at, stamp_before)

    def test_full_conflict_on_an_assigned_person_is_loud(self):
        """A full Conflict on a Person already cast at this Rehearsal is reported in the loud tier."""
        membership = MembershipFactory(semester=self.semester)
        ConflictFactory(person=membership.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)
        SongRoleAssignmentFactory(song=self.song, role=self.role, person=membership.person)

        fallout = self._preview(self._buffer())

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(any(membership.person.name in line for line in fallout.loud))

    def test_conflict_window_overlapping_the_slot_is_loud(self):
        """A partial Conflict Window overlapping the Song's RehearsalSong slot is reported in the loud tier."""
        membership = MembershipFactory(semester=self.semester)
        conflict = ConflictFactory(person=membership.person, rehearsal=self.rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(
            conflict=conflict,
            unavailable_start=self.rehearsal_song.start_time,
            unavailable_end=self.rehearsal_song.end_time,
        )
        SongRoleAssignmentFactory(song=self.song, role=self.role, person=membership.person)

        fallout = self._preview(self._buffer())

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(any(membership.person.name in line for line in fallout.loud))

    def test_a_non_overlapping_conflict_window_is_silent(self):
        """A partial Conflict Window entirely outside the Song's slot raises no loud line."""
        membership = MembershipFactory(semester=self.semester)
        conflict = ConflictFactory(person=membership.person, rehearsal=self.rehearsal, type=Conflict.PARTIAL)
        assert self.rehearsal_song.end_time < self.rehearsal.end_time
        ConflictWindowFactory(
            conflict=conflict,
            unavailable_start=self.rehearsal_song.end_time,
            unavailable_end=self.rehearsal.end_time,
        )
        SongRoleAssignmentFactory(song=self.song, role=self.role, person=membership.person)

        fallout = self._preview(self._buffer())

        self.assertEqual(fallout.loud, [])

    def test_full_conflict_on_a_buffered_backup_is_loud(self):
        """A full Conflict on a Person the Buffer is adding as a Backup is loud, computed post-apply."""
        membership = MembershipFactory(semester=self.semester)
        ConflictFactory(person=membership.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)

        fallout = self._preview(self._buffer(
            added_backup_entries=[(self.rehearsal_song.pk, self.role.pk, membership.person.pk, None)],
        ))

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(any(membership.person.name in line for line in fallout.loud))

    def test_a_person_with_both_a_standing_assignment_and_a_backup_on_the_same_slot_is_warned_only_once(self):
        """A full-Conflict Person holding both a standing assignment and a Backup for the same slot gets one loud line."""
        membership = MembershipFactory(semester=self.semester)
        ConflictFactory(person=membership.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)
        SongRoleAssignmentFactory(song=self.song, role=self.role, person=membership.person)
        other_role = RoleFactory(name='Backup Singer')
        SongRoleRequirementFactory(song=self.song, role=other_role, count=1)
        BackupFactory(rehearsal_song=self.rehearsal_song, role=other_role, person=membership.person)

        fallout = self._preview(self._buffer())

        self.assertEqual(sum(membership.person.name in line for line in fallout.loud), 1)

    def test_unfilled_role_requirement_is_quiet(self):
        """A Song whose Role Requirement nobody fills is reported in the quiet tier."""
        fallout = self._preview(self._buffer())

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(any('unfilled' in line for line in fallout.quiet))

    def test_role_mismatch_is_quiet(self):
        """A standing assignment on a Person who hasn't declared the Role is reported in the quiet tier."""
        membership = MembershipFactory(semester=self.semester)
        SongRoleAssignmentFactory(song=self.song, role=self.role, person=membership.person)

        fallout = self._preview(self._buffer())

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(any("doesn't match" in line for line in fallout.quiet))

    def test_matched_role_raises_no_mismatch_line(self):
        """A Person who has declared the cell's Role as a standing PersonRole raises no mismatch line."""
        membership = MembershipFactory(semester=self.semester)
        PersonRoleFactory(person=membership.person, role=self.role)
        SongRoleAssignmentFactory(song=self.song, role=self.role, person=membership.person)

        fallout = self._preview(self._buffer())

        self.assertFalse(any("doesn't match" in line for line in fallout.quiet))

    def test_fallout_never_blocks_the_save(self):
        """Fallout is reported, and the real save (outside a Preview) still completes and writes the Backup."""
        membership = MembershipFactory(semester=self.semester)
        ConflictFactory(person=membership.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)
        buffer = self._buffer(
            added_backup_entries=[(self.rehearsal_song.pk, self.role.pk, membership.person.pk, None)],
        )

        fallout = self._preview(buffer)
        self.assertTrue(fallout.loud or fallout.quiet)

        apply_rehearsal_backups(buffer, viewing_semester=self.semester, rehearsal=self.rehearsal)

        self.assertTrue(
            Backup.objects.filter(
                rehearsal_song=self.rehearsal_song, role=self.role, person=membership.person,
            ).exists()
        )

    def test_wrong_semester_is_blocked_with_no_fallout(self):
        """A Buffer naming a Semester other than the one being viewed is blocked, with no Fallout computed."""
        other_semester = SemesterFactory(draft=True)

        fallout = self._preview(self._buffer(semester=other_semester))

        self.assertTrue(fallout.is_blocked)
        self.assertEqual(fallout.loud, [])
        self.assertEqual(fallout.quiet, [])

    def test_added_backup_for_a_role_with_no_requirement_is_blocked(self):
        """An added Backup naming a (song, role) pair with no SongRoleRequirement is blocked, with no Fallout (issue #440)."""
        membership = MembershipFactory(semester=self.semester)
        unrequired_role = RoleFactory()

        fallout = self._preview(self._buffer(
            added_backup_entries=[(self.rehearsal_song.pk, unrequired_role.pk, membership.person.pk, None)],
        ))

        self.assertTrue(fallout.is_blocked)
        self.assertEqual(fallout.loud, [])
        self.assertEqual(fallout.quiet, [])

    def test_stale_stamp_is_reported_but_not_blocking(self):
        """A stale Semester stamp is reported via is_stale, and the Preview still runs and computes Fallout."""
        stale_stamp = self.semester.updated_at - timedelta(days=1)

        fallout = self._preview(self._buffer(updated_at=stale_stamp))

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(fallout.is_stale)

    def test_never_reads_conflict_status(self):
        """A rejected full Conflict still raises the loud line -- Conflict.status never gates it."""
        membership = MembershipFactory(semester=self.semester)
        ConflictFactory(
            person=membership.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT,
            status=Conflict.REJECTED,
        )
        SongRoleAssignmentFactory(song=self.song, role=self.role, person=membership.person)

        fallout = self._preview(self._buffer())

        self.assertTrue(any(membership.person.name in line for line in fallout.loud))
