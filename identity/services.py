"""Person creation and the project's first rate limit (issue #327, #482, #483, ADR 0018).

`create_person_with_temp_password` (issue #482) is the current creation
path: it sets a real, immediately-usable password and flags the Person
`must_change_password`, returning the plaintext once for an admin to relay
verbally or by text — no email involved at all. `apply_password_reset`
(issue #483) is its sibling for an *existing* Person: same generated
temp password and forced-change flag, reached from `/members/<pk>/`
instead of account creation.

The email-based invite/reset flow ADR 0018 replaced is fully retired as
of issue #485 — there is no emailed link anywhere in this project any
more.

Rate limiting (`is_login_rate_limited`) lives here too, beside the
authenticate call, per the project's irreversible-side-effect convention: a
limit in a view is a limit the next view forgets.
"""

import string
from datetime import timedelta

from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string

from .models import LoginAttempt, Person

# ADR 0018: a temp password is read aloud or typed from a text message, not
# copy-pasted through a link, so the alphabet drops every character easily
# confused with another when spoken or handwritten (0/O, 1/l/I).
TEMP_PASSWORD_LENGTH = 12
TEMP_PASSWORD_ALPHABET = ''.join(
    character for character in string.ascii_letters + string.digits
    if character not in '0O1lI'
)

# A windowed row count, not a cache (see LoginAttempt's docstring for why).
# The threshold is deliberately generous: it exists to stop unlimited
# guessing, not to annoy a member who mistypes a password twice.
LOGIN_ATTEMPT_WINDOW = timedelta(minutes=15)
MAX_FAILED_LOGIN_ATTEMPTS = 10


class CannotRevokeOwnAdminStatusError(Exception):
    """Raised by `apply_admin_status_change` when an admin attempts to revoke their own admin access."""


class CannotRevokeLastActiveAdminError(Exception):
    """Raised by `apply_admin_status_change` when revoking would leave no Person who is both `is_admin` and active."""


class CannotDeactivateSelfError(Exception):
    """Raised by `apply_person_deactivation` when an admin attempts to deactivate themself."""


class CannotDeactivateLastActiveAdminError(Exception):
    """Raised by `apply_person_deactivation` when deactivating would leave no Person who is both `is_admin` and `is_active`."""


class PersonIsDeactivatedError(Exception):
    """Raised by `apply_password_reset` when the target Person is deactivated (`is_active=False`)."""


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

    The one creation path this project uses: this calls `set_password()`
    with a freshly generated plaintext directly, so the account is
    loggable-in the instant this returns. `must_change_password=True` is
    the durable record that the password was admin-generated rather than
    member-chosen; it's cleared the moment the member successfully sets
    their own (issue #333's change-password flow).

    Sends no mail and reaches no external service at all, so there's
    nothing here that needs `transaction.on_commit()` protection during
    an ADR-0008 Preview: a rolled-back transaction discards the Person row
    (and the temp password with it) for free.

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


def apply_password_reset(*, target, requesting_admin):
    """Reset `target`'s password to a freshly generated temp password, forcing a change on next use (issue #483, ADR 0018).

    The admin-relayed reset path this ADR describes: works on anyone, at
    any time. Sets a real, immediately-usable password via `set_password()`
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
            — a locked-out account can't be handed a working credential
            through this door.
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

    Under ADR 0018 a Person is loggable-in from the moment they're created
    (a real temp password, never an unusable one), so the only lifecycle
    fact worth surfacing is whether that password is still the
    admin-generated one they haven't replaced yet.
    """
    return 'must_change_password' if person.must_change_password else 'active'


def clear_must_change_password(person):
    """Set `person.must_change_password = False` (issue #484): the one place that clears the temp-password nag.

    Mirrors `invite_status_for()`'s "one function decides" convention.
    Called only from `PasswordChangeApiView`'s success path — any
    successful self-serve password change, temp or not, retires the nag,
    since the whole point of the flag is "hasn't replaced the
    admin-generated password yet".
    """
    person.must_change_password = False
    person.save(update_fields=['must_change_password'])
    return person


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
