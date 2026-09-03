"""The retired `/manage/setlist/*` screens: their routes no longer resolve, with no redirect shim (issue #182)."""

from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from identity.factories import PersonFactory

PASSWORD = 'a-strong-test-password-123'

REMOVED_ROUTE_NAMES = (
    'manage-setlist',
    'manage-setlist-edit',
    'manage-setlist-delete',
    'manage-setlist-move-up',
    'manage-setlist-move-down',
)

REMOVED_PATHS = (
    '/manage/setlist/',
    '/manage/setlist/1/edit/',
    '/manage/setlist/1/delete/',
    '/manage/setlist/1/move-up/',
    '/manage/setlist/1/move-down/',
)


class RemovedRouteNamesTests(TestCase):
    def test_none_of_the_removed_route_names_reverse(self):
        """Every retired `/manage/setlist/*` URL name is gone from the URLConf, not just unlinked."""
        for name in REMOVED_ROUTE_NAMES:
            with self.subTest(name=name), self.assertRaises(NoReverseMatch):
                reverse(f'scheduling:{name}')


@override_settings(SECURE_SSL_REDIRECT=False)
class RemovedPathsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic admin Person to log in as, so a 404 below can't be mistaken for an auth gate."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_the_removed_paths_404_for_an_admin_with_no_redirect(self):
        """Each retired path 404s outright for a logged-in admin; nothing redirects it elsewhere."""
        for path in REMOVED_PATHS:
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 404)

    def test_a_post_to_the_removed_paths_also_404s(self):
        """A POST (the verb every retired write used) also 404s rather than resolving to anything."""
        for path in REMOVED_PATHS:
            with self.subTest(path=path):
                response = self.client.post(path)

                self.assertEqual(response.status_code, 404)
