"""Semester setup steps 1-2: the wizard entry point, its finish screen, and the Home door (issue #200)."""

import re

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import MembershipFactory, SemesterFactory, SongFactory
from scheduling.models import Semester
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY

PASSWORD = 'a-strong-test-password-123'

VALID_POST_DATA = {
    'name': 'Fall 2026',
    'default_rehearsal_duration_minutes': 240,
    'default_setup_grace_minutes': 10,
    'default_teardown_grace_minutes': 10,
    'default_song_slot_count': 6,
    'default_arrival_buffer_minutes': 5,
    'default_departure_buffer_minutes': 5,
}


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


@override_settings(SECURE_SSL_REDIRECT=False)
class WizardEntryAuthTests(TestCase):
    def test_anonymous_get_redirects_to_login(self):
        """An anonymous GET to the wizard entry point redirects to login."""
        response = self.client.get(reverse('scheduling:manage-semester-setup'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('identity:login'), response.url)

    def test_anonymous_post_redirects_to_login(self):
        """An anonymous POST to the wizard entry point redirects to login."""
        response = self.client.post(reverse('scheduling:manage-semester-setup'), VALID_POST_DATA)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('identity:login'), response.url)

    def test_member_get_is_forbidden(self):
        """A logged-in non-admin gets a 403 for the wizard entry point."""
        member_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup'))

        self.assertEqual(response.status_code, 403)

    def test_member_post_is_forbidden(self):
        """A logged-in non-admin's POST to the wizard entry point is a 403, and nothing is created."""
        member_client(self)

        response = self.client.post(reverse('scheduling:manage-semester-setup'), VALID_POST_DATA)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Semester.objects.count(), 0)


@override_settings(SECURE_SSL_REDIRECT=False)
class WizardEntryGetTests(TestCase):
    def test_admin_get_renders_the_form(self):
        """An admin's GET renders the name field and the (collapsed) timing-default fields."""
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="name"')
        self.assertContains(response, 'name="default_song_slot_count"')

    def test_no_prior_semester_falls_back_to_constants(self):
        """With zero Semesters, the timing defaults prefill from the documented constants."""
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup'))

        self.assertContains(response, 'value="240"')
        self.assertContains(response, 'value="6"')

    def test_prior_semester_prefills_the_timing_defaults(self):
        """With a prior Semester, its timing defaults are offered as the prefill instead of the constants."""
        SemesterFactory(
            default_rehearsal_duration_minutes=90,
            default_setup_grace_minutes=15,
            default_teardown_grace_minutes=15,
            default_song_slot_count=5,
            default_arrival_buffer_minutes=7,
            default_departure_buffer_minutes=7,
        )
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup'))

        self.assertContains(response, 'value="90"')
        self.assertContains(response, 'value="5"')
        self.assertContains(response, 'value="7"')

    def test_a_parseable_prior_name_suggests_the_next_one(self):
        """A prior Semester named "Fall 2026" suggests "Spring 2027" as the new name."""
        SemesterFactory(name='Fall 2026')
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup'))

        self.assertContains(response, 'value="Spring 2027"')

    def test_an_unparseable_prior_name_leaves_the_name_blank(self):
        """A prior Semester with a name that doesn't parse leaves the name field blank, not erroring."""
        SemesterFactory(name='Summer Intensive')
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'value="Summer Intensive"')


@override_settings(SECURE_SSL_REDIRECT=False)
class WizardEntryPostTests(TestCase):
    def test_valid_submission_creates_a_draft_and_switches_the_viewing_semester(self):
        """Submitting valid data creates a draft Semester and the session's viewing Semester becomes it."""
        admin_client(self)

        response = self.client.post(reverse('scheduling:manage-semester-setup'), VALID_POST_DATA)

        semester = Semester.objects.get(name='Fall 2026')
        self.assertIsNone(semester.published_at)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session[VIEWING_SEMESTER_SESSION_KEY], semester.pk)

    def test_valid_submission_redirects_into_the_roster_step(self):
        """A successful submission redirects into step 3 (the roster import) for the newly created Semester."""
        admin_client(self)

        response = self.client.post(reverse('scheduling:manage-semester-setup'), VALID_POST_DATA)

        semester = Semester.objects.get(name='Fall 2026')
        self.assertRedirects(
            response, reverse('scheduling:manage-semester-setup-roster', args=[semester.pk]),
            target_status_code=302,
        )

    def test_valid_submission_with_no_prior_semester_lands_on_the_finish_screen(self):
        """With no prior Semester, following the redirect chain from a valid submission lands on the finish screen."""
        admin_client(self)

        response = self.client.post(reverse('scheduling:manage-semester-setup'), VALID_POST_DATA, follow=True)

        semester = Semester.objects.get(name='Fall 2026')
        self.assertEqual(response.redirect_chain, [
            (reverse('scheduling:manage-semester-setup-roster', args=[semester.pk]), 302),
            (reverse('scheduling:manage-semester-setup-finish', args=[semester.pk]), 302),
        ])
        self.assertEqual(response.status_code, 200)

    def test_the_non_live_banner_renders_after_creation(self):
        """Following the redirect after creation, the non-live banner appears since the draft isn't published."""
        admin_client(self)

        response = self.client.post(reverse('scheduling:manage-semester-setup'), VALID_POST_DATA, follow=True)

        self.assertContains(response, 'data-testid="semester-banner"')
        self.assertContains(response, 'Fall 2026')

    def test_blank_name_is_rejected_inline_and_creates_nothing(self):
        """A blank name re-renders the form with a readable error and creates no Semester."""
        admin_client(self)
        data = {**VALID_POST_DATA, 'name': '   '}

        response = self.client.post(reverse('scheduling:manage-semester-setup'), data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Semester.objects.count(), 0)

    def test_duplicate_name_is_rejected_inline_and_creates_nothing(self):
        """A name matching an existing Semester re-renders the form with a readable error and creates nothing."""
        SemesterFactory(name='Fall 2026')
        admin_client(self)

        response = self.client.post(reverse('scheduling:manage-semester-setup'), VALID_POST_DATA)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(Semester.objects.count(), 1)

    def test_a_negative_timing_default_is_rejected_inline_and_creates_nothing(self):
        """A negative timing-default value re-renders the form with an inline error and creates nothing."""
        admin_client(self)
        data = {**VALID_POST_DATA, 'default_song_slot_count': -1}

        response = self.client.post(reverse('scheduling:manage-semester-setup'), data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Semester.objects.count(), 0)

    def test_a_non_numeric_timing_default_is_rejected_inline_and_creates_nothing(self):
        """A non-numeric timing-default value re-renders the form with an inline error and creates nothing."""
        admin_client(self)
        data = {**VALID_POST_DATA, 'default_song_slot_count': 'lots'}

        response = self.client.post(reverse('scheduling:manage-semester-setup'), data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Semester.objects.count(), 0)

    def test_a_members_view_of_home_is_unaffected_by_a_new_draft(self):
        """A member's Home renders identically before and after an admin creates a new draft, CSRF token aside."""
        SemesterFactory()  # the Live Semester, so a member has something to see either way.
        member = member_client(self)
        before = self._csrf_free(self.client.get(reverse('scheduling:overview')).content)
        self.client.logout()

        admin_client(self)
        self.client.post(reverse('scheduling:manage-semester-setup'), VALID_POST_DATA)
        self.client.logout()

        self.client.login(username=member.email, password=PASSWORD)
        after = self._csrf_free(self.client.get(reverse('scheduling:overview')).content)
        self.assertEqual(before, after)

    @staticmethod
    def _csrf_free(content):
        """Return `content` with every CSRF token value blanked, so a byte-diff ignores that per-request randomness."""
        return re.sub(rb'name="csrfmiddlewaretoken" value="[^"]*"', b'name="csrfmiddlewaretoken" value=""', content)


@override_settings(SECURE_SSL_REDIRECT=False)
class FinishScreenTests(TestCase):
    def test_finish_screen_names_what_is_still_empty(self):
        """The finish screen reports the roster, setlist and rehearsals as still empty for a bare draft."""
        semester = SemesterFactory(draft=True)
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-finish', args=[semester.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'roster')
        self.assertContains(response, 'setlist')
        self.assertContains(response, 'rehearsal')

    def test_finish_screen_omits_what_is_already_filled_in(self):
        """A Semester with a roster and a song doesn't have those flagged as still empty."""
        semester = SemesterFactory(draft=True)
        MembershipFactory(semester=semester)
        SongFactory(semester=semester)
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-finish', args=[semester.pk]))

        self.assertNotContains(response, 'no roster yet')
        self.assertNotContains(response, 'no setlist yet')
        self.assertContains(response, 'no rehearsals scheduled yet')

    def test_finish_screen_links_back_to_home(self):
        """The finish screen offers a way back to Home."""
        semester = SemesterFactory(draft=True)
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-finish', args=[semester.pk]))

        self.assertContains(response, reverse('scheduling:overview'))

    def test_member_cannot_reach_the_finish_screen(self):
        """A logged-in non-admin gets 403 for the finish screen."""
        semester = SemesterFactory(draft=True)
        member_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup-finish', args=[semester.pk]))

        self.assertEqual(response.status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        """An anonymous request to the finish screen redirects to login."""
        semester = SemesterFactory(draft=True)

        response = self.client.get(reverse('scheduling:manage-semester-setup-finish', args=[semester.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('identity:login'), response.url)


@override_settings(SECURE_SSL_REDIRECT=False)
class FreshInstallHomeTests(TestCase):
    def test_zero_semesters_points_the_admin_at_create_semester(self):
        """With no Semesters at all, an admin's Home links to Create Semester."""
        admin_client(self)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('scheduling:manage-semester-setup'))

    def test_the_panel_offers_create_semester_even_with_existing_semesters(self):
        """Create Semester stays available once terms already exist, not just on a fresh install."""
        SemesterFactory()
        admin_client(self)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertContains(response, reverse('scheduling:manage-semester-setup'))

    def test_a_member_never_sees_create_semester(self):
        """A non-admin's Home never links to Create Semester, with or without existing Semesters."""
        SemesterFactory()
        member_client(self)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertNotContains(response, reverse('scheduling:manage-semester-setup'))


@override_settings(SECURE_SSL_REDIRECT=False)
class ModalFragmentTests(TestCase):
    def test_home_wires_the_create_semester_button_to_the_modal(self):
        """The panel's Create Semester button is wired to open the fetched fragment in a dialog."""
        admin_client(self)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertContains(response, 'semesterSetupModal')
        self.assertContains(response, 'id="semester-setup-dialog"')

    def test_an_xhr_get_returns_only_the_form_fragment(self):
        """A GET carrying X-Requested-With returns the bare form fragment, not the full page shell."""
        admin_client(self)

        response = self.client.get(
            reverse('scheduling:manage-semester-setup'), HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="name"')
        self.assertNotContains(response, '<nav>')

    def test_a_plain_get_still_returns_the_full_page(self):
        """A GET without the XHR header renders the full page, including the nav shell."""
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-setup'))

        self.assertContains(response, '<nav>')
        self.assertContains(response, 'name="name"')
