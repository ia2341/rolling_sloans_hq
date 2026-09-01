"""Member conflicts self-service: /me/conflicts/ (issue #58)."""

from datetime import time

from django.test import TestCase, override_settings
from django.urls import reverse

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
        """With no Semester at all, the page renders without a form instead of erroring."""
        self.semester.delete()

        response = self.client.get(reverse('scheduling:conflicts'))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('form', response.context)

    def test_lists_current_semesters_rehearsals(self):
        """Renders successfully, listing only the current Semester's Rehearsals."""
        RehearsalFactory(semester=self.semester)
        current_semester = SemesterFactory()
        current_rehearsal = RehearsalFactory(semester=current_semester)

        response = self.client.get(reverse('scheduling:conflicts'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['rehearsals']), [current_rehearsal])

    def test_preselects_rehearsals_with_existing_full_conflict(self):
        """A Rehearsal the member has already marked FULL_CONFLICT is preselected in the form."""
        rehearsal = RehearsalFactory(semester=self.semester)
        ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)

        response = self.client.get(reverse('scheduling:conflicts'))

        self.assertEqual(response.status_code, 200)
        self.assertIn(rehearsal, response.context['form'].initial['full_conflict_rehearsals'])


@override_settings(SECURE_SSL_REDIRECT=False)
class ConflictsViewPostTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person and create the current Semester before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()

    def test_valid_post_creates_full_conflicts_and_redirects_with_message(self):
        """Selecting a Rehearsal creates a FULL_CONFLICT Conflict and redirects with a success message."""
        rehearsal = RehearsalFactory(semester=self.semester)

        response = self.client.post(
            reverse('scheduling:conflicts'), {'full_conflict_rehearsals': [rehearsal.pk]}, follow=True,
        )

        self.assertRedirects(response, reverse('scheduling:conflicts'))
        conflict = Conflict.objects.get(person=self.person, rehearsal=rehearsal)
        self.assertEqual(conflict.type, Conflict.FULL_CONFLICT)
        messages = [str(m) for m in response.context['messages']]
        self.assertIn('Conflicts updated.', messages)

    def test_valid_post_removes_deselected_full_conflicts(self):
        """Deselecting a previously-full-conflict Rehearsal deletes its Conflict row."""
        rehearsal = RehearsalFactory(semester=self.semester)
        ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)

        self.client.post(reverse('scheduling:conflicts'), {'full_conflict_rehearsals': []})

        self.assertFalse(Conflict.objects.filter(person=self.person, rehearsal=rehearsal).exists())

    def test_post_does_not_touch_partial_conflicts_for_deselected_rehearsals(self):
        """A partial Conflict (not represented by the checkbox) survives an unrelated bulk POST."""
        rehearsal = RehearsalFactory(semester=self.semester)
        conflict = ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(conflict=conflict)

        self.client.post(reverse('scheduling:conflicts'), {'full_conflict_rehearsals': []})

        conflict.refresh_from_db()
        self.assertEqual(conflict.type, Conflict.PARTIAL)
        self.assertTrue(ConflictWindow.objects.filter(conflict=conflict).exists())

    def test_post_is_scoped_to_the_logged_in_user_only(self):
        """A member's bulk POST can never edit another Person's Conflict — there is no person parameter."""
        other_person = PersonFactory()
        rehearsal = RehearsalFactory(semester=self.semester)
        other_conflict = ConflictFactory(person=other_person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)

        self.client.post(reverse('scheduling:conflicts'), {'full_conflict_rehearsals': []})

        other_conflict.refresh_from_db()
        self.assertEqual(other_conflict.type, Conflict.FULL_CONFLICT)

    def test_invalid_post_rerenders_form_with_errors(self):
        """A POST referencing a nonexistent Rehearsal id re-renders the form with a field error, not a 500."""
        response = self.client.post(reverse('scheduling:conflicts'), {'full_conflict_rehearsals': [999999]})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'is not one of the available choices')
        self.assertFalse(Conflict.objects.filter(person=self.person).exists())


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
