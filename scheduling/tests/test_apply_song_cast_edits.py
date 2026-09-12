"""apply_song_cast_edits(): the Song-level cast write and its Song-scoped staleness check (issue #499, ADR-0019)."""

from datetime import timedelta

from django.test import TestCase

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    PersonRoleFactory,
    RehearsalFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import SongRoleAssignment
from scheduling.services import (
    MissingSongRoleRequirementError,
    SongCastEditBuffer,
    StaleSongCastError,
    WrongViewingSemesterError,
    apply_song_cast_edits,
)


class ApplySongCastEditsTests(TestCase):
    def setUp(self):
        """Build a Semester with one Song, one required Role and one existing SongRoleAssignment."""
        self.semester = SemesterFactory()
        self.role = RoleFactory()
        self.song = SongFactory(semester=self.semester)
        SongRoleRequirementFactory(song=self.song, role=self.role, count=1)
        self.assignment = SongRoleAssignmentFactory(song=self.song, role=self.role)
        self.song.refresh_from_db()

    def _buffer(self, removed_assignment_ids=(), added_entries=(), song=None, updated_at=None):
        """Build a SongCastEditBuffer against self.song unless overridden."""
        song = song or self.song
        return SongCastEditBuffer(
            song_id=song.pk,
            song_updated_at=updated_at if updated_at is not None else song.updated_at,
            removed_assignment_ids=frozenset(removed_assignment_ids),
            added_entries=frozenset(added_entries),
        )

    def test_removes_the_buffered_assignment(self):
        """A Buffer naming an existing SongRoleAssignment's pk deletes that row."""
        apply_song_cast_edits(
            self._buffer(removed_assignment_ids=[self.assignment.pk]), viewing_semester=self.semester,
        )

        self.assertFalse(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())

    def test_removal_is_semester_wide_across_every_rehearsal_and_the_concert(self):
        """Removing a cast member deletes the Song-level row entirely, not a per-rehearsal copy (ADR-0019)."""
        RehearsalFactory(semester=self.semester)
        RehearsalFactory(semester=self.semester)

        apply_song_cast_edits(
            self._buffer(removed_assignment_ids=[self.assignment.pk]), viewing_semester=self.semester,
        )

        self.assertEqual(SongRoleAssignment.objects.filter(song=self.song, role=self.role).count(), 0)

    def test_untouched_assignment_survives(self):
        """An assignment whose pk isn't in the Buffer is left alone."""
        survivor = SongRoleAssignmentFactory(song=self.song, role=self.role)
        self.song.refresh_from_db()

        apply_song_cast_edits(
            self._buffer(removed_assignment_ids=[self.assignment.pk]), viewing_semester=self.semester,
        )

        self.assertTrue(SongRoleAssignment.objects.filter(pk=survivor.pk).exists())

    def test_removal_scoped_to_the_song_ignores_a_foreign_assignment_id(self):
        """An assignment id belonging to a different Song is never deleted, even if named in the Buffer."""
        other_song = SongFactory(semester=self.semester)
        SongRoleRequirementFactory(song=other_song, role=self.role, count=1)
        foreign_assignment = SongRoleAssignmentFactory(song=other_song, role=self.role)

        apply_song_cast_edits(
            self._buffer(removed_assignment_ids=[foreign_assignment.pk]), viewing_semester=self.semester,
        )

        self.assertTrue(SongRoleAssignment.objects.filter(pk=foreign_assignment.pk).exists())

    def test_added_entry_creates_a_new_assignment_for_a_rostered_person(self):
        """An added (role, person) pair for a rostered Person creates a new SongRoleAssignment."""
        membership = MembershipFactory(semester=self.semester)

        apply_song_cast_edits(
            self._buffer(added_entries=[(self.role.pk, membership.person.pk)]), viewing_semester=self.semester,
        )

        self.assertTrue(
            SongRoleAssignment.objects.filter(song=self.song, role=self.role, person=membership.person).exists()
        )

    def test_added_entry_for_a_person_who_has_not_declared_the_role_is_flagged_not_blocked(self):
        """Casting a mismatched Person is allowed with no block; the saved row carries the mismatch flag (ADR-0002)."""
        membership = MembershipFactory(semester=self.semester)

        apply_song_cast_edits(
            self._buffer(added_entries=[(self.role.pk, membership.person.pk)]), viewing_semester=self.semester,
        )

        created = SongRoleAssignment.objects.get(song=self.song, role=self.role, person=membership.person)
        self.assertTrue(created.is_role_mismatch)

    def test_added_entry_for_a_declared_person_is_not_flagged(self):
        """Casting someone who declared the Role saves with is_role_mismatch false (ADR-0002, ADR-0014)."""
        membership = MembershipFactory(semester=self.semester)
        PersonRoleFactory(person=membership.person, role=self.role)

        apply_song_cast_edits(
            self._buffer(added_entries=[(self.role.pk, membership.person.pk)]), viewing_semester=self.semester,
        )

        created = SongRoleAssignment.objects.get(song=self.song, role=self.role, person=membership.person)
        self.assertFalse(created.is_role_mismatch)

    def test_added_entry_for_a_non_rostered_person_is_silently_skipped(self):
        """A tampered add naming a Person with no Membership in the Semester is skipped, not created."""
        outsider = PersonFactory()

        apply_song_cast_edits(
            self._buffer(added_entries=[(self.role.pk, outsider.pk)]), viewing_semester=self.semester,
        )

        self.assertFalse(SongRoleAssignment.objects.filter(song=self.song, person=outsider).exists())

    def test_added_entry_duplicating_an_existing_assignment_is_a_no_op(self):
        """Re-adding an already-cast (role, person) pair is a no-op, not an IntegrityError."""
        apply_song_cast_edits(
            self._buffer(added_entries=[(self.role.pk, self.assignment.person_id)]), viewing_semester=self.semester,
        )

        self.assertEqual(
            SongRoleAssignment.objects.filter(
                song=self.song, role=self.role, person_id=self.assignment.person_id,
            ).count(),
            1,
        )

    def test_added_entry_for_a_role_with_no_requirement_is_rejected_and_writes_nothing(self):
        """An added entry naming a (song, role) pair with no SongRoleRequirement is rejected outright (ADR-0015)."""
        membership = MembershipFactory(semester=self.semester)
        unrequired_role = RoleFactory()

        with self.assertRaises(MissingSongRoleRequirementError):
            apply_song_cast_edits(
                self._buffer(added_entries=[(unrequired_role.pk, membership.person.pk)]),
                viewing_semester=self.semester,
            )

        self.assertFalse(SongRoleAssignment.objects.filter(song=self.song, role=unrequired_role).exists())

    def test_a_rejected_requirement_gate_rolls_back_the_whole_buffer(self):
        """A Requirement-less add rolls back the removal the same Buffer had already applied."""
        membership = MembershipFactory(semester=self.semester)
        unrequired_role = RoleFactory()

        with self.assertRaises(MissingSongRoleRequirementError):
            apply_song_cast_edits(
                self._buffer(
                    removed_assignment_ids=[self.assignment.pk],
                    added_entries=[(unrequired_role.pk, membership.person.pk)],
                ),
                viewing_semester=self.semester,
            )

        self.assertTrue(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())

    def test_mixed_removal_and_add_buffer_produces_exactly_the_intended_rows_in_one_save(self):
        """A Buffer mixing a removal and an add commits both atomically."""
        membership = MembershipFactory(semester=self.semester)

        apply_song_cast_edits(
            self._buffer(
                removed_assignment_ids=[self.assignment.pk],
                added_entries=[(self.role.pk, membership.person.pk)],
            ),
            viewing_semester=self.semester,
        )

        self.assertFalse(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())
        self.assertTrue(
            SongRoleAssignment.objects.filter(song=self.song, role=self.role, person=membership.person).exists()
        )

    def test_a_successful_save_advances_the_songs_own_stamp(self):
        """Saving re-stamps Song.updated_at, so a second Buffer built beforehand is refused."""
        old_updated_at = self.song.updated_at

        apply_song_cast_edits(self._buffer(), viewing_semester=self.semester)

        self.song.refresh_from_db()
        self.assertGreater(self.song.updated_at, old_updated_at)

    def test_a_successful_save_leaves_the_semester_stamp_alone(self):
        """This surface stamps the Song, never the Semester — two admins on two Songs don't collide (ADR-0019)."""
        stamp_before = self.semester.updated_at

        apply_song_cast_edits(
            self._buffer(removed_assignment_ids=[self.assignment.pk]), viewing_semester=self.semester,
        )

        self.semester.refresh_from_db()
        self.assertEqual(self.semester.updated_at, stamp_before)

    def test_stale_song_stamp_rejects_and_writes_nothing(self):
        """A Buffer stamped against an old Song.updated_at is rejected before anything is deleted."""
        stale_stamp = self.song.updated_at - timedelta(days=1)

        with self.assertRaises(StaleSongCastError):
            apply_song_cast_edits(
                self._buffer(removed_assignment_ids=[self.assignment.pk], updated_at=stale_stamp),
                viewing_semester=self.semester,
            )

        self.assertTrue(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())

    def test_stale_song_stamp_names_what_happened(self):
        """A stale-stamp rejection carries a message describing the problem, not a bare exception."""
        stale_stamp = self.song.updated_at - timedelta(days=1)

        with self.assertRaisesMessage(StaleSongCastError, 'changed while you were editing'):
            apply_song_cast_edits(self._buffer(updated_at=stale_stamp), viewing_semester=self.semester)

    def test_two_saves_built_from_the_same_stamp_cannot_both_commit(self):
        """The second of two same-row saves built from one stamp is refused, not silently applied over the first (PR #502 review).

        The regression this guards: a read-then-compare staleness check
        lets two concurrent saves both read the same `Song.updated_at`,
        both pass, and both commit — one admin's edit clobbering the
        other's with neither told to reload. Both Buffers here are built
        *before* either is applied, which is what a real interleaving
        looks like from the database's point of view; the compare-and-swap
        `UPDATE ... WHERE updated_at = <stamp>` is what makes the second
        one's row count zero.
        """
        other_person = PersonFactory()
        MembershipFactory(semester=self.semester, person=other_person)
        PersonRoleFactory(person=other_person, role=self.role)
        first = self._buffer(removed_assignment_ids=[self.assignment.pk])
        second = self._buffer(added_entries=[(self.role.pk, other_person.pk)])

        apply_song_cast_edits(first, viewing_semester=self.semester)

        with self.assertRaises(StaleSongCastError):
            apply_song_cast_edits(second, viewing_semester=self.semester)

        self.assertFalse(
            SongRoleAssignment.objects.filter(song=self.song, person=other_person).exists()
        )

    def test_an_edit_on_another_song_does_not_make_this_buffer_stale(self):
        """Two admins casting two different Songs concurrently don't collide — the stamp is per-Song."""
        other_song = SongFactory(semester=self.semester)
        SongRoleRequirementFactory(song=other_song, role=self.role, count=1)
        other_song.refresh_from_db()
        buffer = self._buffer(removed_assignment_ids=[self.assignment.pk])

        apply_song_cast_edits(
            SongCastEditBuffer(song_id=other_song.pk, song_updated_at=other_song.updated_at),
            viewing_semester=self.semester,
        )
        apply_song_cast_edits(buffer, viewing_semester=self.semester)

        self.assertFalse(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())

    def test_a_song_from_another_semester_hard_fails_and_writes_nothing(self):
        """A Buffer naming a Song outside the viewing Semester is rejected before any write (ADR-0001)."""
        other_semester = SemesterFactory()
        other_song = SongFactory(semester=other_semester)

        with self.assertRaises(WrongViewingSemesterError):
            apply_song_cast_edits(
                SongCastEditBuffer(
                    song_id=other_song.pk,
                    song_updated_at=other_song.updated_at,
                    removed_assignment_ids=frozenset({self.assignment.pk}),
                ),
                viewing_semester=self.semester,
            )

        self.assertTrue(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())

    def test_none_viewing_semester_hard_fails(self):
        """A None viewing Semester (nothing published, no admin selection) rejects any Buffer outright."""
        with self.assertRaises(WrongViewingSemesterError):
            apply_song_cast_edits(self._buffer(), viewing_semester=None)
