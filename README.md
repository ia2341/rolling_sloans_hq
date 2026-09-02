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

## Deploy-config smoke test

```bash
python manage.py check --deploy
```

## CI

`.github/workflows/ci.yml` runs `ruff check .`, `manage.py test` against a real Postgres service, `manage.py check --deploy` under production-like environment variables, and a scan that fails the build on any committed `.env`/`.pem`/`.key`/`id_rsa`/`id_ed25519` file.

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a PR — it covers the privacy constraints (no real member data or credentials, ever), the `factory_boy` + `Faker` convention for test data, and the docstring coverage check CodeRabbit enforces on every PR.
