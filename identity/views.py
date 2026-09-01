from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View

from config.views import AdminRequiredMixin

from .forms import PersonInviteForm
from .models import Person
from .services import invite_person


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


class PasswordChangeView(auth_views.PasswordChangeView):
    """Self-serve password change from the profile page (issue #90), gated by the member's current password.

    Distinct from the token-based forgot-password flow above: this requires
    knowing the current password, so a hijacked session alone can't lock the
    real member out by changing it.
    """

    template_name = 'identity/password_change_form.html'
    success_url = reverse_lazy('identity:password-change-done')


class PasswordChangeDoneView(auth_views.PasswordChangeDoneView):
    """Shown after a successful password change."""

    template_name = 'identity/password_change_done.html'


class PeopleView(AdminRequiredMixin, View):
    """`/manage/people/`: an admin lists Persons and invites new ones (issue #59, issue #17 user story 13)."""

    template_name = 'identity/people.html'

    def get(self, request):
        """Render the roster of existing Persons alongside an empty invite form."""
        return render(request, self.template_name, self._build_context())

    def post(self, request):
        """Validate the invite form and create a Person via `invite_person()`, or re-render with errors."""
        form = PersonInviteForm(request.POST)
        if form.is_valid():
            invite_person(name=form.cleaned_data['name'], email=form.cleaned_data['email'])
            messages.success(request, f"Invited {form.cleaned_data['email']}.")
            return redirect('identity:people')
        return render(request, self.template_name, self._build_context(form))

    def _build_context(self, form=None):
        """Build context: the Person roster ordered by name, plus the invite form (fresh if none is given)."""
        return {
            'people': Person.objects.order_by('name'),
            'form': form or PersonInviteForm(),
        }


class PersonToggleAdminView(AdminRequiredMixin, View):
    """`/manage/people/<id>/toggle-admin/`: an admin flips a Person's `is_admin` flag (issue #59, issue #17 user story 13)."""

    def post(self, request, pk):
        """Flip the target Person's is_admin flag and redirect back to the roster with a success message."""
        person = get_object_or_404(Person, pk=pk)
        person.is_admin = not person.is_admin
        person.save(update_fields=['is_admin'])
        messages.success(request, f'Updated admin access for {person.email}.')
        return redirect('identity:people')
