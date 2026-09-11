# Credentials are relayed by an admin as a one-time-revealed temp password, not emailed

`invite_person()`'s emailed set-password link and the self-serve forgot-password flow are retired. In their place: an admin creates a `Person` or resets an existing one through the same web actions as today, the system generates a temp password and reveals its plaintext exactly once in that synchronous response, and the admin relays it to the member verbally or by text. No member receives a credential email again, ever.

This reverses only the *delivery mechanism* ADR 0013 chose, not the authentication scheme itself. ADR 0013 is not edited to reflect this — it stands as the record of the decision that held until now, aside from one stale surface reference fixed below — and its "no forced-password-change interceptor" and "emailing a temporary password was rejected" passages are the specific two calls this ADR overturns. Everything else 0013 recorded — real passwords over passwordless codes, `ModelBackend`, the 30-day sliding session, `is_login_rate_limited()` — is unaffected and still governs.

## Why now, for a 25-person band

The admin already personally onboards every member — there is no cohort large enough to make an email round-trip cheaper than a text message the admin was going to send anyway to welcome them. Against that, the emailed link carried a real ongoing cost this project was paying for no longer-justified benefit: a verified sending domain and a live Resend key (issue #381), a `RESEND_API_KEY`-shaped single point of failure on the recovery path (0013 itself named this: "an outage at Resend... means no member can complete a password reset"), and the deliverability fragility of any transactional email — spam folders, corporate mail filters, a mistyped address at invite time silently swallowing the one link a member had. None of that risk buys anything a 25-person band needs, because the admin is always one text message away from any member regardless. This issue supersedes #381 entirely: once this ADR and its follow-on land, there is no sending domain left to verify.

## What's reversed, and what's not

**Reversed:**
- The emailed one-time set-password link (`invite_person()`'s `PasswordResetTokenGenerator`-based email) — replaced by a temp password revealed once in the admin's own response.
- The self-serve forgot-password request (`password-reset/`) — a locked-out member no longer has a working self-serve path; they contact an admin. The route itself is *kept*, not deleted, as a dead-end informational page telling the member to contact an admin, so an old bookmark or a search-engine-cached link doesn't 404 — it just stops doing anything.
- `resend_invite()`'s reason to exist — its whole job (recovering a dead invite without creating a second `Person`) collapses into the one Reset-password action described below, which works on anyone at any time, not just a stuck invite.
- `is_auth_email_rate_limited()` and the `AuthEmailRequest` model — both existed to throttle an unauthenticated endpoint that triggered a third-party send (0013: "a way to burn Resend's quota and sending reputation"). With no more outbound auth email, there is nothing left for this limiter to protect. Retirement is left to the follow-on implementation issue below, not actioned by this documentation-only issue.
- 0013's "no forced-password-change interceptor exists, and none was built" and "emailing a temporary password was rejected for the same shape of reason" — both were correct calls *given an emailed link was the alternative being weighed against*. A temp password relayed by a human, not sitting in an inbox indefinitely, does not carry the risk 0013 was pricing in, and pairs naturally with exactly the forced-change gate 0013 declined to build.

**Not reversed:**
- Passwords over passwordless codes (0013's central call).
- `ModelBackend`, the 30-day sliding session, `SESSION_SAVE_EVERY_REQUEST`.
- `is_login_rate_limited()` and `LoginAttempt` — unrelated to email; still the only thing standing between a password scheme and an unthrottled online guessing attack (0013: "a password is online permanently... every guess against it accumulates with no expiry ever pulling it out of reach").
- `PASSWORD_RESET_TIMEOUT` as a concept for token-scoped links stays defined, but nothing in this project issues such a link anymore after the follow-on lands (`identity/urls.py`'s `set-password/<uidb64>/<token>/` route and view are retired along with `invite_person()`'s email path — a decision for the follow-on issue's own scope, not re-litigated here).

## The single-admin lockout question

Today's guards (`apply_person_deactivation`, `apply_admin_status_change`) already refuse to let the active-admin count reach zero once there are 2+ admins, but say nothing about the one-admin case that's realistic for this project: one admin seeded directly at first production deploy, or a band that has only ever had one. Under this ADR, self-serve recovery is gone and an admin-triggered reset requires *another* active admin to click Reset — so if the sole active admin forgets their own password, there is no web-UI path back in at all.

**Decision: a `manage.py` command, deliberately kept outside the web UI.** `manage.py reset_password <email>` — reachable only by an operator with server/DB access — generates a temp password the same way the web action does, sets the same forced-change flag, and prints the plaintext to stdout for the operator to relay. It carries none of the admin-count guardrail the web action needs, because the guardrail exists to stop a *web session* from talking itself into a lockout; an operator who already has shell/DB access on the production host has already cleared a higher bar than any in-app permission check could add.

Rejected alternatives:
- **A documented "always maintain 2+ admins" operational rule, enforced by nothing.** Rejected because it's a promise with no backstop: the day it's violated (an admin transitions off the band with no successor yet promoted, or a second admin account is simply never created) is exactly the day this ADR's whole point — no more email-based recovery — turns a forgotten password into a total lockout with no mechanical way out. A break-glass command costs one file and is correct regardless of how many admins currently exist.
- **Point the operator at Django admin's existing built-in password-change form instead of a bespoke command.** Rejected: it works but sets a real password directly with no temp-password/forced-change semantics, so the sole admin's recovery path would look different in kind from every other member's reset — worth the small duplication to keep one mental model for "how does a Person's password get reset."

## The temp password and its lifecycle

A temp password is a real, permanent password from the instant it's set — not a short-lived token, not something that self-invalidates. What makes it "temp" is a `must_change_password` boolean on `Person`: set whenever an admin action (or the break-glass command) generates one, cleared the moment the member successfully changes their password through the existing SPA change-password flow (issue #333). The two ideas don't conflict — a password can be fully functional for signing in *and* be flagged to force a change on first use; those are independent facts about the same credential, not alternatives.

The generated password itself: `django.utils.crypto.get_random_string()`, long enough to be secure when read aloud or typed from a text message (twelve characters), drawn from an alphabet that drops visually-ambiguous characters (`0`/`O`, `1`/`l`/`I`) since it travels by voice or SMS, not copy-paste through a link.

The gate is a request-level check, not a client-side redirect the SPA could choose to skip — mirroring how auth is already structural in this project (`config/views.py:BaseView`'s `LoginRequiredMixin`, `AdminRequiredMixin`) rather than a per-view opt-in. A `Person` with `must_change_password=True` is redirected off every authenticated route except the change-password endpoint itself until the flag clears.

## Consequences

- No sending domain, no ESP dependency, no `RESEND_API_KEY` single point of failure on the recovery path — issue #381 is obsolete once the follow-on lands.
- A member's onboarding and recovery now depend on the admin being reachable by voice or text at the moment of need, not on email arriving eventually — a real tradeoff for a 25-person band whose admin is already the onboarding point of contact for everyone, but one that would not scale to a larger or less centrally-run group.
- The admin transiently knows every member's password at the moment of relay. Accepted: this project already trusts the admin with far more (adjudicating Conflict reasons, `is_admin` grant/revoke); a five-person band's trust model already assumes this much.
- A locked-out sole admin has no in-app recovery path at all — only `manage.py reset_password`, which requires whoever already holds server/DB access to run it. Accepted as the deliberate cost of removing the mailbox as a universal backstop.
- `password-reset/` remains a live URL that does nothing but point at an admin — a small piece of permanently-dead surface area, kept only so an old link doesn't 404.

## Follow-on: `admin-triggered password reset` implementation issue

This ADR is documentation-only; the following is filed as a separate, blocked-by-this-issue implementation ticket, with its shape decided here so it can be filed as acceptance criteria rather than open questions:

- **Person-page Reset action** — `/members/:personId` gets a "Reset password" admin action in the same slot as Deactivate/Reactivate (#469's pattern), client-confirmed the same way. Unlike self-deactivation and self-revoke, **self-reset is allowed** — it introduces no lockout risk the way those two do, since it can't zero out the admin count or otherwise remove access. *(Narrowed by issue #483: self-reset is refused server-side after all — not for lockout reasons, but because an admin who knows their current password already has a self-serve path, `PasswordChangeApiView`, that confirms it; Reset exists for resetting someone else.)*
- **Reveal UI** — both the Roster editor's create-Person action and the Reset-password action return the temp password inline in the synchronous response: a copyable field with a "shown once — relay it now" warning, dismissed by the admin once relayed, never persisted client-side beyond the page session.
- **Reset collapses resend_invite()'s job** — no separate "regenerate" concept: Reset works on anyone, at any time, so a botched relay or a still-locked-out member is handled by clicking Reset again.
- **`must_change_password`** — new boolean field + migration on `Person`; set by every temp-password-generating path (create, reset, break-glass command); cleared by a successful change-password submission; enforced by a request-level gate alongside `BaseView`/`AdminRequiredMixin`, not a client-only redirect.
- **`manage.py reset_password <email>`** — break-glass path, no admin-count guardrail, prints the plaintext for the operator to relay.
- **Retirement** — `invite_person()`'s email send, `resend_invite()`, `is_auth_email_rate_limited()`, `AuthEmailRequest`, the `set-password/<uidb64>/<token>/` route/view, and the invite/reset email templates are all removed; `password-reset/` is kept as a static contact-an-admin page per this ADR.
- **Generation** — `get_random_string(12, allowed_chars=<ambiguity-excluded alphabet>)`.
