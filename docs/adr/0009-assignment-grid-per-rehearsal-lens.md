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
- **`/manage/assignments/` is deleted outright** — view, template, routes and form, with no redirects. Unlike `identity`'s `/manage/people/`, it held nothing cross-semester.

## Amendment (issue #442, ADR 0015): the grid can no longer show an unrequired Role column

The bullet this amendment replaces said the grid may show a Role column that no Song requires, and that its ad-hoc "+ Add role" control writes no `SongRoleRequirement` because "this surface assigns people, it does not set targets." Issue #439/#440 (ADR 0015) reversed that: a `SongRoleAssignment` can now only be created for a `(song, role)` pair that already carries a `SongRoleRequirement`, so a column with no backing Requirement has nothing to assign into and the grid's own "+ Add role" control (`addable_roles_for()`) is removed. A Role now becomes assignable through exactly one route — the Requirements editor's "+ Add role requirement" control (issue #339) — and the grid's columns are simply every Role with a Requirement, full stop.

This does not reopen the per-Rehearsal-lens question this ADR answers: the grid is still where an admin edits a `SongRoleAssignment`, still scoped per-Rehearsal for the reasons above, and still distinct from `/songs/<pk>/`, which stays read-only for assignments and is where a Requirement itself is authored. ADR 0015 changes what determines whether a column can exist at all, not who edits the cells inside it once it does.

## Narrowed by issue #499 (ADR 0019): casting moved to the Song; this grid is Backups only

**Read `0019-song-level-casting.md` alongside this ADR — the surface question above is decided differently now.** `SongRoleAssignment` is edited on `/songs/<pk>/` and through `/setlist`'s inline per-cell popover; the per-Rehearsal grid writes only `Backup` rows and the Running Order. Three passages above are superseded outright:

- **"availability fallout is only computable through a Rehearsal"**, and its conclusion that a per-Song editor "structurally cannot raise" the loud-tier warning. This was the load-bearing premise, and it was wrong: a Song has Rehearsals of its own, so `services.song_cast_conflict_summary_for()` answers the same question from the Song's side — one entry per *future* `RehearsalSong` of the Song where the candidate has a full Conflict or an overlapping Window — reusing `_windows_overlap()` rather than reimplementing it. See ADR 0019 for why that reformulation is the better warning, not merely an adequate one.
- **"`/songs/<pk>/` stays read-only for assignments"**, and the two-editors-means-two-Buffers cost it was justified by. There are still only two functions writing this table's Buffer, because the Rehearsal grid's own `AssignmentEditBuffer` *lost* its assignment fields rather than gaining a sibling.
- **"The Dress Rehearsal is the backstop"**, which existed only to keep standing-assignment editing reachable late in the Semester. With casting gone from this surface there is nothing there to reach: a Dress Rehearsal has no `RehearsalSong` (ADR 0003), so it has no Backup to add and no Running Order to reorder, and its "Edit Rehearsal" control is removed. `assignment_grid_is_editable()` is now "not the Dress Rehearsal, and `date >= today`" — the `is_full_setlist` clause reversed direction rather than disappearing, because that predicate is also the wire's `can_edit_assignments`.

**Unchanged, and still governing:** the past-date rule itself; the instruction never to "fix" the scope mismatch with a `rehearsal` FK on `SongRoleAssignment` (still ADR 0007's question, still answered by `Backup`); the ADR 0015 amendment above, which decides what makes a Role assignable at all and is orthogonal to which page does the assigning; and `/manage/assignments/` staying deleted.
