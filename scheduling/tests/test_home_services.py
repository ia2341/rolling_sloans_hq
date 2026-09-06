"""Service-level tests for Home's two new derivations (issue #332): the Next-rehearsal card and the setup checklist.

Follows `test_services.py`'s per-function-class shape (see `TimelineForTests`
there, which `next_rehearsal_card_for()` composes rather than reimplements).
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    RehearsalFactory,
    RehearsalPatternFactory,
    RehearsalSongFactory,
    RehearsalTimeFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.services import (
    consume_just_created_semester,
    mark_semester_just_created,
    next_rehearsal_card_for,
    setup_checklist_for,
)


class NextRehearsalCardForTests(TestCase):
    """`next_rehearsal_card_for()`: Home's Next-rehearsal card (issue #332)."""

    def test_no_qualifying_rehearsal_returns_none(self):
        """A Person needed at nothing upcoming gets None, not a card with an empty timeline."""
        semester = SemesterFactory()
        person = PersonFactory()

        card = next_rehearsal_card_for(person, semester)

        self.assertIsNone(card)

    def test_card_carries_the_rehearsal_suggestion_and_timeline(self):
        """The card names the qualifying Rehearsal, a non-None attendance suggestion, and a Timeline the viewer is on."""
        semester = SemesterFactory()
        person = PersonFactory()
        role = RoleFactory()
        rehearsal = RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=1))
        song = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1)
        SongRoleAssignmentFactory(song=song, role=role, person=person)

        card = next_rehearsal_card_for(person, semester)

        self.assertEqual(card.rehearsal, rehearsal)
        self.assertIsNotNone(card.attendance_suggestion)
        self.assertEqual(card.timeline.viewer_song_count, 1)

    def test_dress_rehearsal_always_qualifies(self):
        """The Dress Rehearsal qualifies for a Person holding no Role Assignment at all (ADR-0006)."""
        semester = SemesterFactory()
        person = PersonFactory()
        dress = RehearsalFactory(semester=semester, is_full_setlist=True, date=timezone.localdate() + timedelta(days=1))

        card = next_rehearsal_card_for(person, semester)

        self.assertEqual(card.rehearsal, dress)
        self.assertTrue(card.timeline.is_dress_rehearsal)


class _SessionStub(dict):
    """A plain dict stands in for `request.session` — both support `.pop(key, default)`."""


class JustCreatedSemesterTests(TestCase):
    """`mark_semester_just_created()`/`consume_just_created_semester()`: Home's one-off "created" marker (issue #332)."""

    def test_consume_is_true_exactly_once(self):
        """Marking then consuming reports True the first time and False the second — the pop fires only once."""
        semester = SemesterFactory(draft=True)
        session = _SessionStub()
        request = type('Request', (), {'session': session})()
        mark_semester_just_created(request, semester)

        first = consume_just_created_semester(request, semester)
        second = consume_just_created_semester(request, semester)

        self.assertTrue(first)
        self.assertFalse(second)

    def test_consume_is_false_for_a_different_semester(self):
        """The marker only reports True for the exact Semester it was set for."""
        marked = SemesterFactory(draft=True)
        other = SemesterFactory(draft=True)
        session = _SessionStub()
        request = type('Request', (), {'session': session})()
        mark_semester_just_created(request, marked)

        self.assertFalse(consume_just_created_semester(request, other))

    def test_consume_is_false_with_no_marker_set(self):
        """With nothing marked, consuming reports False and leaves the session untouched."""
        semester = SemesterFactory(draft=True)
        request = type('Request', (), {'session': _SessionStub()})()

        self.assertFalse(consume_just_created_semester(request, semester))


class SetupChecklistForTests(TestCase):
    """`setup_checklist_for()`: Home's derived setup checklist for a draft Semester (issue #332)."""

    def test_every_item_empty(self):
        """A brand-new Semester with nothing in it reports every item not done."""
        semester = SemesterFactory(draft=True)

        items = setup_checklist_for(semester)

        self.assertEqual(len(items), 5)
        self.assertTrue(all(not item.is_done for item in items))

    def test_every_item_done(self):
        """A fully set-up Semester reports every item done."""
        semester = SemesterFactory(draft=True)
        MembershipFactory(semester=semester)
        song = SongFactory(semester=semester)
        role = RoleFactory()
        SongRoleAssignmentFactory(song=song, role=role)
        pattern = RehearsalPatternFactory(semester=semester)
        RehearsalTimeFactory(pattern=pattern)
        RehearsalFactory(semester=semester)

        items = setup_checklist_for(semester)

        self.assertTrue(all(item.is_done for item in items))

    def test_pattern_with_no_rehearsal_times_counts_as_not_set(self):
        """A saved Pattern with zero Rehearsal Times is 'not set' — the formset can be submitted empty."""
        semester = SemesterFactory(draft=True)
        RehearsalPatternFactory(semester=semester)

        items = setup_checklist_for(semester)

        pattern_item = next(item for item in items if item.key == 'rehearsal_pattern')
        self.assertFalse(pattern_item.is_done)

    def test_rehearsal_without_a_pattern_is_legal_and_counts_as_set(self):
        """A hand-added Rehearsal with no saved Pattern still marks 'Rehearsal dates' done — the two facts are independent."""
        semester = SemesterFactory(draft=True)
        RehearsalFactory(semester=semester)

        items = setup_checklist_for(semester)

        dates_item = next(item for item in items if item.key == 'rehearsal_dates')
        pattern_item = next(item for item in items if item.key == 'rehearsal_pattern')
        self.assertTrue(dates_item.is_done)
        self.assertFalse(pattern_item.is_done)

    def test_waiting_on_present_only_on_items_four_and_five(self):
        """`waiting_on` is set on 'rehearsal_dates' and 'casting', and None on the other three."""
        semester = SemesterFactory(draft=True)

        items = setup_checklist_for(semester)

        by_key = {item.key: item for item in items}
        self.assertIsNone(by_key['roster'].waiting_on)
        self.assertIsNone(by_key['setlist'].waiting_on)
        self.assertIsNone(by_key['rehearsal_pattern'].waiting_on)
        self.assertIsNotNone(by_key['rehearsal_dates'].waiting_on)
        self.assertIsNotNone(by_key['casting'].waiting_on)

    def test_each_item_individually_flips_to_done(self):
        """Flipping just the Roster's emptiness leaves the other four items' `is_done` unaffected."""
        semester = SemesterFactory(draft=True)
        MembershipFactory(semester=semester)

        items = setup_checklist_for(semester)

        by_key = {item.key: item for item in items}
        self.assertTrue(by_key['roster'].is_done)
        self.assertFalse(by_key['setlist'].is_done)
        self.assertFalse(by_key['rehearsal_pattern'].is_done)
        self.assertFalse(by_key['rehearsal_dates'].is_done)
        self.assertFalse(by_key['casting'].is_done)
