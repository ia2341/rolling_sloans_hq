from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy


class LoginView(auth_views.LoginView):
    """Email + password login for a `Person` with a set password."""

    template_name = 'identity/login.html'


class LogoutView(auth_views.LogoutView):
    """Clears the session and redirects to the login page."""

    next_page = reverse_lazy('identity:login')


class SetPasswordConfirmView(auth_views.PasswordResetConfirmView):
    """The set-password half of the invite flow (issue #24).

    Reuses Django's built-in token validation (single-use, expires per
    `PASSWORD_RESET_TIMEOUT`) under "set your password" wording rather than
    "reset your password", since these accounts have never had a password.
    """

    template_name = 'identity/set_password_form.html'
    success_url = reverse_lazy('identity:set-password-complete')


class SetPasswordCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'identity/set_password_complete.html'
