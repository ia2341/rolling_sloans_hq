# Contributing

This repo is public — it's the codebase for a private, auth-gated band website, kept public as a showcase of what was built. That only works if the code stays strictly generic: reading it should show *how* the app works, never *what's actually in it*. Follow these rules on every commit.

## Never commit real data or credentials

1. **No real member data, ever** — names, emails, real setlists, real rehearsal dates/times, real recordings, real conflict submissions. This applies everywhere: seed/fixture files, migrations, code comments, commit messages, issue/PR descriptions, even in a "temporary" test commit you plan to fix later. If it identifies a real Rolling Sloans member or event, it doesn't go in the repo.
2. **No real credentials, ever** — API keys, database URLs, the Django `SECRET_KEY`, tokens. These live only in Render environment variables (app runtime) and GitHub Actions encrypted secrets (the backup job) — never in code, never in `.env.example`, never in docs.
3. **`.env.example` gets placeholder values only** (e.g. `RESEND_API_KEY=your-api-key-here`), never a real key with a few characters changed.
4. **Local secrets go in `.env`**, which is already gitignored (see `.gitignore`) — it never leaves your machine.

## Test data

Use **`factory_boy`** + **`Faker`** to generate synthetic data at test-run time (fake names, `@example.com` emails, placeholder song titles like "Song A", synthetic dates). Do not check in static fixture files with hand-written data, even if it looks obviously fake — it's too easy for "realistic-looking" fixture data to drift into actually-real data over time.

Each Django app defines its model factories in a `factories.py` module alongside its models (e.g. `identity/factories.py`), not in `tests/`, so other apps can import and reuse them. See `identity/factories.py` (`PersonFactory`) for the pattern: a `factory.django.DjangoModelFactory` with `factory.Faker(...)` fields for every attribute a test needs realistic-looking data for.

## Backstop

The `no-secrets-committed` CI job scans every push/PR for common secret/credential filename patterns (`.env`, `*.pem`, `*.key`, etc.) as a mechanical safety net. It is not a substitute for judgment — it only catches filenames, not content. Before every commit, ask: *would this line identify a real Rolling Sloans member, or contain a real credential?* If yes, it doesn't go in.
