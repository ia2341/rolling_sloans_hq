"""Project-level view base classes shared across apps."""

from django.contrib.auth.mixins import LoginRequiredMixin
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
