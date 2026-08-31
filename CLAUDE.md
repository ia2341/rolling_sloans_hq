# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Django backend for a private, auth-gated portal for a band ("Rolling Sloans"): who's in the band each semester, what they play, the setlist, and the rehearsal schedule. The repo is public as a showcase, but must never contain real member data or credentials — see "Privacy constraint" below, it governs how you write code and tests here more than typical style rules would.

## Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in local values

# Run
python manage.py migrate
python manage.py runserver

# Tests (all apps)
python manage.py test

# Tests, single app / module / case
python manage.py test identity
python manage.py test identity.tests.test_login
python manage.py test identity.tests.test_login.LoginViewTests.test_valid_login

# Lint (ruff; migrations are excluded via pyproject.toml)
ruff check .

# Deploy-config smoke test (also covered by identity/tests/test_deploy_check.py)
python manage.py check --deploy
```

CI (`.github/workflows/ci.yml`) runs `ruff check .`, `manage.py test` against a real Postgres service, `manage.py check --deploy` under production-like env vars, and a grep-based scan that fails the build on any committed `.env`/`.pem`/`.key`/`id_rsa`/`id_ed25519` file.

## Architecture

Two Django apps today:

- **`identity`** — auth and account lifecycle. `Person` (`identity/models.py`) is a custom `AbstractBaseUser` (`AUTH_USER_MODEL = 'identity.Person'`) keyed on email, with a single `is_admin` flag that `Person.save()` mirrors onto `is_staff`/`is_superuser` — there's no separate Group/Permission scheme. Accounts are never self-registered: `identity/services.py`'s `invite_person()` is the only path to a loggable-in `Person` (besides the Django admin), creating the user with an unusable password and emailing a one-time set-password link (Django's `PasswordResetTokenGenerator`, reused under "set password" wording) inside one atomic transaction — if the invite email fails to send, the `Person` row rolls back so the email stays free for a retry.
- **`scheduling`** — the domain model described in `CONTEXT.md`. Only `Semester` and `Role` exist so far; `Membership`, `Song`, `Rehearsal`, `RehearsalSong`, `Recording`, and `Role Assignment` are designed in `CONTEXT.md` but not yet implemented. Read `CONTEXT.md` before adding any scheduling model or field — it defines the project's ubiquitous language (e.g. "Song" is scoped to one semester, never reused across terms).

**Read `docs/adr/*.md` before touching related behavior** — each records a deliberate rejection of the "obvious" alternative:
- `0001` — `Song` and `Membership` are re-created fresh per `Semester`; only `Person` persists across semesters.
- `0002` — a `Role Assignment` whose Role isn't on the Person's Membership is saved anyway and flagged `is_role_mismatch`, never hard-blocked (admins are the sole authors and need to assign ahead of profile updates).
- `0003` — the Dress Rehearsal's songs are derived live from the current setlist at read-time, not snapshotted into `RehearsalSong` rows, so it can't go stale if the setlist changes after scheduling.
- `0004` — `Recording` files live in a private R2 bucket; uploads go client→R2 via a Django-issued presigned PUT, and playback uses short-lived signed URLs — never public objects, never proxied through the Django app server.

**Config** (`config/settings.py`) is entirely environment-driven via `django-environ`, reading `.env` locally / host-injected vars in production — no setting is ever a literal secret. Notable non-defaults: 30-day sliding session expiry (`SESSION_SAVE_EVERY_REQUEST = True`), `SITE_URL` required and validated at startup when `DEBUG=False` (used to build absolute links like invite/reset URLs outside request context), TLS-everywhere settings gated behind `not DEBUG`, and object storage (`STORAGES['default']`) pointed at an S3-compatible backend (Cloudflare R2) per ADR 0004.

## Conventions

- **Per-app `factories.py`** (not under `tests/`) define `factory_boy` model factories other apps can import — e.g. `identity/factories.py:PersonFactory`, `scheduling/factories.py:SemesterFactory`/`RoleFactory`. Add a factory here, not a static fixture, whenever a model needs test data.
- **Soft-delete over hard-delete** where history matters: `Role.is_active` retires a role with no deletion path (`RoleAdmin.has_delete_permission` returns `False`); the same pattern should be followed for any model where historical references must stay intact (see ADR 0002 for the reasoning that generalizes this).
- **Docstrings are required on every function/method you add or modify** (views, model methods, factories, signal handlers, tests included) — CodeRabbit enforces an 80% diff-scoped coverage threshold on every PR. One line is enough for simple cases.

## Privacy constraint (read `CONTRIBUTING.md` for full detail)

This governs code, comments, commit messages, and test data, not just docs:
- No real member data ever, anywhere in the repo (names, emails, real setlists/dates/recordings) — synthesize everything via `factory_boy` + `Faker` at test-run time.
- No real credentials ever — they live only in Render env vars and GitHub Actions secrets. `.env.example` gets placeholder values only.
