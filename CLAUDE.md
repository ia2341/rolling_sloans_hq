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

CI (`.github/workflows/ci.yml`) runs `ruff check .`, `manage.py test --parallel` against a real Postgres service, `manage.py check --deploy` under production-like env vars, and a grep-based scan that fails the build on any committed `.env`/`.pem`/`.key`/`id_rsa`/`id_ed25519` file.

## Architecture

Two Django apps today:

- **`identity`** — auth and account lifecycle. `Person` (`identity/models.py`) is a custom `AbstractBaseUser` (`AUTH_USER_MODEL = 'identity.Person'`) keyed on email, with a single `is_admin` flag that `Person.save()` mirrors onto `is_staff`/`is_superuser` — there's no separate Group/Permission scheme. Accounts are never self-registered: `identity/services.py`'s `invite_person()` is the only path to a loggable-in `Person` (besides the Django admin), creating the user with an unusable password and emailing a one-time set-password link (Django's `PasswordResetTokenGenerator`, reused under "set password" wording) inside one atomic transaction — if the invite email fails to send, the `Person` row rolls back so the email stays free for a retry.
- **`scheduling`** — the domain described in `CONTEXT.md`, now largely implemented: `Semester`, `Role`, `Membership`, `MembershipRole`, `Song`, `SongRoleRequirement`, `SongRoleAssignment`, `Rehearsal`, `RehearsalSong`, `Conflict`, `ConflictWindow`, `Recording`. Read `CONTEXT.md` before adding any scheduling model or field — it defines the project's ubiquitous language (e.g. "Song" is scoped to one semester, never reused across terms; "Running Order" is a rehearsal's sequence, distinct from the Setlist's concert position).

### How a scheduling request is put together

The non-obvious shape here is that **`scheduling/services.py` is the read-model layer, not just a write layer.** Views are deliberately thin: they resolve the viewing Semester, call service functions, and hand the returned dataclasses (`AssignmentMatrix`, `RehearsalSchedule`, `SongPerformer`, `AttendanceSuggestion`, `RecordingSlotGroup`, …) straight to a template. Derived reads — attendance inference, rehearsal progress, the Song×Role×Person matrix, recording grouping, presigned R2 URLs — live in services, so put new derived logic there rather than in a view or a template tag.

- **Auth is structural, not per-view.** `config/views.py` defines `BaseView` (a `LoginRequiredMixin` every non-auth view in the project mixes in, so none can forget to gate itself) and `AdminRequiredMixin` (adds a 403 for a logged-in non-admin, used by every `manage/*` view). Mix one in ahead of the Django generic class; don't hand-roll a gate.
- **Route shape** (`scheduling/urls.py`): band-wide reads at the root (`/`, `/schedule/`, `/setlist/`, `/songs/<pk>/`, `/members/`, `/members/<pk>/`), per-person self-service under `/me/` (`recordings`), and admin management under `/manage/`. `/schedule/` is the **single** member-facing page (issue #190): it absorbed `/me/conflicts/` outright (no redirect), so a member's own availability — declaration, verdict, note, and the declare/edit/delete controls at `/schedule/<rehearsal_id>/conflict/[delete/]` — folds inline into the rehearsal it concerns rather than living on a page of its own. Note there is **no** `/me/profile/`: `/members/<pk>/` (`MemberDetailView`) is the single per-person page, read-only for a teammate and editable in place for your own pk, and the nav's Profile tab points at your own pk. Its field-by-field verdicts live in `docs/person-page-visibility.md` (ADR 0005).
- **"Which Semester is this request scoped to" is answered in exactly one place**: `services.get_viewing_semester(request)`, for reads *and* writes. Reuse it; never re-derive recency, and never read `id` or `created_at` as a proxy for "the semester". Its sibling `services.get_live_semester()` (greatest `published_at`, nulls excluded, else `None`) answers the different question "what do members see" — keep the two distinct, per ADR 0010. `services.set_viewing_semester(request, semester)` records an admin's session selection (`None` clears it). "Current semester" is a **retired term** — a `Semester` with a null `published_at` is a *draft*, and the one with the greatest `published_at` is the *Live Semester*.
- **The non-live Semester banner comes from the shell, not from a view.** `scheduling/context_processors.py:semester_banner` (wired into `TEMPLATES` in `config/settings.py`) puts `services.semester_banner_for(request)` on every render, and `templates/base.html` includes `scheduling/_semester_banner.html` — so a new page cannot forget to warn an admin that they're editing a draft. It is a context processor precisely because a per-view context key is one a view can skip. The switcher itself is the Overview's `_semester_panel.html` (fed by `services.semester_options_for(request)`) posting to `SemesterSelectView` at `/manage/semester/` — a plain POST-and-redirect, deliberately not HTMX or Alpine, so which Semester an admin edits never hinges on a script loading (issue #169).
- **Song position mutations must hold a lock.** `views._lock_semester()` row-locks the `Semester` inside `transaction.atomic()` so concurrent creates/moves can't collide on `unique_song_position_per_semester`. Any new code that renumbers positions needs the same treatment — and note `RehearsalSong` has a `UniqueConstraint(rehearsal, order)`, so a reorder cannot write new `order` values row by row.
- **`RehearsalSong.save()` derives and persists `start_time`/`end_time`** from `order` + `slot_count` + the Semester's `default_song_slot_count` — never from `Song.length`, which is a display field with no scheduling authority. A slot is an equal share of the Rehearsal's window, not the song's running time, so a 3-minute song and a 7-minute one occupy identical slots (rehearsing a song takes far longer than playing it once); don't wire `length` into `slot_count`. Reordering a rehearsal therefore changes *when each song happens*, which changes which `ConflictWindow`s overlap it — relevant to anything computing availability.

### Frontend

Server-rendered Django templates (`templates/base.html` is the nav shell; per-app templates under `<app>/templates/<app>/`), full-page POST/redirect flows, and a few small hand-rolled vanilla-JS files under `scheduling/static/scheduling/js/` for progressive enhancement.

The admin UI stack is **vendored, pinned and committed** under the top-level `static/` directory — `vendor/pico-2.1.1.min.css`, `vendor/htmx-2.0.10.min.js`, `vendor/alpine-3.17.1.min.js`, `vendor/sortable-1.15.7.min.js` — with the version in each filename, referenced via `{% static %}`. **No `package.json`, no bundler, no node toolchain, no CDN and no DRF** (issue #168; decisions on #123). A CDN was rejected on privacy: this is an auth-gated portal for a named group, and a CDN would announce every member's IP and referer to a third party on every page load. DRF was rejected because the seam for any future API is `services.py`, endpoint-per-interaction, not an HTTP layer. Bumping a library is a download plus a rename plus a `{% static %}` edit — there is no Dependabot visibility on vendored JS.

- The nav shell's `<head>` loads Pico, the override sheet, HTMX and Alpine on every page it wraps. **SortableJS is vendored and resolvable but referenced by no page** — the first drag surface wires it (native HTML5 drag-and-drop does not fire on mobile browsers, so don't reach for it instead).
- CSS is Pico as the near-classless baseline plus **one** hand-written override sheet, `static/css/app.css`, whose reusable values are CSS custom properties on `:root` (`--rs-*` for ours, `--pico-*` to retheme Pico). Add a token there rather than a literal in a template. Pico landed as vendor-and-wire: visual drift from the previously unstyled pages is expected, and nothing in the test suite asserts appearance.
- The four existing hand-rolled JS files are deliberately **not** ported to Alpine. New admin surfaces use Alpine; one of those four gets ported only when it is touched for another reason.
- The Django admin stays mounted as the low-level escape hatch for the long tail the custom UI won't cover.
- **Static serving**: `STATICFILES_DIRS` picks up the top-level `static/`, and WhiteNoise (middleware directly after `SecurityMiddleware`) serves `STATIC_ROOT` in production. The staticfiles backend is WhiteNoise's *non-manifest* `CompressedStaticFilesStorage` — filenames are not content-hashed, because the vendored files already carry their version and a manifest backend would make every `{% static %}` call fail until `collectstatic` had run. Nothing serves static assets unless the deploy build runs `collectstatic`; that's `build.sh`, and CI runs the same step.

**Read `docs/adr/*.md` before touching related behavior** — each records a deliberate rejection of the "obvious" alternative:
- `0001` — `Song` and `Membership` are re-created fresh per `Semester`; only `Person` persists across semesters.
- `0002` — a `Role Assignment` whose Role isn't on the Person's Membership is saved anyway and flagged `is_role_mismatch`, never hard-blocked (admins are the sole authors and need to assign ahead of profile updates).
- `0003` — the Dress Rehearsal's songs are derived live from the current setlist at read-time, not snapshotted into `RehearsalSong` rows, so it can't go stale if the setlist changes after scheduling.
- `0004` — `Recording` files live in a private R2 bucket; uploads go client→R2 via a Django-issued presigned PUT, and playback uses short-lived signed URLs — never public objects, never proxied through the Django app server.
- `0005` — `Conflict` data (especially the free-text `reason`) is never rendered on a member-facing surface, admin viewers included; admins read it only through admin-only surfaces. Field-by-field verdicts for `/members/` and `/members/<pk>/` live in `docs/person-page-visibility.md`.
- `0006` — Dress Rehearsal attendance is mandatory, so no `Conflict` may point at a Rehearsal with `is_full_setlist=True`. Enforced in `Conflict.clean()`/`save()`, `declare_conflict()` and `future_rehearsals_for()`; deliberately **not** by a DB constraint, which cannot reach through the `rehearsal` FK. The other direction is guarded too: `Rehearsal.clean()`/`save()` refuse a flip to `is_full_setlist=True` on a Rehearsal that already has `Conflict` rows, with a count-only message (never who or why, per ADR 0005) — `RehearsalForm` intentionally has no copy of that check.
- `0007` — a `Backup` (one Person covering a Role on a Song at one Rehearsal) is **its own model anchored on `RehearsalSong`**, not a nullable `rehearsal` FK on `SongRoleAssignment`, which would overload a table `CONTEXT.md` defines as a fact about a *Song*. The anchor depends on ADR 0006: the Dress Rehearsal has no `RehearsalSong` rows, so Backups are impossible there — fine only while no `Conflict` can point at it. `covering_for` is an advisory nullable FK to `Person` (`SET_NULL`), never load-bearing: a Backup with no standing assignee is legal and a withdrawn `Conflict` leaves the Backup standing. `attendance_for()` counts Backups; `performers_for(song)` must not. Per ADR 0005 the covered person's name is **admin-only**, though the Backup itself shows on the member-facing Schedule. **Not implemented yet** — the model is specified, not built (issue #143).

- `0008` — unsaved admin edits **preview by running the real `apply_*()` inside `transaction.atomic()` and rolling it back**, never by reimplementing derivation in JS or as pure functions over unsaved instances (every derivation — `_prior_slots`, `_compute_is_role_mismatch`, `attendance_for`, `breaks_for` — reads the DB, so purity would mean two implementations of six read paths). Consequence: **every irreversible external side effect must be registered with `transaction.on_commit()`**, never called inline, or a preview really sends the email and really deletes the R2 object. Preview endpoints are POST-only siblings of their surface, take no `_lock_semester()`, and use a savepoint plus `transaction.set_rollback(True)` so an invalid buffer still renders. **Not implemented yet** — specified, not built (issue #144).
- `0010` — the **Live Semester is the greatest `published_at`** (nullable; null = draft), with `created_at` for chronological ordering — no `status` enum, no partial unique constraint, no singleton pointer row, no unpublish, no `start_date`/`end_date`. Publishing stamps `published_at`; rollback is re-publishing an older Semester through the same code path. An admin's session selection governs **writes as well as reads**, so a `/manage/` write while a draft is selected lands on the draft; a stale or demoted selection falls back silently to the Live Semester, and only admins get the "nothing published, show the newest-created" fallback.

- `0009` — `SongRoleAssignment` (a **Standing Assignment**, semester-scoped per ADR 0001) is edited through the **per-Rehearsal** assignment grid on `/schedule/`, so a cell edit changes every rehearsal and the concert. Deliberate: the loud-tier availability check (`Conflict`/`ConflictWindow` overlapping the Song's slot) is only computable through a Rehearsal, which a per-Song editor could never raise. Do **not** "fix" it with a `rehearsal` FK — that is ADR 0007's `Backup`. `/songs/<pk>/` stays read-only for assignments; a past Rehearsal's grid (`date < today`) is not editable, with the Dress Rehearsal as the backstop; adding a Role column writes no `SongRoleRequirement`. **Not implemented yet** — specified, not built (issue #134).

**Config** (`config/settings.py`) is entirely environment-driven via `django-environ`, reading `.env` locally / host-injected vars in production — no setting is ever a literal secret. Notable non-defaults: 30-day sliding session expiry (`SESSION_SAVE_EVERY_REQUEST = True`), `SITE_URL` required and validated at startup when `DEBUG=False` (used to build absolute links like invite/reset URLs outside request context), TLS-everywhere settings gated behind `not DEBUG`, and object storage (`STORAGES['default']`) pointed at an S3-compatible backend (Cloudflare R2) per ADR 0004.

## Conventions

- **Per-app `factories.py`** (not under `tests/`) define `factory_boy` model factories other apps can import — `identity/factories.py:PersonFactory`, and one in `scheduling/factories.py` for every scheduling model. Add a factory here, not a static fixture, whenever a model needs test data.
- **Soft-delete over hard-delete** where history matters: `Role.is_active` retires a role with no deletion path (`RoleAdmin.has_delete_permission` returns `False`); the same pattern should be followed for any model where historical references must stay intact (see ADR 0002 for the reasoning that generalizes this).
- **Irreversible side effects go through `transaction.on_commit()`**, never inline inside a service function — sending mail, deleting an R2 object, calling any external API. Admin previews run the real save and roll it back (ADR 0008), so an inline side effect fires for real during a preview and cannot be undone. Registering it with `on_commit` makes rollback discard it for free.
- **`AGENTS.md` covers the same ground** for other agents (structure, style, testing, commit/PR expectations). When you change a convention here, check whether it also needs changing there, so the two don't drift.
- **Docstrings are required on every function/method you add or modify** (views, model methods, factories, signal handlers, tests included) — CodeRabbit enforces an 80% diff-scoped coverage threshold on every PR. One line is enough for simple cases.

## Privacy constraint (read `CONTRIBUTING.md` for full detail)

This governs code, comments, commit messages, and test data, not just docs:
- No real member data ever, anywhere in the repo (names, emails, real setlists/dates/recordings) — synthesize everything via `factory_boy` + `Faker` at test-run time.
- No real credentials ever — they live only in Render env vars and GitHub Actions secrets. `.env.example` gets placeholder values only.
