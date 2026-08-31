"""Project-level view base classes shared across apps."""

from django.contrib.auth.mixins import LoginRequiredMixin


class BaseView(LoginRequiredMixin):
    """Mixin applied by every non-auth view in the project, so none can forget to auth-gate itself.

    Every view except the auth views themselves (login, logout, password
    reset) should mix this in ahead of its Django generic view class
    (issue #17 user story 17).
    """
