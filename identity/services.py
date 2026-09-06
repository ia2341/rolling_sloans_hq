"""The invite flow, its recovery path, and the project's first rate limits (issue #327).

`invite_person` creates the `Person` with an unusable password and emails a
one-time set-password link. The link's token comes from Django's
`default_token_generator` (a `PasswordResetTokenGenerator`), so it is
single-use (the hash incorporates the password field, invalidating it the
moment a password is set) and expires per `PASSWORD_RESET_TIMEOUT`.

`resend_invite` recovers a dead invite without a second `Person`. Rate
limiting (`is_login_rate_limited` / `is_auth_email_rate_limited`) lives here
too, beside the send and beside the authenticate call, per the project's
irreversible-side-effect convention: a limit in a view is a limit the next
view forgets.
"""

from datetime import timedelta
from urllib.parse import urljoin

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import AuthEmailRequest, LoginAttempt, Person

# Both limits are windowed row counts, not a cache (see LoginAttempt's and
# AuthEmailRequest's docstrings for why). Thresholds are deliberately
# generous: they exist to stop unlimited guessing/quota-burning, not to
# annoy a member who mistypes a password twice.
LOGIN_ATTEMPT_WINDOW = timedelta(minutes=15)
MAX_FAILED_LOGIN_ATTEMPTS = 10

AUTH_EMAIL_WINDOW = timedelta(minutes=15)
MAX_AUTH_EMAILS = 5


class EmailDeliveryError(Exception):
    """Raised when an invite email was not actually delivered to any recipient."""


class AlreadyHasPasswordError(Exception):
    """Raised by `resend_invite` when the target Person already has a usable password."""


def invite_person(*, name, email, send_via_on_commit=False):
    """Create an allowlisted Person with no usable password and email them an invite.

    The Person creation and invite email are wrapped in a single atomic
    transaction: if the email fails to send (either `send_mail` raises, or
    it returns 0, meaning Django accepted the call but delivered nothing),
    the Person row is rolled back rather than left committed with an
    undelivered invite. This keeps `email`'s uniqueness constraint from
    blocking a retry after a failed invite.

    `send_via_on_commit` threads the one behavioral difference the roster's
    Pending Buffer apply (#336) needs, rather than forking this function:
    the default (`False`) sends inline, so a failed send still rolls back
    the Person row (today's standalone admin invite). Passing `True`
    registers the send with `transaction.on_commit()` instead, so an admin
    Preview's rollback (ADR 0008) discards the send along with everything
    else — but that mode forgoes rollback-on-send-failure, since there is
    nothing left to roll back once the transaction has already committed.
    """
    with transaction.atomic():
        person = Person.objects.create_user(email=email, name=name, password=None)
        if send_via_on_commit:
            transaction.on_commit(lambda: send_invite_email(person))
        else:
            send_invite_email(person)
    return person


def resend_invite(person):
    """Re-send the set-password invite to a Person who has never set a password.

    Its own service function rather than a second call to `invite_person()`,
    which *creates* a Person and must never run twice for the same address.
    `resend_invite()` takes an existing Person, regenerates the token (via
    `send_invite_email` -> `build_set_password_url`) and re-sends.

    Refuses a Person with a usable password: that member's recovery route is
    the self-serve forgot-password flow, and an admin must not be able to
    reset a working account from the roster.

    Because `default_token_generator` incorporates `password` and
    `last_login`, a newly issued token does not invalidate the previous one
    by itself — the previous link stays live until it expires on its own.

    Performs no creating write, so unlike `invite_person()` the send here is
    inline with no `transaction.on_commit()` wrapper: there is no Person row
    to roll back if the send fails, so there is nothing for a wrapper to
    protect.
    """
    if person.has_usable_password():
        raise AlreadyHasPasswordError(f'{person.email} has already set a password')
    send_invite_email(person)
    return person


def people_with_invite_status():
    """Return every Person ordered by name, each annotated with `is_pending_invite`.

    `is_pending_invite` (the negation of `has_usable_password()`) is a
    derived read, so it's computed here rather than in the roster template,
    per the project's "derived reads live in services" convention.
    """
    people = list(Person.objects.order_by('name'))
    for person in people:
        person.is_pending_invite = not person.has_usable_password()
    return people


def build_set_password_url(person):
    """Build the absolute, single-use set-password link for a Person (invite or forgot-password)."""
    uidb64 = urlsafe_base64_encode(force_bytes(person.pk))
    token = default_token_generator.make_token(person)
    path = reverse('identity:set-password-confirm', kwargs={'uidb64': uidb64, 'token': token})
    return urljoin(settings.SITE_URL, path)


def send_invite_email(person):
    """
    Send the person an invitation containing a link to set their password.

    Parameters:
        person: The person who will receive the invitation.

    Raises:
        EmailDeliveryError: If the invitation email is not delivered.
    """
    set_password_url = build_set_password_url(person)
    subject = 'You have been invited to Rolling Sloans'
    body = render_to_string(
        'identity/invite_email.txt',
        {'person': person, 'set_password_url': set_password_url},
    )
    sent_count = send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [person.email])
    if not sent_count:
        raise EmailDeliveryError(f'invite email to {person.email} was not delivered')


def record_login_attempt(*, email, ip_address, was_successful):
    """Record one sign-in POST for the failed-sign-in rate limit."""
    LoginAttempt.objects.create(email=email, ip_address=ip_address, was_successful=was_successful)


def is_login_rate_limited(*, email, ip_address):
    """Return True if either `email` or `ip_address` has too many recent failed sign-ins.

    Keyed on both independently (an OR, not an AND) so neither one member's
    address nor one attacker's host is an unlimited guessing target.
    """
    window_start = timezone.now() - LOGIN_ATTEMPT_WINDOW
    recent_failures = LoginAttempt.objects.filter(was_successful=False, created_at__gte=window_start)
    failures_for_email = recent_failures.filter(email=email).count()
    failures_for_ip = recent_failures.filter(ip_address=ip_address).count()
    return failures_for_email >= MAX_FAILED_LOGIN_ATTEMPTS or failures_for_ip >= MAX_FAILED_LOGIN_ATTEMPTS


def record_auth_email_request(*, email, ip_address):
    """Record one outbound-auth-email request (reset request or resend-invite) for the quota rate limit."""
    AuthEmailRequest.objects.create(email=email, ip_address=ip_address)


def is_auth_email_rate_limited(*, email, ip_address):
    """Return True if either `email` or `ip_address` has requested too many recent auth emails.

    Guards Resend quota and sending reputation, not enumeration: an
    unauthenticated endpoint that triggers third-party email can burn both.
    """
    window_start = timezone.now() - AUTH_EMAIL_WINDOW
    recent_requests = AuthEmailRequest.objects.filter(created_at__gte=window_start)
    requests_for_email = recent_requests.filter(email=email).count()
    requests_for_ip = recent_requests.filter(ip_address=ip_address).count()
    return requests_for_email >= MAX_AUTH_EMAILS or requests_for_ip >= MAX_AUTH_EMAILS
