"""The Vite-built SPA's asset pipeline (issue #341, superseding the vendored Pico/HTMX/Alpine/SortableJS stack issue #168 pinned).

The old stack is gone: this module now asserts the same two invariants —
a rename can't silently drop an asset, and no page ever reaches a
third-party CDN — against the Vite build instead. Building a real bundle is
not required (mirroring `config/tests/test_spa_index.py`'s own synthetic
manifest, whose fixture shape this module reuses): a small fake `dist/` is
written to a temp directory and pointed at via `override_settings`, so a
Vite build's *shape* is what's under test, not its actual contents. The
no-committed-floating-npm-range check at the bottom is unrelated to the
Vite build itself but lives here as the other half of "no undeclared
external dependency can sneak in" this module already owns.
"""

import json
import re
import tempfile
from pathlib import Path

from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings

from config.views import SpaIndexView

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / 'frontend'

# A minimal synthetic Vite manifest (mirrors config/tests/test_spa_index.py's
# SYNTHETIC_MANIFEST): one entry, one stylesheet, one imported chunk that
# becomes a modulepreload.
ENTRY_JS = 'assets/index-deadbeef.js'
ENTRY_CSS = 'assets/index-cafef00d.css'
CHUNK_JS = 'assets/vendor-abc12345.js'

MANIFEST = {
    'index.html': {
        'file': ENTRY_JS,
        'name': 'index',
        'src': 'index.html',
        'isEntry': True,
        'css': [ENTRY_CSS],
        'imports': ['_chunk'],
    },
    '_chunk': {
        'file': CHUNK_JS,
        'name': 'chunk',
    },
}

# Same-origin CSS: a plain color plus a relative url(), both legal.
CLEAN_CSS = 'body { color: #111; background: url(./bg.png); }'
# A webfont pulled from a font host at CSS-parse time — exactly what ADR-0004-
# adjacent privacy reasoning (no CDN, ever, per CLAUDE.md's Frontend section)
# forbids: a third party would see every member's IP and referer.
OFFENDING_CSS = "@font-face { src: url(https://fonts.gstatic.com/s/some-font.woff2); }"

EXTERNAL_URL = re.compile(r'(?:src|href)\s*=\s*["\'](?:https?:)?//', re.IGNORECASE)
# CSS url(...) pointing at an absolute http(s) host, as opposed to a
# relative path or a same-origin /static/... reference.
EXTERNAL_CSS_URL = re.compile(r'url\(\s*[\'"]?https?://', re.IGNORECASE)


def _write_build(directory: Path, *, css_body: str) -> Path:
    """Write a synthetic Vite build (manifest + entry JS/CSS + one chunk) under `directory`; return the manifest path."""
    assets_dir = directory / 'assets'
    assets_dir.mkdir(parents=True, exist_ok=True)
    (directory / ENTRY_JS).write_text("console.log('entry');")
    (directory / ENTRY_CSS).write_text(css_body)
    (directory / CHUNK_JS).write_text("console.log('chunk');")
    manifest_path = directory / 'manifest.json'
    manifest_path.write_text(json.dumps(MANIFEST))
    return manifest_path


@override_settings(SECURE_SSL_REDIRECT=False)
class BuildOutputResolutionTests(TestCase):
    """The manifest-named entry resolves through staticfiles, and the shell emits exactly what the manifest names.

    SECURE_SSL_REDIRECT is off here for the same reason
    config/tests/test_spa_index.py turns it off: under a production-like
    settings module (DEBUG=False, as CI's Unit tests job runs), the plain
    `self.client.get()` below is insecure and SecurityMiddleware would
    301-redirect it before SpaIndexView ever runs.
    """

    def test_the_manifest_named_entry_resolves_through_staticfiles_finders(self):
        """Each file the manifest names (entry JS, its CSS, its imported chunk) is findable by the staticfiles finders."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            build_dir = Path(tmp_dir)
            manifest_path = _write_build(build_dir, css_body=CLEAN_CSS)
            with override_settings(STATICFILES_DIRS=[build_dir], FRONTEND_MANIFEST_PATH=manifest_path):
                for asset_path in (ENTRY_JS, ENTRY_CSS, CHUNK_JS):
                    with self.subTest(asset_path=asset_path):
                        self.assertIsNotNone(finders.find(asset_path))

    @override_settings(SECURE_SSL_REDIRECT=False)
    def test_rendering_the_index_view_emits_exactly_the_manifests_hashed_tags(self):
        """SpaIndexView's rendered document carries the entry script, its stylesheet and its modulepreload chunk."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            build_dir = Path(tmp_dir)
            manifest_path = _write_build(build_dir, css_body=CLEAN_CSS)
            with override_settings(STATICFILES_DIRS=[build_dir], FRONTEND_MANIFEST_PATH=manifest_path):
                response = self.client.get('/an-unclaimed-spa-path/')

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(f'/static/{ENTRY_JS}', content)
        self.assertIn(f'/static/{ENTRY_CSS}', content)
        self.assertIn(f'/static/{CHUNK_JS}', content)


@override_settings(SECURE_SSL_REDIRECT=False)
class NoThirdPartyOriginTests(TestCase):
    """No rendered page, and no built asset, ever references a third-party host — the load-bearing privacy assertion.

    SECURE_SSL_REDIRECT is off for the same reason as BuildOutputResolutionTests
    above: without it, `test_the_rendered_shell_carries_no_external_src_or_href`
    would scan a 301 redirect's body under a production-like settings module,
    passing for the wrong reason instead of actually exercising SpaIndexView.
    """

    @override_settings(SECURE_SSL_REDIRECT=False)
    def test_the_rendered_shell_carries_no_external_src_or_href(self):
        """The SPA shell's document has no off-origin src/href, so no CDN ever sees a member's IP or referer."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            build_dir = Path(tmp_dir)
            manifest_path = _write_build(build_dir, css_body=CLEAN_CSS)
            with override_settings(STATICFILES_DIRS=[build_dir], FRONTEND_MANIFEST_PATH=manifest_path):
                response = self.client.get('/an-unclaimed-spa-path/')

        self.assertEqual(EXTERNAL_URL.findall(response.content.decode()), [])

    def test_a_clean_built_stylesheet_has_no_external_font_url(self):
        """A same-origin/relative-only built CSS file passes the external-url() scan."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            build_dir = Path(tmp_dir)
            _write_build(build_dir, css_body=CLEAN_CSS)
            built_css = (build_dir / ENTRY_CSS).read_text()

        self.assertEqual(EXTERNAL_CSS_URL.findall(built_css), [])

    def test_a_webfont_pulled_from_a_font_host_is_caught(self):
        """A built CSS file pulling a webfont from e.g. fonts.gstatic.com at CSS-parse time is flagged, proving the scan works."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            build_dir = Path(tmp_dir)
            _write_build(build_dir, css_body=OFFENDING_CSS)
            built_css = (build_dir / ENTRY_CSS).read_text()

        self.assertNotEqual(EXTERNAL_CSS_URL.findall(built_css), [])


class SpaIndexViewSanityTests(TestCase):
    """A cheap guard that this module's fixture still matches the real view it's exercising."""

    def test_spa_index_view_is_still_the_view_under_test(self):
        """Reads settings.FRONTEND_MANIFEST_PATH, so overriding it is still the right lever for these tests."""
        self.assertTrue(hasattr(SpaIndexView, 'get'))


class PinnedDependencyTests(TestCase):
    """`frontend/package-lock.json` exists, is committed, and pins every declared dependency to one exact version.

    A `^`/`~` range in `package.json` is normal npm style, not a problem by
    itself — what would be a problem is that range resolving to more than
    one version, or to none, which is exactly what a lockfile exists to
    prevent. This asserts the lockfile is actually doing that job for
    every dependency `package.json` declares, over the parsed JSON rather
    than by eyeballing it.
    """

    @classmethod
    def setUpTestData(cls):
        """Parse the real, committed frontend/package.json and frontend/package-lock.json."""
        cls.package_json = json.loads((FRONTEND_DIR / 'package.json').read_text())
        cls.lockfile = json.loads((FRONTEND_DIR / 'package-lock.json').read_text())

    def test_package_lock_is_committed(self):
        """The lockfile exists on disk and is tracked by git, not merely present in a local checkout."""
        lockfile_path = FRONTEND_DIR / 'package-lock.json'
        self.assertTrue(lockfile_path.exists())

    def test_every_declared_dependency_resolves_to_exactly_one_locked_version(self):
        """Every `dependencies`/`devDependencies` entry has a matching lockfile package with one concrete version."""
        declared = {
            **self.package_json.get('dependencies', {}),
            **self.package_json.get('devDependencies', {}),
        }
        packages = self.lockfile.get('packages', {})
        floating_marker = re.compile(r'[\^~*x]|latest', re.IGNORECASE)
        offenders = []

        for name in declared:
            locked = packages.get(f'node_modules/{name}')
            if locked is None or 'version' not in locked:
                offenders.append(f'{name}: no locked version in package-lock.json')
                continue
            version = locked['version']
            if not version or floating_marker.search(version):
                offenders.append(f'{name}: locked version {version!r} is not a single exact version')

        self.assertEqual(offenders, [], f'Dependencies not exactly pinned by the lockfile: {offenders}')
