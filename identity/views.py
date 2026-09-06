from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View

from config.views import AdminRequiredMixin

from .forms import PersonInviteForm
from .models import Person
from .services import (
    AlreadyHasPasswordError,
    invite_person,
    is_auth_email_rate_limited,
    is_login_rate_limited,
    people_with_invite_status,
    record_auth_email_request,
    record_login_attempt,
    resend_invite,
)


def _client_ip(request):
    """Return the requesting client's IP address, for the rate-limit keys.

    No reverse proxy is configured in front of this project, so
    `REMOTE_ADDR` is the real client address; there is no `X-Forwarded-For`
    to trust.
    """
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


class LoginView(auth_views.LoginView):
    """Email + password login for a `Person` with a set password (#327).

    Layers the project's first rate limit on top of Django's stock
    `AuthenticationForm`, which already returns one generic message for both
    "no such user" and "wrong password" — kept as-is, per #327, so a failed
    attempt never tells the caller which half was wrong. A successful login
    cycles the session key for free: `django.contrib.auth.login()` (called
    by `form_valid`) already does this.
    """

    template_name = 'identity/login.html'

    def post(self, request, *args, **kwargs):
        """Refuse a rate-limited (email, IP) pair before touching credentials at all; otherwise defer to Django's flow."""
        email = request.POST.get('username', '')
        ip_address = _client_ip(request)
        if is_login_rate_limited(email=email, ip_address=ip_address):
            return self.render_to_response(self.get_context_data(form=self.get_form(), throttled=True))
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        """Record the successful attempt, then defer to Django's own login + session-cycle handling."""
        record_login_attempt(
            email=form.cleaned_data.get('username', ''),
            ip_address=_client_ip(self.request),
            was_successful=True,
        )
        return super().form_valid(form)

    def form_invalid(self, form):
        """Record the failed attempt, then defer to Django's own generic-error rendering."""
        record_login_attempt(
            email=self.request.POST.get('username', ''),
            ip_address=_client_ip(self.request),
            was_successful=False,
        )
        return super().form_invalid(form)


class LogoutView(auth_views.LogoutView):
    """Clears the session and redirects to the login page."""

    next_page = reverse_lazy('identity:login')


class SetPasswordConfirmView(auth_views.PasswordResetConfirmView):
    """The single token route serving both the invite and the forgot-password flow (#327).

    Merges the previous `SetPasswordConfirmView` and `PasswordResetConfirmView`
    into one: `has_usable_password()` on the target account picks the
    copy — "Set your password" for a never-set-password invitee, "Choose a
    new password" for someone who has reset before — and a successful POST
    renders inline on the same page instead of redirecting to a separate
    "done" page, collapsing two routes into this one.
    """

    template_name = 'identity/set_password_form.html'
    post_reset_login = False

    def get_context_data(self, **kwargs):
        """Add `has_usable_password` (for the invite-vs-reset copy) and clear `success_url` so nothing redirects."""
        context = super().get_context_data(**kwargs)
        context['has_usable_password'] = bool(self.user and self.user.has_usable_password())
        context['done'] = getattr(self, '_done', False)
        return context

    def form_valid(self, form):
        """Save the new password and re-render this same page with `done=True`, rather than redirecting."""
        form.save()
        self._done = True
        return self.render_to_response(self.get_context_data(form=form))


class PasswordResetRequestView(auth_views.PasswordResetView):
    """The 'forgot your password' request page (#327): one page, no separate "done" redirect.

    Rate-limited on the outbound-email quota limit, keyed on the submitted
    address and the requesting IP: an unauthenticated endpoint that
    triggers third-party email can burn Resend's quota and sending
    reputation, which would take down all authentication, invites
    included. The response is identical whether the address exists,
    whether the send actually happened, or (see `throttled` below) whether
    the request was refused for quota reasons — none of those must become
    an oracle for whether an account exists.
    """

    template_name = 'identity/password_reset_form.html'
    email_template_name = 'identity/password_reset_email.txt'
    subject_template_name = 'identity/password_reset_subject.txt'

    def form_valid(self, form):
        """Send the reset email (unless rate-limited) and re-render this same page with `sent=True`."""
        email = form.cleaned_data['email']
        ip_address = _client_ip(self.request)
        if is_auth_email_rate_limited(email=email, ip_address=ip_address):
            return self.render_to_response(self.get_context_data(form=form, throttled=True))
        record_auth_email_request(email=email, ip_address=ip_address)
        form.save(
            email_template_name=self.email_template_name,
            subject_template_name=self.subject_template_name,
            use_https=self.request.is_secure(),
            request=self.request,
        )
        return self.render_to_response(self.get_context_data(form=form, sent=True))


class PeopleView(AdminRequiredMixin, View):
    """`/manage/people/`: an admin lists Persons, invites new ones, and re-invites pending ones (#327, issue #59)."""

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
        """Build context: the Person roster (with pending-invite status) plus the invite form."""
        return {
            'people': people_with_invite_status(),
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


class PersonResendInviteView(AdminRequiredMixin, View):
    """`/manage/people/<id>/resend-invite/`: an admin re-sends a dead invite link (#327).

    Refused for a Person who has already set a password — that member's
    recovery route is the self-serve forgot-password flow, not an admin
    reset from the roster.
    """

    def post(self, request, pk):
        """Re-invite the target Person, or redirect with a refusal message if they already have a password."""
        person = get_object_or_404(Person, pk=pk)
        try:
            resend_invite(person)
        except AlreadyHasPasswordError:
            messages.error(request, f'{person.email} has already set a password.')
        else:
            messages.success(request, f'Re-sent invite to {person.email}.')
        return redirect('identity:people')
