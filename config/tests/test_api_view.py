"""`ApiView`/`AdminApiView` base-class behaviour (issue #326).

The single most important assertion in this module is that an
unauthenticated `/api/` request returns 401 and never 302 — the failure
mode that would otherwise turn a `fetch()` call into a 200 carrying an
HTML login page. Everything else here is the rest of the documented
status-code contract.
"""

from django.test import TestCase, override_settings

from identity.factories import PersonFactory

PASSWORD = 'a-strong-test-password-123'


@override_settings(ROOT_URLCONF='config.tests.urlconf_for_api_view_tests', SECURE_SSL_REDIRECT=False)
class ApiViewAuthTests(TestCase):
    """Anonymous/authenticated/admin behaviour shared by every `ApiView`/`AdminApiView` endpoint."""

    def test_anonymous_request_gets_401_not_302(self):
        """An anonymous request to an `ApiView` endpoint returns the JSON 401, with no `Location` header."""
        response = self.client.get('/member/')

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {'error': 'authentication_required'})
        self.assertNotIn('Location', response)

    def test_anonymous_request_to_admin_endpoint_also_gets_401_not_403(self):
        """An anonymous request to an `AdminApiView` endpoint still gets the 401, not the admin-only 403."""
        response = self.client.get('/admin/')

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {'error': 'authentication_required'})

    def test_authenticated_non_admin_succeeds_on_member_endpoint(self):
        """An authenticated non-admin succeeds against a plain `ApiView` endpoint."""
        person = PersonFactory(password=PASSWORD)
        self.client.login(username=person.email, password=PASSWORD)

        response = self.client.get('/member/')

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['data'], {'ok': True})
        self.assertIn('context', body)

    def test_authenticated_non_admin_gets_403_on_admin_endpoint(self):
        """An authenticated non-admin request to an `AdminApiView` endpoint returns the JSON 403."""
        person = PersonFactory(password=PASSWORD)
        self.client.login(username=person.email, password=PASSWORD)

        response = self.client.get('/admin/')

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {'error': 'admin_required'})

    def test_authenticated_admin_succeeds_on_admin_endpoint(self):
        """An authenticated admin request to an `AdminApiView` endpoint succeeds and carries the envelope."""
        person = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=person.email, password=PASSWORD)

        response = self.client.get('/admin/')

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['data'], {'ok': True})
        self.assertIn('context', body)

    def test_malformed_body_gets_400(self):
        """A body that isn't parseable JSON returns the documented JSON 400."""
        person = PersonFactory(password=PASSWORD)
        self.client.login(username=person.email, password=PASSWORD)

        response = self.client.post('/member/', data=b'not json', content_type='application/json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {'error': 'malformed_payload'})

    def test_well_formed_body_is_echoed_back(self):
        """A well-formed JSON body parses and is handed to the view, round-tripping through the read envelope."""
        person = PersonFactory(password=PASSWORD)
        self.client.login(username=person.email, password=PASSWORD)

        response = self.client.post('/member/', data={'name': 'value'}, content_type='application/json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], {'name': 'value'})


@override_settings(SECURE_SSL_REDIRECT=False)
class ApiNotFoundTests(TestCase):
    """The terminal `/api/` catch-all (`config/api_urls.py`), against the project's real URLConf."""

    def test_unknown_path_401s_for_an_anonymous_caller(self):
        """An unmatched /api/ path answers an anonymous caller with the ordinary 401, not the 404."""
        response = self.client.get('/api/this-path-does-not-exist/')

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {'error': 'authentication_required'})

    def test_unknown_path_404s_for_an_authenticated_caller(self):
        """An unmatched /api/ path answers an authenticated caller with the documented JSON 404."""
        person = PersonFactory(password=PASSWORD)
        self.client.login(username=person.email, password=PASSWORD)

        response = self.client.get('/api/this-path-does-not-exist/')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {'error': 'not_found'})
