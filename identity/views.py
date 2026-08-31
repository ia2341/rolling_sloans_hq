from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy


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
