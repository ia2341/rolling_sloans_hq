"""Member conflicts self-service: /me/conflicts/ (issue #58)."""

from datetime import time, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    ConflictFactory,
    ConflictWindowFactory,
    RehearsalFactory,
    SemesterFactory,
)
from scheduling.models import Conflict, ConflictWindow

PASSWORD = 'a-strong-test-password-123'


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAccessTests(TestCase):
    def test_conflicts_redirects_anonymous_users_to_login(self):
        """An anonymous request to /me/conflicts/ redirects to the login page."""
        url = reverse('scheduling:conflicts')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_conflict_detail_redirects_anonymous_users_to_login(self):
        """An anonymous request to /me/conflicts/<rehearsal_id>/ redirects to the login page."""
        rehearsal = RehearsalFactory()
        url = reverse('scheduling:conflict-detail', args=[rehearsal.pk])

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")


@override_settings(SECURE_SSL_REDIRECT=False)
class ConflictsViewGetTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person and create the current Semester before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()

    def test_shows_no_active_semester_message_when_none_exists(self):
        """With no Semester at all, the page renders without any rows instead of erroring."""
        self.semester.delete()

        response = self.client.get(reverse('scheduling:conflicts'))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('rows', response.context)

    def test_lists_only_current_semesters_future_rehearsals(self):
        """Renders successfully, listing only the current Semester's future Rehearsals."""
        other_semester = SemesterFactory()
        RehearsalFactory(semester=other_semester, date=timezone.localdate() + timedelta(days=1))
        current_semester = SemesterFactory()
        past_rehearsal = RehearsalFactory(semester=current_semester, date=timezone.localdate() - timedelta(days=1))
        future_rehearsal = RehearsalFactory(semester=current_semester, date=timezone.localdate() + timedelta(days=1))

        response = self.client.get(reverse('scheduling:conflicts'))

        self.assertEqual(response.status_code, 200)
        rehearsals = [row['rehearsal'] for row in response.context['rows']]
        self.assertEqual(rehearsals, [future_rehearsal])
        self.assertNotIn(past_rehearsal, rehearsals)

    def test_undeclared_rehearsal_gets_a_declare_form(self):
        """A future Rehearsal with no existing Conflict for the member gets a declare form, and no Conflict."""
        rehearsal = RehearsalFactory(semester=self.semester, date=timezone.localdate() + timedelta(days=1))

        response = self.client.get(reverse('scheduling:conflicts'))

        row = response.context['rows'][0]
        self.assertEqual(row['rehearsal'], rehearsal)
        self.assertIsNone(row['conflict'])
        self.assertIsNotNone(row['form'])

    def test_already_declared_rehearsal_has_no_declare_form(self):
        """A future Rehearsal with an existing Conflict for the member surfaces that Conflict instead of a form."""
        rehearsal = RehearsalFactory(semester=self.semester, date=timezone.localdate() + timedelta(days=1))
        conflict = ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)

        response = self.client.get(reverse('scheduling:conflicts'))

        row = response.context['rows'][0]
        self.assertEqual(row['conflict'], conflict)
        self.assertIsNone(row['form'])
        self.assertContains(response, "already declared a conflict")

    def test_another_persons_conflict_does_not_disable_this_persons_row(self):
        """A Rehearsal only shows as declared for the member who actually declared a Conflict on it."""
        other_person = PersonFactory()
        rehearsal = RehearsalFactory(semester=self.semester, date=timezone.localdate() + timedelta(days=1))
        ConflictFactory(person=other_person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)

        response = self.client.get(reverse('scheduling:conflicts'))

        row = response.context['rows'][0]
        self.assertIsNone(row['conflict'])
        self.assertIsNotNone(row['form'])


@override_settings(SECURE_SSL_REDIRECT=False)
class ConflictsViewPostTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person and create the current Semester and a future Rehearsal before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(
            semester=self.semester, date=timezone.localdate() + timedelta(days=1), start_time=time(18, 0),
        )

    def _post_data(self, rehearsal, **fields):
        """Build POST data for `rehearsal`'s declare form, prefixed the way the view expects."""
        prefix = f'rehearsal-{rehearsal.pk}'
        data = {'rehearsal_id': str(rehearsal.pk)}
        for name, value in fields.items():
            data[f'{prefix}-{name}'] = value
        return data

    def test_full_absence_post_creates_full_conflict_and_redirects_with_message(self):
        """Declaring full absence creates a FULL_CONFLICT Conflict with no window, and redirects."""
        data = self._post_data(self.rehearsal, declaration_type='full_absence', reason='Out of town.')

        response = self.client.post(reverse('scheduling:conflicts'), data, follow=True)

        self.assertRedirects(response, reverse('scheduling:conflicts'))
        conflict = Conflict.objects.get(person=self.person, rehearsal=self.rehearsal)
        self.assertEqual(conflict.type, Conflict.FULL_CONFLICT)
        self.assertEqual(conflict.reason, 'Out of town.')
        self.assertFalse(ConflictWindow.objects.filter(conflict=conflict).exists())
        messages = [str(m) for m in response.context['messages']]
        self.assertIn('Conflict declared.', messages)

    def test_late_arrival_post_creates_partial_conflict_with_arrival_window(self):
        """Declaring a late arrival creates a PARTIAL Conflict windowed from the Rehearsal's start to the given time."""
        data = self._post_data(self.rehearsal, declaration_type='late_arrival', arrival_time='18:30')

        self.client.post(reverse('scheduling:conflicts'), data)

        conflict = Conflict.objects.get(person=self.person, rehearsal=self.rehearsal)
        self.assertEqual(conflict.type, Conflict.PARTIAL)
        window = ConflictWindow.objects.get(conflict=conflict)
        self.assertEqual(window.unavailable_start, self.rehearsal.start_time)
        self.assertEqual(window.unavailable_end, time(18, 30))

    def test_early_departure_post_creates_partial_conflict_with_departure_window(self):
        """Declaring an early departure creates a PARTIAL Conflict windowed from the given time to the Rehearsal's end."""
        data = self._post_data(self.rehearsal, declaration_type='early_departure', departure_time='19:00')

        self.client.post(reverse('scheduling:conflicts'), data)

        conflict = Conflict.objects.get(person=self.person, rehearsal=self.rehearsal)
        self.assertEqual(conflict.type, Conflict.PARTIAL)
        window = ConflictWindow.objects.get(conflict=conflict)
        self.assertEqual(window.unavailable_start, time(19, 0))
        self.assertEqual(window.unavailable_end, self.rehearsal.end_time)

    def test_post_is_scoped_to_the_logged_in_user_only(self):
        """A member's declare POST never touches another Person's Conflict for the same Rehearsal."""
        other_person = PersonFactory()
        other_conflict = ConflictFactory(person=other_person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)
        data = self._post_data(self.rehearsal, declaration_type='full_absence')

        self.client.post(reverse('scheduling:conflicts'), data)

        other_conflict.refresh_from_db()
        self.assertEqual(other_conflict.type, Conflict.FULL_CONFLICT)
        self.assertTrue(Conflict.objects.filter(person=self.person, rehearsal=self.rehearsal).exists())

    def test_arrival_time_outside_rehearsal_span_rerenders_form_with_errors(self):
        """An arrival_time outside the Rehearsal's span re-renders the page with a field error, not a 500."""
        data = self._post_data(self.rehearsal, declaration_type='late_arrival', arrival_time='17:00')

        response = self.client.post(reverse('scheduling:conflicts'), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Must fall within the Rehearsal&#x27;s time span, after it starts.")
        self.assertFalse(Conflict.objects.filter(person=self.person, rehearsal=self.rehearsal).exists())

    def test_arrival_time_exactly_at_rehearsal_start_rerenders_form_with_errors(self):
        """An arrival_time equal to the Rehearsal's start (a zero-length window) re-renders with a field error, not a 500."""
        data = self._post_data(
            self.rehearsal, declaration_type='late_arrival', arrival_time=self.rehearsal.start_time.strftime('%H:%M'),
        )

        response = self.client.post(reverse('scheduling:conflicts'), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Must fall within the Rehearsal&#x27;s time span, after it starts.")
        self.assertFalse(Conflict.objects.filter(person=self.person, rehearsal=self.rehearsal).exists())

    def test_departure_time_exactly_at_rehearsal_end_rerenders_form_with_errors(self):
        """A departure_time equal to the Rehearsal's end (a zero-length window) re-renders with a field error, not a 500."""
        data = self._post_data(
            self.rehearsal, declaration_type='early_departure',
            departure_time=self.rehearsal.end_time.strftime('%H:%M'),
        )

        response = self.client.post(reverse('scheduling:conflicts'), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Must fall within the Rehearsal&#x27;s time span, before it ends.")
        self.assertFalse(Conflict.objects.filter(person=self.person, rehearsal=self.rehearsal).exists())

    def test_missing_required_time_rerenders_that_rows_form_with_errors(self):
        """Declaring late_arrival without an arrival_time re-renders the page with a field error, not a 500."""
        data = self._post_data(self.rehearsal, declaration_type='late_arrival')

        response = self.client.post(reverse('scheduling:conflicts'), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter the time you will arrive.')
        self.assertFalse(Conflict.objects.filter(person=self.person, rehearsal=self.rehearsal).exists())

    def test_post_for_rehearsal_with_existing_conflict_is_rejected(self):
        """A POST naming a Rehearsal the member already declared a Conflict for 404s instead of creating a duplicate."""
        ConflictFactory(person=self.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)
        data = self._post_data(self.rehearsal, declaration_type='full_absence')

        response = self.client.post(reverse('scheduling:conflicts'), data)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Conflict.objects.filter(person=self.person, rehearsal=self.rehearsal).count(), 1)

    def test_post_referencing_a_nonexistent_rehearsal_404s(self):
        """A POST naming a nonexistent rehearsal_id 404s instead of erroring."""
        response = self.client.post(reverse('scheduling:conflicts'), {'rehearsal_id': '999999'})

        self.assertEqual(response.status_code, 404)

    def test_post_referencing_a_past_rehearsal_in_the_current_semester_404s(self):
        """A POST naming a past Rehearsal in the current Semester (never a declarable row) 404s instead of succeeding."""
        past_rehearsal = RehearsalFactory(semester=self.semester, date=timezone.localdate() - timedelta(days=1))
        data = self._post_data(past_rehearsal, declaration_type='full_absence')

        response = self.client.post(reverse('scheduling:conflicts'), data)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Conflict.objects.filter(person=self.person, rehearsal=past_rehearsal).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class ConflictDetailViewGetTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person and create the current Semester before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()

    def test_404_for_rehearsal_from_an_older_semester(self):
        """A Rehearsal belonging to a non-current Semester is not reachable by id."""
        old_semester = SemesterFactory()
        old_rehearsal = RehearsalFactory(semester=old_semester)
        SemesterFactory()  # becomes the current Semester

        response = self.client.get(reverse('scheduling:conflict-detail', args=[old_rehearsal.pk]))

        self.assertEqual(response.status_code, 404)

    def test_shows_empty_formset_when_no_existing_conflict(self):
        """With no existing Conflict for this Rehearsal, the formset starts with no bound windows."""
        rehearsal = RehearsalFactory(semester=self.semester)

        response = self.client.get(reverse('scheduling:conflict-detail', args=[rehearsal.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['formset'].initial_form_count(), 0)

    def test_shows_existing_windows(self):
        """The member's existing ConflictWindows for this Rehearsal are preloaded into the formset."""
        rehearsal = RehearsalFactory(semester=self.semester)
        conflict = ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.PARTIAL)
        window = ConflictWindowFactory(conflict=conflict)

        response = self.client.get(reverse('scheduling:conflict-detail', args=[rehearsal.pk]))

        self.assertEqual(response.status_code, 200)
        formset = response.context['formset']
        self.assertEqual(formset.initial_form_count(), 1)
        self.assertEqual(formset.forms[0].instance, window)


@override_settings(SECURE_SSL_REDIRECT=False)
class ConflictDetailViewPostTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person, create the current Semester and a Rehearsal, before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(semester=self.semester, start_time=time(18, 0))

    def _management_form_data(self, total=1, initial=0):
        """Build the Django formset management-form fields for `total` forms, `initial` of them pre-existing."""
        return {
            'form-TOTAL_FORMS': str(total),
            'form-INITIAL_FORMS': str(initial),
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
        }

    def test_valid_post_creates_partial_conflict_and_windows_and_redirects_with_message(self):
        """A valid POST with a window creates a PARTIAL Conflict and its ConflictWindow, and redirects."""
        data = {
            **self._management_form_data(),
            'form-0-unavailable_start': '18:15',
            'form-0-unavailable_end': '18:45',
        }

        response = self.client.post(
            reverse('scheduling:conflict-detail', args=[self.rehearsal.pk]), data, follow=True,
        )

        self.assertRedirects(response, reverse('scheduling:conflict-detail', args=[self.rehearsal.pk]))
        conflict = Conflict.objects.get(person=self.person, rehearsal=self.rehearsal)
        self.assertEqual(conflict.type, Conflict.PARTIAL)
        self.assertTrue(ConflictWindow.objects.filter(conflict=conflict).exists())
        messages = [str(m) for m in response.context['messages']]
        self.assertIn('Conflict updated.', messages)

    def test_valid_post_with_no_windows_deletes_existing_conflict(self):
        """Submitting with all windows deleted removes the Conflict row entirely (back to implicit availability)."""
        conflict = ConflictFactory(person=self.person, rehearsal=self.rehearsal, type=Conflict.PARTIAL)
        window = ConflictWindowFactory(conflict=conflict)
        data = {
            **self._management_form_data(total=1, initial=1),
            'form-0-id': str(window.pk),
            'form-0-unavailable_start': '18:15',
            'form-0-unavailable_end': '18:45',
            'form-0-DELETE': 'on',
        }

        self.client.post(reverse('scheduling:conflict-detail', args=[self.rehearsal.pk]), data)

        self.assertFalse(Conflict.objects.filter(person=self.person, rehearsal=self.rehearsal).exists())

    def test_invalid_post_rerenders_formset_with_errors(self):
        """A window outside the Rehearsal's time span re-renders the formset with a field error, not a 500."""
        data = {
            **self._management_form_data(),
            'form-0-unavailable_start': '17:00',
            'form-0-unavailable_end': '17:30',
        }

        response = self.client.post(reverse('scheduling:conflict-detail', args=[self.rehearsal.pk]), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Must fall within the Rehearsal&#x27;s time span.")
        self.assertFalse(Conflict.objects.filter(person=self.person, rehearsal=self.rehearsal).exists())

    def test_reversed_window_rerenders_formset_with_errors(self):
        """A window with unavailable_end before unavailable_start re-renders the formset with a field error."""
        data = {
            **self._management_form_data(),
            'form-0-unavailable_start': '18:45',
            'form-0-unavailable_end': '18:15',
        }

        response = self.client.post(reverse('scheduling:conflict-detail', args=[self.rehearsal.pk]), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'End time must be after start time.')
        self.assertFalse(Conflict.objects.filter(person=self.person, rehearsal=self.rehearsal).exists())

    def test_zero_length_window_rerenders_formset_with_errors(self):
        """A window with unavailable_end equal to unavailable_start re-renders the formset with a field error."""
        data = {
            **self._management_form_data(),
            'form-0-unavailable_start': '18:15',
            'form-0-unavailable_end': '18:15',
        }

        response = self.client.post(reverse('scheduling:conflict-detail', args=[self.rehearsal.pk]), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'End time must be after start time.')
        self.assertFalse(Conflict.objects.filter(person=self.person, rehearsal=self.rehearsal).exists())

    def test_post_does_not_affect_another_members_conflict_for_same_rehearsal(self):
        """A member's POST for this Rehearsal never touches another member's Conflict/windows for it."""
        other_person = PersonFactory()
        other_conflict = ConflictFactory(person=other_person, rehearsal=self.rehearsal, type=Conflict.PARTIAL)
        other_window = ConflictWindowFactory(conflict=other_conflict)
        data = {
            **self._management_form_data(),
            'form-0-unavailable_start': '18:15',
            'form-0-unavailable_end': '18:45',
        }

        self.client.post(reverse('scheduling:conflict-detail', args=[self.rehearsal.pk]), data)

        other_conflict.refresh_from_db()
        self.assertEqual(other_conflict.type, Conflict.PARTIAL)
        self.assertTrue(ConflictWindow.objects.filter(pk=other_window.pk).exists())
        self.assertNotEqual(
            Conflict.objects.get(person=self.person, rehearsal=self.rehearsal).pk, other_conflict.pk,
        )
