"""`identity`'s `/api/` views (issue #333: the Profile page's change-password affordance).

Issue #333 moved change-password into the SPA as the one auth act performed
*with* a session; forgot-password and set-password stay server-rendered
outside it (#327). Issue #362 adds sign-in itself: the SPA's `/login`
route posts here rather than to the server-rendered `identity:login` form,
which stays mounted as a fallback but is no longer where the SPA sends a
signed-out visitor.
"""

import json
from typing import ClassVar

from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.http import JsonResponse
from django.views import View

from config.views import ApiView

from .services import (
    clear_must_change_password,
    client_ip,
    is_login_rate_limited,
    record_login_attempt,
)


class LoginApiView(View):
    """`/api/login/`: the SPA's sign-in endpoint (issue #362, ADR 0013).

    Deliberately **not** an `ApiView` subclass: `ApiView` mixes in
    `LoginRequiredMixin` via `BaseView`, which would 401 the very request
    meant to establish a session in the first place. Builds its own small
    JSON responses instead of `read_response()`/`write_response()` for that
    reason — there is no viewer yet for `build_context()` to serialize
    until `POST` actually succeeds.

    `GET` answers "is this browser already signed in", so the SPA's Login
    page can bounce an already-authenticated visitor away without needing
    its own copy of that check; `POST` authenticates email + password,
    reusing the same `AuthenticationForm` and failed-sign-in rate limit
    `identity/views.py:LoginView` applies to the server-rendered fallback
    page, so both enforce one limit rather than two that could drift apart.
    """

    http_method_names: ClassVar[list[str]] = ['get', 'post']

    def get(self, request):
        """Report whether `request` already carries an authenticated session, and that viewer's context if so."""
        if not request.user.is_authenticated:
            return JsonResponse({'authenticated': False})
        return JsonResponse({'authenticated': True, 'context': self._context(request)})

    def post(self, request):
        """Authenticate the submitted email/password: start a session and return context on success, or report failure.

        A wrong email, a wrong password, and a rate-limited pair all answer
        `{"ok": false}` with the same generic `reason` — never which half
        was wrong, matching `identity/views.py:LoginView`'s existing
        behavior (#327) — except `throttled`, which is its own reason so
        the page can show "too many attempts" rather than "wrong password"
        copy.
        """
        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({'error': 'malformed_payload'}, status=400)

        email = payload.get('email', '')
        password = payload.get('password', '')
        ip_address = client_ip(request)

        if is_login_rate_limited(email=email, ip_address=ip_address):
            return JsonResponse({'ok': False, 'reason': 'throttled'})

        form = AuthenticationForm(request, data={'username': email, 'password': password})
        if not form.is_valid():
            record_login_attempt(email=email, ip_address=ip_address, was_successful=False)
            return JsonResponse({'ok': False, 'reason': 'invalid_credentials'})

        record_login_attempt(email=email, ip_address=ip_address, was_successful=True)
        login(request, form.get_user())
        return JsonResponse({'ok': True, 'context': self._context(request)})

    def _context(self, request):
        """Return the standard `/api/` context block for the now-authenticated `request`.

        Imported locally, matching `config/views.py:ApiView.build_context()`'s
        own comment: this is genuinely a `scheduling` concern (Semester
        lives there), and `identity` shouldn't import it at module scope.
        """
        from scheduling.serializers import serialize_context

        return serialize_context(request)


class PasswordChangeApiView(ApiView, View):
    """`POST /api/password/`: changes the requesting Person's own password (issue #333, self-only).

    Self-only by construction — there is no `pk` in the URL, so this can
    only ever act on `request.user`. Uses Django's own `PasswordChangeForm`
    for the three stock fields (current password, new, confirm) and its
    `AUTH_PASSWORD_VALIDATORS` errors, reported per field via the write
    envelope's `errors` dict. `update_session_auth_hash()` on success is
    load-bearing (issue #333 user story 49): without it, changing your
    password signs out the session you just used to change it.

    Also the single place that clears `Person.must_change_password`
    (issue #484): any successful change here, temp password or not,
    retires the SPA's post-login nag, since the flag's only meaning is
    "hasn't replaced the admin-generated password yet".
    """

    def post(self, request):
        """Validate the submitted password fields and change `request.user`'s password, or return per-field errors."""
        payload = self.parse_json_body(request)
        form = PasswordChangeForm(user=request.user, data={
            'old_password': payload.get('old_password', ''),
            'new_password1': payload.get('new_password1', ''),
            'new_password2': payload.get('new_password2', ''),
        })
        if not form.is_valid():
            return self.write_response(request, ok=False, errors=form.errors)
        form.save()
        update_session_auth_hash(request, form.user)
        clear_must_change_password(form.user)
        return self.write_response(request, ok=True)
