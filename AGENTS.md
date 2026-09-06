# Repository Guidelines

## Project Structure & Module Organization

This is a Django backend for a private, auth-gated band portal. Project configuration lives in `config/` (`settings.py`, root URLs, ASGI/WSGI). Domain code is grouped by app:

- `identity/` owns the custom email-based `Person` user model: sign-in, invitations, and password flows over three server-rendered pages (sign in; request a reset; set a password from a token, serving both the invite and the forgot-password confirm — copy chosen by `has_usable_password()`). An expired invite is recovered by an admin's **Invite again** (`resend_invite()`) rather than a longer token lifetime. The project's first two rate limits live beside it in `identity/services.py`: failed sign-ins and outbound auth email, each keyed on the submitted address *and* the requesting IP, counted as `LoginAttempt`/`AuthEmailRequest` rows rather than cached (`CACHES` is unconfigured, so a cache would silently multiply any limit by the gunicorn worker count).
- `scheduling/` owns semester-scoped band and rehearsal models, plus every `/api/` endpoint and hand-written serializer that fronts them.
- Each app keeps tests in `<app>/tests/`, factories in `<app>/factories.py`, and schema changes in `<app>/migrations/`.

The portal is a React/TypeScript SPA over a same-origin JSON `/api/` — see `CLAUDE.md` for the full architecture (issue #341 finished the cutover from server-rendered Django templates; ADR 0012 records the decision). `frontend/` is an ordinary Vite + React + TypeScript app under `frontend/`, with pinned npm dependencies and a committed `package-lock.json` — ordinary tooling, ordinary Dependabot visibility, no vendor-and-rename bump procedure to maintain. `npm run build` writes `frontend/dist/`, which a Django view (`config/views.py:SpaIndexView`) serves via Vite's build manifest, never as a static file, so `build.sh` and CI both run `npm ci && npm run build` inside `frontend/` **before** `collectstatic` — a build that runs out of order serves assets that don't exist. Two prohibitions survive the migration unchanged: **no CDN reference**, ever (this is an auth-gated portal for a named group; a CDN would announce every member's IP and referer to a third party on every page load) and **no DRF** (the seam for the API is `scheduling/services.py`/`identity/services.py`, endpoint-per-interaction, not a resource-shaped HTTP layer — the migration built exactly that and didn't need DRF to). WhiteNoise still serves `STATIC_ROOT` in production.

Read `CONTEXT.md` before changing scheduling concepts, and read the relevant `docs/adr/` decision record before changing behavior it covers. Never call an irreversible side effect (mail, R2 deletion, any external API) inline inside a service function — register it with `transaction.on_commit()`, since admin previews run the real save and roll it back (ADR 0008).

## Build, Test, and Development Commands

Create a virtual environment, install dependencies, and configure local environment values:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

Run all tests with `python manage.py test`; narrow feedback with, for example, `python manage.py test identity.tests.test_login`. Run `ruff check .` before submitting changes. Use `python manage.py check --deploy` when touching settings or deployment configuration. The Django test suite passes on a checkout that has never run `npm install`.

For `frontend/`: `npm ci`, then `npm run build` (writes `frontend/dist/`, which `SpaIndexView` needs on disk), `npm run lint`, `npm run typecheck`, `npm run test`, and `npm run format:check`. `npm run dev` starts a standalone Vite dev server for iterating on components; point Django at it via `VITE_DEV_SERVER_URL` in `.env` for hot module replacement against the real app.

## Coding Style & Naming Conventions

Follow conventional Django and Python style: four-space indentation, `snake_case` for functions and fields, `PascalCase` for classes, and descriptive test class names ending in `Tests`. Ruff is the project linter; migrations are intentionally excluded.

Every function or method added or modified—including tests and factories—needs a concise docstring. Add reusable synthetic-data factories to the app-level `factories.py`, rather than static fixtures. Prefer soft deletion where historical references matter.

## Testing Guidelines

Use Django's built-in test runner with `factory_boy` and `Faker`. Name test files `test_<feature>.py` and test methods `test_<behavior>`. Cover model constraints, views, and services affected by a change. Do not add static fixture files; generate all test data at test time.

Frontend tests are Vitest + React Testing Library, at the route-component level, against a mocked fetch layer — never a real network call and never a snapshot of component internals. Assert what the route renders and how it responds to interaction (a click, a submit, a validation error rendering inline), not its internal state shape or which hooks it called. `npm run test` runs the suite; `npm run lint`, `npm run typecheck`, and `npm run format:check` are the other three checks CI's node job runs.

## Commit & Pull Request Guidelines

Recent history uses short imperative subjects, such as `Add RehearsalSong with computed slot times` and `Handle the Dress Rehearsal in attendance_for`. Keep commits focused and describe the user-visible behavior. PRs should explain the change, include test/lint results, and attach screenshots for UI changes.

**Every PR body must carry a closing keyword for each issue it resolves** — `Closes #123`, one per line, in the template's `## Closes` section. This is what closes the issue on merge and what clears it from the blocking issues' **Dependencies** tab; a PR that only names the issue in its title closes nothing. Use `Refs #123` for an issue the PR touches but does not resolve.

Two caveats worth knowing before relying on it:

- **GitHub only auto-closes on merge into the default branch (`main`).** A PR merged into a long-lived feature branch closes none of its issues. When work is staged on such a branch, carry the full list of `Closes #…` lines on the final PR into `main`.
- **Issue dependencies are recorded on the issues themselves**, not inferred from PRs. When you file an issue that cannot start until another lands, add the relationship in the issue's **Dependencies** section (or via `gh api repos/{owner}/{repo}/issues/{n}/dependencies/blocked_by -F issue_id=<blocker's id>`), so the blocked issue clears itself the moment its blocker closes.

## Privacy & Configuration

Never commit real members, emails, setlists, rehearsal details, recordings, or credentials. Use generated data and `@example.com` addresses in tests. Keep secrets in local `.env` or deployment-managed environment variables; `.env.example` must contain placeholders only.
