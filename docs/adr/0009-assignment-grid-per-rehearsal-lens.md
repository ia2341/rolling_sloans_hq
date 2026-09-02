# Role Assignments are edited through a per-Rehearsal lens

The admin surface for editing `SongRoleAssignment` is the **rehearsal assignment grid** on `/schedule/` — the Song × Role × Person matrix `services.assignment_matrix_for()` already builds for members. That grid is scoped to one Rehearsal, but a Role Assignment is not: ADR 0001 scopes it to the **Semester**, and the model carries no rehearsal FK. Editing a cell on Wednesday's grid therefore changes who plays that Song at *every* rehearsal and at the concert.

This is deliberate, and it is the thing a future reader will not expect. **Do not "fix" it by adding a `rehearsal` FK to `SongRoleAssignment`** — that is ADR 0007's question, and it was answered with a separate `Backup` model precisely so this table can keep meaning one thing.

## Why the per-Rehearsal surface, when the data is per-Semester

The obvious alternative was to edit assignments on `/songs/<pk>/`, where the data's own scope matches the page's, and where the Song's Role Assignments and Role Requirements already render. It was rejected for two reasons.

The first is that **the grid is where the information needed to make the decision lives**. "Who should play this?" is answered by seeing the whole rehearsal at once: which Roles are unfilled across the evening, who is already carrying three songs, who is in the room. A per-Song page shows one row of that.

The second is that **availability fallout is only computable through a Rehearsal**. A `Conflict` and its `ConflictWindow`s are declared against a Rehearsal, and a `RehearsalSong`'s `start_time`/`end_time` are what a Window overlaps. Assigning someone who cannot be there on the night is the one loud-tier warning this surface can raise, and a per-Song editor structurally cannot raise it. The per-Rehearsal lens is not incidental — it is what makes the edit informed.

The cost is the confusion above, which is paid down in the UI rather than the model: the edit affordance states that a change applies to every rehearsal and the concert, and the picker is split into two labelled sections — "Assigned (every rehearsal + concert)" and "Backup (this rehearsal only)" — so the scope distinction is structural rather than a notice that can be missed.

## Consequences

- **`/songs/<pk>/` stays read-only for assignments.** Two editors for one table would mean two pending buffers, two ADR 0008 preview pairs and two `Semester.updated_at` stale-save stamps for the same rows.
- **A past Rehearsal's grid is not editable** (`date < today`, whole days rather than instants). Semester-wide rows *are* still meaningfully editable through a past date, so this is a usability rule rather than a data-integrity one: a grid captioned with last month's date is a misleading place to change next month's concert. The **Dress Rehearsal is the backstop** — it is the last-dated Rehearsal and its rows are the live setlist (ADR 0003), so it stays editable longest. Once it too has passed, the Semester is over and `/admin/` is the escape hatch.
- **The grid may show a Role column that no Song requires.** Columns are derived from `SongRoleRequirement`, so a Role nobody asked for has no cell to assign into. Edit mode can add such a column for the session, and doing so writes **no** `SongRoleRequirement`: this surface assigns people, it does not set targets.
- **`/manage/assignments/` is deleted outright** — view, template, routes and form, with no redirects. Unlike `identity`'s `/manage/people/`, it held nothing cross-semester.
