# Rolling Sloans HQ

A private, auth-gated Django portal for a band ("Rolling Sloans"): who's in the band each semester, what they play, the setlist, and the rehearsal schedule.

This repo is public as a showcase of what was built. It contains no real member data or credentials — see [`CONTRIBUTING.md`](CONTRIBUTING.md) for the privacy rules that govern every commit.

## Architecture

Two Django apps:

- **`identity`** — auth and account lifecycle. Accounts are never self-registered; an admin invites a `Person` by email, and that's the only path to a loggable-in account besides the Django admin.
- **`scheduling`** — the domain model for semesters, membership, roles, songs, rehearsals, and recordings. See [`CONTEXT.md`](CONTEXT.md) for the ubiquitous language (e.g. "Song" is scoped to one semester and never reused across terms).

Several design decisions that reject the "obvious" alternative are recorded as ADRs in [`docs/adr/`](docs/adr/) — read the relevant one before touching related behavior:

- [`0001`](docs/adr/0001-semester-scoped-entities.md) — `Song` and `Membership` are re-created fresh per `Semester`; only `Person` persists across semesters.
- [`0002`](docs/adr/0002-role-mismatch-soft-flag.md) — a `Role Assignment` whose Role isn't on the Person's Membership is saved anyway and flagged, never hard-blocked.
- [`0003`](docs/adr/0003-dress-rehearsal-live-derivation.md) — the Dress Rehearsal's songs are derived live from the current setlist, not snapshotted.
- [`0004`](docs/adr/0004-recording-storage-access-pattern.md) — `Recording` files live in a private R2 bucket via presigned uploads and short-lived signed playback URLs, never public objects or a proxy through the app server.
- [`0005`](docs/adr/0005-conflict-privacy-boundary.md) — `Conflict` data is never rendered on a member-facing surface, admin viewers included.
- [`0006`](docs/adr/0006-mandatory-dress-rehearsal-attendance.md) — Dress Rehearsal attendance is mandatory, so no `Conflict` may point at it; enforced in the model and services, never by a DB constraint.
- [`0007`](docs/adr/0007-rehearsal-scoped-backup.md) — a `Backup` (a one-Rehearsal stand-in) is its own model anchored on `RehearsalSong`, never a rehearsal-scoped `SongRoleAssignment`; who is being covered for is advisory and admin-only.

Configuration (`config/settings.py`) is entirely environment-driven via `django-environ` — no setting is ever a literal secret.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in local values
```

## Running

```bash
python manage.py migrate
python manage.py runserver
```

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

`.github/workflows/ci.yml` runs `ruff check .`, `manage.py test` against a real Postgres service, `manage.py check --deploy` under production-like environment variables, and a scan that fails the build on any committed `.env`/`.pem`/`.key`/`id_rsa`/`id_ed25519` file.

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a PR — it covers the privacy constraints (no real member data or credentials, ever), the `factory_boy` + `Faker` convention for test data, and the docstring coverage check CodeRabbit enforces on every PR.
