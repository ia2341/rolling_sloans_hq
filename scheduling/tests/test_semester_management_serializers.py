"""Exact-key-set tests for the new Semester-control serializers (issue #329).

Per ADR 0005, `test_carries_counts_only_no_conflict_data` on each payload
asserts on *absent* keys — no `reason`, `note`, or person-identity field
exists at all, mirroring `test_person_page_visibility.py`'s convention
(#316) rather than merely asserting such values are blank.
"""

from django.test import SimpleTestCase

from scheduling.factories import SemesterFactory
from scheduling.serializers import (
    serialize_semester_defaults_fallout,
    serialize_semester_deletion_summary,
    serialize_semester_management_rows,
    serialize_semester_publish_impact,
)
from scheduling.services import (
    SEMESTER_STATUS_DRAFT,
    SemesterDefaultsFallout,
    SemesterDeletionSummary,
    SemesterManagementRow,
    SemesterPublishImpact,
)

_PRIVACY_FORBIDDEN_KEYS = {'reason', 'note', 'declared_by', 'person', 'person_id', 'person_name', 'email'}


class SerializeSemesterManagementRowsTests(SimpleTestCase):
    """`serialize_semester_management_rows()` emits exactly its documented key set per row."""

    def test_returns_exactly_the_documented_keys(self):
        """One row serializes to exactly the documented top-level keys."""
        semester = SemesterFactory.build(pk=1, name='Fall 2026')
        row = SemesterManagementRow(
            semester=semester, status=SEMESTER_STATUS_DRAFT, is_viewing=True,
            member_count=3, song_count=4, rehearsal_count=5, recording_count=6,
            updated_at=semester.updated_at,
        )

        payload = serialize_semester_management_rows([row])

        self.assertEqual(len(payload), 1)
        self.assertEqual(
            set(payload[0].keys()),
            {
                'id', 'name', 'status', 'is_viewing', 'member_count', 'song_count',
                'rehearsal_count', 'recording_count', 'updated_at',
            },
        )

    def test_carries_counts_only_no_conflict_data(self):
        """No key on the row payload names a Conflict reason, note or person identity (ADR 0005)."""
        semester = SemesterFactory.build(pk=1, name='Fall 2026')
        row = SemesterManagementRow(
            semester=semester, status=SEMESTER_STATUS_DRAFT, is_viewing=False,
            member_count=0, song_count=0, rehearsal_count=0, recording_count=0,
            updated_at=semester.updated_at,
        )

        payload = serialize_semester_management_rows([row])[0]

        self.assertFalse(set(payload.keys()) & _PRIVACY_FORBIDDEN_KEYS)


class SerializeSemesterPublishImpactTests(SimpleTestCase):
    """`serialize_semester_publish_impact()` emits exactly its documented key set."""

    def test_returns_exactly_the_documented_keys_with_an_incumbent(self):
        """An impact naming a real incumbent serializes to exactly the documented shape."""
        target = SemesterFactory.build(pk=1, name='Fall 2026')
        incumbent = SemesterFactory.build(pk=2, name='Spring 2026')
        impact = SemesterPublishImpact(
            target_semester=target, is_already_live=False, incumbent=incumbent,
            incumbent_rehearsal_count=3, incumbent_song_count=4,
            has_no_setlist=True, has_no_rehearsals=True,
        )

        payload = serialize_semester_publish_impact(impact)

        self.assertEqual(
            set(payload.keys()),
            {
                'target_semester_id', 'target_semester_name', 'is_already_live', 'incumbent',
                'incumbent_rehearsal_count', 'incumbent_song_count', 'has_no_setlist', 'has_no_rehearsals',
            },
        )
        self.assertEqual(set(payload['incumbent'].keys()), {'id', 'name'})

    def test_incumbent_is_null_when_there_is_none(self):
        """An already-live target's incumbent serializes to `None`, not a zeroed object."""
        target = SemesterFactory.build(pk=1, name='Fall 2026')
        impact = SemesterPublishImpact(
            target_semester=target, is_already_live=True, incumbent=None,
            incumbent_rehearsal_count=0, incumbent_song_count=0,
            has_no_setlist=False, has_no_rehearsals=False,
        )

        payload = serialize_semester_publish_impact(impact)

        self.assertIsNone(payload['incumbent'])

    def test_carries_counts_only_no_conflict_data(self):
        """No key on the impact payload names a Conflict reason, note or person identity (ADR 0005)."""
        target = SemesterFactory.build(pk=1, name='Fall 2026')
        impact = SemesterPublishImpact(
            target_semester=target, is_already_live=True, incumbent=None,
            incumbent_rehearsal_count=0, incumbent_song_count=0,
            has_no_setlist=False, has_no_rehearsals=False,
        )

        payload = serialize_semester_publish_impact(impact)

        self.assertFalse(set(payload.keys()) & _PRIVACY_FORBIDDEN_KEYS)


class SerializeSemesterDeletionSummaryTests(SimpleTestCase):
    """`serialize_semester_deletion_summary()` emits exactly its documented key set."""

    def test_returns_exactly_the_documented_keys(self):
        """A summary serializes to exactly its four counts, nothing more."""
        summary = SemesterDeletionSummary(member_count=1, song_count=2, rehearsal_count=3, recording_count=4)

        payload = serialize_semester_deletion_summary(summary)

        self.assertEqual(set(payload.keys()), {'member_count', 'song_count', 'rehearsal_count', 'recording_count'})
        self.assertFalse(set(payload.keys()) & _PRIVACY_FORBIDDEN_KEYS)


class SerializeSemesterDefaultsFalloutTests(SimpleTestCase):
    """`serialize_semester_defaults_fallout()` emits exactly its documented key set."""

    def test_returns_exactly_the_documented_keys(self):
        """A Fallout with loud/quiet lines serializes to exactly the documented top-level keys."""
        fallout = SemesterDefaultsFallout(
            is_blocked=False, block_message='', is_stale=False, changed_rehearsal_count=2,
            loud=['1 recording on Song A was made against 7:00pm-7:07pm, now 7:00pm-7:10pm.'],
            quiet=["A declared Conflict Window no longer overlaps 2026-01-01's rehearsal time after this reapply."],
        )

        payload = serialize_semester_defaults_fallout(fallout)

        self.assertEqual(
            set(payload.keys()),
            {'is_blocked', 'block_message', 'is_stale', 'changed_rehearsal_count', 'loud', 'quiet'},
        )

    def test_a_blocked_fallout_carries_no_conflict_identifying_data(self):
        """A blocked Fallout's block_message/loud/quiet keys exist, but no key names a Conflict reason or person."""
        fallout = SemesterDefaultsFallout(
            is_blocked=True, block_message='This Semester no longer exists.', is_stale=False,
            changed_rehearsal_count=0, loud=[], quiet=[],
        )

        payload = serialize_semester_defaults_fallout(fallout)

        self.assertFalse(set(payload.keys()) & _PRIVACY_FORBIDDEN_KEYS)
