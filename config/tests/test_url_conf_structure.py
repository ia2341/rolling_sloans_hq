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
from django.test import Client, SimpleTestCase, override_settings
from django.urls import URLResolver, get_resolver, reverse

from config.views import AdminApiView, AdminPreviewApiView, ApiView, BaseView

# Explicit and short by design (per the issue): auth views that run before a
# Person can be assumed to exist. Adding to this list is a visible act in a
# diff. Change password (issue #90) used to be here too, gating itself via
# Django's own `login_required` decorator instead of `BaseView`; #327 removes
# it from this URLConf entirely in favor of an SPA affordance #333 builds.
ALLOWLISTED_VIEW_NAMES = {
    'LoginView',
    'LogoutView',
    # A static, dead-end "contact an admin" page (issue #487, ADR 0018):
    # the emailed set-password link it used to gate recovery behind
    # (`identity:set-password-confirm`) is retired, so this route now
    # renders with no form and gates nothing.
    'PasswordResetRequestView',
    # Serves the React SPA's shell document (issue #325). Deliberately not
    # login-gated: the document carries no member data — everything the SPA
    # renders comes from /api/, which is gated by ApiView — and gating it
    # would break the fetch wrapper's contract that a 401 triggers a
    # full-page navigation to login, which requires the shell to still be
    # servable to a browser whose session has just expired.
    'SpaIndexView',
    # The SPA's own sign-in endpoint (issue #362): establishes the session
    # `BaseView`'s `LoginRequiredMixin` would otherwise demand already
    # exist, so it can't inherit `BaseView` any more than `LoginView` can.
    'LoginApiView',
}

# The Django admin mount is a resolver, not a view, so it's allowlisted by
# URL prefix rather than by trying to walk into it.
ALLOWLISTED_RESOLVER_NAMESPACES = {admin.site.name}

# The one `/api/` view that cannot inherit `ApiView` (issue #362): `ApiView`
# 401s an unauthenticated request via `BaseView`'s `LoginRequiredMixin`,
# which would refuse the very request meant to establish a session in the
# first place. `LoginApiView` builds its own minimal JSON responses instead
# — see its docstring.
ALLOWLISTED_API_VIEW_NAMES = {'LoginApiView'}


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


@override_settings(SECURE_SSL_REDIRECT=False)
class ApiViewCoverageTests(SimpleTestCase):
    """Every `/api/` view must inherit `ApiView`, and every zero-argument `/api/` route must 401, never 302 (issue #326).

    SECURE_SSL_REDIRECT is off here because CI's Unit tests job runs under
    a production-like settings module (DEBUG=False); without this, the
    plain (insecure) `Client()` requests below would 301 before ever
    reaching the view, and this module's whole point is asserting the
    view's own status code.
    """

    def test_every_api_view_inherits_api_view(self):
        """Walk the `/api/` URLConf and assert each view class is an `ApiView` subclass, unless allowlisted."""
        api_resolver = _find_api_resolver(get_resolver().url_patterns)
        self.assertIsNotNone(api_resolver, 'No api/ route found in the project URLConf.')
        offenders = []

        for view_class in _iter_view_classes(api_resolver.url_patterns):
            if issubclass(view_class, ApiView):
                continue
            if view_class.__name__ in ALLOWLISTED_API_VIEW_NAMES:
                continue
            offenders.append(f'{view_class.__module__}.{view_class.__qualname__}')

        self.assertEqual(
            offenders,
            [],
            f'The following /api/ views do not inherit ApiView: {offenders}',
        )

    @override_settings(SECURE_SSL_REDIRECT=False)
    def test_every_zero_argument_api_route_401s_anonymously_and_never_302s(self):
        """An anonymous request to every parameter-free `/api/` route returns 401 with no `Location` header, unless allowlisted."""
        api_resolver = _find_api_resolver(get_resolver().url_patterns)
        self.assertIsNotNone(api_resolver, 'No api/ route found in the project URLConf.')
        client = Client()
        offenders = []

        for path, view_class in _iter_api_leaf_path_view_pairs(api_resolver.url_patterns, prefix='/api/'):
            if view_class.__name__ in ALLOWLISTED_API_VIEW_NAMES:
                continue
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


# The Band/Person surfaces (issue #333). `_iter_api_leaf_paths` above skips
# every parameterised route (member/roles/recording-delete), so those need
# their own explicit 401 coverage; the zero-argument ones are already swept
# by `test_every_zero_argument_api_route_401s_anonymously_and_never_302s`,
# but are named here too so this module documents every new #333 route in
# one place, per the issue's ask.
NEW_API_VIEW_IMPORT_PATHS = {
    'BandApiView': 'scheduling.api_views.BandApiView',
    'PersonApiView': 'scheduling.api_views.PersonApiView',
    'PersonRolesApiView': 'scheduling.api_views.PersonRolesApiView',
    'RecordingPresignApiView': 'scheduling.api_views.RecordingPresignApiView',
    'RecordingConfirmApiView': 'scheduling.api_views.RecordingConfirmApiView',
    'RecordingDeleteApiView': 'scheduling.api_views.RecordingDeleteApiView',
    'PasswordChangeApiView': 'identity.api_views.PasswordChangeApiView',
}


def _import_view_class(dotted_path):
    """Return the view class named by `dotted_path` (e.g. `'scheduling.api_views.BandApiView'`)."""
    module_path, class_name = dotted_path.rsplit('.', 1)
    module = __import__(module_path, fromlist=[class_name])
    return getattr(module, class_name)


@override_settings(SECURE_SSL_REDIRECT=False)
class BandPersonApiRouteCoverageTests(SimpleTestCase):
    """Issue #333's Band/Person/Recordings/password-change routes: `ApiView`, never `AdminApiView`, and a bare 401 anonymously.

    Every route here is member-facing (a non-admin needs it for their own
    pk), so none of them may be an `AdminApiView` — the only admin-
    conditional content on these surfaces is per-field, decided inside the
    view or serializer, not by gating the whole endpoint.
    """

    def test_every_new_view_inherits_api_view_and_not_admin_api_view(self):
        """Each of issue #333's new views is an `ApiView` subclass and not an `AdminApiView` subclass."""
        for name, dotted_path in NEW_API_VIEW_IMPORT_PATHS.items():
            view_class = _import_view_class(dotted_path)
            with self.subTest(view=name):
                self.assertTrue(issubclass(view_class, ApiView), f'{name} must inherit ApiView')
                self.assertFalse(issubclass(view_class, AdminApiView), f'{name} must not inherit AdminApiView')

    @override_settings(SECURE_SSL_REDIRECT=False)
    def test_anonymous_get_401s_on_every_new_route_never_302s(self):
        """An anonymous GET to every new #333 route (zero-argument or parameterised) answers 401, never a redirect."""
        client = Client()
        routes = [
            reverse('api-members'),
            reverse('api-member-detail', args=[1]),
            reverse('api-member-roles', args=[1]),
            reverse('api-recordings-presign'),
            reverse('api-recordings-confirm'),
            reverse('api-recordings-delete', args=[1]),
            reverse('api-password-change'),
        ]
        offenders = []
        for path in routes:
            response = client.get(path)
            if response.status_code != 401 or 'Location' in response:
                offenders.append((path, response.status_code))

        self.assertEqual(offenders, [], f'The following routes did not answer anonymously with a bare 401: {offenders}')


# The rehearsal editor's routes (issue #337). `_iter_api_leaf_paths` above
# already sweeps every zero-argument route here (the editor read, its
# Preview/Save, the Pattern-save, the generation-diff, and the deal) via
# the generic `AdminApiView`-coverage tests; the per-Rehearsal shuffle
# route is parameterised, so it needs its own explicit 401 coverage, named
# here so this module documents the whole surface in one place.
@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleEditorApiRouteCoverageTests(SimpleTestCase):
    """Issue #337's schedule-editor routes: every view is `AdminApiView`/`AdminPreviewApiView`, and a bare 401 anonymously."""

    @override_settings(SECURE_SSL_REDIRECT=False)
    def test_shuffle_route_401s_anonymously_and_never_302s(self):
        """An anonymous GET to the parameterised per-Rehearsal shuffle route answers 401, never a redirect."""
        client = Client()

        response = client.get(reverse('api-schedule-editor-shuffle', args=[1]))

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_every_schedule_editor_view_is_admin_gated(self):
        """Every schedule-editor view (read, Preview, Save, Pattern-save, generation-diff, deal, shuffle) is an `AdminApiView`."""
        from scheduling.api_views import (
            RehearsalGenerationDiffApiView,
            RehearsalPatternSaveApiView,
            ScheduleEditorApiView,
            ScheduleEditorDealApiView,
            ScheduleEditorPreviewApiView,
            ScheduleEditorSaveApiView,
            ScheduleEditorShuffleApiView,
        )

        for view_class in (
            ScheduleEditorApiView, ScheduleEditorPreviewApiView, ScheduleEditorSaveApiView,
            RehearsalPatternSaveApiView, RehearsalGenerationDiffApiView,
            ScheduleEditorDealApiView, ScheduleEditorShuffleApiView,
        ):
            with self.subTest(view=view_class.__name__):
                self.assertTrue(issubclass(view_class, AdminApiView), f'{view_class.__name__} must inherit AdminApiView')


# The assignment editor's routes (issue #338). `_iter_api_leaf_paths` above
# skips every parameterised route here (the picker, the per-Rehearsal
# preview/save pair), so they need their own explicit 401 coverage, named
# here so this module documents the whole surface in one place.
@override_settings(SECURE_SSL_REDIRECT=False)
class AssignmentEditorApiRouteCoverageTests(SimpleTestCase):
    """Issue #338's assignment-editor routes: every view is `AdminApiView`/`AdminPreviewApiView`, and a bare 401 anonymously."""

    @override_settings(SECURE_SSL_REDIRECT=False)
    def test_routes_401_anonymously_and_never_302(self):
        """An anonymous GET/POST to every parameterised #338 route answers 401, never a redirect."""
        client = Client()
        routes = [
            reverse('api-schedule-assignments-picker', args=[1, 1, 1]),
            reverse('api-schedule-assignments-preview', args=[1]),
            reverse('api-schedule-assignments-save', args=[1]),
        ]
        offenders = []
        for path in routes:
            response = client.get(path)
            if response.status_code != 401 or 'Location' in response:
                offenders.append((path, response.status_code))

        self.assertEqual(offenders, [], f'The following routes did not answer anonymously with a bare 401: {offenders}')

    def test_every_assignment_editor_view_is_admin_gated(self):
        """Every assignment-editor view (picker, Preview, Save) is an `AdminApiView`, and Preview is an `AdminPreviewApiView`."""
        from scheduling.api_views import (
            AssignmentPickerApiView,
            AssignmentPreviewApiView,
            AssignmentSaveApiView,
        )

        for view_class in (AssignmentPickerApiView, AssignmentPreviewApiView, AssignmentSaveApiView):
            with self.subTest(view=view_class.__name__):
                self.assertTrue(issubclass(view_class, AdminApiView), f'{view_class.__name__} must inherit AdminApiView')
        self.assertTrue(issubclass(AssignmentPreviewApiView, AdminPreviewApiView))


# The Semester-control surface's routes (issue #329). `_iter_api_leaf_paths`
# above already sweeps every zero-argument route here (management-rows,
# select, create, and the Reapply-defaults preview/save pair) via the
# generic `ApiViewCoverageTests` checks; the three per-Semester routes
# (publish-impact, deletion-summary, publish, delete) are parameterised, so
# they need their own explicit 401 coverage, named here so this module
# documents the whole surface in one place.
@override_settings(SECURE_SSL_REDIRECT=False)
class SemesterControlApiRouteCoverageTests(SimpleTestCase):
    """Issue #329's Semester-control routes: every view is `AdminApiView`/`AdminPreviewApiView`, and a bare 401 anonymously."""

    @override_settings(SECURE_SSL_REDIRECT=False)
    def test_every_parameterised_route_401s_anonymously_and_never_302s(self):
        """An anonymous GET/POST to each parameterised per-Semester route answers 401, never a redirect."""
        client = Client()
        routes = [
            ('get', reverse('api-semesters-publish-impact', args=[1])),
            ('get', reverse('api-semesters-deletion-summary', args=[1])),
            ('post', reverse('api-semesters-publish', args=[1])),
            ('post', reverse('api-semesters-delete', args=[1])),
        ]

        for method, path in routes:
            with self.subTest(path=path):
                response = getattr(client, method)(path)
                self.assertEqual(response.status_code, 401)
                self.assertNotIn('Location', response)

    def test_every_semester_control_view_is_admin_gated(self):
        """Every Semester-control view is an `AdminApiView` (the Reapply-defaults Preview is additionally `AdminPreviewApiView`)."""
        from scheduling.api_views import (
            SemesterCreateApiView,
            SemesterDefaultsReapplyPreviewApiView,
            SemesterDefaultsReapplySaveApiView,
            SemesterDeleteApiView,
            SemesterDeletionSummaryApiView,
            SemesterManagementRowsApiView,
            SemesterPublishApiView,
            SemesterPublishImpactApiView,
            SemesterSelectApiView,
        )

        for view_class in (
            SemesterManagementRowsApiView, SemesterPublishImpactApiView, SemesterDeletionSummaryApiView,
            SemesterSelectApiView, SemesterCreateApiView, SemesterPublishApiView, SemesterDeleteApiView,
            SemesterDefaultsReapplyPreviewApiView, SemesterDefaultsReapplySaveApiView,
        ):
            with self.subTest(view=view_class.__name__):
                self.assertTrue(issubclass(view_class, AdminApiView), f'{view_class.__name__} must inherit AdminApiView')

        self.assertTrue(issubclass(SemesterDefaultsReapplyPreviewApiView, AdminPreviewApiView))
