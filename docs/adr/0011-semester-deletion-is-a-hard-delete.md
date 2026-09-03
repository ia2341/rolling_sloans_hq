# Semester deletion is a hard delete, not soft

Deleting a Semester (issue #171) is a real `DELETE`, cascading through Memberships, MembershipRoles, Songs, SongRoleRequirements, SongRoleAssignments, Rehearsals, RehearsalSongs, Conflicts, ConflictWindows and Recordings — and, for Recordings, through to the private-bucket objects those rows named. `Person` rows are the one thing left standing: a member of a deleted term still logs in and uses the site, simply with no roster entry for that term anymore.

This is a deliberate exception to the repo's soft-delete-where-history-matters convention (`Role.is_active`, and generally ADR 0002's reasoning). That convention protects references that outlive the thing they point at. Semester deletion is the opposite case: an admin choosing to discard a whole term's history outright — a superseded or never-published Semester nobody needs a trace of — not a reference an unrelated row still needs to resolve. Soft-deleting a Semester would leave every FK'd row (Memberships, Songs, Rehearsals, Recordings…) alive and pointing at a "deleted" Semester forever, which is exactly the accumulation this feature exists to let an admin clear out.

## Why the Live Semester is still refused

An admin can hard-delete *any other* Semester, but never the Live Semester — the one non-admins are currently looking at. The refusal lives in `delete_semester()` itself, not only in the view, so no future caller (a script, a different view, the Django admin's bulk action) can route around it. Deleting the Live Semester out from under members isn't a smaller version of this feature; it's a different, unwanted operation. Publishing a different Semester first is the only path to deleting the incumbent.

## Why the confirmation offers no export

The spec (issue #165, amended on #124) explicitly rejected an export-before-delete branch. The confirmation is one decision — delete or don't — naming the four counts (members, songs, rehearsals, recordings) with the recording count called out plainly as members' uploaded audio, so nobody is surprised later by silently vanished takes. Retrieval of recordings before deletion is not a supported feature; an admin who wants to keep the audio needs to have decided that before clicking Delete.

## Consequences

- Recording object keys are collected **before** `semester.delete()` runs, since the rows naming them are gone the instant the cascade completes — there is no reading them back afterward.
- The storage deletions are registered with `transaction.on_commit()` and are best-effort: a storage outage is logged, never raised, and never rolls back or blocks the Semester row deletion that already committed. This is the first use of `transaction.on_commit()` in the codebase, establishing the convention ADR 0008 (preview-by-rollback) will lean on: every irreversible external side effect goes through `on_commit`, never inline.
- There is no undo. A deleted Semester, its Memberships, Songs, Rehearsals, and Recordings are gone from the database, and the Recording objects are gone from storage. This is the whole point of the feature — old terms and abandoned drafts should stop accumulating in the switcher forever — but it means the delete confirmation is the only safety net there is.
