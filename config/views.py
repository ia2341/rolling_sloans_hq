"""Project-level view base classes shared across apps."""

import json
from typing import ClassVar

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import HttpResponseForbidden, JsonResponse
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
        """Return this view's admin-required refusal for a logged-in non-admin; otherwise defer to the login-gated dispatch chain."""
        if request.user.is_authenticated and not request.user.is_admin:
            return self.handle_admin_required()
        return super().dispatch(request, *args, **kwargs)

    def handle_admin_required(self):
        """Return the refusal for a logged-in non-admin Person (issue #326: overridable so `AdminApiView` can answer JSON instead of HTML)."""
        return HttpResponseForbidden()


class MalformedPayloadError(ValueError):
    """Raised by `ApiView.parse_json_body()` for a request body that isn't parseable JSON (issue #326)."""


class ApiView(BaseView):
    """Base class for every `/api/` endpoint (issue #326): the login gate answers a 401, never a redirect.

    `fetch()` follows a 302 transparently, which would turn an expired
    session into a 200 carrying an HTML login page. Overriding
    `handle_no_permission()` here means every `/api/` route inherits the
    JSON 401 for free, the same way `BaseView` gives every route the login
    gate for free — there is no supported way to serve a `/api/` response
    without it.

    Also owns the envelope every `/api/` response wears: `read_response()`
    and `write_response()` attach the `context` block themselves, so an
    endpoint cannot forget it either.
    """

    def handle_no_permission(self):
        """Answer an unauthenticated request with the documented JSON 401, never a redirect."""
        return JsonResponse({'error': 'authentication_required'}, status=401)

    def dispatch(self, request, *args, **kwargs):
        """Run the normal dispatch chain, turning a `MalformedPayloadError` into the documented JSON 400."""
        try:
            return super().dispatch(request, *args, **kwargs)
        except MalformedPayloadError:
            return JsonResponse({'error': 'malformed_payload'}, status=400)

    def parse_json_body(self, request):
        """Return `request.body` parsed as JSON, or raise `MalformedPayloadError` for an unparseable body."""
        try:
            return json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise MalformedPayloadError('Malformed JSON body.') from error

    def build_context(self, request):
        """Return the six-key `context` block every `/api/` response carries (issue #326).

        Imported locally, not at module scope: `config/views.py` is
        project-level infrastructure every app depends on, and importing an
        app's serializer module at the top of it would invert that
        direction for no benefit — the context block is genuinely a
        `scheduling` concern (Semester lives there), delegating to
        `identity` for the viewer.
        """
        from scheduling.serializers import serialize_context

        return serialize_context(request)

    def read_response(self, request, data):
        """Return the read envelope: `{"context": ..., "data": data}`, for an endpoint answering a question."""
        return JsonResponse({'context': self.build_context(request), 'data': data})

    def write_response(
        self,
        request,
        *,
        ok,
        errors=None,
        non_field_errors=None,
        fallout=None,
        values=None,
        data=None,
    ):
        """Return the write envelope for an endpoint that takes a Pending Buffer (issue #326)."""
        return JsonResponse({
            'context': self.build_context(request),
            'ok': ok,
            'errors': errors or {},
            'non_field_errors': non_field_errors or [],
            'fallout': fallout,
            'values': values,
            'data': data,
        })


class AdminApiView(AdminRequiredMixin, ApiView):
    """Base class for every admin-only `/api/` endpoint (issue #326).

    MRO is `AdminApiView -> AdminRequiredMixin -> ApiView -> BaseView ->
    LoginRequiredMixin`, deliberately: the admin check runs first, but an
    anonymous caller still gets `ApiView`'s JSON 401 rather than
    `AdminRequiredMixin`'s refusal, because `AdminRequiredMixin` only
    rejects an *authenticated* non-admin and otherwise defers to the
    login-gated dispatch chain below it.
    """

    def handle_admin_required(self):
        """Answer a logged-in non-admin's request with the documented JSON 403."""
        return JsonResponse({'error': 'admin_required'}, status=403)


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


class AdminPreviewApiView(PreviewMixin, AdminApiView, View):
    """Base class for an admin-only `/api/` Preview endpoint (issue #334, ADR 0008).

    MRO is `AdminPreviewApiView -> PreviewMixin -> AdminApiView ->
    AdminRequiredMixin -> ApiView -> BaseView -> LoginRequiredMixin ->
    View`, mirroring the pre-SPA `PreviewMixin, AdminRequiredMixin, View`
    ordering: `PreviewMixin` owns `post()` (and the `http_method_names =
    ['post']` that comes with it), so it must sit ahead of the mixin chain
    that owns `dispatch()` — the admin/auth gate still runs first, since
    `PreviewMixin.post()` is only ever reached once `dispatch()` (resolved
    through `AdminRequiredMixin`/`BaseView`/`LoginRequiredMixin`) has let
    the request through. `View` is listed explicitly (unlike the pre-SPA
    version, where the concrete view class supplied it) because none of
    `AdminApiView`/`AdminRequiredMixin`/`ApiView`/`BaseView` are
    `django.views.View` subclasses themselves — each is a plain mixin, by
    the same convention `SetlistApiView(ApiView, View)` already follows —
    so a base class meant to be used directly (as this one is, by every
    admin Preview endpoint) has to supply `View` itself rather than assume
    a subclass will. A subclass supplies only `run_preview()`; the
    transaction-then-rollback shape is entirely `PreviewMixin`'s.
    """


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
