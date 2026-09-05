"""`identity`'s `/api/` views (issue #333: the Profile page's change-password affordance).

The rest of `identity`'s auth model — sign-in, forgot-password, set-password
— stays server-rendered outside the SPA (#327); this is the one auth act
performed *with* a session, so it moves into the SPA per issue #333's
Implementation Decisions.
"""

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.views import View

from config.views import ApiView


class PasswordChangeApiView(ApiView, View):
    """`POST /api/password/`: changes the requesting Person's own password (issue #333, self-only).

    Self-only by construction — there is no `pk` in the URL, so this can
    only ever act on `request.user`. Uses Django's own `PasswordChangeForm`
    for the three stock fields (current password, new, confirm) and its
    `AUTH_PASSWORD_VALIDATORS` errors, reported per field via the write
    envelope's `errors` dict. `update_session_auth_hash()` on success is
    load-bearing (issue #333 user story 49): without it, changing your
    password signs out the session you just used to change it.
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
        return self.write_response(request, ok=True)
