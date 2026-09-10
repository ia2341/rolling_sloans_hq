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

import logging
from datetime import timedelta
from urllib.parse import urljoin

from anymail.exceptions import AnymailError
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sessions.models import Session
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import AuthEmailRequest, LoginAttempt, Person

logger = logging.getLogger(__name__)

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


class CannotRevokeOwnAdminStatusError(Exception):
    """Raised by `apply_admin_status_change` when an admin attempts to revoke their own admin access."""


class CannotRevokeLastActiveAdminError(Exception):
    """Raised by `apply_admin_status_change` when revoking would leave no Person who is both `is_admin` and `is_active`."""


class CannotDeactivateSelfError(Exception):
    """Raised by `apply_person_deactivation` when an admin attempts to deactivate themself."""


class CannotDeactivateLastActiveAdminError(Exception):
    """Raised by `apply_person_deactivation` when deactivating would leave no Person who is both `is_admin` and `is_active`."""


class PersonIsDeactivatedError(Exception):
    """Raised by `resend_invite` when the target Person is deactivated (`is_active=False`)."""


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

    Stamps `invited_at` (issue #397) up front, inside the same transaction
    as the create — a failed inline send rolls both back together, and an
    on-commit send has already committed to being sent by the time this
    returns either way.
    """
    with transaction.atomic():
        person = Person.objects.create_user(email=email, name=name, password=None)
        person.invited_at = timezone.now()
        person.save(update_fields=['invited_at'])
        if send_via_on_commit:
            transaction.on_commit(lambda: send_invite_email(person))
        else:
            send_invite_email(person)
    return person


def add_person(*, name, email):
    """Create a Person with no usable password and no invite sent (issue #397).

    Lets an admin stage a semester roster — add people, assign their Roles
    and castings — ahead of actually inviting them. Unlike `invite_person()`
    this sends no mail and leaves `invited_at` unset, so
    `invite_status_for()` reads the result as `'not_yet_invited'`. Wrapped
    in `transaction.atomic()` for symmetry with `invite_person()`, even
    though there's no side effect here to protect, so a caller composing
    this inside a larger transaction (the roster edit Buffer) behaves the
    same either way.
    """
    with transaction.atomic():
        person = Person.objects.create_user(email=email, name=name, password=None)
    return person


def resend_invite(person):
    """Send (or re-send) the set-password invite to a Person who has never set a password.

    Its own service function rather than a second call to `invite_person()`,
    which *creates* a Person and must never run twice for the same address.
    `resend_invite()` takes an existing Person, regenerates the token (via
    `send_invite_email` -> `build_set_password_url`) and sends.

    Also the one path (issue #397) that turns a `'not_yet_invited'` Person
    `'invited'`: it doesn't care whether `invited_at` was already set, so
    the same call serves both the Roster editor's "Invite again" and the
    Person page's "Invite" action for someone never invited at all.

    Refuses a Person with a usable password: that member's recovery route is
    the self-serve forgot-password flow, and an admin must not be able to
    reset a working account from the roster.

    Refuses a deactivated Person (issue #469): without this check, a
    deactivated-but-never-accepted invite could still get a working
    set-password email sent to it, letting someone set a password on an
    account that's supposed to be locked out.

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
    if not person.is_active:
        raise PersonIsDeactivatedError(f'{person.email} is deactivated and cannot be invited')
    send_invite_email(person)
    person.invited_at = timezone.now()
    person.save(update_fields=['invited_at'])
    return person


def other_active_admins(person):
    """Return every Person other than `person` who is both `is_admin=True` and `is_active=True`.

    A standalone helper, not inlined into `apply_admin_status_change()`'s
    guard, because it answers a question a second lifecycle act needs
    unchanged: Deactivate (ADR 0017, the sibling issue in this line of
    work) refuses to deactivate the last Person who can still log in and
    administer, which is the identical "who else can" check this function
    already answers.
    """
    return Person.objects.filter(is_admin=True, is_active=True).exclude(pk=person.pk)


def apply_admin_status_change(*, target, is_admin, requesting_admin):
    """Set `target.is_admin` to `is_admin`, refusing to leave the band with no one who can administer it.

    Only a revoke (`is_admin=False` on a currently-admin `target`) is ever
    refused — granting admin access, and reapplying the status `target`
    already holds, carry neither risk this guards against, so both are a
    plain, unconditional write.

    Raises:
        CannotRevokeOwnAdminStatusError: `target` is `requesting_admin`
            themselves — an admin must have another admin revoke them,
            never themselves, so a mistake is always recoverable by
            someone.
        CannotRevokeLastActiveAdminError: `target` is the last remaining
            Person who is both `is_admin=True` and `is_active=True` —
            revoking them would leave no one able to log in and
            administer the band. Only checked when `target` is itself
            currently active: a deactivated admin isn't part of that
            count today, so clearing their flag can't be the revoke that
            empties it. This is `other_active_admins(target)` coming back
            empty, not "the last `is_admin=True` row".
    """
    if not is_admin and target.is_admin:
        if target.pk == requesting_admin.pk:
            raise CannotRevokeOwnAdminStatusError('You cannot revoke your own admin access.')
        if target.is_active and not other_active_admins(target).exists():
            raise CannotRevokeLastActiveAdminError(
                f'{target.name} is the last active admin and cannot be revoked.'
            )
    target.is_admin = is_admin
    target.save(update_fields=['is_admin'])
    return target


def _terminate_sessions_for(person):
    """Delete every live `Session` row belonging to `person` (ADR 0017).

    `SESSION_SAVE_EVERY_REQUEST=True` gives 30-day sliding sessions with no
    per-request `is_active` check, so a deactivated Person with an open tab
    would otherwise keep acting for up to 30 more days. `Session` stores an
    opaque encoded blob keyed by session key with no FK to `Person`, so
    finding this Person's sessions means decoding each still-live row and
    comparing `_auth_user_id` (the stock key `django.contrib.auth.login()`
    sets, stored as a string) against `person.pk`.
    """
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        if session.get_decoded().get('_auth_user_id') == str(person.pk):
            session.delete()


def apply_person_deactivation(*, target, requesting_admin):
    """Set `target.is_active = False`, block login, and end any live session immediately.

    Reuses `other_active_admins()` (built for `apply_admin_status_change()`)
    for the identical "who else can administer" guard, per ADR 0017.
    Deliberately not a Pending Buffer/Preview/Fallout surface: there is no
    server-computed derivation to preview, only a direct write plus a
    client-side confirmation dialog built from already-loaded data.

    Admin status, Roles, and Memberships are left untouched — Deactivate is
    reversible and discards nothing.

    Two admins deactivating each other at the same instant could otherwise
    both pass the guard before either write lands, emptying the active-admin
    set — so the whole check-then-write runs inside one transaction that
    row-locks every currently-active-admin row (in a stable `pk` order, so
    two overlapping calls can't deadlock on each other) before re-reading
    `target` and evaluating the guard against that locked, up-to-date state.

    Raises:
        CannotDeactivateSelfError: `target` is `requesting_admin`
            themselves — an admin must have another admin deactivate them.
        CannotDeactivateLastActiveAdminError: `target` is the last
            remaining Person who is both `is_admin=True` and
            `is_active=True` — deactivating them would leave no one able
            to log in and administer the band.
    """
    if target.pk == requesting_admin.pk:
        raise CannotDeactivateSelfError('You cannot deactivate yourself.')
    with transaction.atomic():
        list(Person.objects.filter(is_admin=True, is_active=True).order_by('pk').select_for_update())
        target = Person.objects.select_for_update().get(pk=target.pk)
        if target.is_admin and target.is_active and not other_active_admins(target).exists():
            raise CannotDeactivateLastActiveAdminError(
                f'{target.name} is the last active admin and cannot be deactivated.'
            )
        target.is_active = False
        target.save(update_fields=['is_active'])
        _terminate_sessions_for(target)
    return target


def apply_person_reactivation(target):
    """Set `target.is_active = True` and touch nothing else (ADR 0017).

    The pure inverse of `apply_person_deactivation()`: no fallout to
    compute, no guard to check, a plain apply-only call. Admin status,
    Roles, and Memberships are exactly as they were left by Deactivate.
    """
    target.is_active = True
    target.save(update_fields=['is_active'])
    return target


def invite_status_for(person):
    """Return `person`'s invite lifecycle status (issue #397): `'not_yet_invited'`, `'invited'`, or `'accepted'`.

    Checked in this order because `has_usable_password()` is the terminal
    state and takes precedence: `invited_at` stays set forever once an
    invite has ever been sent, so a Person who has since set a password
    would otherwise misread as merely `'invited'`.
    """
    if person.has_usable_password():
        return 'accepted'
    if person.invited_at is not None:
        return 'invited'
    return 'not_yet_invited'


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
        EmailDeliveryError: If the invitation email is not delivered — either
            `send_mail()` itself raised (e.g. a rejected `RESEND_API_KEY`, an
            unverified sender domain, or a Resend outage under the
            production `anymail.backends.resend.EmailBackend`) or it
            returned 0, meaning the backend accepted the call but delivered
            to no recipient.
    """
    set_password_url = build_set_password_url(person)
    subject = 'You have been invited to Rolling Sloans'
    body = render_to_string(
        'identity/invite_email.txt',
        {'person': person, 'set_password_url': set_password_url},
    )
    try:
        sent_count = send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [person.email])
    except AnymailError as error:
        logger.error('invite email to %s failed to send via %s: %s', person.email, type(error).__name__, error)
        raise EmailDeliveryError(f'invite email to {person.email} was not delivered') from error
    if not sent_count:
        raise EmailDeliveryError(f'invite email to {person.email} was not delivered')


def client_ip(request):
    """Return the requesting client's IP address, for the rate-limit keys (issue #327, #362).

    No reverse proxy is configured in front of this project, so
    `REMOTE_ADDR` is the real client address; there is no `X-Forwarded-For`
    to trust. Shared by the server-rendered `LoginView` and the SPA's
    `LoginApiView`, so both enforce the same rate limit from the same key.
    """
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


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
