# Repository Guidelines

## Project Structure & Module Organization

This is a Django backend for a private, auth-gated band portal. Project configuration lives in `config/` (`settings.py`, root URLs, ASGI/WSGI). Domain code is grouped by app:

- `identity/` owns the custom email-based `Person` user model, login, invitations, password flows, and related templates.
- `scheduling/` owns semester-scoped band and rehearsal models.
- Each app keeps tests in `<app>/tests/`, factories in `<app>/factories.py`, and schema changes in `<app>/migrations/`.

Frontend assets are vendored, pinned and committed under the top-level `static/` directory (Pico.css, HTMX, Alpine, SortableJS), with one hand-written override sheet at `static/css/app.css`. Never add a `package.json`, a bundler, a node toolchain, a CDN reference or DRF; bump a vendored library by committing the new file under its new version-stamped name and updating the `{% static %}` reference. WhiteNoise serves `STATIC_ROOT` in production, so the deploy build has to run `collectstatic` (`build.sh`).

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

Run all tests with `python manage.py test`; narrow feedback with, for example, `python manage.py test identity.tests.test_login`. Run `ruff check .` before submitting changes. Use `python manage.py check --deploy` when touching settings or deployment configuration.

## Coding Style & Naming Conventions

Follow conventional Django and Python style: four-space indentation, `snake_case` for functions and fields, `PascalCase` for classes, and descriptive test class names ending in `Tests`. Ruff is the project linter; migrations are intentionally excluded.

Every function or method added or modified—including tests and factories—needs a concise docstring. Add reusable synthetic-data factories to the app-level `factories.py`, rather than static fixtures. Prefer soft deletion where historical references matter.

## Testing Guidelines

Use Django's built-in test runner with `factory_boy` and `Faker`. Name test files `test_<feature>.py` and test methods `test_<behavior>`. Cover model constraints, views, and services affected by a change. Do not add static fixture files; generate all test data at test time.

## Commit & Pull Request Guidelines

Recent history uses short imperative subjects, such as `Add RehearsalSong with computed slot times` and `Handle the Dress Rehearsal in attendance_for`. Keep commits focused and describe the user-visible behavior. PRs should explain the change, include test/lint results, and attach screenshots for template or admin UI changes.

**Every PR body must carry a closing keyword for each issue it resolves** — `Closes #123`, one per line, in the template's `## Closes` section. This is what closes the issue on merge and what clears it from the blocking issues' **Dependencies** tab; a PR that only names the issue in its title closes nothing. Use `Refs #123` for an issue the PR touches but does not resolve.

Two caveats worth knowing before relying on it:

- **GitHub only auto-closes on merge into the default branch (`main`).** A PR merged into a long-lived feature branch closes none of its issues. When work is staged on such a branch, carry the full list of `Closes #…` lines on the final PR into `main`.
- **Issue dependencies are recorded on the issues themselves**, not inferred from PRs. When you file an issue that cannot start until another lands, add the relationship in the issue's **Dependencies** section (or via `gh api repos/{owner}/{repo}/issues/{n}/dependencies/blocked_by -F issue_id=<blocker's id>`), so the blocked issue clears itself the moment its blocker closes.

## Privacy & Configuration

Never commit real members, emails, setlists, rehearsal details, recordings, or credentials. Use generated data and `@example.com` addresses in tests. Keep secrets in local `.env` or deployment-managed environment variables; `.env.example` must contain placeholders only.
