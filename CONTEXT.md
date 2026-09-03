# Rolling Sloans

The domain model for the Rolling Sloans band website: tracking who's in the band each semester, what they play, the setlist, and the rehearsal schedule.

## Language

**Person**:
A band member's persistent identity (name, login), independent of any one semester. The same Person can span multiple semesters across their MBA tenure.
_Avoid_: Member, User

**Semester**:
One term (e.g. "Fall 2026") that gets its own fresh roster, setlist, and rehearsal schedule — the unit at which the band "refreshes." A Semester nobody has Published is a **draft**: it exists, an admin can build it out, and no member sees it.
_Avoid_: Term, Season

**Live Semester**:
The one Semester non-admin members see — its roster, setlist and schedule are what the site shows them. At most one is live, and there may be none, before the first Publish. Distinct from the Semester an admin is *viewing*, which may be a draft they are preparing.
_Avoid_: Current semester, Active semester *("current" was the old incidental heuristic — the most recently created row — that the lifecycle exists to remove; `Semester` carries no dates, so the app genuinely cannot know which term is happening in real time)*

**Publish**:
The act of making a Semester the Live Semester. Operates only on a whole Semester: edits *within* a semester are never published, they take effect when saved. There is no unpublish — rolling back is Publishing an older Semester, which simply makes that one live again.
_Avoid_: Go live, Release, Activate

**Membership**:
A Person's participation in one Semester. Carries the roles that person has declared they can play *that* semester — declarations can change semester to semester as people pick up or drop instruments.
_Avoid_: Roster entry, Profile *(as an entity — "Profile" is fine as the name of the page that presents a Membership)*

**Role**:
A specific instrument or function a person can fill on a song (e.g. singer, guitarist, drummer). One global catalog shared across all semesters — a semester doesn't redefine roles, it just uses whichever subset applies.
_Avoid_: Part, Instrument

**Song**:
A piece belonging to one specific Semester's setlist. If the same title is performed again in a later semester, that's a distinct Song — titles can repeat, Songs don't carry over.
_Avoid_: Track, Number

**Setlist**:
The ordered collection of a Semester's Songs (by concert position). Not a separate entity — it's the Songs belonging to a Semester, in order.

**Role Requirement**:
The target headcount for one Role on one Song (e.g. three singers). A target admins track fill-status against, never a cap — nothing prevents assigning more or fewer people than requested. It is *only* a target: a Role Requirement confers no assignability, so a Person can hold a Role Assignment on a Song that carries no Requirement for that Role, and writing a Requirement is not how a Role becomes assignable.
_Avoid_: Quota, Cap, Gate

**Role Assignment**:
The fact that a specific Person fills a specific Role on a specific Song. One Person can hold multiple Role Assignments across different songs, or even multiple roles on the same song.
_Avoid_: Casting

**Standing Assignment**:
A Role Assignment, named this way when contrasting it with a Backup: it holds for every Rehearsal and for the concert, where a Backup holds for one Rehearsal. The same fact and the same row — the word only marks which scope is meant.
_Avoid_: Permanent assignment, Default assignment

**Role mismatch**:
The condition where a Role Assignment's Role isn't among the Roles the assigned Person declared on their Membership for that semester. Surfaced as a flag for an admin to resolve — either by changing the assignment or updating the person's declared roles — never a hard block.

**Backup**:
A Person covering a Role on a Song at one specific Rehearsal — usually because the Role's usual holder has a Conflict, sometimes because nobody holds it at all. Scoped to that Rehearsal alone — it never changes the Song's Role Assignment or the Person's declared roles on their Membership. Who is being covered for is recorded where there is someone, but it is context rather than part of the fact: the Backup stands even after that person's Conflict is withdrawn. A valid, expected state, not an error.
_Avoid_: Substitute, Fill-in, Understudy

**Rehearsal**:
A dated, timed event within a Semester during which some of that semester's Songs are worked through, one after another in timed blocks.
_Avoid_: Practice, Session

**Dress Rehearsal**:
The Rehearsal whose song coverage always tracks the Semester's current setlist, in concert order — not a fixed set of songs chosen in advance, since it should reflect whatever the setlist looks like at the time. Attendance is **mandatory**: every member is expected there, so no Conflict can be declared against it (ADR-0006).

**Rehearsal Pattern**:
The recurring shape of a Semester's rehearsal calendar — its Rehearsal Times, the range of dates they run over, and its Skip Dates. Records what was asked for, not what exists: the Rehearsals themselves are the source of truth, and changing a Pattern changes nothing until it is used to generate.
_Avoid_: Schedule template, Recurrence

**Rehearsal Time**:
One recurring day-and-time within a Rehearsal Pattern (e.g. "Wednesdays, 7–11pm"). A Semester usually has a couple that hold steady across the term, and each carries its own start and end — different days legitimately run different lengths.
_Avoid_: Slot *(collides with a Song's timed block inside a Rehearsal)*, Weekly time

**Skip Date**:
A date inside a Semester's range on which no Rehearsal happens even though a Rehearsal Time matches it — a holiday, a break, an exam week.
_Avoid_: Blackout, Exception

**Conflict**:
A Person's declared unavailability for one Rehearsal other than the Dress Rehearsal, where attendance is mandatory (ADR-0006) — either **full** (not there at all) or **partial** (there for some of it). Editable in place at any time; there is no submission deadline or edit lock. The *absence* of a Conflict is implicit full availability, not an explicit "available" status — the distinction is deliberate, so a future confirmed-available status stays expressible.
_Avoid_: Absence, Excuse, Unavailability

**Conflict Window**:
One disjoint range of time a Person is unavailable within a partial Conflict's Rehearsal. Several Windows express non-contiguous unavailability (e.g. away 6–7pm and again 8:30–9pm). A full Conflict has no Windows.
_Avoid_: Gap, Exception

**Running Order**:
The sequence of Songs within one specific Rehearsal — what gets worked through in what order that evening. Distinct from concert position, which belongs to the Setlist: a Rehearsal has a Running Order, a Semester has a Setlist. The Dress Rehearsal has no Running Order of its own, since its songs always track the Setlist in concert order.
_Avoid_: Rehearsal order, Song order *(both collide with concert position)*

**Adjudication**:
An admin's decision to approve or reject a Conflict — pending until made, then approved or rejected. Adjudicating does not by itself change the schedule: approving records that the band will work around the Person, not how, and the Running Order and Backups that actually accommodate them are separate acts an admin carries out afterwards. Rejecting preserves the declaration rather than discarding it — the Person is simply told the band expects them there. An Adjudication may carry a short note from the admin, which the Person reads alongside the outcome. It is not a record: a Person's edit returns their Conflict to pending and takes the note with it, so nothing distinguishes a re-edited Conflict from one never adjudicated, and pending is not a queue that empties — a Conflict for a Rehearsal now past keeps whatever state it was left in.
_Avoid_: Approval *(names only one of the two outcomes)*, Review

**Accommodation**:
A Running Order under which every Person's assigned Songs fall outside their own Conflict Windows. What an admin weighs when adjudicating is whether an Accommodation *exists* for the set of Conflicts being approved together — a question about the whole Rehearsal, not about one Conflict in isolation. A full Conflict has no Accommodation to look for: the Person is simply absent, and no Running Order changes that.
_Avoid_: Fix, Resolution, Rescheduling

**Recording**:
An uploaded audio file of a member's take on one song's slot at one rehearsal (a RehearsalSong) — not the rehearsal or song in the abstract. Multiple Recordings can exist for the same RehearsalSong (e.g. several takes), each with its own uploader and optional note.
_Avoid_: Upload, Track

**Pending Buffer**:
The set of unsaved edits an admin has accumulated on a bulk-edit surface but not yet committed — the rows added, changed, and marked for removal, held client-side between one "Save Changes" and the next. A Buffer is a proposal, not a state of the band: nothing in it is true until it is saved, and abandoning the page discards it whole.
_Avoid_: Draft, Staged changes *("draft" is taken — an unpublished Semester)*

**Preview**:
The server's answer to "what would saving this Pending Buffer do?", computed by running the real save and discarding it. A Preview never changes anything: it reports Validation Errors and Fallout, and is the only way an admin sees consequences the server alone can compute (slot times, Role mismatches, unfillable Role Requirements, what a removal destroys).
_Avoid_: Dry run, Simulation *(both suggest an approximation of the save; a Preview is the save itself, thrown away)*

**Fallout**:
What saving a Pending Buffer would *do to existing data* — consequences of a save that is perfectly valid. **Loud** Fallout destroys or breaks something (a removal wiping a Person's Role Assignments, a Role Requirement left unfillable); **quiet** Fallout is worth noticing but benign (a newly-flagged Role mismatch, a Membership left with no declared Roles). Fallout never blocks a save, in either tier (ADR-0002).

Distinct from a **Validation Error**, which means the Buffer cannot be saved at all (a slot overrun, a duplicate Running Order position, an unparseable length) and always blocks. The two are never presented as one list: an admin who learns that loud Fallout is sometimes ignorable will start ignoring Validation Errors too.
_Avoid_: Warning, Side effect *("warning" blurs the blocking/non-blocking line the two terms exist to draw)*
