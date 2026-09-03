"""Project-level view base classes shared across apps."""

from typing import ClassVar

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import HttpResponseForbidden


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
