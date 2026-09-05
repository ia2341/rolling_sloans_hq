"""Exact-key-set tests for the new Setlist edit Fallout/Buffer serializers (issue #334)."""

from django.test import SimpleTestCase

from scheduling.serializers import (
    serialize_setlist_edit_buffer,
    serialize_setlist_edit_fallout,
)
from scheduling.services import (
    SetlistEditBuffer,
    SetlistEditFallout,
    SetlistEditRow,
    SetlistSongDeletion,
)


class SerializeSetlistEditFalloutTests(SimpleTestCase):
    """`serialize_setlist_edit_fallout()` emits exactly its documented key set, named field-by-field."""

    def test_returns_exactly_the_documented_keys(self):
        """A Fallout with one pending deletion serializes to exactly the documented top-level keys."""
        fallout = SetlistEditFallout(
            is_blocked=False,
            block_message='',
            is_stale=False,
            pending_adds=['New Song'],
            pending_edits=['Old → New'],
            reordered=True,
            pending_deletions=[
                SetlistSongDeletion(title='Doomed', recording_count=2, uploader_count=1, running_order_count=3),
            ],
            loud=['Deleting Doomed destroys 2 recordings.'],
            quiet=['Reordering the setlist changes concert position only.'],
        )

        payload = serialize_setlist_edit_fallout(fallout)

        self.assertEqual(
            set(payload.keys()),
            {
                'is_blocked', 'block_message', 'is_stale', 'pending_adds', 'pending_edits',
                'reordered', 'pending_deletions', 'loud', 'quiet',
            },
        )
        self.assertEqual(
            set(payload['pending_deletions'][0].keys()),
            {'title', 'recording_count', 'uploader_count', 'running_order_count'},
        )


class SerializeSetlistEditBufferTests(SimpleTestCase):
    """`serialize_setlist_edit_buffer()` (the Preview `values` echo) emits exactly its documented key set."""

    def test_returns_exactly_the_documented_keys(self):
        """A Buffer with one existing-row edit and one new row serializes to exactly the documented shape."""
        from datetime import timedelta

        from django.utils import timezone

        buffer = SetlistEditBuffer(
            semester_id=1,
            semester_updated_at=timezone.now(),
            rows=[
                SetlistEditRow(song_id=7, title='T', artist='A', length=timedelta(minutes=3, seconds=30), notes='n'),
                SetlistEditRow(song_id=None, title='New', artist='B', length=timedelta(minutes=2), notes=''),
            ],
            deleted_song_ids=frozenset({9, 10}),
        )

        payload = serialize_setlist_edit_buffer(buffer)

        self.assertEqual(set(payload.keys()), {'semester_id', 'semester_updated_at', 'rows', 'deleted_song_ids'})
        self.assertEqual(
            set(payload['rows'][0].keys()),
            {'row_key', 'song_id', 'title', 'artist', 'length', 'notes'},
        )
        self.assertEqual(payload['deleted_song_ids'], [9, 10])
        self.assertEqual(payload['rows'][0]['length'], '3:30')
        self.assertEqual(payload['rows'][1]['song_id'], None)
