"""Alpine component scripts must load before Alpine's own vendor script (issue #289).

Alpine's vendored build calls `Alpine.start()` from a microtask right after
its own `<script>` finishes executing -- and that microtask drains before any
*later* deferred script runs. A page whose `Alpine.data()` registration was
loaded after the Alpine vendor tag therefore attaches its
`document.addEventListener('alpine:init', ...)` listener too late:
`alpine:init` has already fired, the registration never happens, and every
`x-data="<name>(...)"` on the page throws "<name> is not defined".

`templates/base.html`'s `{% block alpine_components %}` (positioned ahead of
the Alpine `<script>` tag, right after htmx) is the structural fix -- every
page's component script, and any SortableJS vendor tag a component's
`init()` calls `Sortable.create` from, belongs in that block. This is the
regression backstop: it renders every page known to carry (or, for a page
reached only via an htmx swap, preload) an `x-data` component as a logged-in
admin, and fails if any script that calls `Alpine.data()` appears in the
rendered HTML after the Alpine vendor tag.

In the style of `scheduling/tests/test_manage_cleanup_sweep.py`: a static
grep/regex sweep over rendered HTML, no headless browser and no node
toolchain (issue #168 stands).
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import RehearsalFactory, SemesterFactory, SongFactory
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY

PASSWORD = 'a-strong-test-password-123'

# Matches the vendored Alpine tag regardless of its pinned version, so a
# future bump (a filename rename, per CLAUDE.md's vendoring convention)
# doesn't silently stop this sweep from finding it.
ALPINE_VENDOR_SRC_RE = re.compile(r'vendor/alpine-[\d.]+\.min\.js$')
SCRIPT_SRC_RE = re.compile(r'<script[^>]+\bsrc="([^"]+)"')


def _alpine_registering_basenames():
    """Return the basename of every scheduling/static/scheduling/js/*.js file that calls Alpine.data().

    Derived by scanning the source rather than hardcoded, so a new
    component file is covered by this sweep the day it's added (issue
    #289's acceptance criteria) instead of needing this test updated too.
    """
    js_dir = Path(settings.BASE_DIR) / 'scheduling' / 'static' / 'scheduling' / 'js'
    return {
        path.name
        for path in js_dir.glob('*.js')
        if 'Alpine.data(' in path.read_text()
    }


ALPINE_REGISTERING_BASENAMES = _alpine_registering_basenames()


def _assert_registrations_precede_alpine(test_case, html, page_label):
    """Assert every `<script>` tag in `html` that registers an Alpine component appears before the Alpine vendor tag.

    Fails loudly, naming both `page_label` and the offending script `src`,
    so a regression (a component script template-tag drifting back into
    `{% block content %}`) is easy to trace back to its template.
    """
    srcs = SCRIPT_SRC_RE.findall(html)
    alpine_indexes = [i for i, src in enumerate(srcs) if ALPINE_VENDOR_SRC_RE.search(src)]
    test_case.assertEqual(
        len(alpine_indexes), 1,
        f'{page_label}: expected exactly one Alpine vendor <script> tag in the rendered page, '
        f'found {len(alpine_indexes)} (scripts seen: {srcs!r})',
    )
    alpine_index = alpine_indexes[0]

    for index, src in enumerate(srcs):
        basename = src.rsplit('/', 1)[-1]
        if basename in ALPINE_REGISTERING_BASENAMES:
            test_case.assertLess(
                index, alpine_index,
                f'{page_label}: {src!r} registers an Alpine component (Alpine.data()) but is loaded '
                f'after the Alpine vendor tag -- its alpine:init listener attaches after alpine:init '
                f'has already fired, so the component never registers.',
            )


@override_settings(SECURE_SSL_REDIRECT=False)
class AlpineComponentScriptOrderTests(TestCase):
    """Renders every page carrying (directly, or preloaded for an htmx-swapped fragment) an Alpine component."""

    @classmethod
    def setUpTestData(cls):
        """Build the synthetic admin, viewing Semester, Song, Rehearsal and draft Semester every page under test needs.

        `cls.semester` is built before `cls.draft` so `_prior_semester()`
        (services.py) resolves it as the draft's prior Semester -- without
        that, the roster-import setup step redirects straight past step 3
        instead of rendering it.
        """
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.semester = SemesterFactory()
        cls.song = SongFactory(semester=cls.semester)
        cls.rehearsal = RehearsalFactory(semester=cls.semester, is_full_setlist=False)
        cls.draft = SemesterFactory(draft=True)

    def setUp(self):
        """Log in as the synthetic admin before each page render."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def _reset_viewing_semester(self):
        """Pin the session's viewing Semester back to `self.semester` between page renders.

        A couple of the semester-setup steps (reached by pk, not by the
        viewing Semester) set the session's viewing selection as a side
        effect of rendering; resetting it keeps every other page in this
        sweep scoped to the same Semester its fixtures (`self.rehearsal`,
        `self.song`) belong to.
        """
        session = self.client.session
        session[VIEWING_SEMESTER_SESSION_KEY] = self.semester.pk
        session.save()

    def test_every_alpine_surface_loads_its_registration_before_alpine_starts(self):
        """Every page with an x-data component (or one preloaded for a same-page htmx swap) orders its scripts correctly."""
        pages = [
            ('Overview (/)', reverse('scheduling:overview')),
            ('Setlist (/setlist/)', reverse('scheduling:setlist')),
            ('Setlist edit (/setlist/edit/)', reverse('scheduling:setlist-edit')),
            (
                'Schedule, viewing a Rehearsal (/schedule/?rehearsal=<id>)',
                f"{reverse('scheduling:schedule')}?rehearsal={self.rehearsal.pk}",
            ),
            ('Schedule edit (/schedule/edit/)', reverse('scheduling:schedule-edit')),
            ('Song detail (/songs/<pk>/)', reverse('scheduling:song-detail', args=[self.song.pk])),
            (
                'Song requirements edit (/songs/<pk>/requirements/edit/)',
                reverse('scheduling:song-requirements-edit', args=[self.song.pk]),
            ),
            ('Band Members (/members/)', reverse('scheduling:members')),
            ('Band Members edit (/members/?mode=edit)', f"{reverse('scheduling:members')}?mode=edit"),
            (
                'Semester setup, roster step (setup/<pk>/roster/)',
                reverse('scheduling:manage-semester-setup-roster', args=[self.draft.pk]),
            ),
            (
                'Semester setup, setlist step (setup/<pk>/setlist/)',
                reverse('scheduling:manage-semester-setup-setlist', args=[self.draft.pk]),
            ),
            (
                'Semester setup, rehearsals step (setup/<pk>/rehearsals/)',
                reverse('scheduling:manage-semester-setup-rehearsals', args=[self.draft.pk]),
            ),
        ]

        for label, url in pages:
            with self.subTest(page=label):
                self._reset_viewing_semester()

                response = self.client.get(url)

                self.assertEqual(response.status_code, 200, f'{label}: expected 200, got {response.status_code}')
                _assert_registrations_precede_alpine(self, response.content.decode(), label)


class AlpineRegisteringFilesAreNonEmptyTests(TestCase):
    def test_at_least_one_js_file_registers_an_alpine_component(self):
        """Sanity check: the derived set isn't empty, so a broken glob/scan can't make the sweep above vacuously pass."""
        self.assertTrue(ALPINE_REGISTERING_BASENAMES)
