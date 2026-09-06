# Role mismatch is a soft flag, not a hard block

A Role Assignment where the assigned Person hasn't declared that Role is allowed to be saved, but marked `is_role_mismatch` for an admin to notice and resolve. We considered rejecting the write outright (hard block), but admins are the sole authors of assignments and may legitimately need to assign someone ahead of their profile being updated (e.g. a last-minute fill-in). A hard block would force admins to edit the person's profile first just to make an assignment, adding friction for a case that's supposed to be an exception, not the common path.

**Data source (issue #375, ADR 0014):** the check reads a person-level `PersonRole` table, not `MembershipRole` scoped to the viewing Semester. This changes only where the check looks for "what this Person can play" — the soft-flag behavior described above (allowed to save, surfaced for an admin, never a hard block) is unchanged.
