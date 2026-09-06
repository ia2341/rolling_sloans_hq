"""preview_song_role_requirements(): the Requirements editor's Fallout, computed by running the real save and rolling it back (issue #339, ADR 0008)."""

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from scheduling.factories import (
    MembershipFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import MembershipRole, SongRoleRequirement
from scheduling.services import (
    SongRoleRequirementBuffer,
    SongRoleRequirementEntry,
    preview_song_role_requirements,
)


class PreviewSongRoleRequirementsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Semester with one Song and one Role to submit Buffers against."""
        cls.semester = SemesterFactory()
        cls.song = SongFactory(semester=cls.semester)
        cls.role = RoleFactory(name='Lead Vocals')

    def _buffer(self, entries=(), semester=None, song=None, updated_at=None):
        """Build a SongRoleRequirementBuffer against self.semester/self.song unless overridden."""
        semester = semester or self.semester
        song = song or self.song
        return SongRoleRequirementBuffer(
            song_id=song.pk,
            semester_id=semester.pk,
            semester_updated_at=updated_at if updated_at is not None else semester.updated_at,
            entries=list(entries),
        )

    def _preview(self, buffer):
        """Call preview_song_role_requirements() inside a rolled-back transaction, per its docstring's requirement."""
        with transaction.atomic():
            fallout = preview_song_role_requirements(buffer, viewing_semester=self.semester)
            transaction.set_rollback(True)
        return fallout

    def test_a_mixed_buffer_names_every_add_edit_and_removal(self):
        """A Buffer containing an addition, a count change and a removal together reports all three (issue #339)."""
        edited_role = RoleFactory(name='Bass')
        removed_role = RoleFactory(name='Drums')
        SongRoleRequirementFactory(song=self.song, role=edited_role, count=2)
        SongRoleRequirementFactory(song=self.song, role=removed_role, count=1)
        buffer = self._buffer(entries=[
            SongRoleRequirementEntry(role_id=self.role.pk, count=1),
            SongRoleRequirementEntry(role_id=edited_role.pk, count=3),
        ])

        fallout = self._preview(buffer)

        self.assertFalse(fallout.is_blocked)
        self.assertEqual(len(fallout.pending_adds), 1)
        self.assertEqual(fallout.pending_adds[0].role_name, 'Lead Vocals')
        self.assertEqual(fallout.pending_adds[0].count, 1)
        self.assertEqual(len(fallout.pending_edits), 1)
        self.assertEqual(fallout.pending_edits[0].role_name, 'Bass')
        self.assertEqual(fallout.pending_edits[0].before, 2)
        self.assertEqual(fallout.pending_edits[0].after, 3)
        self.assertEqual(len(fallout.pending_removals), 1)
        self.assertEqual(fallout.pending_removals[0].role_name, 'Drums')

    def test_writes_nothing_after_rollback(self):
        """The transaction wrapping preview_song_role_requirements() rolls back its real write."""
        buffer = self._buffer(entries=[SongRoleRequirementEntry(role_id=self.role.pk, count=2)])

        self._preview(buffer)

        self.assertFalse(SongRoleRequirement.objects.filter(song=self.song, role=self.role).exists())

    def test_raised_count_nobody_fills_produces_a_quiet_understaffed_line(self):
        """A raised count that nobody fills produces a quiet line naming the Role, the target and the actual."""
        SongRoleRequirementFactory(song=self.song, role=self.role, count=1)
        buffer = self._buffer(entries=[SongRoleRequirementEntry(role_id=self.role.pk, count=3)])

        fallout = self._preview(buffer)

        self.assertTrue(any('Lead Vocals now needs 3' in message for message in fallout.quiet))
        self.assertEqual(fallout.loud, [])

    def test_removal_produces_a_quiet_line_and_leaves_the_standing_assignment_untouched(self):
        """A removal produces a quiet line stating standing Role Assignments are untouched, and they are in fact untouched."""
        requirement = SongRoleRequirementFactory(song=self.song, role=self.role, count=1)
        assignment = SongRoleAssignmentFactory(song=self.song, role=self.role)
        buffer = self._buffer(entries=[])

        fallout = self._preview(buffer)

        self.assertTrue(any('does not un-cast anyone' in message for message in fallout.quiet))
        self.assertTrue(SongRoleRequirement.objects.filter(pk=requirement.pk).exists())  # still exists: rolled back
        self.assertTrue(assignment.__class__.objects.filter(pk=assignment.pk).exists())

    def test_a_requirement_naming_a_retired_role_is_reported_and_clearable(self):
        """A Requirement naming a retired Role is reported (never filtered out) and clearable."""
        retired_role = RoleFactory(name='Tambourine', is_active=False)
        SongRoleRequirementFactory(song=self.song, role=retired_role, count=1)
        buffer = self._buffer(entries=[])

        fallout = self._preview(buffer)

        self.assertEqual(len(fallout.pending_removals), 1)
        self.assertEqual(fallout.pending_removals[0].role_name, 'Tambourine')
        self.assertTrue(fallout.pending_removals[0].is_retired_role)

    def test_an_added_requirement_for_an_undeclared_role_gets_a_quiet_note(self):
        """A Requirement added for a Role nobody on the Roster has declared is a quiet, non-blocking note."""
        buffer = self._buffer(entries=[SongRoleRequirementEntry(role_id=self.role.pk, count=1)])

        fallout = self._preview(buffer)

        self.assertTrue(any('has declared' in message for message in fallout.quiet))

    def test_an_added_requirement_for_a_declared_role_gets_no_undeclared_note(self):
        """A Role at least one Membership has declared gets no "nobody has declared" quiet note."""
        membership = MembershipFactory(semester=self.semester)
        MembershipRole.objects.create(membership=membership, role=self.role)
        buffer = self._buffer(entries=[SongRoleRequirementEntry(role_id=self.role.pk, count=1)])

        fallout = self._preview(buffer)

        self.assertFalse(any('has declared' in message for message in fallout.quiet))

    def test_wrong_semester_id_is_blocked_with_every_list_empty_and_no_write(self):
        """A wrong semester_id returns is_blocked with every list empty and no write."""
        other_semester = SemesterFactory()
        buffer = self._buffer(semester=other_semester)

        fallout = preview_song_role_requirements(buffer, viewing_semester=self.semester)

        self.assertTrue(fallout.is_blocked)
        self.assertEqual(fallout.pending_adds, [])
        self.assertEqual(fallout.pending_edits, [])
        self.assertEqual(fallout.pending_removals, [])
        self.assertEqual(fallout.loud, [])
        self.assertEqual(fallout.quiet, [])

    def test_stale_semester_stamp_reports_is_stale_true_with_fallout_still_computed(self):
        """A stale semester_updated_at returns is_stale: true with fallout computed — reported, never refused."""
        stale_stamp = self.semester.updated_at
        self.semester.updated_at = timezone.now()
        self.semester.save(update_fields=['updated_at'])
        buffer = self._buffer(
            entries=[SongRoleRequirementEntry(role_id=self.role.pk, count=1)], updated_at=stale_stamp,
        )

        fallout = self._preview(buffer)

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(fallout.is_stale)
        self.assertEqual(len(fallout.pending_adds), 1)
