## Summary

<!-- What changed, and the user-visible behavior. -->

## Closes

<!--
REQUIRED. One closing keyword per issue this PR resolves, each on its own line:

Closes #123

GitHub only auto-closes on merge into `main`. A PR merging into a long-lived
feature branch closes nothing — carry the full list of `Closes #…` lines on the
final PR into `main` instead, one per issue that branch resolved.

Use `Refs #123` for an issue this PR touches but does not resolve, so the
Dependencies tab is not cleared early.
-->

Closes #

## Test plan

- [ ] `python manage.py test`
- [ ] `ruff check .`
- [ ] `python manage.py check --deploy`

<!-- Screenshots for template or admin UI changes. -->

## Privacy check

- [ ] No real member data (names, emails, setlists, dates, recordings) in code, tests, comments or commit messages
- [ ] No real credentials; `.env.example` carries placeholders only
