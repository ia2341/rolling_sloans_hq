from django.contrib.auth import views as auth_views

from .services import client_ip, is_login_rate_limited, record_login_attempt


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
