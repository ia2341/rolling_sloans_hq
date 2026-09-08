# Person off-boarding is a reversible Deactivate, not a delete

`/accounts/manage/people/`'s retirement (issue #342) leaves two Person-lifecycle acts with nowhere to live: granting/revoking admin, and taking someone off-boarded. We're building the second as **Deactivate** — `Person.is_active = False`, blocking login, immediately terminating any live session, and hiding the Person from current-facing views — never as a delete. The row, email, password hash, historical Role Assignments, and Memberships are all untouched, and the act reverses via Reactivate. This differs from a Semester's own Delete (ADR 0011), which is a genuine hard, cascading, unreversed removal; Person off-boarding needed the opposite guarantee, since a Person is durable identity (ADR 0001) and historical assignments referencing them must keep rendering, not error.

## Consequences

- The "last admin" guard (also newly built for admin grant/revoke, alongside a self-revoke guard) counts only Persons who are both `is_admin=True` and `is_active=True` — a deactivated admin's flag survives deactivation (admin status only ever changes by explicit action, never as a side effect) but doesn't count toward "someone must be able to log in and administer."
- `resend_invite()` refuses an inactive Person, so "deactivated" is a dead end at the invite layer too, not just at login.
- Deactivation does not touch future-facing scheduling state (future Memberships, Role Assignments, Rehearsal Running Orders) — those are surfaced to the deactivating admin as a warning, sourced from `/members/:personId`'s existing read model, but left for a human to resolve separately.
- This is deliberately **not** built as a Pending Buffer/Preview/Fallout surface (ADR 0008's shape): there's no multi-field edit to accumulate, and the warning is a read of data the page already loads, not a rolled-back real save. "Fallout" (per CONTEXT.md) stays a term reserved for what a Preview computes; this warning is not that, and isn't called by that name.
- Reactivation is the inverse with nothing to warn about: it restores login and current-view visibility and nothing else, since nothing else was ever touched.
