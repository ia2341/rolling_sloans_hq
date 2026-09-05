"""Tests for the SPA shell view and its Vite-manifest resolution (issue #325).

A good test here asserts what a browser gets back — status, and which asset
URLs appear in the document — not how the view got there. Building a real
Vite bundle is explicitly not required: a synthetic manifest, written to a
temporary directory and pointed at with `override_settings`, stands in for
`npm run build`'s output.
"""

import json
import tempfile
from pathlib import Path

from django.contrib.staticfiles.finders import find
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from config import checks

# The root path is already claimed by scheduling's Overview page, so tests
# aimed at the catch-all use a path no existing app route defines.
UNCLAIMED_PATH = '/an-unclaimed-spa-path/'

FAKE_ENTRY_FILE = 'assets/index-deadbeef.js'
FAKE_CSS_FILE = 'assets/index-cafef00d.css'
FAKE_CHUNK_FILE = 'assets/vendor-abc12345.js'

SYNTHETIC_MANIFEST = {
    'index.html': {
        'file': FAKE_ENTRY_FILE,
        'name': 'index',
        'src': 'index.html',
        'isEntry': True,
        'css': [FAKE_CSS_FILE],
        'imports': ['_vendor-chunk'],
    },
    '_vendor-chunk': {
        'file': FAKE_CHUNK_FILE,
        'name': 'vendor-chunk',
    },
}


def _write_manifest(directory: Path, manifest: dict) -> Path:
    """Write `manifest` as JSON under `directory`, returning the manifest file's path."""
    manifest_path = directory / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest))
    return manifest_path


@override_settings(SECURE_SSL_REDIRECT=False)
class SpaShellManifestTests(TestCase):
    """Requests to the SPA route, resolved against a synthetic Vite manifest."""

    def test_renders_the_hashed_urls_the_manifest_names(self):
        """The shell document references exactly the script, stylesheet and modulepreload URLs the manifest names."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest_path = _write_manifest(Path(tmp_dir), SYNTHETIC_MANIFEST)
            with override_settings(FRONTEND_MANIFEST_PATH=manifest_path):
                response = self.client.get(UNCLAIMED_PATH)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(f'/static/{FAKE_ENTRY_FILE}', content)
        self.assertIn(f'/static/{FAKE_CSS_FILE}', content)
        self.assertIn(f'/static/{FAKE_CHUNK_FILE}', content)

    def test_an_unclaimed_path_returns_the_same_shell(self):
        """A path no other route claims still returns 200 with the SPA shell — the client owns 404, not Django."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest_path = _write_manifest(Path(tmp_dir), SYNTHETIC_MANIFEST)
            with override_settings(FRONTEND_MANIFEST_PATH=manifest_path):
                response = self.client.get('/some/path/nothing/claims/')

        self.assertEqual(response.status_code, 200)
        self.assertIn(f'/static/{FAKE_ENTRY_FILE}', response.content.decode())

    def test_anonymous_request_returns_the_shell_not_a_redirect(self):
        """Pins the precondition for issue #326's 401-triggered full-page navigation: no login redirect here."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest_path = _write_manifest(Path(tmp_dir), SYNTHETIC_MANIFEST)
            with override_settings(FRONTEND_MANIFEST_PATH=manifest_path):
                response = Client().get(UNCLAIMED_PATH)

        self.assertEqual(response.status_code, 200)

    def test_response_carries_a_csrftoken_cookie(self):
        """The fetch wrapper (issue #326) reads this cookie to send back as X-CSRFToken on unsafe requests."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest_path = _write_manifest(Path(tmp_dir), SYNTHETIC_MANIFEST)
            with override_settings(FRONTEND_MANIFEST_PATH=manifest_path):
                response = self.client.get(UNCLAIMED_PATH)

        self.assertIn('csrftoken', response.cookies)

    def test_missing_manifest_raises_a_configuration_error(self):
        """No manifest on disk raises, naming the build command, rather than serving a document with no script tag."""
        missing_path = Path(tempfile.mkdtemp()) / 'manifest.json'
        with (
            override_settings(FRONTEND_MANIFEST_PATH=missing_path),
            self.assertRaisesMessage(ImproperlyConfigured, 'npm run build'),
        ):
            self.client.get(UNCLAIMED_PATH)


@override_settings(SECURE_SSL_REDIRECT=False)
class RouteOrderingTests(TestCase):
    """The catch-all must not swallow a path the earlier patterns already claim (issue #325)."""

    def test_admin_route_reaches_the_django_admin(self):
        """`/admin/` still resolves to the Django admin's own login page, not the SPA shell."""
        response = self.client.get('/admin/login/')

        self.assertNotIn(b'<div id="root">', response.content)

    def test_login_route_reaches_the_login_view(self):
        """`/accounts/login/` still resolves to identity's own login view, not the SPA shell."""
        response = self.client.get(reverse('identity:login'))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'<div id="root">', response.content)

    def test_static_asset_reaches_whitenoise_not_the_shell(self):
        """A collected static asset is served by WhiteNoise, ahead of URL resolution reaching the catch-all."""
        self.assertIsNotNone(find('vendor/pico-2.1.1.min.css'))

        with (
            tempfile.TemporaryDirectory() as static_root,
            override_settings(STATIC_ROOT=static_root),
        ):
            call_command('collectstatic', '--no-input', verbosity=0)
            response = self.client.get('/static/vendor/pico-2.1.1.min.css')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get('Content-Type', '').startswith('text/css'))


class SpaBuildOutputCheckTests(SimpleTestCase):
    """The deploy-time system check that catches an out-of-order `build.sh` (issue #325)."""

    def test_errors_when_debug_false_and_build_output_missing(self):
        """`check --deploy` fails when the manifest is absent outside DEBUG."""
        missing_path = Path(tempfile.mkdtemp()) / 'manifest.json'
        with override_settings(DEBUG=False, FRONTEND_MANIFEST_PATH=missing_path):
            errors = checks.spa_build_output_exists(None)

        self.assertEqual([error.id for error in errors], ['config.E001'])

    def test_no_error_in_debug_even_when_build_output_missing(self):
        """A fresh dev checkout with no build yet isn't a deploy failure."""
        missing_path = Path(tempfile.mkdtemp()) / 'manifest.json'
        with override_settings(DEBUG=True, FRONTEND_MANIFEST_PATH=missing_path):
            errors = checks.spa_build_output_exists(None)

        self.assertEqual(errors, [])

    def test_no_error_when_build_output_present(self):
        """The check passes once the manifest Vite writes is on disk."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest_path = _write_manifest(Path(tmp_dir), SYNTHETIC_MANIFEST)
            with override_settings(DEBUG=False, FRONTEND_MANIFEST_PATH=manifest_path):
                errors = checks.spa_build_output_exists(None)

        self.assertEqual(errors, [])
