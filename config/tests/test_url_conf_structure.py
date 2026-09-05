"""Structural test guarding the project's one auth invariant (issue #315), extended for `/api/` (issue #326).

`config.views.BaseView` mixes `LoginRequiredMixin` into every non-auth view,
so no view can forget to gate itself. That property is currently just a
convention every new view has to remember to follow; this test makes it a
build failure to skip, ahead of the `/api/` SPA migration (issue #307) that
will multiply the number of views in the project.

Issue #326 adds the sharper `/api/` invariant: every view under `/api/`
must inherit `ApiView`, and every zero-argument `/api/` route must answer
an anonymous request with 401 and never 302 — the single client contract
that must never regress.
"""

from django.contrib import admin
from django.test import Client, SimpleTestCase
from django.urls import URLResolver, get_resolver

from config.views import AdminPreviewApiView, ApiView, BaseView

# Explicit and short by design (per the issue): auth views that run before a
# Person can be assumed to exist. Adding to this list is a visible act in a
# diff. Change password (issue #90) used to be here too, gating itself via
# Django's own `login_required` decorator instead of `BaseView`; #327 removes
# it from this URLConf entirely in favor of an SPA affordance #333 builds.
ALLOWLISTED_VIEW_NAMES = {
    'LoginView',
    'LogoutView',
    # The single token route serving both the invite and forgot-password
    # flows (issue #327) — collapsed from the previous SetPasswordConfirmView
    # + PasswordResetConfirmView pair.
    'SetPasswordConfirmView',
    'PasswordResetRequestView',
    # Serves the React SPA's shell document (issue #325). Deliberately not
    # login-gated: the document carries no member data — everything the SPA
    # renders comes from /api/, which is gated by ApiView — and gating it
    # would break the fetch wrapper's contract that a 401 triggers a
    # full-page navigation to login, which requires the shell to still be
    # servable to a browser whose session has just expired.
    'SpaIndexView',
}

# The Django admin mount is a resolver, not a view, so it's allowlisted by
# URL prefix rather than by trying to walk into it.
ALLOWLISTED_RESOLVER_NAMESPACES = {admin.site.name}


def _iter_view_classes(url_patterns):
    """Recursively walk a URLconf, yielding the `view_class` of every resolved pattern.

    `include()`d URLconfs surface as `URLResolver` instances whose own
    `url_patterns` need flattening; the admin site's resolver is skipped by
    namespace rather than walked into, since it has no single `view_class`.
    """
    for entry in url_patterns:
        if isinstance(entry, URLResolver):
            if entry.namespace in ALLOWLISTED_RESOLVER_NAMESPACES:
                continue
            yield from _iter_view_classes(entry.url_patterns)
        else:
            view_class = getattr(entry.callback, 'view_class', None)
            if view_class is not None:
                yield view_class


class BaseViewCoverageTests(SimpleTestCase):
    """Every route's view must inherit `BaseView`, unless explicitly allowlisted."""

    def test_every_view_inherits_base_view_or_is_allowlisted(self):
        """Walk the full URLConf and assert each view class is a `BaseView` subclass or on the allowlist."""
        resolver = get_resolver()
        offenders = []

        for view_class in _iter_view_classes(resolver.url_patterns):
            if issubclass(view_class, BaseView):
                continue
            if view_class.__name__ in ALLOWLISTED_VIEW_NAMES:
                continue
            offenders.append(f'{view_class.__module__}.{view_class.__qualname__}')

        self.assertEqual(
            offenders,
            [],
            'The following views neither inherit BaseView nor appear on '
            'ALLOWLISTED_VIEW_NAMES in config/tests/test_url_conf_structure.py: '
            f'{offenders}',
        )


def _find_api_resolver(url_patterns):
    """Return the `URLResolver` for the `api/` prefix among `url_patterns`, or None if it isn't there."""
    for entry in url_patterns:
        if isinstance(entry, URLResolver) and str(entry.pattern) == 'api/':
            return entry
    return None


def _iter_api_leaf_paths(url_patterns, prefix=''):
    """Recursively walk an `/api/`-rooted URLconf, yielding the full path string of every zero-argument leaf route.

    A route with any captured parameter (the terminal catch-all included)
    is skipped: reversing it needs an argument this generic walk has no
    business inventing, and parameterised routes are covered by their own
    surface tickets' tests (per the issue).
    """
    for entry in url_patterns:
        if isinstance(entry, URLResolver):
            yield from _iter_api_leaf_paths(entry.url_patterns, prefix + str(entry.pattern))
        elif entry.pattern.regex.groups == 0:
            yield prefix + str(entry.pattern)


def _iter_api_leaf_path_view_pairs(url_patterns, prefix=''):
    """Recursively walk an `/api/`-rooted URLconf, yielding `(full_path, view_class)` for every zero-argument leaf route.

    Mirrors `_iter_api_leaf_paths()`, but keeps the resolved view class
    alongside its path — `_iter_view_classes()` alone loses the path, and
    `_iter_api_leaf_paths()` alone loses the view, and issue #334's
    "every `.../preview/` route is an `AdminPreviewApiView` subclass"
    check needs both at once.
    """
    for entry in url_patterns:
        if isinstance(entry, URLResolver):
            yield from _iter_api_leaf_path_view_pairs(entry.url_patterns, prefix + str(entry.pattern))
        elif entry.pattern.regex.groups == 0:
            view_class = getattr(entry.callback, 'view_class', None)
            if view_class is not None:
                yield prefix + str(entry.pattern), view_class


class ApiViewCoverageTests(SimpleTestCase):
    """Every `/api/` view must inherit `ApiView`, and every zero-argument `/api/` route must 401, never 302 (issue #326)."""

    def test_every_api_view_inherits_api_view(self):
        """Walk the `/api/` URLConf and assert each view class is an `ApiView` subclass."""
        api_resolver = _find_api_resolver(get_resolver().url_patterns)
        self.assertIsNotNone(api_resolver, 'No api/ route found in the project URLConf.')
        offenders = []

        for view_class in _iter_view_classes(api_resolver.url_patterns):
            if not issubclass(view_class, ApiView):
                offenders.append(f'{view_class.__module__}.{view_class.__qualname__}')

        self.assertEqual(
            offenders,
            [],
            f'The following /api/ views do not inherit ApiView: {offenders}',
        )

    def test_every_zero_argument_api_route_401s_anonymously_and_never_302s(self):
        """An anonymous request to every parameter-free `/api/` route returns 401 with no `Location` header."""
        api_resolver = _find_api_resolver(get_resolver().url_patterns)
        self.assertIsNotNone(api_resolver, 'No api/ route found in the project URLConf.')
        client = Client()
        offenders = []

        for path in _iter_api_leaf_paths(api_resolver.url_patterns, prefix='/api/'):
            response = client.get(path)
            if response.status_code != 401 or 'Location' in response:
                offenders.append((path, response.status_code))

        self.assertEqual(
            offenders,
            [],
            f'The following /api/ routes did not answer an anonymous request with a bare 401: {offenders}',
        )

    def test_every_preview_route_resolves_to_an_admin_preview_api_view_subclass(self):
        """Every `/api/` route ending in `preview/` must resolve to an `AdminPreviewApiView` subclass (issue #334).

        The generic `test_every_api_view_inherits_api_view` above already
        proves every `/api/` view is an `ApiView`; this sharpens that for
        the Preview shape specifically, since `AdminPreviewApiView` is what
        actually guarantees the ADR-0008 run-and-roll-back transaction —
        a plain `AdminApiView` subclass at a `preview/` path would 401/403
        identically but silently skip the rollback.
        """
        api_resolver = _find_api_resolver(get_resolver().url_patterns)
        self.assertIsNotNone(api_resolver, 'No api/ route found in the project URLConf.')
        offenders = []

        for path, view_class in _iter_api_leaf_path_view_pairs(api_resolver.url_patterns, prefix='/api/'):
            if path.endswith('preview/') and not issubclass(view_class, AdminPreviewApiView):
                offenders.append(f'{path} -> {view_class.__module__}.{view_class.__qualname__}')

        self.assertEqual(
            offenders,
            [],
            f'The following /api/ .../preview/ routes do not inherit AdminPreviewApiView: {offenders}',
        )
