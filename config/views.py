"""Project-level view base classes shared across apps."""

from typing import ClassVar

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import ensure_csrf_cookie

from config import spa


class BaseView(LoginRequiredMixin):
    """Mixin applied by every non-auth view in the project, so none can forget to auth-gate itself.

    Every view except the auth views themselves (login, logout, password
    reset) should mix this in ahead of its Django generic view class
    (issue #17 user story 17).
    """


class AdminRequiredMixin(BaseView):
    """Mixin applied by every `/manage/` view, rejecting non-admins with 403 (issue #17 user story 14).

    Layered on top of `BaseView`'s login gate: an anonymous request still
    redirects to login, but a logged-in non-admin `Person` is rejected
    outright, before the wrapped view's `get`/`post` ever runs.
    """

    def dispatch(self, request, *args, **kwargs):
        """Return 403 for a logged-in non-admin Person; otherwise defer to the login-gated dispatch chain."""
        if request.user.is_authenticated and not request.user.is_admin:
            return HttpResponseForbidden()
        return super().dispatch(request, *args, **kwargs)


class PreviewMixin:
    """Owns the Preview transaction shape (ADR 0008, issue #228): run the real write, then always roll it back.

    Mixed in ahead of `AdminRequiredMixin` by any POST-only view that shows
    an admin Fallout for a Pending Buffer without committing it. A subclass
    overrides `run_preview(request, *args, **kwargs)` to bind its own
    form/formset, call its own `preview_*()` service function, and return
    the rendered response; this mixin wraps that call in a transaction and
    ends by setting rollback explicitly — never by letting a sentinel
    exception escape the stack (ADR 0008) — so nothing it does can commit,
    regardless of what `run_preview` raises or returns.
    """

    http_method_names: ClassVar[list[str]] = ['post']

    def post(self, request, *args, **kwargs):
        """Run `self.run_preview()` inside a transaction, then always roll it back."""
        with transaction.atomic():
            response = self.run_preview(request, *args, **kwargs)
            transaction.set_rollback(True)
        return response


class SpaIndexView(View):
    """Serves the React SPA's shell document (issue #325).

    Deliberately not login-gated, and not a `BaseView` — that is the
    decision, not an oversight. The document itself carries no member data;
    every byte the SPA displays arrives from `/api/`, which is gated by
    `ApiView`. Gating this view would cost a redirect round trip on every
    cold load and would break the fetch wrapper's contract that a 401
    triggers a full-page navigation to the login page, which requires this
    shell to still be servable to a browser whose session has just expired.
    Allowlisted in `config/tests/test_url_conf_structure.py` for exactly
    this reason.
    """

    http_method_names: ClassVar[list[str]] = ['get']

    @method_decorator(ensure_csrf_cookie)
    def get(self, request, *args, **kwargs):
        """Render the shell: from a running Vite dev server in development, or the build manifest otherwise.

        The fetch wrapper the SPA uses for its first write request (issue
        #326) reads the `csrftoken` cookie `ensure_csrf_cookie` guarantees
        here, since the SPA never renders a Django form that would set it
        as a side effect.
        """
        if settings.VITE_DEV_SERVER_URL:
            dev_server_url = settings.VITE_DEV_SERVER_URL.rstrip('/')
            static_path = settings.STATIC_URL.strip('/')
            context = {
                'vite_client_url': f'{dev_server_url}/{static_path}/@vite/client',
                'script_url': f'{dev_server_url}/{static_path}/{settings.FRONTEND_DEV_ENTRY}',
                'modulepreload_urls': (),
                'stylesheet_urls': (),
            }
        else:
            assets = spa.get_spa_assets()
            context = {
                'vite_client_url': None,
                'script_url': assets.script_url,
                'modulepreload_urls': assets.modulepreload_urls,
                'stylesheet_urls': assets.stylesheet_urls,
            }
        return render(request, 'config/spa_index.html', context)
