"""The Home admin panel: dropdown, publish, delete and the surviving `/manage/` doors (issue #199)."""

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import SemesterFactory

PASSWORD = 'a-strong-test-password-123'
PANEL_MARKER = 'data-testid="semester-panel"'


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
class PanelContentTests(TestCase):
    def test_the_panel_offers_publish_for_the_viewed_semester(self):
        """The panel's publish form targets #170's publish route for the currently viewed Semester."""
        draft = SemesterFactory(draft=True)
        admin_client(self)
        self.client.post(reverse('scheduling:manage-semester-select'), {'semester': draft.pk})

        response = self.client.get(reverse('scheduling:overview'))

        self.assertContains(
            response, f'action="{reverse("scheduling:manage-semesters-publish", args=[draft.pk])}"',
        )

    def test_the_panel_offers_delete_for_a_non_live_viewed_semester(self):
        """The panel links to #171's delete confirmation for a viewed Semester that isn't Live."""
        SemesterFactory()
        draft = SemesterFactory(draft=True)
        admin_client(self)
        self.client.post(reverse('scheduling:manage-semester-select'), {'semester': draft.pk})

        response = self.client.get(reverse('scheduling:overview'))

        self.assertContains(response, reverse('scheduling:manage-semesters-delete', args=[draft.pk]))

    def test_the_panel_offers_no_delete_for_the_live_semester(self):
        """The panel omits the delete link when the viewed Semester is the Live one, mirroring #171's own rule."""
        live = SemesterFactory()
        admin_client(self)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertNotContains(response, reverse('scheduling:manage-semesters-delete', args=[live.pk]))

    def test_the_panel_links_to_the_surviving_manage_surfaces(self):
        """The panel links to the conflict adjudication index and the people list."""
        SemesterFactory()
        admin_client(self)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertContains(response, reverse('scheduling:manage-conflicts'))
        self.assertContains(response, reverse('identity:people'))

    def test_a_member_sees_none_of_the_panel(self):
        """A logged-in non-admin's Home renders no panel, no publish/delete, and no admin-surface links."""
        semester = SemesterFactory()
        member_client(self)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertNotContains(response, PANEL_MARKER)
        self.assertNotContains(response, reverse('scheduling:manage-semesters-publish', args=[semester.pk]))
        self.assertNotContains(response, reverse('identity:people'))


@override_settings(SECURE_SSL_REDIRECT=False)
class ZeroSemesterTests(TestCase):
    def test_an_admin_still_gets_the_panel_with_no_semesters(self):
        """With zero Semesters, an admin's panel still renders rather than erroring or vanishing."""
        admin_client(self)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, PANEL_MARKER)
        self.assertContains(response, reverse('scheduling:manage-conflicts'))
        self.assertContains(response, reverse('identity:people'))

    def test_the_panel_offers_no_dropdown_or_semester_actions_with_no_semesters(self):
        """With zero Semesters, the panel has no select element and no publish/delete controls to offer."""
        admin_client(self)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertNotContains(response, '<select id="semester-select"')
        self.assertNotContains(response, reverse('scheduling:manage-semester-select'))
