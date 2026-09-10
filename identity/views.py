from django.contrib.auth import views as auth_views

from .services import (
    client_ip,
    is_auth_email_rate_limited,
    is_login_rate_limited,
    record_auth_email_request,
    record_login_attempt,
)


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
        ip_address = client_ip(request)
        if is_login_rate_limited(email=email, ip_address=ip_address):
            return self.render_to_response(self.get_context_data(form=self.get_form(), throttled=True))
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        """Record the successful attempt, then defer to Django's own login + session-cycle handling."""
        record_login_attempt(
            email=form.cleaned_data.get('username', ''),
            ip_address=client_ip(self.request),
            was_successful=True,
        )
        return super().form_valid(form)

    def form_invalid(self, form):
        """Record the failed attempt, then defer to Django's own generic-error rendering."""
        record_login_attempt(
            email=self.request.POST.get('username', ''),
            ip_address=client_ip(self.request),
            was_successful=False,
        )
        return super().form_invalid(form)


class LogoutView(auth_views.LogoutView):
    """Clears the session and redirects to the SPA's login page (issue #362).

    A literal path, not `reverse_lazy('identity:login')`: `/login` is an
    SPA client route (`frontend/src/routes.tsx`), not a Django URL name, so
    there is nothing to reverse. The server-rendered `identity:login`
    template still exists and still works if visited directly, but it's no
    longer where a signed-out session should land.
    """

    next_page = '/login'


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
        ip_address = client_ip(self.request)
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
