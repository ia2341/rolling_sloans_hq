"""The manage/* cleanup sweep (issue #204): no template is left pointing at a retired screen.

#182, #196/#224 and #197/#213 each retired their own `/manage/*` screen
(view, route and template) with no redirect shim. This test is the
project-wide backstop behind those per-ticket retirements: it scans
every template in the tree for a reference to any of the removed
routes, so a future edit that accidentally re-adds a dead link (or a
future retirement that forgets to clean up after itself) fails loudly
here rather than shipping a link to a 404. It also pins down the
converse: the surviving `/manage/conflicts/*` and `/manage/people/*`
routes reverse, per ADR 0005 and issue #191 — they're the deliberate
exception to the `manage/*` retirement, not a missed migration.
"""

from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from identity.factories import PersonFactory

PASSWORD = 'a-strong-test-password-123'

# Every URL name retired outright across #182 (/manage/setlist/*),
# #196/#224 (/manage/schedule/*) and #197/#213 (/manage/assignments/*).
REMOVED_ROUTE_NAMES = (
    'scheduling:manage-setlist',
    'scheduling:manage-setlist-edit',
    'scheduling:manage-setlist-delete',
    'scheduling:manage-setlist-move-up',
    'scheduling:manage-setlist-move-down',
    'scheduling:manage-schedule',
    'scheduling:manage-schedule-edit',
    'scheduling:manage-assignments',
    'scheduling:manage-assignments-delete',
)

# The literal path prefixes those same routes used to live under, so the
# sweep also catches a hand-written href that never went through {% url %}.
REMOVED_PATH_PREFIXES = (
    '/manage/setlist/',
    '/manage/schedule/',
    '/manage/assignments/',
)

# Every `/manage/*` route left in the URLConf after the retirement: semester
# setup/select/publish/delete (untouched by #204), and the two surfaces #204
# is actually about — conflict adjudication (scheduling) and people
# management (identity), the deliberate exception per ADR 0005/#191.
SURVIVING_ROUTE_NAMES = (
    'scheduling:manage-semester-select',
    'scheduling:manage-semester-setup',
    'scheduling:manage-semesters',
    'scheduling:manage-semesters-publish',
    'scheduling:manage-semesters-delete',
    'scheduling:manage-semesters-reapply-defaults',
    'scheduling:manage-conflicts',
    'scheduling:manage-conflicts-detail',
    'identity:people',
    'identity:people-toggle-admin',
)

# (name, args) for the surviving routes that take a positional pk/rehearsal_id,
# so the reverse-test below can resolve them too.
SURVIVING_ROUTE_ARGS = {
    'scheduling:manage-semesters-publish': [1],
    'scheduling:manage-semesters-delete': [1],
    'scheduling:manage-semesters-reapply-defaults': [1],
    'scheduling:manage-conflicts-detail': [1],
    'identity:people-toggle-admin': [1],
}


def _all_template_sources():
    """Yield (path, text) for every .html template under every configured template directory.

    Walks `DIRS` (the project-level `templates/`) and each installed
    app's `<app>/templates/`, mirroring how Django's own loaders find
    templates, so the sweep can't miss a directory a loader would find.
    """
    seen = set()
    dirs = list(settings.TEMPLATES[0].get('DIRS') or [])
    if settings.TEMPLATES[0].get('APP_DIRS'):
        # Simpler and more robust than resolving INSTALLED_APPS entries: just
        # glob every "templates" directory under the repo root.
        repo_root = Path(settings.BASE_DIR)
        dirs.extend(p for p in repo_root.glob('*/templates') if p.is_dir())

    for directory in dirs:
        directory = Path(directory)
        if not directory.exists():
            continue
        for path in directory.rglob('*.html'):
            if path in seen:
                continue
            seen.add(path)
            yield path, path.read_text()


class RemovedRouteNamesDoNotReverseTests(TestCase):
    def test_none_of_the_removed_route_names_reverse(self):
        """Every retired `manage/*` URL name is gone from the URLConf outright, not just unlinked."""
        for name in REMOVED_ROUTE_NAMES:
            with self.subTest(name=name), self.assertRaises(NoReverseMatch):
                reverse(name)


class SurvivingRouteNamesReverseTests(TestCase):
    def test_surviving_manage_routes_reverse(self):
        """`/manage/conflicts/` and `/manage/people/` (and the semester-management doors) still resolve."""
        for name in SURVIVING_ROUTE_NAMES:
            with self.subTest(name=name):
                args = SURVIVING_ROUTE_ARGS.get(name, [])
                self.assertTrue(reverse(name, args=args).startswith('/'))


class NoTemplateReferencesARetiredRouteTests(TestCase):
    def test_no_template_contains_a_removed_route_name_or_path(self):
        """No template anywhere in the tree names a retired route or hardcodes its old path.

        Covers both spellings a template could use: `{% url
        'scheduling:manage-schedule' %}` (caught via the route name) and a
        hand-written `href="/manage/assignments/…"` (caught via the path
        prefix) — either would otherwise silently 404 in the browser.
        """
        offenders = []
        for path, text in _all_template_sources():
            for name in REMOVED_ROUTE_NAMES:
                if name in text:
                    offenders.append(f'{path}: references removed route name {name!r}')
            for prefix in REMOVED_PATH_PREFIXES:
                if prefix in text:
                    offenders.append(f'{path}: hardcodes removed path prefix {prefix!r}')

        self.assertEqual(offenders, [], '\n'.join(offenders))

    @override_settings(SECURE_SSL_REDIRECT=False)
    def test_home_admin_panel_links_both_surviving_doors(self):
        """The Home admin panel (`/`) renders a door to `/manage/conflicts/` and `/manage/people/` (#204).

        The retirement must not strand the two surfaces that stay; this
        renders the real page an admin lands on rather than trusting the
        route-name checks above to stand in for "and it's linked".
        """
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=admin.email, password=PASSWORD)

        response = self.client.get('/')
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn(reverse('scheduling:manage-conflicts'), content)
        self.assertIn(reverse('identity:people'), content)

    def test_no_orphaned_manage_templates_remain_in_the_tree(self):
        """The templates the retired screens used to render are deleted, not left dangling unreferenced."""
        repo_root = Path(settings.BASE_DIR)
        orphaned_names = (
            'manage_setlist.html',
            'manage_schedule.html',
            'manage_assignments.html',
        )
        found = [
            str(path)
            for path in repo_root.rglob('*.html')
            if path.name in orphaned_names
        ]

        self.assertEqual(found, [])
