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
- **`scheduling`** — the domain described in `CONTEXT.md`, now largely implemented: `Semester`, `Role`, `Membership`, `MembershipRole`, `Song`, `SongRoleRequirement`, `SongRoleAssignment`, `Rehearsal`, `RehearsalSong`, `Conflict`, `ConflictWindow`, `Recording`. Read `CONTEXT.md` before adding any scheduling model or field — it defines the project's ubiquitous language (e.g. "Song" is scoped to one semester, never reused across terms; "Running Order" is a rehearsal's sequence, distinct from the Setlist's concert position).

### How a scheduling request is put together

The non-obvious shape here is that **`scheduling/services.py` is the read-model layer, not just a write layer.** Views are deliberately thin: they resolve the current semester, call service functions, and hand the returned dataclasses (`AssignmentMatrix`, `RehearsalSchedule`, `SongPerformer`, `AttendanceSuggestion`, `RecordingSlotGroup`, …) straight to a template. Derived reads — attendance inference, rehearsal progress, the Song×Role×Person matrix, recording grouping, presigned R2 URLs — live in services, so put new derived logic there rather than in a view or a template tag.

- **Auth is structural, not per-view.** `config/views.py` defines `BaseView` (a `LoginRequiredMixin` every non-auth view in the project mixes in, so none can forget to gate itself) and `AdminRequiredMixin` (adds a 403 for a logged-in non-admin, used by every `manage/*` view). Mix one in ahead of the Django generic class; don't hand-roll a gate.
- **Route shape** (`scheduling/urls.py`): band-wide reads at the root (`/`, `/schedule/`, `/setlist/`, `/songs/<pk>/`, `/members/`, `/members/<pk>/`), per-person self-service under `/me/` (`conflicts`, `recordings`), and admin management under `/manage/`. Note there is **no** `/me/profile/`: `/members/<pk>/` (`MemberDetailView`) is the single per-person page, read-only for a teammate and editable in place for your own pk, and the nav's Profile tab points at your own pk. Its field-by-field verdicts live in `docs/person-page-visibility.md` (ADR 0005).
- **"The current semester" is defined in exactly one place**: `services.get_current_semester()` (most recently created `Semester`, or `None`). Reuse it; don't re-derive recency. `Semester` has no draft/published state yet — that's a decision recorded on the admin-experience map, not yet in the model.
- **Song position mutations must hold a lock.** `views._lock_semester()` row-locks the `Semester` inside `transaction.atomic()` so concurrent creates/moves can't collide on `unique_song_position_per_semester`. Any new code that renumbers positions needs the same treatment — and note `RehearsalSong` has a `UniqueConstraint(rehearsal, order)`, so a reorder cannot write new `order` values row by row.
- **`RehearsalSong.save()` derives and persists `start_time`/`end_time`** from `order` + `slot_count` + the Semester's `default_song_slot_count`. Reordering a rehearsal therefore changes *when each song happens*, which changes which `ConflictWindow`s overlap it — relevant to anything computing availability.

### Frontend

Server-rendered Django templates (`templates/base.html` is the nav shell; per-app templates under `<app>/templates/<app>/`), full-page POST/redirect flows, and a few small hand-rolled vanilla-JS files under `scheduling/static/scheduling/js/` for progressive enhancement. There is **no** `package.json`, no bundler, and no CSS file in the repo yet.

A decision on the admin UI stack has been made but **not yet implemented**: Django templates + HTMX + Alpine + Pico.css + SortableJS, vendored and pinned under `static/`, with no node toolchain and no DRF; the seam for any future API is `services.py`, not an HTTP layer. See issue #123 for the full rationale before introducing a frontend dependency.

**Read `docs/adr/*.md` before touching related behavior** — each records a deliberate rejection of the "obvious" alternative:
- `0001` — `Song` and `Membership` are re-created fresh per `Semester`; only `Person` persists across semesters.
- `0002` — a `Role Assignment` whose Role isn't on the Person's Membership is saved anyway and flagged `is_role_mismatch`, never hard-blocked (admins are the sole authors and need to assign ahead of profile updates).
- `0003` — the Dress Rehearsal's songs are derived live from the current setlist at read-time, not snapshotted into `RehearsalSong` rows, so it can't go stale if the setlist changes after scheduling.
- `0004` — `Recording` files live in a private R2 bucket; uploads go client→R2 via a Django-issued presigned PUT, and playback uses short-lived signed URLs — never public objects, never proxied through the Django app server.
- `0005` — `Conflict` data (especially the free-text `reason`) is never rendered on a member-facing surface, admin viewers included; admins read it only through admin-only surfaces. Field-by-field verdicts for `/members/` and `/members/<pk>/` live in `docs/person-page-visibility.md`.
- `0006` — Dress Rehearsal attendance is mandatory, so no `Conflict` may point at a Rehearsal with `is_full_setlist=True`. Enforced in `Conflict.clean()`/`save()`, `declare_conflict()` and `future_rehearsals_for()`; deliberately **not** by a DB constraint, which cannot reach through the `rehearsal` FK. The other direction is guarded too: `Rehearsal.clean()`/`save()` refuse a flip to `is_full_setlist=True` on a Rehearsal that already has `Conflict` rows, with a count-only message (never who or why, per ADR 0005) — `RehearsalForm` intentionally has no copy of that check.

**Config** (`config/settings.py`) is entirely environment-driven via `django-environ`, reading `.env` locally / host-injected vars in production — no setting is ever a literal secret. Notable non-defaults: 30-day sliding session expiry (`SESSION_SAVE_EVERY_REQUEST = True`), `SITE_URL` required and validated at startup when `DEBUG=False` (used to build absolute links like invite/reset URLs outside request context), TLS-everywhere settings gated behind `not DEBUG`, and object storage (`STORAGES['default']`) pointed at an S3-compatible backend (Cloudflare R2) per ADR 0004.

## Conventions

- **Per-app `factories.py`** (not under `tests/`) define `factory_boy` model factories other apps can import — `identity/factories.py:PersonFactory`, and one in `scheduling/factories.py` for every scheduling model. Add a factory here, not a static fixture, whenever a model needs test data.
- **Soft-delete over hard-delete** where history matters: `Role.is_active` retires a role with no deletion path (`RoleAdmin.has_delete_permission` returns `False`); the same pattern should be followed for any model where historical references must stay intact (see ADR 0002 for the reasoning that generalizes this).
- **`AGENTS.md` covers the same ground** for other agents (structure, style, testing, commit/PR expectations). When you change a convention here, check whether it also needs changing there, so the two don't drift.
- **Docstrings are required on every function/method you add or modify** (views, model methods, factories, signal handlers, tests included) — CodeRabbit enforces an 80% diff-scoped coverage threshold on every PR. One line is enough for simple cases.

## Privacy constraint (read `CONTRIBUTING.md` for full detail)

This governs code, comments, commit messages, and test data, not just docs:
- No real member data ever, anywhere in the repo (names, emails, real setlists/dates/recordings) — synthesize everything via `factory_boy` + `Faker` at test-run time.
- No real credentials ever — they live only in Render env vars and GitHub Actions secrets. `.env.example` gets placeholder values only.
