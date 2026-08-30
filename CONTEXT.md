# Rolling Sloans

The domain model for the Rolling Sloans band website: tracking who's in the band each semester, what they play, the setlist, and the rehearsal schedule.

## Language

**Person**:
A band member's persistent identity (name, login), independent of any one semester. The same Person can span multiple semesters across their MBA tenure.
_Avoid_: Member, User

**Semester**:
One term (e.g. "Fall 2026") that gets its own fresh roster, setlist, and rehearsal schedule — the unit at which the band "refreshes."
_Avoid_: Term, Season

**Membership**:
A Person's participation in one Semester. Carries the roles that person has declared they can play *that* semester — declarations can change semester to semester as people pick up or drop instruments.
_Avoid_: Roster entry, Profile

**Role**:
A specific instrument or function a person can fill on a song (e.g. singer, guitarist, drummer). One global catalog shared across all semesters — a semester doesn't redefine roles, it just uses whichever subset applies.
_Avoid_: Part, Instrument

**Song**:
A piece belonging to one specific Semester's setlist. If the same title is performed again in a later semester, that's a distinct Song — titles can repeat, Songs don't carry over.
_Avoid_: Track, Number

**Setlist**:
The ordered collection of a Semester's Songs (by concert position). Not a separate entity — it's the Songs belonging to a Semester, in order.

**Role Assignment**:
The fact that a specific Person fills a specific Role on a specific Song. One Person can hold multiple Role Assignments across different songs, or even multiple roles on the same song.
_Avoid_: Casting

**Role mismatch**:
The condition where a Role Assignment's Role isn't among the Roles the assigned Person declared on their Membership for that semester. Surfaced as a flag for an admin to resolve — either by changing the assignment or updating the person's declared roles — never a hard block.

**Rehearsal**:
A dated, timed event within a Semester during which some of that semester's Songs are worked through, one after another in timed blocks.
_Avoid_: Practice, Session

**Dress Rehearsal**:
The Rehearsal whose song coverage always tracks the Semester's current setlist, in concert order — not a fixed set of songs chosen in advance, since it should reflect whatever the setlist looks like at the time.

**Recording**:
An uploaded audio file of a member's take on one song's slot at one rehearsal (a RehearsalSong) — not the rehearsal or song in the abstract. Multiple Recordings can exist for the same RehearsalSong (e.g. several takes), each with its own uploader and optional note.
_Avoid_: Upload, Track
