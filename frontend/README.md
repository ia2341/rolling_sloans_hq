# frontend

The React/TypeScript SPA served same-origin by Django (issue #325, part of
map #302). Built with Vite; see the repo root `CLAUDE.md`/`AGENTS.md` for
how this fits into the Django project and the deploy build.

## Commands

```bash
npm ci
npm run dev          # Vite dev server, for iterating on components in isolation
npm run build         # writes frontend/dist/, which Django's SpaIndexView reads via its manifest
npm run preview       # serves a production build locally
npm run lint          # ESLint
npm run typecheck     # tsc --noEmit
npm run test          # Vitest + React Testing Library
npm run format:check  # Prettier
```

## Local dev loop against Django

The default loop is: run `npm run build` (optionally with `--watch`)
alongside `python manage.py runserver`, so Django's `SpaIndexView` reads the
build manifest like it does in production.

For hot module replacement instead, run `npm run dev` and point Django at it
by setting `VITE_DEV_SERVER_URL` (e.g. `http://localhost:5173`) in `.env`.
The app is still served from Django's origin — only asset tags point at the
Vite dev server — so session cookies and `/api/` calls are unaffected. This
setting is refused outside `DJANGO_DEBUG=True`.
