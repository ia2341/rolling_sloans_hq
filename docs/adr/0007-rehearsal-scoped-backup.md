# A Backup is its own model, not a rehearsal-scoped Role Assignment

A **Backup** — a Person covering a Role on a Song at one specific Rehearsal — is a new model rather than a nullable `rehearsal` FK on `SongRoleAssignment`. `CONTEXT.md` defines a Role Assignment as a fact about a *Song*: "the fact that a specific Person fills a specific Role on a specific Song." Adding a nullable `rehearsal` would make that table mean two different things depending on whether one column is null, and every existing read of it — `performers_for()`, `attendance_for()`, the Song page, the `unique_song_role_person` constraint — would have to learn to filter on that column or silently start reporting one evening's stand-in as a fact about the setlist. A second table keeps each read honest by default.

This is the second answer this codebase has given to "someone can't play their part." ADR 0002 answered the *role fit* version — assign anyway, flag `is_role_mismatch`, never block. That is not this problem: a role mismatch is a standing condition of an assignment, a Backup is a one-evening substitution, and neither substitutes for the other. A future reader who finds ADR 0002 and wonders why its soft-flag shape wasn't reused here should read the two as answering different questions.

## The anchor is `RehearsalSong`, which depends on ADR 0006

A Backup hangs off a `RehearsalSong` — the timed slot — not off a `(Rehearsal, Song)` pair. `RehearsalSong` is what actually exists in time, it is already what `Recording` anchors to, and it gives cascade-on-song-swap for free: pull a Song out of a rehearsal's Running Order and its Backups go with it, which is the correct outcome.

**This is only safe because of ADR 0006.** The Dress Rehearsal has no `RehearsalSong` rows at all (ADR 0003 derives its songs live), so a `RehearsalSong` anchor makes Backups structurally impossible there. That is acceptable only because ADR 0006 makes Dress Rehearsal attendance mandatory and forbids any `Conflict` against it, removing the cause a Backup exists to answer. **If ADR 0006 is ever reversed, this decision reopens with it** — a Dress Rehearsal that can carry Conflicts can need Backups, and this anchor could not express them.

## `covering_for` is advisory, never load-bearing

A Backup records `(rehearsal_song, role, person)` as a standalone fact — "this person plays this role at this slot" — plus a nullable `covering_for` FK to **`Person`**, annotating who is being stood in for. It deliberately does *not* point at the `SongRoleAssignment` being overridden. That row is routinely deleted and re-created (issue #130's member removal purges assignments wholesale), so an FK to it would leave Backups dying or dangling on edits that have nothing to do with the substitution. Pointing at `Person` matches `Conflict.person` and `SongRoleAssignment.person`, which are already FKs to `Person` rather than to `Membership`.

Three consequences follow from `covering_for` being an annotation rather than a dependency:

- **`SET_NULL`, not `CASCADE`.** Deleting the covered Person must not delete someone else's Backup; it degrades to the no-standing-assignee case below.
- **A Backup with no standing assignee is legal** (`covering_for` null). Nobody holds that Role on that Song and an admin drafts someone in for the night. Forbidding it would make this model stricter than the Role Requirement it serves, which `CONTEXT.md` defines as "a target, never a cap."
- **Withdrawing the covered Conflict does nothing automatically.** The Backup stands until an admin removes it. Auto-deleting would silently undo an admin's arrangement in response to a member's action — after the Backup may already have learned the part — and blocking the withdrawal would make a member's own availability hostage to an admin's plan. Staleness ("covering for someone who no longer has a Conflict") is computed live and shown as a quiet admin advisory, never stored, in the same spirit as ADR 0003's live derivation.

## Uniqueness, deletion, and the mismatch flag

`UniqueConstraint(rehearsal_song, role, person)` mirrors `unique_song_role_person`: one row per Person per Role per slot, but **any number of people per `(slot, role)`** — three singers can each have a Conflict. A `CheckConstraint` forbids `person == covering_for`, which is a genuine impossibility rather than an advisory condition; this is not in tension with ADR 0002, whose soft-flag rule is about role *fit*.

Deletion is **hard**, cascading from `rehearsal_song`, `role`, and `person`. The repo's soft-delete convention (`Role.is_active`) exists where historical references must stay intact; nothing references a Backup, and a removed one means "that arrangement isn't happening." There is no `created_at` and no free-text `notes` — the latter would be the second free-text field about a person's absence, and ADR 0005 exists to contain the first.

`is_role_mismatch` is a **stored field recomputed in `save()`**, exactly mirroring `SongRoleAssignment`, with `_reevaluate_song_role_assignments_for()` generalised to sweep Backups when a `MembershipRole` changes. Deriving it live here while storing it there would leave the same concept computed two ways in one admin grid. A Backup for a Person not rostered in the Semester at all is likewise allowed and flagged, per ADR 0002.

## Member-facing surfaces show the Backup, never the covered name

The rehearsal schedule shows **"X (backup)"** to every member — X needs to know they are playing, and so does everyone else in the room. The `covering_for` name renders on **admin surfaces only**. "X is covering for Y at Rehearsal 4" is an unambiguous disclosure that Y declared a Conflict that night, which is precisely what ADR 0005 keeps off member-facing routes; ADR 0005 governs rendering rather than storage, so recording the FK is fine. This **extends** ADR 0005 to a new field rather than amending it, and the field-by-field verdicts stay in [`docs/person-page-visibility.md`](../person-page-visibility.md).

`Rehearsal.attendance_for()` **does** account for Backups: a Backup on a rehearsal's first or last slot genuinely changes when that person must arrive and leave, and omitting it would tell someone they aren't needed at a rehearsal an admin just drafted them into. `services.performers_for(song)` **does not**: it is a Song-level read feeding the Song page, and folding one night's substitution into it would misreport who plays the song, which is a Setlist fact.

`Recording` needs no change. Upload is not gated on any assignment today — `Recording.uploaded_by` is a plain `Person` FK — so a Backup can already upload their take, and the `RehearsalSong` anchor means it lands on exactly the slot the Backup is scoped to. The two models already agree; this is recorded so nobody goes looking for the integration work.
