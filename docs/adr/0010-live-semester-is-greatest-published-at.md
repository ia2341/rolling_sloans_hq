# The Live Semester is the greatest `published_at`

`Semester` carries the whole lifecycle in **two nullable-or-stamped datetimes and nothing else**: `published_at` (null means never published — a draft) and `created_at` (`auto_now_add`, so semesters can be ordered chronologically without leaning on primary keys). The **Live Semester** — the one non-admin members see — is derived, every time it is asked for, as the row with the greatest non-null `published_at`.

There is no `status` enum, no partial unique constraint, no singleton pointer row, and no unpublish action. Publishing sets `published_at` to now; that is the entire operation, and it is idempotent on the already-live Semester. Rolling back is Publishing an older Semester, which bumps its stamp past the incumbent's — an honest record of what is live *now*, rather than a mutation that erases the fact that something else was live yesterday.

## Why not a `status` enum

`draft | live | archived` is the shape a reader reaches for first. It was rejected because:

- It buys an **archived** state nothing in this domain needs, and then demands an explicit archive step on every publish: making Fall 2027 live means also demoting Fall 2026, so one user action becomes two writes that can disagree.
- Keeping "at most one live" true then needs a partial unique constraint (`WHERE status = 'live'`) *and* the demotion write inside the same transaction. The datetime formulation makes the invariant structural — "greatest" is unique by construction — so there is nothing to enforce and nothing to get out of step.
- It cannot express rollback without a third write. With `published_at`, rollback and publish are literally the same code path.

## Why not a singleton pointer row

A `LiveSemester` row (or a settings-style pointer) holding one FK was rejected because it makes **draft-ness a derived non-property**: "not pointed at" collapses a never-shown draft and last year's finished term into one indistinguishable state. The switcher has to label those two differently — *Draft* versus *Previously published* — and only a per-Semester publish record can tell them apart.

## Why not `start_date`/`end_date`

`Semester` deliberately carries no term dates. `published_at` is the sole authority on which semester is real; dates would introduce a second, silently competing answer to "which semester is it", and a wall-clock one the band's actual usage does not track.

## Consequences

- **`get_current_semester()` is gone**, with no compatibility shim. It returned the greatest `id` — an incidental heuristic, not a decision — and creating next term's Semester therefore switched every member's site to an empty shell mid-term. Two functions replace it, and the split is load-bearing: `get_live_semester()` answers "what do members see" and takes no request; `get_viewing_semester(request)` answers "what is *this* request scoped to". Conflating them is how a draft leaks to a member.
- **The viewing Semester governs writes, not just reads.** An admin viewing a draft who adds a Song through `/manage/` writes it to the draft. Every scoped read and every `/manage/*` write funnels through `views._scoped_to_viewing_semester(model, get_viewing_semester(request))`, so there is one place this can be got wrong.
- **The selection lives in `request.session`**, and therefore dies at logout. A `?semester=<id>` param or an `/s/<id>/` URL prefix was rejected because the admin controls built on this are inlined onto the *existing* member-facing pages, so a URL-borne selection would have to be threaded through every link and form on all of them.
- **Only admins get a fallback.** With nothing published, an admin resolves to the most recently *created* Semester — otherwise a solo admin bootstrapping the first term is trapped in empty states with no way to see the thing they are building. A member resolves to `None` and gets the pre-publish empty state, which is the existing no-Semester branch, unchanged.
- **A stale selection never raises.** A selection pointing at a since-deleted Semester, or held by an account that has lost `is_admin`, falls back silently to the Live Semester.
- **The migration is invisible to members.** `published_at` backfills non-null onto exactly the row the outgoing `get_current_semester()` returned (the greatest `id`) and null everywhere else, so deploying the lifecycle changes nothing anyone can see. Older rows becoming drafts is the honest description of rows nobody ever deliberately published, and any row for which that is wrong is one Publish away from correct.
- **Ties fall back to the greater `id`.** Two rows published in the same instant would otherwise order non-deterministically. This is a tiebreak, not a second notion of recency — nothing may read `id` as a proxy for order.
- **Publishing is visibility only.** It never gates edits inside a semester and never locks a published one; there is no staged-edit layer, and "Save Changes" stays the write boundary within a semester. ADR 0003 depends on this: the Dress Rehearsal's songs are derived live from the setlist *precisely so they cannot go stale*, which a draft-copy-per-entity model would undo.
