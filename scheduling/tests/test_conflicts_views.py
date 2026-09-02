"""Member conflicts self-service: /me/conflicts/ (issues #58, #98, #99)."""

from datetime import time, timedelta
from unittest.mock import patch

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

    def test_conflict_edit_redirects_anonymous_users_to_login(self):
        """An anonymous request to /me/conflicts/<rehearsal_id>/edit/ redirects to the login page."""
        rehearsal = RehearsalFactory()
        url = reverse('scheduling:conflict-edit', args=[rehearsal.pk])

        response = self.client.post(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_conflict_delete_redirects_anonymous_users_to_login(self):
        """An anonymous request to /me/conflicts/<rehearsal_id>/delete/ redirects to the login page."""
        rehearsal = RehearsalFactory()
        url = reverse('scheduling:conflict-delete', args=[rehearsal.pk])

        response = self.client.post(url)

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

    def test_concurrent_duplicate_declaration_404s_instead_of_500(self):
        """A request that loses a race against a concurrent duplicate declaration 404s, not a 500 IntegrityError."""
        ConflictFactory(person=self.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)
        data = self._post_data(self.rehearsal, declaration_type='full_absence')

        with patch('scheduling.views.Conflict.objects.filter') as mock_filter:
            mock_filter.return_value.exists.return_value = False
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
class ConflictsViewHistoryGetTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person and create the current Semester before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()

    def test_history_only_includes_rehearsals_with_a_submitted_conflict(self):
        """A Rehearsal with no Conflict for this member is absent from History; a declared one is present."""
        RehearsalFactory(semester=self.semester)
        declared = RehearsalFactory(semester=self.semester)
        ConflictFactory(person=self.person, rehearsal=declared, type=Conflict.FULL_CONFLICT)

        response = self.client.get(reverse('scheduling:conflicts'))

        rehearsals = [row['rehearsal'] for row in response.context['history']]
        self.assertEqual(rehearsals, [declared])

    def test_future_history_row_gets_an_edit_form_prefilled_from_the_existing_conflict(self):
        """A future declared Rehearsal's History row carries an edit form pre-filled with its Conflict's values."""
        rehearsal = RehearsalFactory(
            semester=self.semester, date=timezone.localdate() + timedelta(days=1), start_time=time(18, 0),
        )
        conflict = ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.PARTIAL, reason='Traffic.')
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))

        response = self.client.get(reverse('scheduling:conflicts'))

        [row] = response.context['history']
        self.assertTrue(row['is_future'])
        self.assertIsNotNone(row['form'])
        self.assertEqual(row['form'].initial['declaration_type'], 'late_arrival')
        self.assertEqual(row['form'].initial['arrival_time'], time(18, 30))
        self.assertEqual(row['form'].initial['reason'], 'Traffic.')

    def test_past_history_row_has_no_edit_form(self):
        """A past declared Rehearsal's History row carries no edit form."""
        rehearsal = RehearsalFactory(semester=self.semester, date=timezone.localdate() - timedelta(days=1))
        ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)

        response = self.client.get(reverse('scheduling:conflicts'))

        [row] = response.context['history']
        self.assertFalse(row['is_future'])
        self.assertIsNone(row['form'])

    def test_history_row_shows_derived_type_label_and_reason(self):
        """A History row's type_label/reason surface the Conflict's derived declaration and reason text."""
        rehearsal = RehearsalFactory(semester=self.semester, date=timezone.localdate() + timedelta(days=1))
        ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT, reason='Out of town.')

        response = self.client.get(reverse('scheduling:conflicts'))

        self.assertContains(response, 'Full absence')
        self.assertContains(response, 'Out of town.')


@override_settings(SECURE_SSL_REDIRECT=False)
class ConflictEditViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person and create the current Semester and a future declared Rehearsal before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(
            semester=self.semester, date=timezone.localdate() + timedelta(days=1), start_time=time(18, 0),
        )
        self.conflict = ConflictFactory(person=self.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)

    def _post_data(self, rehearsal, **fields):
        """Build POST data for `rehearsal`'s History edit form, prefixed the way the view expects."""
        prefix = f'history-{rehearsal.pk}'
        return {f'{prefix}-{name}': value for name, value in fields.items()}

    def test_valid_edit_updates_the_existing_conflict_and_redirects(self):
        """A valid edit updates the existing Conflict in place (no second row) and redirects with a message."""
        data = self._post_data(self.rehearsal, declaration_type='late_arrival', arrival_time='18:30')

        response = self.client.post(
            reverse('scheduling:conflict-edit', args=[self.rehearsal.pk]), data, follow=True,
        )

        self.assertRedirects(response, reverse('scheduling:conflicts'))
        self.assertEqual(Conflict.objects.filter(person=self.person, rehearsal=self.rehearsal).count(), 1)
        self.conflict.refresh_from_db()
        self.assertEqual(self.conflict.type, Conflict.PARTIAL)
        messages = [str(m) for m in response.context['messages']]
        self.assertIn('Conflict updated.', messages)

    def test_invalid_edit_rerenders_the_conflicts_page_with_errors(self):
        """An edit submission outside the Rehearsal's span re-renders the page with a field error, not a 500."""
        data = self._post_data(self.rehearsal, declaration_type='late_arrival', arrival_time='05:00')

        response = self.client.post(reverse('scheduling:conflict-edit', args=[self.rehearsal.pk]), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Must fall within the Rehearsal&#x27;s time span, after it starts.")
        self.conflict.refresh_from_db()
        self.assertEqual(self.conflict.type, Conflict.FULL_CONFLICT)

    def test_edit_is_scoped_to_the_logged_in_user_only(self):
        """A member's edit POST edits their own Conflict but never touches another Person's for the same Rehearsal."""
        other_person = PersonFactory(password=PASSWORD)
        other_conflict = ConflictFactory(person=other_person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)
        data = self._post_data(self.rehearsal, declaration_type='late_arrival', arrival_time='18:30')

        self.client.post(reverse('scheduling:conflict-edit', args=[self.rehearsal.pk]), data)

        other_conflict.refresh_from_db()
        self.assertEqual(other_conflict.type, Conflict.FULL_CONFLICT)
        self.conflict.refresh_from_db()
        self.assertEqual(self.conflict.type, Conflict.PARTIAL)

    def test_edit_of_undeclared_rehearsal_404s(self):
        """An edit POST naming a Rehearsal the member never declared a Conflict for 404s."""
        undeclared = RehearsalFactory(semester=self.semester, date=timezone.localdate() + timedelta(days=1))
        data = self._post_data(undeclared, declaration_type='full_absence')

        response = self.client.post(reverse('scheduling:conflict-edit', args=[undeclared.pk]), data)

        self.assertEqual(response.status_code, 404)

    def test_edit_of_a_past_rehearsal_is_rejected_server_side_even_when_directly_posted(self):
        """A crafted edit POST naming a past declared Rehearsal 404s, independent of any template-hidden control."""
        past_rehearsal = RehearsalFactory(semester=self.semester, date=timezone.localdate() - timedelta(days=1))
        past_conflict = ConflictFactory(person=self.person, rehearsal=past_rehearsal, type=Conflict.FULL_CONFLICT)
        data = self._post_data(past_rehearsal, declaration_type='late_arrival', arrival_time='18:30')

        response = self.client.post(reverse('scheduling:conflict-edit', args=[past_rehearsal.pk]), data)

        self.assertEqual(response.status_code, 404)
        past_conflict.refresh_from_db()
        self.assertEqual(past_conflict.type, Conflict.FULL_CONFLICT)


@override_settings(SECURE_SSL_REDIRECT=False)
class ConflictDeleteViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person and create the current Semester and a future declared Rehearsal before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(semester=self.semester, date=timezone.localdate() + timedelta(days=1))
        self.conflict = ConflictFactory(person=self.person, rehearsal=self.rehearsal, type=Conflict.PARTIAL)
        self.window = ConflictWindowFactory(conflict=self.conflict)

    def test_valid_delete_removes_the_conflict_and_its_windows_and_redirects(self):
        """Deleting a future Conflict removes it (and its ConflictWindows, via cascade) and redirects with a message."""
        response = self.client.post(
            reverse('scheduling:conflict-delete', args=[self.rehearsal.pk]), follow=True,
        )

        self.assertRedirects(response, reverse('scheduling:conflicts'))
        self.assertFalse(Conflict.objects.filter(pk=self.conflict.pk).exists())
        self.assertFalse(ConflictWindow.objects.filter(pk=self.window.pk).exists())
        messages = [str(m) for m in response.context['messages']]
        self.assertIn('Conflict removed.', messages)

    def test_delete_is_scoped_to_the_logged_in_user_only(self):
        """A member's delete POST never removes another Person's Conflict for the same Rehearsal."""
        other_person = PersonFactory()
        other_conflict = ConflictFactory(person=other_person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)

        self.client.post(reverse('scheduling:conflict-delete', args=[self.rehearsal.pk]))

        self.assertTrue(Conflict.objects.filter(pk=other_conflict.pk).exists())
        self.assertFalse(Conflict.objects.filter(pk=self.conflict.pk).exists())

    def test_delete_of_undeclared_rehearsal_404s(self):
        """A delete POST naming a Rehearsal the member never declared a Conflict for 404s."""
        undeclared = RehearsalFactory(semester=self.semester, date=timezone.localdate() + timedelta(days=1))

        response = self.client.post(reverse('scheduling:conflict-delete', args=[undeclared.pk]))

        self.assertEqual(response.status_code, 404)

    def test_delete_of_a_past_rehearsal_is_rejected_server_side_even_when_directly_posted(self):
        """A crafted delete POST naming a past declared Rehearsal 404s, independent of any template-hidden control."""
        past_rehearsal = RehearsalFactory(semester=self.semester, date=timezone.localdate() - timedelta(days=1))
        past_conflict = ConflictFactory(person=self.person, rehearsal=past_rehearsal, type=Conflict.FULL_CONFLICT)

        response = self.client.post(reverse('scheduling:conflict-delete', args=[past_rehearsal.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Conflict.objects.filter(pk=past_conflict.pk).exists())
