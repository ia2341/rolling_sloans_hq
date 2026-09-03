# Person page visibility rules

The field-by-field verdicts governing the two member-facing roster routes:

- **`/members/`** — the Band Members list (`MembersView`, issue #137)
- **`/members/<int:pk>/`** — the single person page (issue #138), read-only for a teammate and editable in place for your own pk **or, since issue #232, for an admin viewing anyone's pk**

Both routes are member-facing surfaces for every logged-in Person, admins included. Admin status changes nothing about what these two pages render, apart from one exception each, split by cardinality: `/members/` gains an admin-only **Edit roster** mode across the whole Roster (issue #227), and `/members/<pk>/` keeps the always-inline `MembershipRolesForm` that lets *you* edit your own declared Roles regardless of admin status (issue #138) — and now relaxes its POST guard so an admin can save that same form on **anyone's** page (issue #232). Both edit surfaces are bound by the same verdicts below.

**How to read a verdict.** *Teammate* is any logged-in Person viewing someone else's row or page. *Self* is a Person viewing their own. **`never`** means never on **these two surfaces** — it is not a claim about the whole application. Several fields marked `never` here are legitimately rendered elsewhere: `Song.artist` on the Song page, `Conflict.reason` on `/schedule/` for its owner and in `ConflictAdmin` for an admin.

**Anything not listed below is `never` by default.** New fields on the models covered here do not become visible by being added; they become visible by being added to this table with a verdict.

## `/members/` — the list row

**Admin (edit mode)** is the third verdict column added by issue #227's Roster editor: an admin-only mode on this same route, entered via "Edit roster", holding one Pending Buffer committed by `apply_roster_edits()` under a single Save Changes. It never changes the Teammate/Self verdicts for a non-admin viewer, or for an admin who hasn't pressed the button (read mode stays byte-identical).

| Field | Teammate | Self | Admin (edit mode) | Notes |
| --- | --- | --- | --- | --- |
| `Person.name` | ✅ | ✅ | ✅ read + **write** | Read mode links to `/members/<pk>/`; edit mode renders it as a text field instead |
| `Person.pk` | ✅ | ✅ | ✅ | As the link target (read mode) or the row's hidden identity (edit mode); never rendered as text |
| `Semester.name` | ✅ | ✅ | ✅ | Page heading, via the session-selected viewing Semester (issue #167); the non-live banner renders whenever it's a draft |
| `MembershipRole.role` → `Role.name` | ✅ | ✅ | ✅ read + **write** | Read mode comma-joins declared Roles (`—` when none); edit mode renders a checkbox group over **active** Roles only |
| Count of distinct assigned Songs | ✅ | ✅ | ❌ never | `Membership.songs_count`, annotated by `roster_for`; not a candidate for editing, so edit mode omits it |
| `SongRoleAssignment.is_role_mismatch` | ❌ never | ❌ never | ✅ quiet flag | The admin's queue marker (ADR 0002), surfaced only in edit mode as a per-row completeness flag — never a name, never a Song, never rendered to a Teammate or Self view |
| Remove-from-Roster control | ❌ never | ❌ never | ✅, except the requesting admin's own row | Absent (with a short reason in its place) from the row belonging to the admin submitting the request — `apply_roster_edits()`'s `SelfRemovalError` backstops a hand-crafted POST |
| `Conflict`, `ConflictWindow` (any field, `reason` above all) | ❌ never | ❌ never | ❌ never | ADR 0005's boundary is drawn around the surface, not the viewer — nothing about Roster editing needs Conflict data |
| `Person.email` | ❌ never | ❌ never | ✅, "Invite someone new" form input and removal confirmation only | Issue #230: the invite form is a blank input an admin types into, never a rendering of an existing Person's address; the removal confirmation shows a to-be-removed Person's email so two similarly-named people can be told apart. Nowhere else on this page |
| everything else | ❌ never | ❌ never | ❌ never | Every admin-status field — cross-semester identity stays on the admin-only people-management page, since admin status is not semester-scoped |

## `/members/<int:pk>/` — the person page

**Admin (edit mode)** below is issue #232's relaxed POST guard: the same always-inline `MembershipRolesForm` a Person sees on their own page also renders, and saves, for an admin viewing anyone else's page. It changes nothing about the Teammate/Self columns for a non-admin viewer, and it is **not** a third rendering mode with its own template branch — an admin viewing their own page still just gets the Self behavior. There is no batch, no Preview, and no remove control here at any cardinality (removal stays on `/members/`, per issue #232).

### `Person` (`identity/models.py`)

| Field | Teammate | Self | Admin (edit mode) | Notes |
| --- | --- | --- | --- | --- |
| `name` | ✅ | ✅ | ✅ | |
| `email` | ❌ never | ✅ self only | ❌ never | See "Known divergence" below — an admin viewing a teammate gets the Teammate verdict, not Self's |
| `pk` | ✅ | ✅ | ✅ | Route parameter; not rendered as text |
| `password` | ❌ never | ❌ never | ❌ never | Self gets the `identity:password-change` link instead; that link is self-only too |
| `last_login` | ❌ never | ❌ never | ❌ never | |
| `is_active` | ❌ never | ❌ never | ❌ never | |
| `is_admin` | ❌ never | ❌ never | ❌ never | Admin status is not member-facing on either route; the badge stays on the admin-only `identity/templates/identity/people.html` |
| `is_staff`, `is_superuser` | ❌ never | ❌ never | ❌ never | Mirrors of `is_admin` (`Person.save()`) |
| Permission/group relations (`PermissionsMixin`) | ❌ never | ❌ never | ❌ never | No Group/Permission scheme exists to render |

### `Membership`, `MembershipRole`, `Role` (`scheduling/models.py`)

Current `Semester` only, per ADR 0001 — there is no past-semester history on this page.

| Field | Teammate | Self | Admin (edit mode) | Notes |
| --- | --- | --- | --- | --- |
| `Membership.semester` → `Semester.name` | ✅ | ✅ | ✅ | Page heading |
| `MembershipRole.role` → `Role.name` | ✅ | ✅ read + **write** | ✅ read + **write** | Self edits via the always-inline `MembershipRolesForm`; an admin edits the same form on anyone's page (issue #232); no edit toggle either way |
| `Role.is_active` | ❌ never | ❌ never | ❌ never | A declared Role that has since been retired still renders by name; the flag itself is never shown |
| `Semester.default_*` timing fields | ❌ never | ❌ never | ❌ never | Not candidates on this page |

### `SongRoleAssignment` and the `Song` fields it reaches

| Field | Teammate | Self | Admin (edit mode) | Notes |
| --- | --- | --- | --- | --- |
| `song` → `Song.title` | ✅ | ✅ | ✅ | Links to the Song page |
| `role` → `Role.name` | ✅ | ✅ | ✅ | The Role filled on that Song — see "Role mismatch is inferable" below |
| `is_role_mismatch` | ❌ never | ❌ never | ❌ never | ADR 0002 makes this an admin queue marker, not a fact about the Person. A teammate has no business being told someone is playing outside their declared Roles, and showing it to the Person invites them to self-resolve the adjudication ADR 0002 assigns to an admin. Issue #227 surfaces it, on the Roster editor's per-row completeness flag on **`/members/`** — not on this page, for an admin viewer either |
| `Song.artist`, `length`, `notes`, `position` | ❌ never | ❌ never | ❌ never | Song detail belongs on the Song page |

### `Conflict` and `ConflictWindow`

Every field, for everyone, including the owner and an admin viewer of this page: **`never`**. See [ADR 0005](adr/0005-conflict-privacy-boundary.md) — the boundary is drawn around the surface, not the viewer, so issue #232's admin write access to declared Roles carries no Conflict visibility with it.

| Field | Teammate | Self | Admin (edit mode) | Notes |
| --- | --- | --- | --- | --- |
| `Conflict.reason` | ❌ never | ❌ never | ❌ never | The free-text field ADR 0005 exists to protect |
| `Conflict.type`, `rehearsal`, `created_at`, `updated_at` | ❌ never | ❌ never | ❌ never | The owner reads these at `/schedule/` |
| `Conflict.status` | ❌ never | ❌ never | ❌ never | The Adjudication outcome. The owner reads it at `/schedule/`, and an admin at `/manage/conflicts/<rehearsal_id>/`; neither of those is one of these two routes |
| The Adjudication note | ❌ never | ❌ never | ❌ never | Admin-authored, and read by the Conflict's owner only — at `/schedule/`, alongside the status. Same verdict as `reason` here, for the same reason: this page has no Rehearsal in scope and is read by teammates |
| `ConflictWindow.unavailable_start`, `unavailable_end` | ❌ never | ❌ never | ❌ never | |

### Derived attendance data (`scheduling/services.py`, `Rehearsal.attendance_for`)

| Value | Teammate | Self | Admin (edit mode) | Notes |
| --- | --- | --- | --- | --- |
| `Rehearsal.attendance_for` | ❌ never | ❌ never | ❌ never | Needs a Rehearsal in scope; this page has none |
| `breaks_for` | ❌ never | ❌ never | ❌ never | Self reads this on Schedule |
| `next_attended_rehearsal_for` | ❌ never | ❌ never | ❌ never | Self reads this on Overview |
| `attendance_suggestion_for` | ❌ never | ❌ never | ❌ never | Partial inference of the same availability picture ADR 0005 protects |

### `Recording`

Every field, for everyone: **`never`**. A Recording's identity is the `RehearsalSong` slot it belongs to (`CONTEXT.md`), and the uploader is provenance rather than ownership — so Recordings are reached from the Song side only. A person-side listing would add a second signed-URL issuance path (ADR 0004) for no information the Song page doesn't already carry.

### `Backup`

Every field, for everyone, including the person backing up: **`never`** on these two routes. See [ADR 0007](adr/0007-rehearsal-scoped-backup.md).

| Field | Teammate | Self | Admin (edit mode) | Notes |
| --- | --- | --- | --- | --- |
| `rehearsal_song`, `role`, `person` | ❌ never | ❌ never | ❌ never | A Backup is scoped to one Rehearsal slot and this page has no Rehearsal in scope — the same reason `attendance_for` is `never` above. The Backup itself **is** member-visible on the Schedule, rendered as "*name* (backup)" |
| `covering_for` | ❌ never | ❌ never | ❌ never | **Admin surfaces only, everywhere** — but not *this* admin surface. Naming the covered Person discloses that they declared a `Conflict` for that date, which is exactly what ADR 0005 keeps off member-facing routes. ADR 0005 governs rendering, not storage |
| `is_role_mismatch` | ❌ never | ❌ never | ❌ never | Same verdict and same reasoning as `SongRoleAssignment.is_role_mismatch` above: an admin queue marker per ADR 0002, not a fact about the Person |

This section states a verdict the "anything not listed is `never`" default already gives, because a reader will actively wonder: a Backup *is* shown to all members on the Schedule, so its absence here would otherwise read as an oversight rather than a decision.

## The not-in-semester self case

`/members/<pk>/` 404s for a Person with no current-`Semester` `Membership` — **except** your own pk, which preserves the unsaved-`Membership` path so a newly-invited member can declare Roles before an admin rosters them. In that state the page renders:

- `Person.name`, `Person.email`, and the change-password link
- the inline `MembershipRolesForm`, bound to the unsaved `Membership`
- an explicit empty-state line

and renders **no** declared-Roles list and **no** assigned-Songs section at all — not a zero. A `0` there is indistinguishable from "rostered but idle", and this Person is not on the roster.

When there is no current `Semester` at all, both routes show an empty state, matching `SetlistView`.

## Two notes for a future reader

**Role mismatch is inferable, and that is accepted.** Rendering declared Roles alongside the Role filled on each assigned Song lets a teammate spot a mismatch by eye, even though `is_role_mismatch` is `never`. This is not an oversight. What `never` withholds is the *admin's queue marker* — the signal that someone should act — not the underlying assignment, which is already rendered to all members on the Song page (`scheduling/templates/scheduling/song_detail.html`). Suppressing the Role to close the inference would hide from a teammate what they can read one click away, and would leave the page with little to say beyond the list row.

**A Person is rendered by `.name`, never as a `Person`.** `Person.__str__` returns the email address (`identity/models.py:99`), so rendering a `Person` object directly in a template publishes that email to every logged-in member, contradicting the `email → self only` verdict above. Issue #138 fixed four such renderings that predate this table — the Song page's Assignments list and Recordings list, the Songs page's performers column, and the Schedule matrix — and `scheduling/tests/test_views.py:MemberFacingEmailPrivacyTests` holds the line. Templates render `.name` explicitly; the admin-only `manage_assignments.html` and `identity/people.html` are outside this rule and keep showing the email deliberately.
