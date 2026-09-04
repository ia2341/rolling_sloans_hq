"""save_rehearsal_pattern() and preview_rehearsal_generation(): the Rehearsal Pattern editor's two seams (issue #222)."""

from datetime import date, time, timedelta

from django.test import TestCase

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
    RehearsalPatternCollisionError,
    RehearsalPatternInput,
    RehearsalTimeInput,
    SkipDateInput,
    preview_rehearsal_generation,
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


TOMORROW = date(2026, 9, 2)  # a Wednesday


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
