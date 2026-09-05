"""`scheduling/serializers.py`'s rehearsal-editor functions: exact key sets (issue #337, ADR 0005)."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from scheduling.factories import (
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.serializers import (
    serialize_rehearsal_deal,
    serialize_rehearsal_edit_buffer,
    serialize_rehearsal_edit_fallout,
    serialize_rehearsal_generation_diff,
    serialize_schedule_editor,
    serialize_shuffle_rows,
)
from scheduling.services import (
    DealtRow,
    GenerationCreateItem,
    GenerationKeepItem,
    GenerationOrphanItem,
    GenerationRetimeItem,
    RehearsalEditBuffer,
    RehearsalEditRow,
    RehearsalGenerationDiff,
    RunningOrderRow,
    deal_running_orders,
    preview_rehearsal_edits,
)

TOMORROW = timezone.localdate() + timedelta(days=1)

EDITOR_KEYS = {'semester_name', 'rehearsals', 'past_rehearsals', 'setlist_songs', 'semester_defaults', 'pattern'}
EDITABLE_REHEARSAL_KEYS = {
    'id', 'date', 'start_time', 'end_time', 'is_full_setlist',
    'setup_grace_minutes', 'teardown_grace_minutes', 'arrival_buffer_minutes', 'departure_buffer_minutes',
    'running_order',
}
RUNNING_ORDER_ROW_KEYS = {
    'rehearsal_song_id', 'song_id', 'song_title', 'slot_count', 'start_time', 'end_time',
    'is_pinned', 'pinned_reasons',
}
PAST_REHEARSAL_KEYS = {'id', 'date', 'start_time', 'end_time', 'is_full_setlist', 'song_count'}
FALLOUT_KEYS = {'is_blocked', 'block_message', 'is_stale', 'loud', 'quiet', 'doomed_recording_groups'}
DOOMED_GROUP_KEYS = {'label', 'recording_count', 'uploader_count'}
BUFFER_ECHO_KEYS = {'semester_id', 'semester_updated_at', 'rows', 'deleted_rehearsal_ids'}
ROW_ECHO_KEYS = {
    'row_key', 'rehearsal_id', 'date', 'start_time', 'end_time', 'is_full_setlist',
    'setup_grace_minutes', 'teardown_grace_minutes', 'arrival_buffer_minutes', 'departure_buffer_minutes',
    'running_order',
}
GENERATION_DIFF_KEYS = {'creates', 'keeps', 'retimes', 'orphans'}
DEAL_KEYS = {'rehearsals'}
DEALT_REHEARSAL_KEYS = {'rehearsal_id', 'rows'}


class ScheduleEditorSerializerTests(TestCase):
    """`serialize_schedule_editor()`'s exact key sets, at every nesting level."""

    def test_top_level_and_nested_keys(self):
        """The editor payload, its editable Rehearsal rows, its Running Order rows, and its past-Rehearsal rows each carry exactly their documented keys."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester, position=1)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW)
        RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        RehearsalFactory(semester=semester, date=timezone.localdate() - timedelta(days=1))

        data = serialize_schedule_editor(semester)

        self.assertEqual(set(data), EDITOR_KEYS)
        self.assertEqual(set(data['rehearsals'][0]), EDITABLE_REHEARSAL_KEYS)
        self.assertEqual(set(data['rehearsals'][0]['running_order'][0]), RUNNING_ORDER_ROW_KEYS)
        self.assertEqual(set(data['past_rehearsals'][0]), PAST_REHEARSAL_KEYS)

    def test_none_semester_returns_the_documented_empty_shape(self):
        """`serialize_schedule_editor(None)` carries exactly the documented top-level keys, all empty/null."""
        data = serialize_schedule_editor(None)

        self.assertEqual(set(data), EDITOR_KEYS)


class RehearsalEditFalloutSerializerTests(TestCase):
    """`serialize_rehearsal_edit_fallout()`'s exact key set, including the doomed-Recording group's absent-key contract."""

    def test_exact_key_set_and_doomed_group_absent_keys(self):
        """The fallout envelope and its doomed-Recording group each carry exactly their documented keys — no Conflict, name, or reason key at all (ADR 0005)."""
        from django.db import transaction

        semester = SemesterFactory()
        song = SongFactory(semester=semester, position=1)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW)
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        RecordingFactory(rehearsal_song=rehearsal_song)
        buffer = RehearsalEditBuffer(
            semester_id=semester.pk, semester_updated_at=semester.updated_at, rows=[],
            deleted_rehearsal_ids=[rehearsal.pk],
        )

        # preview_rehearsal_edits() runs a real write; ADR 0008 requires the
        # caller to wrap it in a transaction and roll it back (mirroring
        # PreviewMixin's own shape) rather than let this test's write survive.
        with transaction.atomic():
            fallout = preview_rehearsal_edits(buffer, viewing_semester=semester)
            data = serialize_rehearsal_edit_fallout(fallout)
            transaction.set_rollback(True)

        self.assertEqual(set(data), FALLOUT_KEYS)
        self.assertEqual(len(data['doomed_recording_groups']), 1)
        self.assertEqual(set(data['doomed_recording_groups'][0]), DOOMED_GROUP_KEYS)


class RehearsalEditBufferEchoSerializerTests(TestCase):
    """`serialize_rehearsal_edit_buffer()`'s exact key set, at both the row and the wrapping level."""

    def test_exact_key_set(self):
        """The echoed buffer and its one row each carry exactly their documented keys."""
        semester = SemesterFactory()
        buffer = RehearsalEditBuffer(
            semester_id=semester.pk, semester_updated_at=semester.updated_at,
            rows=[
                RehearsalEditRow(
                    rehearsal_id=None, date=TOMORROW, start_time=timezone.now().time(), end_time=None,
                    is_full_setlist=False, setup_grace_minutes=None, teardown_grace_minutes=None,
                    arrival_buffer_minutes=None, departure_buffer_minutes=None,
                    running_order=[RunningOrderRow(rehearsal_song_id=None, song_id=1, slot_count=1)],
                ),
            ],
            deleted_rehearsal_ids=[],
        )

        data = serialize_rehearsal_edit_buffer(buffer)

        self.assertEqual(set(data), BUFFER_ECHO_KEYS)
        self.assertEqual(set(data['rows'][0]), ROW_ECHO_KEYS)
        self.assertEqual(set(data['rows'][0]['running_order'][0]), {'rehearsal_song_id', 'song_id', 'slot_count'})


class RehearsalGenerationDiffSerializerTests(TestCase):
    """`serialize_rehearsal_generation_diff()`'s exact key set for all four buckets."""

    def test_exact_key_set_for_every_bucket(self):
        """Each of the four bucket item shapes carries exactly its documented keys."""
        now_time = timezone.now().time()
        diff = RehearsalGenerationDiff(
            creates=[GenerationCreateItem(date=TOMORROW, start_time=now_time, end_time=now_time, is_dress_rehearsal=False)],
            keeps=[GenerationKeepItem(rehearsal_id=1, date=TOMORROW, start_time=now_time, end_time=now_time)],
            retimes=[GenerationRetimeItem(
                rehearsal_id=1, date=TOMORROW, old_start_time=now_time, old_end_time=now_time,
                new_start_time=now_time, new_end_time=now_time, song_count=0, conflict_count=0,
            )],
            orphans=[GenerationOrphanItem(
                rehearsal_id=1, date=TOMORROW, start_time=now_time, end_time=now_time,
                song_count=0, conflict_count=0, recording_count=0,
            )],
        )

        data = serialize_rehearsal_generation_diff(diff)

        self.assertEqual(set(data), GENERATION_DIFF_KEYS)
        self.assertEqual(
            set(data['creates'][0]), {'date', 'start_time', 'end_time', 'is_dress_rehearsal'},
        )
        self.assertEqual(set(data['keeps'][0]), {'rehearsal_id', 'date', 'start_time', 'end_time'})
        self.assertEqual(
            set(data['retimes'][0]),
            {'rehearsal_id', 'date', 'old_start_time', 'old_end_time', 'new_start_time', 'new_end_time', 'song_count', 'conflict_count'},
        )
        self.assertEqual(
            set(data['orphans'][0]),
            {'rehearsal_id', 'date', 'start_time', 'end_time', 'song_count', 'conflict_count', 'recording_count', 'delete_disabled'},
        )


class RehearsalDealSerializerTests(TestCase):
    """`serialize_rehearsal_deal()`/`serialize_shuffle_rows()`'s exact key sets."""

    def test_exact_key_set(self):
        """A real deal's serialized shape carries exactly the documented keys at every level."""
        semester = SemesterFactory()
        SongFactory(semester=semester, position=1)
        RehearsalFactory(semester=semester, date=TOMORROW)

        deal = deal_running_orders(semester)
        data = serialize_rehearsal_deal(deal)

        self.assertEqual(set(data), DEAL_KEYS)
        self.assertEqual(set(data['rehearsals'][0]), DEALT_REHEARSAL_KEYS)
        self.assertEqual(set(data['rehearsals'][0]['rows'][0]), {'rehearsal_song_id', 'song_id', 'slot_count'})

    def test_shuffle_rows_exact_key_set(self):
        """`serialize_shuffle_rows()`'s wrapper and row shapes carry exactly the documented keys."""
        rows = [DealtRow(rehearsal_song_id=1, song_id=2, slot_count=1)]

        data = serialize_shuffle_rows(rows)

        self.assertEqual(set(data), {'rows'})
        self.assertEqual(set(data['rows'][0]), {'rehearsal_song_id', 'song_id', 'slot_count'})
