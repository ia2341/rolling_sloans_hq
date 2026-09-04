"""`/schedule/edit/`: the admin-only "Edit rehearsals" mode — the toggle, the buffer, and the past-date lock (issue #219)."""

from datetime import time, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import RehearsalFactory, SemesterFactory
from scheduling.models import Rehearsal
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY

PASSWORD = 'a-strong-test-password-123'
TOMORROW = timezone.localdate() + timedelta(days=1)
NEXT_WEEK = timezone.localdate() + timedelta(days=7)
YESTERDAY = timezone.localdate() - timedelta(days=1)


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


def select(test_case, semester):
    """Record `semester` as the client's session selection, mirroring `services.set_viewing_semester`."""
    session = test_case.client.session
    session[VIEWING_SEMESTER_SESSION_KEY] = semester.pk
    session.save()


def formset_data(rehearsals, edits=None, extra_rows=(), semester_id=None, stamp=None):
    """Build POST data for `RehearsalEditFormSet`, one row per existing Rehearsal plus any `extra_rows`.

    Every existing row starts from the Rehearsal's current values so a
    test only has to spell out the fields it means to change, keyed by
    pk in `edits`. `extra_rows` are plain dicts appended past
    `INITIAL_FORMS`, for a brand-new row. `semester_id`/`stamp` default to
    the first Rehearsal's Semester; both are required even with zero
    Rehearsals, so a caller building a from-empty Buffer must pass them.
    """
    edits = edits or {}
    data = {
        'rehearsal-TOTAL_FORMS': str(len(rehearsals) + len(extra_rows)),
        'rehearsal-INITIAL_FORMS': str(len(rehearsals)),
        'rehearsal-MIN_NUM_FORMS': '0',
        'rehearsal-MAX_NUM_FORMS': '1000',
    }
    for index, rehearsal in enumerate(rehearsals):
        row = {
            'date': rehearsal.date.isoformat(),
            'start_time': rehearsal.start_time.isoformat(),
            'end_time': rehearsal.end_time.isoformat() if rehearsal.end_time else '',
            'is_full_setlist': rehearsal.is_full_setlist,
            'setup_grace_minutes': rehearsal.setup_grace_minutes,
            'teardown_grace_minutes': rehearsal.teardown_grace_minutes,
            'arrival_buffer_minutes': rehearsal.arrival_buffer_minutes,
            'departure_buffer_minutes': rehearsal.departure_buffer_minutes,
        }
        row.update(edits.get(rehearsal.pk, {}))
        data[f'rehearsal-{index}-id'] = str(rehearsal.pk)
        for field, value in row.items():
            if value is None:
                continue
            data[f'rehearsal-{index}-{field}'] = value
    for offset, extra_row in enumerate(extra_rows):
        index = len(rehearsals) + offset
        for field, value in extra_row.items():
            if value is None:
                continue
            data[f'rehearsal-{index}-{field}'] = value
    if semester_id is None and rehearsals:
        semester_id = rehearsals[0].semester.pk
    if stamp is None and rehearsals:
        stamp = rehearsals[0].semester.updated_at.isoformat()
    data['schedule_semester_id'] = str(semester_id) if semester_id is not None else ''
    data['schedule_semester_updated_at'] = stamp or ''
    return data


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleEditButtonTests(TestCase):
    def test_edit_button_renders_for_an_admin(self):
        """The read-mode /schedule/?view=all page renders the 'Edit rehearsals' button for a logged-in admin."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=TOMORROW)
        admin_client(self)

        response = self.client.get(f"{reverse('scheduling:schedule')}?view=all")

        self.assertContains(response, 'id="edit-rehearsals-button"')

    def test_edit_button_is_absent_for_a_member(self):
        """A member sees no edit affordance on the All-Rehearsals list."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=TOMORROW)
        member_client(self)

        response = self.client.get(f"{reverse('scheduling:schedule')}?view=all")

        self.assertNotContains(response, 'id="edit-rehearsals-button"')
        self.assertNotContains(response, 'schedule-edit-form')

    def test_edit_button_renders_on_a_semester_with_zero_rehearsals(self):
        """A brand-new Semester with no Rehearsals still shows the button, so it isn't a dead end."""
        SemesterFactory()
        admin_client(self)

        response = self.client.get(f"{reverse('scheduling:schedule')}?view=all")

        self.assertContains(response, 'id="edit-rehearsals-button"')


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleEditAccessTests(TestCase):
    def test_get_redirects_anonymous_users_to_login(self):
        """An anonymous GET to /schedule/edit/ redirects to the login page."""
        url = reverse('scheduling:schedule-edit')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_post_redirects_anonymous_users_to_login(self):
        """An anonymous POST to /schedule/edit/ redirects to login and changes nothing."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        url = reverse('scheduling:schedule-edit')

        response = self.client.post(url, formset_data([rehearsal], edits={rehearsal.pk: {'start_time': '19:00'}}))

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.start_time, time(18, 0))

    def test_get_is_forbidden_for_a_non_admin(self):
        """A logged-in non-admin's GET to /schedule/edit/ returns 403."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=TOMORROW)
        member_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit'))

        self.assertEqual(response.status_code, 403)

    def test_post_is_forbidden_for_a_non_admin_and_changes_nothing(self):
        """A logged-in non-admin's POST to /schedule/edit/ returns 403 and changes nothing."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        member_client(self)

        response = self.client.post(
            reverse('scheduling:schedule-edit'), formset_data([rehearsal], edits={rehearsal.pk: {'start_time': '19:00'}}),
        )

        self.assertEqual(response.status_code, 403)
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.start_time, time(18, 0))


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleEditGetTests(TestCase):
    def test_full_page_get_renders_the_grid_and_the_banner(self):
        """A direct (non-htmx) GET renders the full page, including the non-live Semester banner."""
        draft = SemesterFactory(draft=True)
        RehearsalFactory(semester=draft, date=TOMORROW)
        admin_client(self)
        select(self, draft)

        response = self.client.get(reverse('scheduling:schedule-edit'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="semester-banner"')
        self.assertContains(response, 'id="schedule-edit-form"')

    def test_htmx_get_returns_a_bare_fragment(self):
        """An `HX-Request` GET returns just the grid fragment, not the full page shell."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=TOMORROW)
        admin_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit'), HTTP_HX_REQUEST='true')

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<html')
        self.assertContains(response, 'id="schedule-edit-form"')

    def test_a_past_rehearsal_renders_with_no_inputs(self):
        """A past-dated Rehearsal renders in the collapsed past section with no editable inputs anywhere in the grid."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=YESTERDAY, start_time=time(18, 0))
        RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(19, 0))
        admin_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit'))
        content = response.content.decode()

        self.assertIn('id="schedule-edit-past"', content)
        # Exactly one editable row (the future Rehearsal) — the past one contributes none.
        self.assertEqual(content.count('class="schedule-edit-row"'), 1)

    def test_a_today_dated_rehearsal_is_still_editable(self):
        """A Rehearsal dated exactly today renders as an editable row, not a locked one."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=timezone.localdate(), start_time=time(18, 0))
        admin_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit'))

        self.assertContains(response, 'name="rehearsal-0-date"')

    def test_zero_rehearsals_still_renders_one_blank_row(self):
        """A Semester with no Rehearsals renders one blank row rather than an empty grid."""
        SemesterFactory()
        admin_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit'))

        self.assertContains(response, 'name="rehearsal-0-date"')

    def test_a_blank_new_rows_override_renders_as_placeholder_not_a_value(self):
        """A brand-new row's override field renders the Semester default as placeholder text, never a filled-in value.

        An *existing* Rehearsal is never a fair test of this: `Rehearsal.save()`
        already concretizes a blank override into a real value at creation
        time (an existing, documented invariant this ticket doesn't change —
        see `apply_rehearsal_edits()`'s docstring), so only a never-yet-saved
        row can still be blank when the grid renders it.
        """
        SemesterFactory(default_setup_grace_minutes=12)
        admin_client(self)

        response = self.client.get(reverse('scheduling:schedule-edit'))
        content = response.content.decode()

        self.assertIn('placeholder="12"', content)
        row_start = content.index('name="rehearsal-0-setup_grace_minutes"')
        row_end = content.index('>', row_start)
        self.assertNotIn('value="12"', content[row_start:row_end])


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleEditSaveTests(TestCase):
    def test_valid_save_commits_and_redirects_to_the_all_rehearsals_list(self):
        """A valid Save Changes commits the edited field and returns to the All-Rehearsals list."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        admin_client(self)
        data = formset_data([rehearsal], edits={rehearsal.pk: {'start_time': '17:00'}})

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertRedirects(response, f"{reverse('scheduling:schedule')}?view=all")
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.start_time, time(17, 0))

    def test_a_new_row_is_created_on_save(self):
        """A blank extra row filled in and saved creates a new Rehearsal."""
        semester = SemesterFactory()
        admin_client(self)
        data = formset_data([], semester_id=semester.pk, stamp=semester.updated_at.isoformat(), extra_rows=[{
            'date': NEXT_WEEK.isoformat(), 'start_time': '18:00', 'end_time': '20:00', 'is_full_setlist': False,
        }])

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertRedirects(response, f"{reverse('scheduling:schedule')}?view=all")
        self.assertTrue(Rehearsal.objects.filter(semester=semester, date=NEXT_WEEK).exists())

    def test_two_pending_rows_sharing_a_date_block_the_save(self):
        """Two rows dated the same day block the save entirely; the database is unchanged afterwards."""
        semester = SemesterFactory()
        first = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        admin_client(self)
        data = formset_data([first], extra_rows=[{
            'date': first.date.isoformat(), 'start_time': '20:00', 'end_time': '21:00', 'is_full_setlist': False,
        }])

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Rehearsal.objects.filter(semester=semester).count(), 1)
        first.refresh_from_db()
        self.assertEqual(first.start_time, time(18, 0))

    def test_an_end_time_before_start_time_blocks_the_save(self):
        """An end time before the start time blocks the save; the database is unchanged afterwards."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        admin_client(self)
        data = formset_data([rehearsal], edits={rehearsal.pk: {'start_time': '20:00', 'end_time': '19:00'}})

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.start_time, time(18, 0))

    def test_an_invalid_override_field_reopens_its_advanced_timing_details(self):
        """A row with a bad override value re-renders with that row's <details> open, so the error is actually visible."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        admin_client(self)
        data = formset_data([rehearsal], edits={rehearsal.pk: {'setup_grace_minutes': '-5'}})

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        details_start = content.index('schedule-edit-overrides-expander')
        details_tag_end = content.index('>', details_start)
        self.assertIn('open', content[details_start:details_tag_end])

    def test_a_new_row_dated_in_the_past_is_a_blocking_validation_error_naming_the_django_admin(self):
        """A new row dated before today is a blocking Validation Error, naming the Django admin, and writes nothing."""
        semester = SemesterFactory()
        admin_client(self)
        data = formset_data([], semester_id=semester.pk, stamp=semester.updated_at.isoformat(), extra_rows=[{
            'date': YESTERDAY.isoformat(), 'start_time': '18:00', 'end_time': '20:00', 'is_full_setlist': False,
        }])

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Django admin')
        self.assertFalse(Rehearsal.objects.filter(semester=semester, date=YESTERDAY).exists())

    def test_backdating_a_future_row_to_the_past_is_blocked_the_same_way(self):
        """Editing an existing future row's date to a past one is blocked exactly like a new past row."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        admin_client(self)
        data = formset_data([rehearsal], edits={rehearsal.pk: {'date': YESTERDAY.isoformat()}})

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Django admin')
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.date, TOMORROW)

    def test_a_blocked_save_preserves_every_submitted_value(self):
        """A validation failure re-renders the grid with the submitted (unsaved) values still present."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0), end_time=time(20, 0))
        admin_client(self)
        data = formset_data([rehearsal], edits={rehearsal.pk: {'start_time': '20:00', 'end_time': '19:00'}})

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertContains(response, 'value="20:00"')

    def test_a_stale_stamp_is_rejected_wholesale_and_writes_nothing(self):
        """A save carrying an older Semester stamp than the current one is rejected, writing nothing."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        stale_stamp = semester.updated_at.isoformat()
        semester.updated_at = timezone.now() + timedelta(seconds=1)
        semester.save(update_fields=['updated_at'])
        admin_client(self)
        data = formset_data([rehearsal], edits={rehearsal.pk: {'start_time': '19:00'}}, stamp=stale_stamp)

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.start_time, time(18, 0))
        self.assertContains(response, 'reload and reapply')
        self.assertContains(response, f'value="{stale_stamp}"')

        second_response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(second_response.status_code, 200)
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.start_time, time(18, 0))
        self.assertContains(second_response, 'reload and reapply')

    def test_a_wrong_semester_id_is_rejected_and_writes_nothing(self):
        """A hidden Semester id that no longer matches the session's viewed Semester is rejected wholesale."""
        semester = SemesterFactory()
        other = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, start_time=time(18, 0))
        admin_client(self)
        select(self, semester)
        data = formset_data([rehearsal], edits={rehearsal.pk: {'start_time': '19:00'}}, semester_id=other.pk)

        response = self.client.post(reverse('scheduling:schedule-edit'), data)

        self.assertEqual(response.status_code, 200)
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.start_time, time(18, 0))

    def test_a_past_dated_rehearsal_is_excluded_from_the_editable_queryset_so_it_cannot_be_targeted_by_pk(self):
        """A row naming a past-dated Rehearsal's pk can't edit it: the queryset excludes it, so Django binds a new instance instead.

        `apply_rehearsal_edits()`'s own hard failure for a genuinely
        forged/raced past row is covered at the service layer
        (`test_apply_rehearsal_edits.py`) — Django's own ModelFormSet
        instance matching, scoped to this view's future-only queryset,
        already prevents an out-of-queryset pk from reaching an edit of
        the real row through this surface.
        """
        semester = SemesterFactory()
        past_rehearsal = RehearsalFactory(semester=semester, date=YESTERDAY, start_time=time(18, 0))
        admin_client(self)
        data = {
            'rehearsal-TOTAL_FORMS': '1',
            'rehearsal-INITIAL_FORMS': '1',
            'rehearsal-MIN_NUM_FORMS': '0',
            'rehearsal-MAX_NUM_FORMS': '1000',
            'rehearsal-0-id': str(past_rehearsal.pk),
            'rehearsal-0-date': NEXT_WEEK.isoformat(),
            'rehearsal-0-start_time': '18:00',
            'rehearsal-0-end_time': '20:00',
            'schedule_semester_id': str(semester.pk),
            'schedule_semester_updated_at': semester.updated_at.isoformat(),
        }

        self.client.post(reverse('scheduling:schedule-edit'), data)

        past_rehearsal.refresh_from_db()
        self.assertEqual(past_rehearsal.date, YESTERDAY)
        self.assertEqual(past_rehearsal.start_time, time(18, 0))
