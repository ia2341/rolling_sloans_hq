"""Person creation, the legacy invite flow, and the project's first rate limits (issue #327, #482, #483, ADR 0018).

`create_person_with_temp_password` (issue #482) is the current creation
path: it sets a real, immediately-usable password and flags the Person
`must_change_password`, returning the plaintext once for an admin to relay
verbally or by text — no email involved at all. `apply_password_reset`
(issue #483) is its sibling for an *existing* Person: same generated
temp password and forced-change flag, reached from `/members/<pk>/`
instead of account creation.

`invite_person`/`add_person`/`resend_invite` are the legacy email-invite
path ADR 0018 replaces. They create the `Person` with an unusable password
and (for `invite_person`/`resend_invite`) email a one-time set-password
link — the link's token comes from Django's `default_token_generator` (a
`PasswordResetTokenGenerator`), so it is single-use (the hash incorporates
the password field, invalidating it the moment a password is set) and
expires per `PASSWORD_RESET_TIMEOUT`. Kept, unused by the Roster editor's
creation path as of #482, until the follow-on issue named in ADR 0018
retires them outright.

Rate limiting (`is_login_rate_limited` / `is_auth_email_rate_limited`) lives
here too, beside the send and beside the authenticate call, per the
project's irreversible-side-effect convention: a limit in a view is a limit
the next view forgets.
"""

import logging
import string
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
from django.utils.crypto import get_random_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import AuthEmailRequest, LoginAttempt, Person

logger = logging.getLogger(__name__)

# ADR 0018: a temp password is read aloud or typed from a text message, not
# copy-pasted through a link, so the alphabet drops every character easily
# confused with another when spoken or handwritten (0/O, 1/l/I).
TEMP_PASSWORD_LENGTH = 12
TEMP_PASSWORD_ALPHABET = ''.join(
    character for character in string.ascii_letters + string.digits
    if character not in '0O1lI'
)

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


class CannotResetOwnPasswordError(Exception):
    """Raised by `apply_password_reset` when an admin attempts to reset their own password through this endpoint.

    An admin who knows their current password has the self-serve
    change-password flow (`PasswordChangeApiView`) instead; this endpoint
    exists for resetting *other* members, so a self-reset here would just
    be a confusing second way to do the same thing with none of the
    current-password confirmation the self-serve flow requires.
    """


def generate_temp_password():
    """Return a fresh temp password string (ADR 0018): 12 characters, no visually-ambiguous ones."""
    return get_random_string(TEMP_PASSWORD_LENGTH, allowed_chars=TEMP_PASSWORD_ALPHABET)


def create_person_with_temp_password(*, name, email):
    """Create a Person with a real, immediately-usable temp password, forcing a change on first use (issue #482, ADR 0018).

    The one creation path this project uses now: unlike `invite_person()`'s
    unusable password plus emailed link, this calls `set_password()` with a
    freshly generated plaintext directly, so the account is loggable-in the
    instant this returns — there is no separate "accept the invite" step
    left to wait on. `must_change_password=True` is the durable record that
    the password was admin-generated rather than member-chosen; it's
    cleared the moment the member successfully sets their own (issue #333's
    change-password flow).

    Sends no mail and reaches no external service at all, so unlike
    `invite_person()` there's nothing here that needs `transaction.
    on_commit()` protection during an ADR-0008 Preview: a rolled-back
    transaction discards the Person row (and the temp password with it)
    for free.

    Returns:
        A `(person, temp_password)` tuple — the plaintext is returned
        exactly once and never persisted or logged; callers must relay it
        to the admin's response and nowhere else.
    """
    with transaction.atomic():
        temp_password = generate_temp_password()
        person = Person.objects.create_user(email=email, name=name, password=temp_password)
        person.must_change_password = True
        person.save(update_fields=['must_change_password'])
    return person, temp_password


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


def apply_password_reset(*, target, requesting_admin):
    """Reset `target`'s password to a freshly generated temp password, forcing a change on next use (issue #483, ADR 0018).

    The admin-relayed reset path this ADR describes: works on anyone, at
    any time, replacing `resend_invite()`'s narrower job of recovering
    only a never-accepted invite. Sets a real, immediately-usable password
    via `set_password()` (not an unusable one, unlike `invite_person()`)
    so the target can sign in the instant the admin relays it, and flags
    `must_change_password=True` — the same durable "was admin-generated"
    record `create_person_with_temp_password()` sets, cleared the moment
    the member successfully changes their own password.

    `set_password()` rotates the session auth hash Django embeds in every
    session, so any of `target`'s existing sessions are invalidated as a
    side effect on their next request — no separate session-termination
    step is needed here the way `apply_person_deactivation()` needs one.

    Raises:
        PersonIsDeactivatedError: `target` is deactivated (`is_active=False`)
            — mirrors `resend_invite()`'s identical refusal, so a locked-out
            account can't be handed a working credential through this door
            either.
        CannotResetOwnPasswordError: `target` is `requesting_admin`
            themselves — self-reset must go through the self-serve
            change-password flow instead, which confirms the current
            password before accepting a new one.

    Returns:
        A `(target, temp_password)` tuple — the plaintext is returned
        exactly once and must be relayed in the caller's response, never
        logged or persisted.
    """
    if target.pk == requesting_admin.pk:
        raise CannotResetOwnPasswordError('You cannot reset your own password here — use Change password instead.')
    if not target.is_active:
        raise PersonIsDeactivatedError(f'{target.email} is deactivated and cannot have their password reset')
    temp_password = generate_temp_password()
    target.set_password(temp_password)
    target.must_change_password = True
    target.save(update_fields=['password', 'must_change_password'])
    return target, temp_password


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
    """Return `person`'s credential lifecycle status (issue #482, ADR 0018): `'must_change_password'` or `'active'`.

    Replaces the old three-state `'not_yet_invited'`/`'invited'`/
    `'accepted'` read of `has_usable_password()`/`invited_at`: under ADR
    0018 a Person is loggable-in from the moment they're created (a real
    temp password, never an unusable one), so the only remaining lifecycle
    fact worth surfacing is whether that password is still the
    admin-generated one they haven't replaced yet.
    """
    return 'must_change_password' if person.must_change_password else 'active'


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
