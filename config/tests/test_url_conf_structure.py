"""Structural test guarding the project's one auth invariant (issue #315).

`config.views.BaseView` mixes `LoginRequiredMixin` into every non-auth view,
so no view can forget to gate itself. That property is currently just a
convention every new view has to remember to follow; this test makes it a
build failure to skip, ahead of the `/api/` SPA migration (issue #307) that
will multiply the number of views in the project.
"""

from django.contrib import admin
from django.test import SimpleTestCase
from django.urls import URLResolver, get_resolver

from config.views import BaseView

# Explicit and short by design (per the issue): auth views that run before a
# Person can be assumed to exist, or (password-change/-done) that gate
# themselves via Django's own `login_required` decorator instead of
# `BaseView`. Adding to this list is a visible act in a diff.
ALLOWLISTED_VIEW_NAMES = {
    'LoginView',
    'LogoutView',
    'SetPasswordConfirmView',
    'SetPasswordCompleteView',
    'PasswordResetRequestView',
    'PasswordResetDoneView',
    'PasswordResetConfirmView',
    'PasswordResetCompleteView',
    'PasswordChangeView',
    'PasswordChangeDoneView',
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
