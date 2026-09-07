"""save_rehearsal_pattern() and preview_rehearsal_generation(): the Rehearsal Pattern editor's two seams (issue #222)."""

from datetime import date, time, timedelta

from django.test import TestCase
from django.utils import timezone

from scheduling.factories import (
    ConflictFactory,
    RecordingFactory,
    RehearsalFactory,
    RehearsalPatternFactory,
    RehearsalSongFactory,
    RehearsalTimeFactory,
    SemesterFactory,
    SkipDateFactory,
)
from scheduling.models import RehearsalPattern, RehearsalTime, SkipDate
from scheduling.services import (
    PriorRehearsalTimesProposal,
    RehearsalPatternCollisionError,
    RehearsalPatternInput,
    RehearsalTimeInput,
    SkipDateInput,
    preview_rehearsal_generation,
    prior_rehearsal_times_for,
    save_rehearsal_pattern,
)


class SaveRehearsalPatternTests(TestCase):
    def test_creates_a_pattern_with_its_rehearsal_times_and_skip_dates(self):
        """A brand-new Pattern is persisted with every Rehearsal Time and Skip Date row it carried."""
        semester = SemesterFactory()
        pattern_input = RehearsalPatternInput(
            start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
            rehearsal_times=[RehearsalTimeInput(day_of_week=RehearsalTime.WEDNESDAY, start_time=time(19, 0), end_time=time(23, 0))],
            skip_dates=[SkipDateInput(start_date=date(2026, 11, 26), end_date=date(2026, 11, 30))],
        )

        db_pattern = save_rehearsal_pattern(semester, pattern_input)

        self.assertEqual(RehearsalPattern.objects.count(), 1)
        self.assertEqual(db_pattern.start_date, date(2026, 9, 1))
        self.assertEqual(db_pattern.end_date, date(2026, 12, 15))
        rehearsal_time = RehearsalTime.objects.get(pattern=db_pattern)
        self.assertEqual(rehearsal_time.day_of_week, RehearsalTime.WEDNESDAY)
        skip_date = SkipDate.objects.get(pattern=db_pattern)
        self.assertEqual((skip_date.start_date, skip_date.end_date), (date(2026, 11, 26), date(2026, 11, 30)))

    def test_writes_no_rehearsal(self):
        """Saving a Pattern creates no Rehearsal row at all."""
        semester = SemesterFactory()
        pattern_input = RehearsalPatternInput(
            start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
            rehearsal_times=[RehearsalTimeInput(day_of_week=RehearsalTime.WEDNESDAY, start_time=time(19, 0), end_time=time(23, 0))],
        )

        save_rehearsal_pattern(semester, pattern_input)

        self.assertEqual(semester.rehearsal_set.count(), 0)

    def test_replaces_an_existing_pattern_wholesale(self):
        """Re-saving a Semester's Pattern replaces its prior Rehearsal Times and Skip Dates rather than appending to them."""
        semester = SemesterFactory()
        pattern = RehearsalPatternFactory(semester=semester)
        RehearsalTimeFactory(pattern=pattern, day_of_week=RehearsalTime.MONDAY)
        SkipDateFactory(pattern=pattern)

        save_rehearsal_pattern(semester, RehearsalPatternInput(
            start_date=date(2027, 1, 1), end_date=date(2027, 5, 1),
            rehearsal_times=[RehearsalTimeInput(day_of_week=RehearsalTime.FRIDAY, start_time=time(18, 0), end_time=time(20, 0))],
            skip_dates=[],
        ))

        self.assertEqual(RehearsalPattern.objects.count(), 1)
        reloaded = RehearsalPattern.objects.get(pk=pattern.pk)
        self.assertEqual(reloaded.start_date, date(2027, 1, 1))
        self.assertEqual(list(RehearsalTime.objects.filter(pattern=reloaded).values_list('day_of_week', flat=True)), [RehearsalTime.FRIDAY])
        self.assertEqual(SkipDate.objects.filter(pattern=reloaded).count(), 0)

    def test_two_rehearsal_times_on_the_same_day_raise_a_collision_error(self):
        """Two Rehearsal Times sharing a day-of-week are rejected before anything is written."""
        semester = SemesterFactory()
        pattern_input = RehearsalPatternInput(
            start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
            rehearsal_times=[
                RehearsalTimeInput(day_of_week=RehearsalTime.WEDNESDAY, start_time=time(19, 0), end_time=time(21, 0)),
                RehearsalTimeInput(day_of_week=RehearsalTime.WEDNESDAY, start_time=time(21, 0), end_time=time(23, 0)),
            ],
        )

        with self.assertRaises(RehearsalPatternCollisionError):
            save_rehearsal_pattern(semester, pattern_input)

        self.assertEqual(RehearsalPattern.objects.count(), 0)


# A future Wednesday, computed relative to today rather than hardcoded, so preview_rehearsal_generation()'s
# clamp to today (issue #222 review) never eats one of these tests' generated dates out from under it.
_earliest = timezone.localdate() + timedelta(days=1)
TOMORROW = _earliest + timedelta(days=(RehearsalTime.WEDNESDAY - _earliest.weekday()) % 7)


class PreviewRehearsalGenerationTests(TestCase):
    def _pattern(self, **overrides):
        defaults = {
            'start_date': TOMORROW,
            'end_date': TOMORROW + timedelta(days=27),
            'rehearsal_times': [RehearsalTimeInput(day_of_week=RehearsalTime.WEDNESDAY, start_time=time(19, 0), end_time=time(23, 0))],
            'skip_dates': [],
        }
        defaults.update(overrides)
        return RehearsalPatternInput(**defaults)

    def test_first_run_on_an_empty_semester_produces_only_creates(self):
        """A Semester with no Rehearsals generates every matching date as a Create, with no Keep/Re-time/Orphan."""
        semester = SemesterFactory()

        diff = preview_rehearsal_generation(semester, self._pattern())

        wednesdays = [TOMORROW, TOMORROW + timedelta(days=7), TOMORROW + timedelta(days=14), TOMORROW + timedelta(days=21)]
        self.assertEqual([item.date for item in diff.creates], wednesdays)
        self.assertEqual(diff.keeps, [])
        self.assertEqual(diff.retimes, [])
        self.assertEqual(diff.orphans, [])

    def test_a_range_starting_before_today_is_clamped_to_today(self):
        """A Pattern/range whose start_date is in the past never produces a Create, Re-time, or Orphan the Pending Buffer would refuse to save (issue #222 review)."""
        semester = SemesterFactory()
        past_wednesday = TOMORROW - timedelta(days=7)
        stale_rehearsal = RehearsalFactory(semester=semester, date=past_wednesday, start_time=time(18, 0), end_time=time(20, 0))

        diff = preview_rehearsal_generation(semester, self._pattern(start_date=past_wednesday))

        self.assertNotIn(past_wednesday, [item.date for item in diff.creates])
        self.assertNotIn(stale_rehearsal.pk, [item.rehearsal_id for item in diff.retimes])
        self.assertNotIn(stale_rehearsal.pk, [item.rehearsal_id for item in diff.orphans])

    def test_a_range_entirely_before_today_produces_an_empty_diff(self):
        """A range that ends before today, not just starts before it, generates nothing rather than raising."""
        semester = SemesterFactory()

        diff = preview_rehearsal_generation(
            semester, self._pattern(), date_range=(TOMORROW - timedelta(days=14), TOMORROW - timedelta(days=7)),
        )

        self.assertEqual(diff.creates, [])
        self.assertEqual(diff.keeps, [])
        self.assertEqual(diff.retimes, [])
        self.assertEqual(diff.orphans, [])

    def test_writes_nothing_at_all(self):
        """Computing the diff creates no Rehearsal and leaves the Semester's own row untouched."""
        semester = SemesterFactory()
        updated_at_before = semester.updated_at

        preview_rehearsal_generation(semester, self._pattern())

        self.assertEqual(semester.rehearsal_set.count(), 0)
        semester.refresh_from_db()
        self.assertEqual(semester.updated_at, updated_at_before)

    def test_existing_matching_rehearsal_is_a_keep(self):
        """An existing Rehearsal whose date and hours already match the Pattern lands in Keep, not Create."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(19, 0), end_time=time(23, 0))

        diff = preview_rehearsal_generation(semester, self._pattern())

        self.assertEqual([item.rehearsal_id for item in diff.keeps], [rehearsal.pk])
        self.assertEqual([item.date for item in diff.creates], [TOMORROW + timedelta(days=7), TOMORROW + timedelta(days=14), TOMORROW + timedelta(days=21)])

    def test_existing_rehearsal_with_different_hours_is_a_retime_with_blast_radius(self):
        """An existing Rehearsal whose hours differ from the Pattern's is a Re-time, naming its song and conflict counts."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        RehearsalSongFactory(rehearsal=rehearsal)
        ConflictFactory(rehearsal=rehearsal)

        diff = preview_rehearsal_generation(semester, self._pattern())

        self.assertEqual(len(diff.retimes), 1)
        retime = diff.retimes[0]
        self.assertEqual(retime.rehearsal_id, rehearsal.pk)
        self.assertEqual((retime.old_start_time, retime.old_end_time), (time(18, 0), time(20, 0)))
        self.assertEqual((retime.new_start_time, retime.new_end_time), (time(19, 0), time(23, 0)))
        self.assertEqual(retime.song_count, 1)
        self.assertEqual(retime.conflict_count, 1)
        self.assertEqual(diff.keeps, [])

    def test_a_narrowed_range_leaves_an_out_of_range_existing_rehearsal_untouched(self):
        """A generation range narrower than the Pattern's own leaves an existing Rehearsal outside it neither Created nor Orphaned."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=TOMORROW + timedelta(days=21), start_time=time(19, 0), end_time=time(23, 0))

        diff = preview_rehearsal_generation(
            semester, self._pattern(), date_range=(TOMORROW, TOMORROW + timedelta(days=13)),
        )

        self.assertEqual([item.date for item in diff.creates], [TOMORROW, TOMORROW + timedelta(days=7)])
        self.assertEqual(diff.orphans, [])

    def test_an_existing_rehearsal_the_pattern_no_longer_produces_is_an_orphan_with_what_it_would_lose(self):
        """Removing a Rehearsal Time orphans the existing Rehearsals it used to produce, naming what deleting them would lose."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(19, 0), end_time=time(23, 0))
        RehearsalSongFactory(rehearsal=rehearsal)
        ConflictFactory(rehearsal=rehearsal)
        RecordingFactory(rehearsal_song=RehearsalSongFactory(rehearsal=rehearsal))

        diff = preview_rehearsal_generation(semester, self._pattern(rehearsal_times=[
            RehearsalTimeInput(day_of_week=RehearsalTime.THURSDAY, start_time=time(19, 0), end_time=time(23, 0)),
        ]))

        self.assertEqual(len(diff.orphans), 1)
        orphan = diff.orphans[0]
        self.assertEqual(orphan.rehearsal_id, rehearsal.pk)
        self.assertEqual(orphan.song_count, 2)
        self.assertEqual(orphan.conflict_count, 1)
        self.assertEqual(orphan.recording_count, 1)
        self.assertTrue(orphan.delete_disabled)

    def test_orphan_with_no_recordings_has_delete_enabled(self):
        """An Orphan carrying no Recordings has its delete checkbox available."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(19, 0), end_time=time(23, 0))

        diff = preview_rehearsal_generation(semester, self._pattern(rehearsal_times=[
            RehearsalTimeInput(day_of_week=RehearsalTime.THURSDAY, start_time=time(19, 0), end_time=time(23, 0)),
        ]))

        self.assertFalse(diff.orphans[0].delete_disabled)

    def test_skip_date_excludes_a_matching_date(self):
        """A Skip Date covering a would-be generated date removes it from Create entirely."""
        semester = SemesterFactory()

        diff = preview_rehearsal_generation(semester, self._pattern(
            skip_dates=[SkipDateInput(start_date=TOMORROW, end_date=None)],
        ))

        self.assertNotIn(TOMORROW, [item.date for item in diff.creates])

    def test_skip_date_range_excludes_every_date_in_it_inclusive(self):
        """A Skip Date range excludes every date from its start through its end, inclusive."""
        semester = SemesterFactory()

        diff = preview_rehearsal_generation(semester, self._pattern(
            skip_dates=[SkipDateInput(start_date=TOMORROW, end_date=TOMORROW + timedelta(days=7))],
        ))

        self.assertEqual([item.date for item in diff.creates], [TOMORROW + timedelta(days=14), TOMORROW + timedelta(days=21)])

    def test_last_n_generated_dates_are_flagged_dress_rehearsal(self):
        """The last default_dress_rehearsal_count generated dates are created flagged as the Dress Rehearsal."""
        semester = SemesterFactory(default_dress_rehearsal_count=2)

        diff = preview_rehearsal_generation(semester, self._pattern())

        flagged = [item.date for item in diff.creates if item.is_dress_rehearsal]
        self.assertEqual(flagged, [TOMORROW + timedelta(days=14), TOMORROW + timedelta(days=21)])

    def test_a_kept_or_retimed_date_within_the_dress_tail_is_never_flagged(self):
        """An existing Rehearsal within the tail N dates keeps its own Dress flag untouched -- a re-run never migrates it."""
        semester = SemesterFactory(default_dress_rehearsal_count=1)
        RehearsalFactory(semester=semester, date=TOMORROW + timedelta(days=21), start_time=time(19, 0), end_time=time(23, 0))

        diff = preview_rehearsal_generation(semester, self._pattern())

        self.assertEqual(len(diff.keeps), 1)
        self.assertFalse(hasattr(diff.keeps[0], 'is_dress_rehearsal'))
        self.assertEqual([item.is_dress_rehearsal for item in diff.creates], [False, False, False])

    def test_two_colliding_rehearsal_times_raise_before_any_query_runs(self):
        """A Pattern-level day-of-week collision is raised by preview too, not only by save."""
        semester = SemesterFactory()
        pattern_input = self._pattern(rehearsal_times=[
            RehearsalTimeInput(day_of_week=RehearsalTime.WEDNESDAY, start_time=time(19, 0), end_time=time(21, 0)),
            RehearsalTimeInput(day_of_week=RehearsalTime.WEDNESDAY, start_time=time(21, 0), end_time=time(23, 0)),
        ])

        with self.assertRaises(RehearsalPatternCollisionError):
            preview_rehearsal_generation(semester, pattern_input)


class WireFormatDayOfWeekTests(TestCase):
    """`day_of_week` is read as a raw wire-format integer, not only via `RehearsalTime`'s named constants (issue #406).

    Pins the frontend/backend numbering contract itself under test:
    `GenerateDatesModal.tsx`'s `DAY_NAMES` array used to index Sunday=0…
    Saturday=6 for its `<option value={day}>` values, while this function's
    `current.weekday()` (and `RehearsalTime.DAY_OF_WEEK_CHOICES`) is
    Monday=0…Sunday=6 — every previewed date landed one weekday later than
    the one actually picked. `day_of_week=2` here is the raw integer a
    fixed frontend submits for "Wednesday" (`RehearsalTime.WEDNESDAY` is
    also `2`, but this test deliberately never imports that constant, so a
    future accidental renumbering of it couldn't mask a regression here).
    """

    def test_raw_integer_two_generates_real_wednesdays_not_thursdays(self):
        """A Pattern built from the raw integer `2` (not `RehearsalTime.WEDNESDAY`) generates Wednesdays, matching the wire contract's Monday=0 convention."""
        semester = SemesterFactory()
        pattern_input = RehearsalPatternInput(
            start_date=date(2026, 9, 26), end_date=date(2026, 12, 6),
            rehearsal_times=[RehearsalTimeInput(day_of_week=2, start_time=time(19, 0), end_time=time(21, 0))],
            skip_dates=[],
        )

        diff = preview_rehearsal_generation(semester, pattern_input)

        generated_dates = [item.date for item in diff.creates]
        self.assertTrue(generated_dates)
        self.assertEqual(generated_dates[0], date(2026, 9, 30))
        self.assertTrue(all(generated_date.weekday() == 2 for generated_date in generated_dates))


class PriorRehearsalTimesForTests(TestCase):
    """prior_rehearsal_times_for(): the retired Semester Setup wizard's opt-in prefill, at the service layer (issue #341).

    Ported from `test_semester_setup_rehearsals_step.py`, deleted along
    with the rest of the pre-SPA wizard: the underlying ADR-relevant
    guarantee — a prior Semester's Rehearsal Times are offered only as an
    opt-in proposal, never auto-copied, and its date range/Skip Dates are
    never offered at all — outlives the view that used to expose it.
    """

    def test_offers_the_prior_semesters_rehearsal_times_as_an_opt_in_proposal(self):
        """A prior Semester's saved Rehearsal Times come back as a proposal naming that Semester, not written anywhere."""
        prior = SemesterFactory()
        pattern = RehearsalPatternFactory(semester=prior, start_date=date(2026, 1, 1), end_date=date(2026, 4, 1))
        RehearsalTimeFactory(pattern=pattern, day_of_week=RehearsalTime.WEDNESDAY, start_time=time(19, 0), end_time=time(23, 0))
        semester = SemesterFactory()

        proposal = prior_rehearsal_times_for(semester)

        self.assertEqual(proposal.source_semester, prior)
        self.assertEqual(len(proposal.rehearsal_times), 1)
        self.assertEqual(proposal.rehearsal_times[0].day_of_week, RehearsalTime.WEDNESDAY)
        self.assertEqual(RehearsalPattern.objects.filter(semester=semester).count(), 0)

    def test_the_prior_semesters_range_and_skip_dates_are_never_offered(self):
        """The proposal carries only Rehearsal Times — no start/end date and no Skip Date ever comes back."""
        prior = SemesterFactory()
        pattern = RehearsalPatternFactory(semester=prior, start_date=date(2026, 1, 1), end_date=date(2026, 4, 1))
        RehearsalTimeFactory(pattern=pattern, day_of_week=RehearsalTime.WEDNESDAY, start_time=time(19, 0), end_time=time(23, 0))
        SkipDateFactory(pattern=pattern, start_date=date(2026, 2, 1), end_date=date(2026, 2, 7))
        semester = SemesterFactory()

        proposal = prior_rehearsal_times_for(semester)

        self.assertIsInstance(proposal, PriorRehearsalTimesProposal)
        for rehearsal_time_input in proposal.rehearsal_times:
            self.assertFalse(hasattr(rehearsal_time_input, 'start_date'))
            self.assertFalse(hasattr(rehearsal_time_input, 'skip_dates'))

    def test_with_no_prior_semester_the_proposal_is_empty(self):
        """A Semester with nothing before it gets an empty proposal, not an error."""
        semester = SemesterFactory()

        proposal = prior_rehearsal_times_for(semester)

        self.assertEqual(proposal, PriorRehearsalTimesProposal(source_semester=None, rehearsal_times=[]))
