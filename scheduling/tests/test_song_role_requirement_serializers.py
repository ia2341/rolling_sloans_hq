"""Exact-key-set tests for the Song Role Requirements editor's Fallout/Buffer serializers (issue #339)."""

from django.test import SimpleTestCase
from django.utils import timezone

from scheduling.serializers import (
    serialize_song_role_requirement_buffer,
    serialize_song_role_requirement_fallout,
)
from scheduling.services import (
    SongRoleRequirementAddition,
    SongRoleRequirementBuffer,
    SongRoleRequirementCountChange,
    SongRoleRequirementEntry,
    SongRoleRequirementFallout,
    SongRoleRequirementRemoval,
)


class SerializeSongRoleRequirementFalloutTests(SimpleTestCase):
    """`serialize_song_role_requirement_fallout()` emits exactly its documented key set, named field-by-field."""

    def test_returns_exactly_the_documented_keys(self):
        """A Fallout with one add, one edit and one removal serializes to exactly the documented top-level keys."""
        fallout = SongRoleRequirementFallout(
            is_blocked=False,
            block_message='',
            is_stale=False,
            pending_adds=[SongRoleRequirementAddition(role_name='Keys', count=1)],
            pending_edits=[SongRoleRequirementCountChange(role_name='Lead Vocals', before=2, after=3)],
            pending_removals=[SongRoleRequirementRemoval(role_name='Bass', is_retired_role=False)],
            loud=[],
            quiet=['Lead Vocals now needs 3 and 2 are cast.'],
        )

        payload = serialize_song_role_requirement_fallout(fallout)

        self.assertEqual(
            set(payload.keys()),
            {
                'is_blocked', 'block_message', 'is_stale',
                'pending_adds', 'pending_edits', 'pending_removals', 'loud', 'quiet',
            },
        )
        self.assertEqual(set(payload['pending_adds'][0].keys()), {'role_name', 'count'})
        self.assertEqual(set(payload['pending_edits'][0].keys()), {'role_name', 'before', 'after'})
        self.assertEqual(set(payload['pending_removals'][0].keys()), {'role_name', 'is_retired_role'})


class SerializeSongRoleRequirementBufferTests(SimpleTestCase):
    """`serialize_song_role_requirement_buffer()` (the Preview `values` echo) emits exactly its documented key set."""

    def test_returns_exactly_the_documented_keys(self):
        """A Buffer with one entry serializes to exactly the documented shape."""
        buffer = SongRoleRequirementBuffer(
            song_id=1,
            semester_id=2,
            semester_updated_at=timezone.now(),
            entries=[SongRoleRequirementEntry(role_id=5, count=2)],
        )

        payload = serialize_song_role_requirement_buffer(buffer)

        self.assertEqual(
            set(payload.keys()), {'song_id', 'semester_id', 'semester_updated_at', 'entries'},
        )
        self.assertEqual(set(payload['entries'][0].keys()), {'role_id', 'count'})
