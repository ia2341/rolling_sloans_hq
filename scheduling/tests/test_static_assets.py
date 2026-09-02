"""The vendored admin UI stack and the nav shell's references to it (issue #168).

Nothing here asserts appearance or the contents of a vendored library: the
point is that a rename cannot silently drop a stylesheet or a script, and that
no page reaches for a third-party CDN.
"""

import re

from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory

PASSWORD = 'a-strong-test-password-123'

# The pinned vendored files. Version lives in the filename, so a bump is a
# visible rename rather than a silent content swap.
PICO_CSS = 'vendor/pico-2.1.1.min.css'
HTMX_JS = 'vendor/htmx-2.0.10.min.js'
ALPINE_JS = 'vendor/alpine-3.17.1.min.js'
SORTABLE_JS = 'vendor/sortable-1.15.7.min.js'
OVERRIDE_CSS = 'css/app.css'

# Loaded by the nav shell on every page.
SHELL_ASSETS = (PICO_CSS, OVERRIDE_CSS, HTMX_JS, ALPINE_JS)

# Vendored and resolvable, but wired by no page yet — the first drag surface
# adds the <script> tag.
UNREFERENCED_ASSETS = (SORTABLE_JS,)

EXTERNAL_URL = re.compile(r'(?:src|href)\s*=\s*["\'](?:https?:)?//', re.IGNORECASE)


class VendoredAssetResolutionTests(TestCase):
    def test_every_vendored_asset_resolves_through_staticfiles(self):
        """Each pinned vendor path, plus the override sheet, is findable by the staticfiles finders."""
        for path in SHELL_ASSETS + UNREFERENCED_ASSETS:
            with self.subTest(path=path):
                self.assertIsNotNone(finders.find(path))


@override_settings(SECURE_SSL_REDIRECT=False)
class NavShellAssetTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person, since every portal page is auth-gated."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_shell_references_every_asset_it_loads(self):
        """The rendered shell carries the {% static %} URL of Pico, the override sheet, HTMX and Alpine."""
        response = self.client.get(reverse('scheduling:overview'))

        for path in SHELL_ASSETS:
            with self.subTest(path=path):
                self.assertContains(response, static(path))

    def test_shell_does_not_reference_the_unwired_assets(self):
        """SortableJS is vendored but referenced by no page until the first drag surface wires it."""
        response = self.client.get(reverse('scheduling:overview'))

        for path in UNREFERENCED_ASSETS:
            with self.subTest(path=path):
                self.assertNotContains(response, static(path))

    def test_shell_requests_nothing_from_a_third_party(self):
        """No src/href on a rendered page points off-origin, so no CDN sees a member's IP."""
        response = self.client.get(reverse('scheduling:overview'))

        self.assertEqual(EXTERNAL_URL.findall(response.content.decode()), [])
