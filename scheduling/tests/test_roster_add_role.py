"""The Roster editor's inline "Add Role" control: /members/roles/add/ (issue #230)."""

from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from identity.factories import PersonFactory
from scheduling.factories import RoleFactory, SemesterFactory
from scheduling.models import Role

PASSWORD = 'a-strong-test-password-123'


def _add_role_url():
    """Return the inline Add Role endpoint's URL."""
    return reverse('scheduling:members-add-role')


def _assert_ticked(test_case, content, pk):
    """Assert the checkbox for Role pk `pk` is rendered checked, tolerant of attribute ordering."""
    test_case.assertRegex(content.decode(), rf'value="{pk}"[^>]*checked')


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessControlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic non-admin Person."""
        cls.person = PersonFactory(password=PASSWORD)

    def test_anonymous_post_redirects_to_login(self):
        """An anonymous Add Role POST redirects to login and creates no Role."""
        response = self.client.post(_add_role_url(), {'kind': 'roster', 'prefix': 'roster-0', 'role_name': 'Trombone'})

        self.assertRedirects(response, f"{reverse('identity:login')}?next={_add_role_url()}")
        self.assertFalse(Role.objects.filter(name='Trombone').exists())

    def test_non_admin_post_is_forbidden(self):
        """A logged-in non-admin's Add Role POST returns 403 and creates no Role."""
        self.client.login(username=self.person.email, password=PASSWORD)

        response = self.client.post(_add_role_url(), {'kind': 'roster', 'prefix': 'roster-0', 'role_name': 'Trombone'})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Role.objects.filter(name='Trombone').exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class AddRoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic admin Person and a Semester (unused directly, but keeps the surface realistic)."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.semester = SemesterFactory()

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_new_role_name_creates_and_ticks_it_on_the_edit_table_row(self):
        """A brand-new name creates a Role and the response ticks it, scoped to the triggering row's field name."""
        response = self.client.post(_add_role_url(), {
            'kind': 'roster', 'prefix': 'roster-0', 'role_name': 'Trombone',
        })

        self.assertEqual(response.status_code, 200)
        role = Role.objects.get(name='Trombone')
        self.assertTrue(role.is_active)
        _assert_ticked(self, response.content, role.pk)
        self.assertContains(response, 'name="roster-0-roles"')
        self.assertContains(response, 'Added')

    def test_new_role_name_creates_and_ticks_it_on_an_add_list_row(self):
        """The same control works for an add-list row, using its own formset's field name."""
        response = self.client.post(_add_role_url(), {
            'kind': 'roster_add', 'prefix': 'roster_add-2', 'role_name': 'Tuba',
        })

        self.assertEqual(response.status_code, 200)
        role = Role.objects.get(name='Tuba')
        _assert_ticked(self, response.content, role.pk)
        self.assertContains(response, 'name="roster_add-2-roles"')

    def test_case_insensitive_match_ticks_the_existing_role_and_creates_nothing(self):
        """A name matching an active Role case-insensitively ticks it, reports a match, and creates no duplicate."""
        existing = RoleFactory(name='Trombone', is_active=True)

        response = self.client.post(_add_role_url(), {
            'kind': 'roster', 'prefix': 'roster-0', 'role_name': 'trombone',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Role.objects.filter(name__iexact='trombone').count(), 1)
        _assert_ticked(self, response.content, existing.pk)
        self.assertContains(response, 'Matched')

    def test_retired_match_is_reactivated(self):
        """A case-insensitive match against a retired Role brings it back into play."""
        retired = RoleFactory(name='Trombone', is_active=False)

        response = self.client.post(_add_role_url(), {
            'kind': 'roster', 'prefix': 'roster-0', 'role_name': 'Trombone',
        })

        retired.refresh_from_db()
        self.assertTrue(retired.is_active)
        self.assertContains(response, 'Reactivated')

    def test_already_ticked_roles_on_the_row_are_preserved(self):
        """Adding a Role doesn't un-tick whatever the row already had checked."""
        already_ticked = RoleFactory(name='Bassist')

        response = self.client.post(_add_role_url(), {
            'kind': 'roster', 'prefix': 'roster-0', 'role_name': 'Trombone',
            'roster-0-roles': [str(already_ticked.pk)],
        })

        new_role = Role.objects.get(name='Trombone')
        _assert_ticked(self, response.content, already_ticked.pk)
        _assert_ticked(self, response.content, new_role.pk)

    def test_role_commits_even_if_no_save_changes_follows(self):
        """The Role is a real, immediate commit -- it exists in the database with no batch save involved."""
        self.client.post(_add_role_url(), {
            'kind': 'roster', 'prefix': 'roster-0', 'role_name': 'Trombone',
        })

        self.assertTrue(Role.objects.filter(name='Trombone', is_active=True).exists())

    def test_blank_role_name_is_a_bad_request(self):
        """A blank Role name is rejected rather than creating an empty-named Role."""
        response = self.client.post(_add_role_url(), {
            'kind': 'roster', 'prefix': 'roster-0', 'role_name': '   ',
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Role.objects.count(), 0)

    def test_missing_prefix_is_a_bad_request(self):
        """A malformed POST missing the row prefix is rejected rather than crashing."""
        response = self.client.post(_add_role_url(), {'kind': 'roster', 'role_name': 'Trombone'})

        self.assertEqual(response.status_code, 400)

    def test_no_inline_retire_endpoint_exists(self):
        """There is no route to retire a Role from this surface -- that stays in the Django admin."""
        with self.assertRaises(NoReverseMatch):
            reverse('scheduling:members-remove-role')
