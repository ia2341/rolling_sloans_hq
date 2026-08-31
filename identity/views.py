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


class PasswordResetRequestView(auth_views.PasswordResetView):
    """The 'forgot password' request half of the self-serve reset flow (issue #26)."""

    template_name = 'identity/password_reset_form.html'
    email_template_name = 'identity/password_reset_email.txt'
    subject_template_name = 'identity/password_reset_subject.txt'
    success_url = reverse_lazy('identity:password-reset-done')


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    """Shown after a reset request regardless of whether the email is known, to avoid leaking that."""

    template_name = 'identity/password_reset_done.html'


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    """The confirm half of the reset flow: submitting a new password invalidates the link (issue #26)."""

    template_name = 'identity/password_reset_confirm.html'
    success_url = reverse_lazy('identity:password-reset-complete')


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'identity/password_reset_complete.html'
