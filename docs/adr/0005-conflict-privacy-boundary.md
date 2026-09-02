# Conflict data is never rendered on a member-facing surface

A Person's `Conflict` rows — the free-text `reason` above all — are never rendered on any member-facing page, including the person page at `/members/<pk>/` and including when the viewer is an admin. Admins keep full access to Conflict data, `reason` included, through admin-only surfaces (today `ConflictAdmin`), because adjudicating a conflict and scheduling around it needs that context. The boundary is therefore drawn around the *surface*, not around the *viewer*: `/members/<pk>/` is a member-facing page even when an admin is looking at it.

We considered making `reason` owner-only even for admins (excluding it from `ConflictAdmin`), and considered a strict owner-only rule for all Conflict data. Both are behaviour changes rather than documentation of the existing boundary — the admin already reads `reason` today — and both misread which disclosure people actually object to. The concern a member has is that their bandmates will see *why* they're missing a rehearsal, not that the person building the schedule will.

## Consequences

- The owner reads their own Conflict data at `/conflicts/`, not on their person page. `/members/<pk>/` renders no Conflict data for anyone, its owner included, so there is exactly one place this data is presented to a member and one owner-scoped query behind it.
- Derived attendance data (`Rehearsal.attendance_for`, `breaks_for`, `next_attended_rehearsal_for`, `attendance_suggestion_for`) is also absent from both `/members/` and `/members/<pk>/`. It is a partial inference of the same availability picture, so surfacing it per-person would undercut this boundary without touching a `Conflict` row. Self reads it on Overview and Schedule, anchored to a specific Rehearsal.
- Issue #130's admin edit layer on `/members/<pk>/` must not add a Conflict or attendance column. Its permission test is "is this surface member-facing", which is a property of the route, not of `request.user.is_admin` — an admin-only *column* on a member-facing page is the specific thing this ADR rules out.
- The absence of an availability column on the roster is deliberate. A future reader will reasonably wonder why the band's own roster won't tell them who is coming to the next rehearsal; the answer is that band-wide convenience was traded away for it.

The field-by-field verdicts for both routes live in [`docs/person-page-visibility.md`](../person-page-visibility.md).
