"""Semester setup step 5: capturing the Rehearsal Pattern, then handing off to the Rehearsals surface (issue #203)."""

from datetime import date, time

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import (
    RehearsalPatternFactory,
    RehearsalTimeFactory,
    SemesterFactory,
)
from scheduling.models import Rehearsal, RehearsalPattern, RehearsalTime
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY

PASSWORD = 'a-strong-test-password-123'


def admin_client(test_case):
    """Log a synthetic admin Person into `test_case`'s client and return that Person."""
    person = PersonFactory(password=PASSWORD, is_admin=True)
    test_case.client.login(username=person.email, password=PASSWORD)
    return person


def member_client(test_case):
    """Log a synthetic non-admin Person into `test_case`'s client and return that Person."""
    person = PersonFactory(password=PASSWORD)
    test_case.client.login(username=person.email, password=PASSWORD)
    return person


def rehearsal_time_post_data(rows, prefix='rehearsal-time'):
    """Build formset POST data for `rows`, each a dict of day_of_week/start_time/end_time."""
    data = {
        f'{prefix}-TOTAL_FORMS': str(len(rows)),
        f'{prefix}-INITIAL_FORMS': '0',
        f'{prefix}-MIN_NUM_FORMS': '0',
        f'{prefix}-MAX_NUM_FORMS': '1000',
    }
    for index, row in enumerate(rows):
        data[f'{prefix}-{index}-day_of_week'] = str(row['day_of_week'])
        data[f'{prefix}-{index}-start_time'] = row['start_time']
        data[f'{prefix}-{index}-end_time'] = row['end_time']
    return data


@override_settings(SECURE_SSL_REDIRECT=False)
class RehearsalsStepAuthTests(TestCase):
    def test_anonymous_get_redirects_to_login(self):
        """An anonymous GET to the rehearsals step redirects to login."""
        semester = SemesterFactory(draft=True)

        response = self.client.get(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('identity:login'), response.url)

    def test_member_get_is_forbidden(self):
        """A logged-in non-admin gets a 403 for the rehearsals step."""
        semester = SemesterFactory(draft=True)
        member_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]))

        self.assertEqual(response.status_code, 403)

    def test_anonymous_post_redirects_to_login(self):
        """An anonymous POST to the rehearsals step redirects to login and writes nothing."""
        semester = SemesterFactory(draft=True)

        response = self.client.post(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('identity:login'), response.url)
        self.assertFalse(RehearsalPattern.objects.exists())

    def test_member_post_is_forbidden(self):
        """A logged-in non-admin gets a 403 for a POST to the rehearsals step, and writes nothing."""
        semester = SemesterFactory(draft=True)
        member_client(self)

        response = self.client.post(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(RehearsalPattern.objects.exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class RehearsalsStepGetTests(TestCase):
    def test_switches_the_session_viewing_semester_to_the_draft(self):
        """Visiting the step directly still scopes reads/writes to this draft, not whatever was selected before."""
        other = SemesterFactory()
        semester = SemesterFactory(draft=True)
        admin_client(self)
        session = self.client.session
        session[VIEWING_SEMESTER_SESSION_KEY] = other.pk
        session.save()

        self.client.get(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]))

        self.assertEqual(self.client.session[VIEWING_SEMESTER_SESSION_KEY], semester.pk)

    def test_offers_a_skip_link_to_the_finish_screen(self):
        """The step offers a Skip link to the finish screen, writing nothing."""
        semester = SemesterFactory(draft=True, name='Summer Intensive')
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]))

        self.assertContains(response, reverse('scheduling:manage-semester-setup-finish', args=[semester.pk]))
        self.assertFalse(RehearsalPattern.objects.exists())

    def test_a_parseable_fall_name_soft_prefills_the_date_range(self):
        """A "Fall <year>" name prefills Sep 1-Dec 31 of that year."""
        semester = SemesterFactory(draft=True, name='Fall 2026')
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]))

        self.assertContains(response, '2026-09-01')
        self.assertContains(response, '2026-12-31')

    def test_a_parseable_spring_name_soft_prefills_the_date_range(self):
        """A "Spring <year>" name prefills Feb 1-May 31 of that year."""
        semester = SemesterFactory(draft=True, name='Spring 2027')
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]))

        self.assertContains(response, '2027-02-01')
        self.assertContains(response, '2027-05-31')

    def test_an_unparseable_name_leaves_the_date_range_blank_and_still_renders(self):
        """A name that doesn't parse (e.g. "Summer Intensive") leaves the range blank and blocks nothing."""
        semester = SemesterFactory(draft=True, name='Summer Intensive')
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '2026-09-01')

    def test_offers_the_prior_semesters_rehearsal_times_as_an_opt_in_link(self):
        """A prior Semester with a saved Pattern offers its Rehearsal Times as an opt-in link, not automatically."""
        prior = SemesterFactory(name='Fall 2025')
        prior_pattern = RehearsalPatternFactory(semester=prior)
        RehearsalTimeFactory(pattern=prior_pattern, day_of_week=RehearsalTime.WEDNESDAY, start_time=time(19, 0), end_time=time(23, 0))
        semester = SemesterFactory(draft=True, name='Spring 2026')
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]))

        self.assertContains(response, "Use Fall 2025's Rehearsal Times")
        self.assertNotContains(response, 'value="19:00:00"')

    def test_the_opt_in_link_prefills_the_time_formset_without_saving_anything(self):
        """Following the opt-in link prefills the Rehearsal Time rows, and saves nothing until the form is submitted."""
        prior = SemesterFactory(name='Fall 2025')
        prior_pattern = RehearsalPatternFactory(semester=prior)
        RehearsalTimeFactory(
            pattern=prior_pattern, day_of_week=RehearsalTime.WEDNESDAY, start_time=time(19, 0), end_time=time(23, 0),
        )
        semester = SemesterFactory(draft=True, name='Spring 2026')
        admin_client(self)

        response = self.client.get(
            reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]), {'use_prior_times': '1'},
        )

        self.assertContains(response, '19:00:00')
        self.assertContains(response, '23:00:00')
        self.assertFalse(RehearsalPattern.objects.filter(semester=semester).exists())

    def test_the_prior_semesters_range_and_skip_dates_are_never_offered(self):
        """Only the prior Semester's Rehearsal Times are ever proposed -- never its range or Skip Dates."""
        prior = SemesterFactory(name='Fall 2025')
        prior_pattern = RehearsalPatternFactory(
            semester=prior, start_date=date(2025, 9, 1), end_date=date(2025, 12, 20),
        )
        RehearsalTimeFactory(pattern=prior_pattern)
        semester = SemesterFactory(draft=True, name='Summer Intensive')
        admin_client(self)

        response = self.client.get(
            reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]), {'use_prior_times': '1'},
        )

        self.assertNotContains(response, '2025-09-01')
        self.assertNotContains(response, '2025-12-20')

    def test_with_no_prior_semester_no_opt_in_link_is_offered(self):
        """A Semester with no prior term offers no opt-in prefill link."""
        semester = SemesterFactory(draft=True)
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]))

        self.assertNotContains(response, 'id="use-prior-rehearsal-times"')

    def test_revisiting_after_a_save_shows_this_drafts_own_saved_pattern(self):
        """Revisiting the step after saving shows this draft's own Pattern, not a fresh soft-prefill."""
        semester = SemesterFactory(draft=True, name='Fall 2026')
        pattern = RehearsalPatternFactory(semester=semester, start_date=date(2026, 9, 5), end_date=date(2026, 12, 10))
        RehearsalTimeFactory(pattern=pattern, day_of_week=RehearsalTime.MONDAY, start_time=time(18, 0), end_time=time(21, 0))
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]))

        self.assertContains(response, '2026-09-05')
        self.assertContains(response, '2026-12-10')
        self.assertContains(response, '18:00:00')


@override_settings(SECURE_SSL_REDIRECT=False)
class RehearsalsStepSaveTests(TestCase):
    def test_saving_creates_a_pattern_and_its_rehearsal_times_and_redirects_to_schedule_edit(self):
        """A valid submission calls save_rehearsal_pattern() and redirects straight to the Rehearsals surface."""
        semester = SemesterFactory(draft=True)
        admin_client(self)
        data = {
            'range-start_date': '2026-09-01', 'range-end_date': '2026-12-31',
            **rehearsal_time_post_data([{'day_of_week': 2, 'start_time': '19:00', 'end_time': '23:00'}]),
        }

        response = self.client.post(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]), data)

        self.assertRedirects(response, reverse('scheduling:schedule-edit'))
        pattern = RehearsalPattern.objects.get(semester=semester)
        self.assertEqual(pattern.start_date, date(2026, 9, 1))
        self.assertEqual(pattern.end_date, date(2026, 12, 31))
        rehearsal_time = RehearsalTime.objects.get(pattern=pattern)
        self.assertEqual(rehearsal_time.day_of_week, 2)
        self.assertEqual(rehearsal_time.start_time, time(19, 0))
        self.assertEqual(rehearsal_time.end_time, time(23, 0))

    def test_saving_creates_no_rehearsal_rows(self):
        """After a successful save, zero Rehearsal rows exist -- generation is a separate, later step."""
        semester = SemesterFactory(draft=True)
        admin_client(self)
        data = {
            'range-start_date': '2026-09-01', 'range-end_date': '2026-12-31',
            **rehearsal_time_post_data([{'day_of_week': 2, 'start_time': '19:00', 'end_time': '23:00'}]),
        }

        self.client.post(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]), data)

        self.assertEqual(Rehearsal.objects.filter(semester=semester).count(), 0)

    def test_saving_with_no_rehearsal_times_is_allowed(self):
        """A date range with zero Rehearsal Times is a valid, saveable Pattern (the step is otherwise skippable)."""
        semester = SemesterFactory(draft=True)
        admin_client(self)
        data = {'range-start_date': '2026-09-01', 'range-end_date': '2026-12-31', **rehearsal_time_post_data([])}

        response = self.client.post(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]), data)

        self.assertRedirects(response, reverse('scheduling:schedule-edit'))
        pattern = RehearsalPattern.objects.get(semester=semester)
        self.assertEqual(RehearsalTime.objects.filter(pattern=pattern).count(), 0)

    def test_a_reversed_date_range_is_rejected_with_a_form_error(self):
        """An end date before the start date is rejected without writing anything."""
        semester = SemesterFactory(draft=True)
        admin_client(self)
        data = {
            'range-start_date': '2026-12-31', 'range-end_date': '2026-09-01',
            **rehearsal_time_post_data([]),
        }

        response = self.client.post(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'End date must be on or after start date.')
        self.assertFalse(RehearsalPattern.objects.exists())

    def test_two_rehearsal_times_on_the_same_day_are_rejected_as_a_collision(self):
        """Two Rehearsal Times sharing a day-of-week surface RehearsalPatternCollisionError's message, writing nothing."""
        semester = SemesterFactory(draft=True)
        admin_client(self)
        data = {
            'range-start_date': '2026-09-01', 'range-end_date': '2026-12-31',
            **rehearsal_time_post_data([
                {'day_of_week': 2, 'start_time': '19:00', 'end_time': '23:00'},
                {'day_of_week': 2, 'start_time': '10:00', 'end_time': '12:00'},
            ]),
        }

        response = self.client.post(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'collide')
        self.assertFalse(RehearsalPattern.objects.exists())

    def test_saving_replaces_a_previously_saved_pattern_for_the_same_draft(self):
        """Re-submitting the step for the same draft replaces its Pattern wholesale, not duplicating it."""
        semester = SemesterFactory(draft=True)
        pattern = RehearsalPatternFactory(semester=semester, start_date=date(2026, 9, 1), end_date=date(2026, 12, 1))
        RehearsalTimeFactory(pattern=pattern, day_of_week=RehearsalTime.MONDAY)
        admin_client(self)
        data = {
            'range-start_date': '2026-09-05', 'range-end_date': '2026-12-15',
            **rehearsal_time_post_data([{'day_of_week': 4, 'start_time': '18:00', 'end_time': '21:00'}]),
        }

        self.client.post(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]), data)

        self.assertEqual(RehearsalPattern.objects.filter(semester=semester).count(), 1)
        saved = RehearsalPattern.objects.get(semester=semester)
        self.assertEqual(saved.start_date, date(2026, 9, 5))
        self.assertEqual(list(saved.rehearsal_times.values_list('day_of_week', flat=True)), [4])

    def test_saving_never_touches_the_prior_semesters_pattern(self):
        """Saving this draft's Pattern leaves the prior Semester's own Pattern untouched."""
        prior = SemesterFactory(name='Fall 2025')
        prior_pattern = RehearsalPatternFactory(semester=prior, start_date=date(2025, 9, 1), end_date=date(2025, 12, 1))
        RehearsalTimeFactory(pattern=prior_pattern, day_of_week=RehearsalTime.MONDAY)
        semester = SemesterFactory(draft=True, name='Spring 2026')
        admin_client(self)
        data = {
            'range-start_date': '2026-02-01', 'range-end_date': '2026-05-31',
            **rehearsal_time_post_data([{'day_of_week': 2, 'start_time': '19:00', 'end_time': '23:00'}]),
        }

        self.client.post(reverse('scheduling:manage-semester-setup-rehearsals', args=[semester.pk]), data)

        prior_pattern.refresh_from_db()
        self.assertEqual(prior_pattern.start_date, date(2025, 9, 1))
        self.assertEqual(RehearsalTime.objects.filter(pattern=prior_pattern).count(), 1)
