"""preview_song_role_assignments(): Fallout tiering computed by running the real apply and rolling it back (issue #212, ADR 0008)."""

from datetime import time, timedelta

from django.db import transaction
from django.test import TestCase

from scheduling.factories import (
    BackupFactory,
    ConflictFactory,
    ConflictWindowFactory,
    MembershipFactory,
    MembershipRoleFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import Conflict, SongRoleAssignment
from scheduling.services import (
    AssignmentEditBuffer,
    apply_song_role_assignments,
    preview_song_role_assignments,
)


class PreviewSongRoleAssignmentsTests(TestCase):
    def setUp(self):
        """Build a Semester with a future Rehearsal holding one Song/Role slot."""
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False, start_time=time(18, 0))
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory(name='Singer')
        SongRoleRequirementFactory(song=self.song, role=self.role, count=1)
        RehearsalSongFactory(rehearsal=self.rehearsal, song=self.song, order=1, slot_count=1)

    def _buffer(self, removed_ids=(), added_entries=(), semester=None, updated_at=None):
        """Build an AssignmentEditBuffer against self.semester unless overridden."""
        semester = semester or self.semester
        return AssignmentEditBuffer(
            semester_id=semester.pk,
            semester_updated_at=updated_at if updated_at is not None else semester.updated_at,
            removed_assignment_ids=frozenset(removed_ids),
            added_entries=frozenset(added_entries),
        )

    def _preview(self, buffer):
        """Call preview_song_role_assignments() inside a transaction the test itself rolls back, per its docstring's requirement."""
        with transaction.atomic():
            fallout = preview_song_role_assignments(buffer, rehearsal=self.rehearsal, viewing_semester=self.semester)
            transaction.set_rollback(True)
        return fallout

    def test_writes_nothing(self):
        """A preview of an add+removal batch leaves every row count and the Semester stamp untouched."""
        kept = SongRoleAssignmentFactory(song=self.song, role=self.role)
        membership = MembershipFactory(semester=self.semester)
        assignment_count_before = SongRoleAssignment.objects.count()
        stamp_before = self.semester.updated_at

        self._preview(self._buffer(
            removed_ids=[kept.pk],
            added_entries=[(self.song.pk, self.role.pk, membership.person.pk)],
        ))

        self.assertEqual(SongRoleAssignment.objects.count(), assignment_count_before)
        self.semester.refresh_from_db()
        self.assertEqual(self.semester.updated_at, stamp_before)

    def test_full_conflict_on_an_assigned_person_is_loud(self):
        """A full Conflict on a Person assigned at this Rehearsal is reported in the loud tier."""
        membership = MembershipFactory(semester=self.semester)
        ConflictFactory(person=membership.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)

        fallout = self._preview(self._buffer(
            added_entries=[(self.song.pk, self.role.pk, membership.person.pk)],
        ))

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(any(membership.person.name in line for line in fallout.loud))

    def test_conflict_window_overlapping_the_slot_is_loud(self):
        """A partial Conflict Window overlapping the Song's RehearsalSong slot is reported in the loud tier."""
        membership = MembershipFactory(semester=self.semester)
        conflict = ConflictFactory(person=membership.person, rehearsal=self.rehearsal, type=Conflict.PARTIAL)
        rehearsal_song = self.song.rehearsalsong_set.get(rehearsal=self.rehearsal)
        ConflictWindowFactory(
            conflict=conflict, unavailable_start=rehearsal_song.start_time, unavailable_end=rehearsal_song.end_time,
        )

        fallout = self._preview(self._buffer(
            added_entries=[(self.song.pk, self.role.pk, membership.person.pk)],
        ))

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(any(membership.person.name in line for line in fallout.loud))

    def test_a_non_overlapping_conflict_window_is_silent(self):
        """A partial Conflict Window entirely outside the Song's slot raises no loud line."""
        membership = MembershipFactory(semester=self.semester)
        rehearsal_song = self.song.rehearsalsong_set.get(rehearsal=self.rehearsal)
        conflict = ConflictFactory(person=membership.person, rehearsal=self.rehearsal, type=Conflict.PARTIAL)
        assert rehearsal_song.end_time < self.rehearsal.end_time
        ConflictWindowFactory(
            conflict=conflict, unavailable_start=rehearsal_song.end_time, unavailable_end=self.rehearsal.end_time,
        )

        fallout = self._preview(self._buffer(
            added_entries=[(self.song.pk, self.role.pk, membership.person.pk)],
        ))

        self.assertEqual(fallout.loud, [])

    def test_full_conflict_on_a_backup_is_loud(self):
        """A full Conflict on a Person holding only a Backup (no standing assignment) at this Rehearsal is loud."""
        membership = MembershipFactory(semester=self.semester)
        ConflictFactory(person=membership.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)
        rehearsal_song = self.song.rehearsalsong_set.get(rehearsal=self.rehearsal)
        BackupFactory(rehearsal_song=rehearsal_song, role=self.role, person=membership.person)

        fallout = self._preview(self._buffer())

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(any(membership.person.name in line for line in fallout.loud))

    def test_a_person_with_both_a_standing_assignment_and_a_backup_on_the_same_slot_is_warned_only_once(self):
        """A full-Conflict Person holding both a standing assignment and a Backup for the same slot gets one loud line."""
        membership = MembershipFactory(semester=self.semester)
        ConflictFactory(person=membership.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)
        SongRoleAssignmentFactory(song=self.song, role=self.role, person=membership.person)
        rehearsal_song = self.song.rehearsalsong_set.get(rehearsal=self.rehearsal)
        other_role = RoleFactory(name='Backup Singer')
        BackupFactory(rehearsal_song=rehearsal_song, role=other_role, person=membership.person)

        fallout = self._preview(self._buffer())

        self.assertEqual(sum(membership.person.name in line for line in fallout.loud), 1)

    def test_unfilled_role_requirement_is_quiet(self):
        """Removing the sole assignment leaves the Song's Role Requirement unfilled, reported in the quiet tier."""
        assignment = SongRoleAssignmentFactory(song=self.song, role=self.role)

        fallout = self._preview(self._buffer(removed_ids=[assignment.pk]))

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(any('unfilled' in line for line in fallout.quiet))

    def test_role_mismatch_is_quiet(self):
        """Assigning a Person who hasn't declared the cell's Role flags a mismatch, reported in the quiet tier."""
        membership = MembershipFactory(semester=self.semester)

        fallout = self._preview(self._buffer(
            added_entries=[(self.song.pk, self.role.pk, membership.person.pk)],
        ))

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(any("doesn't match" in line for line in fallout.quiet))

    def test_none_of_the_four_fallout_cases_block_the_save(self):
        """Each Fallout case is reported, and the real save (outside a Preview) still completes and writes the rows."""
        membership = MembershipFactory(semester=self.semester)
        ConflictFactory(person=membership.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)
        assignment = SongRoleAssignmentFactory(song=self.song, role=self.role)
        buffer = self._buffer(
            removed_ids=[assignment.pk],
            added_entries=[(self.song.pk, self.role.pk, membership.person.pk)],
        )

        fallout = self._preview(buffer)
        self.assertTrue(fallout.loud or fallout.quiet)

        apply_song_role_assignments(buffer, viewing_semester=self.semester)

        self.assertFalse(SongRoleAssignment.objects.filter(pk=assignment.pk).exists())
        self.assertTrue(
            SongRoleAssignment.objects.filter(song=self.song, role=self.role, person=membership.person).exists()
        )

    def test_matched_role_raises_no_mismatch_line(self):
        """A Person who has declared the cell's Role is assigned with no mismatch line."""
        membership = MembershipFactory(semester=self.semester)
        MembershipRoleFactory(membership=membership, role=self.role)

        fallout = self._preview(self._buffer(
            added_entries=[(self.song.pk, self.role.pk, membership.person.pk)],
        ))

        self.assertFalse(any("doesn't match" in line for line in fallout.quiet))

    def test_wrong_semester_is_blocked_with_no_fallout(self):
        """A Buffer naming a Semester other than the one being viewed is blocked, with no Fallout computed."""
        other_semester = SemesterFactory(draft=True)

        fallout = self._preview(self._buffer(semester=other_semester))

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

        fallout = self._preview(self._buffer(
            added_entries=[(self.song.pk, self.role.pk, membership.person.pk)],
        ))

        self.assertTrue(any(membership.person.name in line for line in fallout.loud))
