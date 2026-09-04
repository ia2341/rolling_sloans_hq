# Rolling Sloans HQ

A private, auth-gated Django portal for a band ("Rolling Sloans"): who's in the band each semester, what they play, the setlist, and the rehearsal schedule.

This repo is public as a showcase of what was built. It contains no real member data or credentials — see [`CONTRIBUTING.md`](CONTRIBUTING.md) for the privacy rules that govern every commit.

## Stack

Django 6.1 on Postgres, server-rendered templates with full-page POST/redirect
flows, and a vendored progressive-enhancement layer (Pico.css, HTMX, Alpine,
SortableJS). No `package.json`, no bundler, no node toolchain, no CDN and no
DRF — the seam for any future API is `services.py`, endpoint-per-interaction,
not an HTTP layer. Recordings live in a private Cloudflare R2 bucket
(`django-storages`), transactional mail goes out through Resend
(`django-anymail`), WhiteNoise serves static assets, and an optional Spotify
Client Credentials integration turns a public playlist link into setlist rows.

## Architecture

Two Django apps:

- **`identity`** — auth and account lifecycle. Accounts are never self-registered; an admin invites a `Person` by email, and that's the only path to a loggable-in account besides the Django admin.
- **`scheduling`** — the domain model for semesters, membership, roles, songs, rehearsals, and recordings. See [`CONTEXT.md`](CONTEXT.md) for the ubiquitous language (e.g. "Song" is scoped to one semester and never reused across terms).

`scheduling/services.py` is the **read-model layer, not just a write layer**.
Views are deliberately thin: they resolve the viewing Semester, call service
functions, and hand the returned dataclasses straight to a template. Every
derived read — attendance inference, rehearsal progress, the Song x Role x
Person assignment matrix, recording grouping, presigned R2 URLs — lives in
services rather than in a view or a template tag.

Every admin edit surface is built from the same three parts: unsaved edits
collect into a frozen-dataclass **Pending Buffer**, `apply_*(buffer, ...)`
commits it, and `preview_*(buffer, ...)` shows an admin the **Fallout** of
saving. The preview is not a reimplementation — it runs the real `apply_*()`
inside a transaction and rolls it back, so there is never a second, drifting
copy of a derivation. The cost of that choice is a rule the codebase holds
everywhere: irreversible external side effects (mail, R2 deletion, any
external API) are registered with `transaction.on_commit()` and never called
inline, or a preview would really send the email and really delete the object.

Several design decisions that reject the "obvious" alternative are recorded as ADRs in [`docs/adr/`](docs/adr/) — read the relevant one before touching related behavior:

- [`0001`](docs/adr/0001-semester-scoped-entities.md) — `Song` and `Membership` are re-created fresh per `Semester`; only `Person` persists across semesters.
- [`0002`](docs/adr/0002-role-mismatch-soft-flag.md) — a `Role Assignment` whose Role isn't on the Person's Membership is saved anyway and flagged, never hard-blocked.
- [`0003`](docs/adr/0003-dress-rehearsal-live-derivation.md) — the Dress Rehearsal's songs are derived live from the current setlist, not snapshotted.
- [`0004`](docs/adr/0004-recording-storage-access-pattern.md) — `Recording` files live in a private R2 bucket via presigned uploads and short-lived signed playback URLs, never public objects or a proxy through the app server.
- [`0005`](docs/adr/0005-conflict-privacy-boundary.md) — `Conflict` data is never rendered on a member-facing surface, admin viewers included.
- [`0006`](docs/adr/0006-mandatory-dress-rehearsal-attendance.md) — Dress Rehearsal attendance is mandatory, so no `Conflict` may point at it; enforced in the model and services, never by a DB constraint.
- [`0007`](docs/adr/0007-rehearsal-scoped-backup.md) — a `Backup` (a one-Rehearsal stand-in) is its own model anchored on `RehearsalSong`, never a rehearsal-scoped `SongRoleAssignment`; who is being covered for is advisory and admin-only.
- [`0008`](docs/adr/0008-preview-by-rollback.md) — unsaved admin edits preview by running the real `apply_*()` and rolling it back, never by reimplementing derivation in JS or as pure functions.
- [`0009`](docs/adr/0009-assignment-grid-per-rehearsal-lens.md) — semester-wide Standing Assignments are edited through a per-Rehearsal grid, because the availability check that makes the edit safe is only computable through a Rehearsal.
- [`0010`](docs/adr/0010-live-semester-is-greatest-published-at.md) — the Live Semester is simply the greatest `published_at`: no status enum, no singleton pointer row, no unpublish. Rollback is re-publishing an older Semester through the same code path.
- [`0011`](docs/adr/0011-semester-deletion-is-a-hard-delete.md) — deleting a Semester is a real hard delete, cascading to its recordings' stored objects; a deliberate exception to the soft-delete convention, and the Live Semester is always refused.

Configuration (`config/settings.py`) is entirely environment-driven via `django-environ` — no setting is ever a literal secret.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in local values
```

A Postgres database reachable at `DATABASE_URL` is the only external service
local work actually needs. The `AWS_*` R2 variables are read without a default,
so they must be *present* for the app to boot — the `.env.example` placeholders
are enough to run and test everything except a real recording upload. Spotify
is genuinely optional: with `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` unset,
playlist import degrades to a message rather than an error.

## Running

```bash
python manage.py migrate
python manage.py runserver
```

Local dev does not need a live Resend key. With `DJANGO_DEBUG=True`, outbound
email defaults to Django's console backend, so inviting a member prints the
message — set-password link included — to the runserver terminal, and the
invite → set password → profile flow can be walked end to end offline. Set
`DJANGO_EMAIL_BACKEND` to override that locally (`.env.example` has the
Resend value commented out ready to uncomment). With `DJANGO_DEBUG=False` the
Resend backend is pinned and `DJANGO_EMAIL_BACKEND` is ignored, so nothing
can quietly divert a real member's invite in production.

## Tests

```bash
# All apps
python manage.py test

# Single app / module / case
python manage.py test identity
python manage.py test identity.tests.test_login
python manage.py test identity.tests.test_login.LoginViewTests.test_valid_login
```

## Lint

```bash
ruff check .
```

## Static assets

The admin UI stack is vendored, pinned and committed under the top-level
`static/` directory — HTMX, Alpine, [Pico.css](https://picocss.com) and
SortableJS, each with its version in the filename, plus one hand-written
override sheet (`static/css/app.css`) built on CSS custom properties as
tokens. There is no `package.json`, no bundler and no CDN: a CDN would
announce every member's IP and referer to a third party on each page load of
what is meant to be a private portal. Bumping a library means downloading the
new file, renaming it, and updating the `{% static %}` reference.

In production WhiteNoise serves whatever `collectstatic` wrote to
`STATIC_ROOT`, so the deploy build must run it — that is what `build.sh` is
for, and it is the host's build command.

## Deploy

```bash
./build.sh   # pip install, collectstatic, migrate — the host's build command
```

## Deploy-config smoke test

```bash
python manage.py check --deploy
```

## CI

`.github/workflows/ci.yml` runs `ruff check .`, `manage.py test --parallel` against a real Postgres service, `manage.py check --deploy` under production-like environment variables, and a scan that fails the build on any committed `.env`/`.pem`/`.key`/`id_rsa`/`id_ed25519` file.

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a PR — it covers the privacy constraints (no real member data or credentials, ever), the `factory_boy` + `Faker` convention for test data, and the docstring coverage check CodeRabbit enforces on every PR.
