"""preview_song_cast_edits(): Fallout tiering computed by running the real apply and rolling it back (issue #499, ADR 0008, ADR 0019)."""

import json
from datetime import date, time, timedelta

from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from scheduling.factories import (
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
from scheduling.models import Conflict, Song, SongRoleAssignment
from scheduling.services import (
    SongCastEditBuffer,
    apply_song_cast_edits,
    preview_song_cast_edits,
)
from scheduling.tests.api_test_helpers import admin_client, select
from scheduling.tests.preview_helpers import assert_preview_writes_nothing


class PreviewSongCastEditsTests(TestCase):
    def setUp(self):
        """Build a Semester with a future Rehearsal holding one Song/Role slot."""
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(
            semester=self.semester, is_full_setlist=False, start_time=time(18, 0),
            date=timezone.localdate() + timedelta(days=7),
        )
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory(name='Singer')
        SongRoleRequirementFactory(song=self.song, role=self.role, count=1)
        self.rehearsal_song = RehearsalSongFactory(
            rehearsal=self.rehearsal, song=self.song, order=1, slot_count=1,
        )
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

    def _preview(self, buffer):
        """Call preview_song_cast_edits() inside a transaction the test itself rolls back, per its docstring's requirement."""
        with transaction.atomic():
            fallout = preview_song_cast_edits(buffer, viewing_semester=self.semester)
            transaction.set_rollback(True)
        return fallout

    def test_writes_nothing(self):
        """A preview of an add+removal batch leaves every row count and the Song's own stamp untouched."""
        kept = SongRoleAssignmentFactory(song=self.song, role=self.role)
        membership = MembershipFactory(semester=self.semester)
        self.song.refresh_from_db()
        count_before = SongRoleAssignment.objects.count()
        stamp_before = self.song.updated_at

        self._preview(self._buffer(
            removed_assignment_ids=[kept.pk],
            added_entries=[(self.role.pk, membership.person.pk)],
        ))

        self.assertEqual(SongRoleAssignment.objects.count(), count_before)
        self.song.refresh_from_db()
        self.assertEqual(self.song.updated_at, stamp_before)

    def test_pending_adds_name_the_role_and_the_person(self):
        """A staged add is echoed back as a (role_name, person_name) line for the Save popup."""
        membership = MembershipFactory(semester=self.semester)

        fallout = self._preview(self._buffer(added_entries=[(self.role.pk, membership.person.pk)]))

        self.assertEqual(
            [(change.role_name, change.person_name) for change in fallout.pending_adds],
            [(self.role.name, membership.person.name)],
        )

    def test_pending_removals_name_the_role_and_the_person(self):
        """A staged removal is echoed back as a (role_name, person_name) line, read before the row is deleted."""
        assignment = SongRoleAssignmentFactory(song=self.song, role=self.role)
        self.song.refresh_from_db()

        fallout = self._preview(self._buffer(removed_assignment_ids=[assignment.pk]))

        self.assertEqual(
            [(change.role_name, change.person_name) for change in fallout.pending_removals],
            [(self.role.name, assignment.person.name)],
        )

    def test_full_conflict_at_a_future_rehearsal_of_this_song_is_loud(self):
        """Casting someone with a full Conflict at a future Rehearsal of this Song raises a loud line (ADR-0019)."""
        membership = MembershipFactory(semester=self.semester)
        ConflictFactory(person=membership.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)

        fallout = self._preview(self._buffer(added_entries=[(self.role.pk, membership.person.pk)]))

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(any(membership.person.name in line for line in fallout.loud))

    def test_conflict_window_overlapping_the_slot_is_loud(self):
        """A partial Conflict Window overlapping the Song's slot at a future Rehearsal raises a loud line."""
        membership = MembershipFactory(semester=self.semester)
        conflict = ConflictFactory(person=membership.person, rehearsal=self.rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(
            conflict=conflict,
            unavailable_start=self.rehearsal_song.start_time,
            unavailable_end=self.rehearsal_song.end_time,
        )

        fallout = self._preview(self._buffer(added_entries=[(self.role.pk, membership.person.pk)]))

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

        fallout = self._preview(self._buffer(added_entries=[(self.role.pk, membership.person.pk)]))

        self.assertEqual(fallout.loud, [])

    def test_a_loud_line_never_carries_the_conflicts_reason(self):
        """The loud tier names a date, never the Conflict's free text (ADR-0005)."""
        membership = MembershipFactory(semester=self.semester)
        ConflictFactory(
            person=membership.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT,
            reason='a private synthetic reason string',
        )

        fallout = self._preview(self._buffer(added_entries=[(self.role.pk, membership.person.pk)]))

        self.assertFalse(any('private synthetic reason' in line for line in fallout.loud))

    def test_a_past_rehearsal_conflict_is_not_loud(self):
        """Availability at a Rehearsal that already happened can't inform a new cast decision, so it stays silent."""
        past_rehearsal = RehearsalFactory(
            semester=self.semester, is_full_setlist=False, date=date(2020, 1, 6),
        )
        RehearsalSongFactory(rehearsal=past_rehearsal, song=self.song, order=1, slot_count=1)
        membership = MembershipFactory(semester=self.semester)
        ConflictFactory(person=membership.person, rehearsal=past_rehearsal, type=Conflict.FULL_CONFLICT)

        fallout = self._preview(self._buffer(added_entries=[(self.role.pk, membership.person.pk)]))

        self.assertEqual(fallout.loud, [])

    def test_unfilled_role_requirement_is_quiet(self):
        """Removing the sole cast member leaves the Song's Role Requirement unfilled, reported in the quiet tier."""
        assignment = SongRoleAssignmentFactory(song=self.song, role=self.role)
        self.song.refresh_from_db()

        fallout = self._preview(self._buffer(removed_assignment_ids=[assignment.pk]))

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(any('unfilled' in line for line in fallout.quiet))

    def test_role_mismatch_is_quiet(self):
        """Casting a Person who hasn't declared the Role flags a mismatch, reported in the quiet tier (ADR-0002)."""
        membership = MembershipFactory(semester=self.semester)

        fallout = self._preview(self._buffer(added_entries=[(self.role.pk, membership.person.pk)]))

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(any("doesn't match" in line for line in fallout.quiet))

    def test_matched_role_raises_no_mismatch_line(self):
        """A Person who has declared the Role as a standing PersonRole is cast with no mismatch line."""
        membership = MembershipFactory(semester=self.semester)
        PersonRoleFactory(person=membership.person, role=self.role)

        fallout = self._preview(self._buffer(added_entries=[(self.role.pk, membership.person.pk)]))

        self.assertFalse(any("doesn't match" in line for line in fallout.quiet))

    def test_nothing_in_the_fallout_blocks_the_save(self):
        """Every Fallout case is reported, and the real save (outside a Preview) still writes the rows."""
        membership = MembershipFactory(semester=self.semester)
        ConflictFactory(person=membership.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)
        assignment = SongRoleAssignmentFactory(song=self.song, role=self.role)
        self.song.refresh_from_db()
        buffer = self._buffer(
            removed_assignment_ids=[assignment.pk],
            added_entries=[(self.role.pk, membership.person.pk)],
        )

        fallout = self._preview(buffer)
        self.assertTrue(fallout.loud or fallout.quiet)

        apply_song_cast_edits(buffer, viewing_semester=self.semester)

        self.assertFalse(SongRoleAssignment.objects.filter(pk=assignment.pk).exists())
        self.assertTrue(
            SongRoleAssignment.objects.filter(song=self.song, role=self.role, person=membership.person).exists()
        )

    def test_a_song_from_another_semester_is_blocked_with_no_fallout(self):
        """A Buffer naming a Song outside the viewing Semester is blocked, with no Fallout computed."""
        other_semester = SemesterFactory(draft=True)
        other_song = SongFactory(semester=other_semester)

        fallout = self._preview(self._buffer(song=other_song))

        self.assertTrue(fallout.is_blocked)
        self.assertEqual(fallout.loud, [])
        self.assertEqual(fallout.quiet, [])

    def test_added_entry_for_a_role_with_no_requirement_is_blocked(self):
        """An added entry naming a (song, role) pair with no SongRoleRequirement is blocked, with no Fallout (ADR-0015)."""
        membership = MembershipFactory(semester=self.semester)
        unrequired_role = RoleFactory()

        fallout = self._preview(self._buffer(added_entries=[(unrequired_role.pk, membership.person.pk)]))

        self.assertTrue(fallout.is_blocked)
        self.assertEqual(fallout.pending_adds, [])
        self.assertEqual(fallout.loud, [])
        self.assertEqual(fallout.quiet, [])

    def test_stale_stamp_is_reported_but_not_blocking(self):
        """A stale Song stamp is reported via is_stale, and the Preview still runs and computes Fallout."""
        stale_stamp = self.song.updated_at - timedelta(days=1)

        fallout = self._preview(self._buffer(updated_at=stale_stamp))

        self.assertFalse(fallout.is_blocked)
        self.assertTrue(fallout.is_stale)


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewWritesNothingTests(TestCase):
    """The mandatory ADR-0008 writes-nothing assertion for `/api/songs/<pk>/cast/preview/` (issue #499)."""

    def setUp(self):
        """Log an admin in against a Semester whose Song already carries a removable cast member."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()
        SongRoleRequirementFactory(song=self.song, role=self.role, count=1)
        self.removable = SongRoleAssignmentFactory(song=self.song, role=self.role)
        self.membership = MembershipFactory(semester=self.semester)
        self.song.refresh_from_db()

    def test_mixed_buffer_previews_ok_and_writes_nothing(self):
        """A Buffer carrying both a removal and an add previews cleanly and commits nothing at all (ADR 0008)."""
        response = assert_preview_writes_nothing(
            self,
            reverse('api-song-cast-preview', args=[self.song.pk]),
            models_to_check=[SongRoleAssignment, Song],
            semester=self.semester,
            json_body={
                'song_updated_at': self.song.updated_at.isoformat(),
                'removed_assignment_ids': [self.removable.pk],
                'added_entries': [{'role_id': self.role.pk, 'person_id': self.membership.person.pk}],
            },
        )

        self.assertTrue(json.loads(response.content)['ok'])

    def test_the_songs_own_stamp_is_not_bumped_by_a_preview(self):
        """`Semester.updated_at` isn't this surface's anchor, so the Song's own stamp is what must stay put."""
        stamp_before = self.song.updated_at

        assert_preview_writes_nothing(
            self,
            reverse('api-song-cast-preview', args=[self.song.pk]),
            models_to_check=[SongRoleAssignment],
            json_body={
                'song_updated_at': self.song.updated_at.isoformat(),
                'removed_assignment_ids': [self.removable.pk],
                'added_entries': [],
            },
        )

        self.song.refresh_from_db()
        self.assertEqual(self.song.updated_at, stamp_before)
