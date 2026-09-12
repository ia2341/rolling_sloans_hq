"""apply_rehearsal_backups(): the per-Rehearsal Backup write and the two staleness checks (issues #210, #216, ADR-0019).

Every case that exercised a `SongRoleAssignment` removal or add moved to
`test_apply_song_cast_edits.py` when ADR-0019 moved casting off this
surface — what's left here is the Backup half, plus the Buffer-level
checks (wrong Semester, stale stamp) that guard it.
"""

from datetime import timedelta

from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import Backup
from scheduling.services import (
    AssignmentEditBuffer,
    MissingSongRoleRequirementError,
    StaleAssignmentSemesterError,
    WrongViewingSemesterError,
    apply_rehearsal_backups,
)


class ApplyRehearsalBackupsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Semester with one Song on one Rehearsal's Running Order, plus a required Role."""
        cls.semester = SemesterFactory()
        cls.role = RoleFactory()
        cls.song = SongFactory(semester=cls.semester)
        cls.requirement = SongRoleRequirementFactory(song=cls.song, role=cls.role, count=1)
        cls.rehearsal = RehearsalFactory(semester=cls.semester)
        cls.rehearsal_song = RehearsalSongFactory(rehearsal=cls.rehearsal, song=cls.song)

    def _buffer(
        self,
        removed_backup_ids=(),
        added_backup_entries=(),
        backup_covering_for_updates=(),
        semester=None,
        updated_at=None,
    ):
        """Build a Backup-only AssignmentEditBuffer against self.semester unless overridden."""
        semester = semester or self.semester
        return AssignmentEditBuffer(
            semester_id=semester.pk,
            semester_updated_at=updated_at if updated_at is not None else semester.updated_at,
            removed_backup_ids=frozenset(removed_backup_ids),
            added_backup_entries=frozenset(added_backup_entries),
            backup_covering_for_updates=frozenset(backup_covering_for_updates),
        )

    def test_buffer_carries_no_assignment_fields_at_all(self):
        """The Buffer's dataclass no longer defines the cast-editing fields ADR-0019 moved to SongCastEditBuffer."""
        field_names = set(AssignmentEditBuffer.__dataclass_fields__)

        self.assertNotIn('removed_assignment_ids', field_names)
        self.assertNotIn('added_entries', field_names)

    def test_added_backup_entry_for_a_rostered_person_is_created(self):
        """An added Backup entry for a rostered Person on a required Role creates the row (issues #216, #440)."""
        membership = MembershipFactory(semester=self.semester)
        buffer = self._buffer(
            added_backup_entries=[(self.rehearsal_song.pk, self.role.pk, membership.person.pk, None)],
        )

        apply_rehearsal_backups(buffer, viewing_semester=self.semester, rehearsal=self.rehearsal)

        self.assertTrue(
            Backup.objects.filter(
                rehearsal_song=self.rehearsal_song, role=self.role, person=membership.person,
            ).exists()
        )

    def test_added_backup_entry_for_a_role_with_no_requirement_is_rejected_and_writes_nothing(self):
        """An added Backup entry naming a (song, role) pair with no SongRoleRequirement is rejected (issue #440)."""
        membership = MembershipFactory(semester=self.semester)
        unrequired_role = RoleFactory()
        buffer = self._buffer(
            added_backup_entries=[(self.rehearsal_song.pk, unrequired_role.pk, membership.person.pk, None)],
        )

        with self.assertRaises(MissingSongRoleRequirementError):
            apply_rehearsal_backups(buffer, viewing_semester=self.semester, rehearsal=self.rehearsal)

        self.assertFalse(
            Backup.objects.filter(
                rehearsal_song=self.rehearsal_song, role=unrequired_role, person=membership.person,
            ).exists()
        )

    def test_added_backup_entry_for_a_non_rostered_person_is_silently_skipped(self):
        """A tampered add naming a Person with no Membership in the Semester is skipped, not created."""
        outsider = PersonFactory()
        buffer = self._buffer(
            added_backup_entries=[(self.rehearsal_song.pk, self.role.pk, outsider.pk, None)],
        )

        apply_rehearsal_backups(buffer, viewing_semester=self.semester, rehearsal=self.rehearsal)

        self.assertFalse(Backup.objects.filter(person=outsider).exists())

    def test_added_backup_entry_naming_another_rehearsals_slot_is_silently_skipped(self):
        """A hand-crafted POST naming a RehearsalSong from a different Rehearsal touches nothing."""
        other_rehearsal = RehearsalFactory(semester=self.semester)
        other_rehearsal_song = RehearsalSongFactory(rehearsal=other_rehearsal, song=self.song)
        membership = MembershipFactory(semester=self.semester)
        buffer = self._buffer(
            added_backup_entries=[(other_rehearsal_song.pk, self.role.pk, membership.person.pk, None)],
        )

        apply_rehearsal_backups(buffer, viewing_semester=self.semester, rehearsal=self.rehearsal)

        self.assertFalse(Backup.objects.filter(rehearsal_song=other_rehearsal_song).exists())

    def test_covering_for_is_kept_when_it_names_a_standing_assignee(self):
        """A covering_for pick naming a standing assignee on the same cell is recorded (ADR-0007)."""
        standing = SongRoleAssignmentFactory(song=self.song, role=self.role)
        membership = MembershipFactory(semester=self.semester)
        buffer = self._buffer(
            added_backup_entries=[
                (self.rehearsal_song.pk, self.role.pk, membership.person.pk, standing.person_id),
            ],
        )

        apply_rehearsal_backups(buffer, viewing_semester=self.semester, rehearsal=self.rehearsal)

        backup = Backup.objects.get(rehearsal_song=self.rehearsal_song, person=membership.person)
        self.assertEqual(backup.covering_for_id, standing.person_id)

    def test_covering_for_naming_a_non_assignee_is_dropped_to_none(self):
        """A covering_for pick naming someone who isn't a standing assignee is dropped, never failing the save."""
        membership = MembershipFactory(semester=self.semester)
        bystander = MembershipFactory(semester=self.semester)
        buffer = self._buffer(
            added_backup_entries=[
                (self.rehearsal_song.pk, self.role.pk, membership.person.pk, bystander.person.pk),
            ],
        )

        apply_rehearsal_backups(buffer, viewing_semester=self.semester, rehearsal=self.rehearsal)

        backup = Backup.objects.get(rehearsal_song=self.rehearsal_song, person=membership.person)
        self.assertIsNone(backup.covering_for_id)

    def test_removes_the_buffered_backup(self):
        """A Buffer naming an existing Backup's pk deletes that row."""
        membership = MembershipFactory(semester=self.semester)
        backup = Backup.objects.create(
            rehearsal_song=self.rehearsal_song, role=self.role, person=membership.person,
        )
        buffer = self._buffer(removed_backup_ids=[backup.pk])

        apply_rehearsal_backups(buffer, viewing_semester=self.semester, rehearsal=self.rehearsal)

        self.assertFalse(Backup.objects.filter(pk=backup.pk).exists())

    def test_removal_ignores_a_backup_from_another_rehearsal(self):
        """A Backup id belonging to a different Rehearsal is never deleted, even if named in the Buffer."""
        other_rehearsal = RehearsalFactory(semester=self.semester)
        other_rehearsal_song = RehearsalSongFactory(rehearsal=other_rehearsal, song=self.song)
        membership = MembershipFactory(semester=self.semester)
        foreign_backup = Backup.objects.create(
            rehearsal_song=other_rehearsal_song, role=self.role, person=membership.person,
        )
        buffer = self._buffer(removed_backup_ids=[foreign_backup.pk])

        apply_rehearsal_backups(buffer, viewing_semester=self.semester, rehearsal=self.rehearsal)

        self.assertTrue(Backup.objects.filter(pk=foreign_backup.pk).exists())

    def test_covering_for_update_applies_to_a_live_backup(self):
        """A backup_covering_for_updates pair rewrites an already-persisted Backup's covering_for."""
        standing = SongRoleAssignmentFactory(song=self.song, role=self.role)
        membership = MembershipFactory(semester=self.semester)
        backup = Backup.objects.create(
            rehearsal_song=self.rehearsal_song, role=self.role, person=membership.person,
        )
        buffer = self._buffer(backup_covering_for_updates=[(backup.pk, standing.person_id)])

        apply_rehearsal_backups(buffer, viewing_semester=self.semester, rehearsal=self.rehearsal)

        backup.refresh_from_db()
        self.assertEqual(backup.covering_for_id, standing.person_id)

    def test_empty_buffer_writes_nothing_but_still_bumps_the_stamp(self):
        """An empty Buffer is a legal no-op save: nothing is written, but the Semester's stamp still advances."""
        old_updated_at = self.semester.updated_at
        buffer = self._buffer()

        apply_rehearsal_backups(buffer, viewing_semester=self.semester, rehearsal=self.rehearsal)

        self.semester.refresh_from_db()
        self.assertGreater(self.semester.updated_at, old_updated_at)

    def test_stale_semester_stamp_rejects_and_writes_nothing(self):
        """A Buffer stamped against an old Semester.updated_at is rejected before anything is written."""
        membership = MembershipFactory(semester=self.semester)
        stale_stamp = self.semester.updated_at - timedelta(days=1)
        buffer = self._buffer(
            added_backup_entries=[(self.rehearsal_song.pk, self.role.pk, membership.person.pk, None)],
            updated_at=stale_stamp,
        )

        with self.assertRaises(StaleAssignmentSemesterError):
            apply_rehearsal_backups(buffer, viewing_semester=self.semester, rehearsal=self.rehearsal)

        self.assertFalse(Backup.objects.filter(person=membership.person).exists())

    def test_stale_semester_stamp_names_what_happened(self):
        """A stale-stamp rejection carries a message describing the problem, not a bare exception."""
        stale_stamp = self.semester.updated_at - timedelta(days=1)
        buffer = self._buffer(updated_at=stale_stamp)

        with self.assertRaisesMessage(StaleAssignmentSemesterError, 'changed while you were editing'):
            apply_rehearsal_backups(buffer, viewing_semester=self.semester, rehearsal=self.rehearsal)

    def test_two_saves_built_from_the_same_stamp_cannot_both_commit(self):
        """The second of two same-row saves built from one stamp is refused, not silently applied over the first (PR #502 review).

        The sibling of `test_apply_song_cast_edits.py`'s own case, for the
        same class of bug: a read-then-compare staleness check let two
        concurrent Backup saves both read the same `Semester.updated_at`,
        both pass, and both commit. Both Buffers are built before either
        is applied, and the compare-and-swap
        `UPDATE ... WHERE updated_at = <stamp>` is what refuses the
        second one.
        """
        first_person = MembershipFactory(semester=self.semester).person
        second_person = MembershipFactory(semester=self.semester).person
        first = self._buffer(
            added_backup_entries=[(self.rehearsal_song.pk, self.role.pk, first_person.pk, None)],
        )
        second = self._buffer(
            added_backup_entries=[(self.rehearsal_song.pk, self.role.pk, second_person.pk, None)],
        )

        apply_rehearsal_backups(first, viewing_semester=self.semester, rehearsal=self.rehearsal)

        with self.assertRaises(StaleAssignmentSemesterError):
            apply_rehearsal_backups(second, viewing_semester=self.semester, rehearsal=self.rehearsal)

        self.assertTrue(Backup.objects.filter(person=first_person).exists())
        self.assertFalse(Backup.objects.filter(person=second_person).exists())

    def test_wrong_viewing_semester_hard_fails_and_writes_nothing(self):
        """A Buffer whose semester_id doesn't match the session-scoped viewing Semester is rejected before any write."""
        other_semester = SemesterFactory()
        membership = MembershipFactory(semester=self.semester)
        buffer = self._buffer(
            semester=other_semester,
            added_backup_entries=[(self.rehearsal_song.pk, self.role.pk, membership.person.pk, None)],
        )

        with self.assertRaises(WrongViewingSemesterError):
            apply_rehearsal_backups(buffer, viewing_semester=self.semester, rehearsal=self.rehearsal)

        self.assertFalse(Backup.objects.filter(person=membership.person).exists())

    def test_none_viewing_semester_hard_fails(self):
        """A None viewing Semester (nothing published, no admin selection) rejects any Buffer outright."""
        buffer = self._buffer()

        with self.assertRaises(WrongViewingSemesterError):
            apply_rehearsal_backups(buffer, viewing_semester=None, rehearsal=self.rehearsal)

    def test_no_standing_assignment_is_ever_written_or_deleted(self):
        """This surface touches no SongRoleAssignment at all any more (ADR-0019)."""
        standing = SongRoleAssignmentFactory(song=self.song, role=self.role)
        membership = MembershipFactory(semester=self.semester)
        buffer = self._buffer(
            added_backup_entries=[(self.rehearsal_song.pk, self.role.pk, membership.person.pk, None)],
        )

        apply_rehearsal_backups(buffer, viewing_semester=self.semester, rehearsal=self.rehearsal)

        standing.refresh_from_db()
        self.assertEqual(standing.song_id, self.song.pk)
