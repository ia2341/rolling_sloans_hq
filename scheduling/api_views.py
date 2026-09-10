"""`/api/` views for the Setlist and Song detail (issue #330), the Schedule surface (issue #331), the Band/Person surfaces (issue #333), and the Setlist edit surface (issue #334).

Reads (`SetlistApiView`, `SongDetailApiView`, `BandApiView`, `PersonApiView`,
`PersonRolesApiView`, the Recordings endpoints) are `ApiView`s, not
`AdminApiView`s: every route here is member-facing, and the only
admin-conditional content (the ADR-0009 `next_rehearsal` pointer, and
`can_edit_roles` on the Person page) is decided by the serializer or the
view's own per-request check, not by gating the whole endpoint — a
non-admin still needs to read these surfaces.

The Setlist edit surface's Preview and Save (`SetlistPreviewApiView`,
`SetlistSaveApiView`) are admin-only writes, added by issue #334 as the
Setlist's proof-of-concept for the shared Pending-Buffer-over-HTTP shape:
`build_setlist_buffer_from_request()` is the ONE place a submitted JSON
body becomes a `SetlistEditBuffer`, and both views call it — never a
second, forked parsing path (ADR 0008's "preview and save cannot
disagree" rule, re-shaped across an HTTP boundary rather than weakened by
one).
"""

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View

from config.views import AdminApiView, AdminPreviewApiView, ApiView
from identity.models import Person
from identity.services import (
    AlreadyHasPasswordError,
    CannotDeactivateLastActiveAdminError,
    CannotDeactivateSelfError,
    CannotRevokeLastActiveAdminError,
    CannotRevokeOwnAdminStatusError,
    EmailDeliveryError,
    PersonIsDeactivatedError,
    apply_admin_status_change,
    apply_person_deactivation,
    apply_person_reactivation,
    resend_invite,
)
from scheduling import serializers, services, spotify
from scheduling.api_builders import (
    AdjudicationBufferValidationError,
    AssignmentBufferValidationError,
    RehearsalBufferValidationError,
    RehearsalPatternInputError,
    RosterBufferValidationError,
    SemesterDefaultsReapplyBufferValidationError,
    SetlistBufferValidationError,
    SongRoleRequirementBufferValidationError,
    build_adjudication_buffer_from_request,
    build_assignment_buffer_from_request,
    build_generation_date_range_from_body,
    build_rehearsal_buffer_from_request,
    build_rehearsal_pattern_input_from_body,
    build_rehearsal_reorder_buffer_from_request,
    build_roster_buffer_from_request,
    build_semester_defaults_reapply_buffer_from_request,
    build_setlist_buffer_from_request,
    build_song_role_requirement_buffer_from_request,
)
from scheduling.forms import DeclareConflictForm
from scheduling.models import (
    Conflict,
    Membership,
    Recording,
    Rehearsal,
    RehearsalSong,
    Role,
    Semester,
    Song,
)
from scheduling.services import (
    DealInfeasibleError,
    EmptySetlistError,
    InvalidSemesterNameError,
    LiveSemesterDeletionError,
    MissingSongRoleRequirementError,
    NoEligibleRehearsalsError,
    PastRehearsalEditError,
    RecordingUploadError,
    RehearsalPatternCollisionError,
    RunningOrderValidationError,
    SelfRemovalError,
    SemesterDefaultsReapplyBlockedError,
    StaleAdjudicationSemesterError,
    StaleAssignmentSemesterError,
    StaleRehearsalSemesterError,
    StaleRosterSemesterError,
    StaleSemesterDefaultsError,
    StaleSetlistSemesterError,
    StaleSongRoleRequirementsError,
    UnknownConflictError,
    WrongAdjudicationSemesterError,
    WrongViewingSemesterError,
)


class HomeApiView(ApiView, View):
    """`GET /api/`: Home's Next-rehearsal, Upcoming-rehearsals and Song-progress regions, plus (admin, draft) the setup checklist (issue #332).

    Member-facing, not admin-gated: the admin-only setup-checklist block
    is decided inside `serializers.serialize_home()`, not by gating the
    whole endpoint — a non-admin still needs to read the rest of Home.
    """

    def get(self, request):
        """Return the Home envelope for `get_viewing_semester(request)`, or its empty shape when nothing is published/selected."""
        semester = services.get_viewing_semester(request)
        return self.read_response(request, serializers.serialize_home(request, semester))


class SetlistApiView(ApiView, View):
    """`GET /api/setlist/`: the viewing Semester's whole Setlist read model, in one round trip."""

    def get(self, request):
        """Return the Setlist envelope for `get_viewing_semester(request)`, or its empty shape when nothing is published/selected."""
        semester = services.get_viewing_semester(request)
        return self.read_response(request, serializers.serialize_setlist(semester))


class SongDetailApiView(ApiView, View):
    """`GET /api/songs/<pk>/`: one Song's read model, scoped to the viewing Semester."""

    def get(self, request, pk):
        """Return the Song envelope, 404ing when `pk` names a Song outside the viewing Semester (ADR 0001)."""
        semester = services.get_viewing_semester(request)
        song = get_object_or_404(Song, pk=pk, semester=semester)
        is_admin = bool(getattr(request.user, 'is_admin', False))
        next_rehearsal = None
        if is_admin:
            upcoming = services.upcoming_rehearsals_for(semester, count=1)
            next_rehearsal = upcoming[0] if upcoming else None
        data = serializers.serialize_song(song, is_admin=is_admin, next_rehearsal=next_rehearsal)
        return self.read_response(request, data)


def _song_in_viewing_semester_or_404(request, pk):
    """Return the viewing Semester's Song `pk` names, or 404 (ADR 0001, mirrors `SongDetailApiView.get()`)."""
    semester = services.get_viewing_semester(request)
    return get_object_or_404(Song, pk=pk, semester=semester)


class SongRoleRequirementPreviewApiView(AdminPreviewApiView):
    """`POST /api/songs/<pk>/requirements/preview/`: the Requirements editor's Preview, run for real and rolled back (issue #339, ADR 0008)."""

    def run_preview(self, request, pk):
        """Build the Requirements edit Buffer from the JSON body and return its rendered Fallout envelope.

        Mirrors `SetlistPreviewApiView.run_preview()`: a
        `SongRoleRequirementBufferValidationError` renders as `ok: false`
        with per-row `errors`/`non_field_errors` and the raw submitted body
        echoed back as `values`; a `semester_id` that doesn't match the
        viewing Semester is answered as the shared 409 before
        `preview_song_role_requirements()` is ever called, so that
        function's `is_blocked` Fallout shape never has to double as this
        endpoint's 4xx contract. `pk` is 404'd against the viewing
        Semester first (ADR 0001), the same as `SongDetailApiView.get()`.
        """
        _song_in_viewing_semester_or_404(request, pk)
        viewing_semester = services.get_viewing_semester(request)
        try:
            buffer = build_song_role_requirement_buffer_from_request(request, song_id=pk, viewing_semester=viewing_semester)
        except SongRoleRequirementBufferValidationError as error:
            return self.write_response(
                request, ok=False, errors=error.row_errors, non_field_errors=error.non_field_errors,
                fallout=None, values=error.raw_body,
            )

        if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
            return _wrong_semester_response(
                "This Requirements edit Buffer's Semester doesn't match the Semester you're currently viewing."
            )

        fallout = services.preview_song_role_requirements(buffer, viewing_semester=viewing_semester)
        return self.write_response(
            request, ok=True,
            fallout=serializers.serialize_song_role_requirement_fallout(fallout),
            values=serializers.serialize_song_role_requirement_buffer(buffer),
        )


class SongRoleRequirementSaveApiView(AdminApiView, View):
    """`POST /api/songs/<pk>/requirements/save/`: the Requirements editor's Save — the real, committing write (issue #339)."""

    def post(self, request, pk):
        """Build the Requirements edit Buffer from the JSON body and apply it, or report why it couldn't be applied.

        Calls the same `build_song_role_requirement_buffer_from_request()`
        the Preview endpoint calls, then the unchanged
        `apply_song_role_requirements()`. A wrong `semester_id` answers the
        shared 409 before `apply_song_role_requirements()` is even called;
        a `StaleSongRoleRequirementsError` is reported as `ok: false` with
        a `non_field_errors` message rather than a hard 4xx, per ADR 0008's
        "stale is reported, never refused" rule. `values` is omitted on
        every response here, per #326's rule that a write response doesn't
        echo the Buffer back.
        """
        _song_in_viewing_semester_or_404(request, pk)
        viewing_semester = services.get_viewing_semester(request)
        try:
            buffer = build_song_role_requirement_buffer_from_request(request, song_id=pk, viewing_semester=viewing_semester)
        except SongRoleRequirementBufferValidationError as error:
            return self.write_response(
                request, ok=False, errors=error.row_errors, non_field_errors=error.non_field_errors,
                fallout=None, values=None,
            )

        if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
            return _wrong_semester_response(
                "This Requirements edit Buffer's Semester doesn't match the Semester you're currently viewing."
            )

        try:
            services.apply_song_role_requirements(buffer, viewing_semester=viewing_semester)
        except WrongViewingSemesterError as error:
            return _wrong_semester_response(str(error))
        except StaleSongRoleRequirementsError as error:
            return self.write_response(request, ok=False, non_field_errors=[str(error)], fallout=None, values=None)

        return self.write_response(request, ok=True, values=None)


def _wrong_semester_response(message: str) -> JsonResponse:
    """Return the shared 409 for a Pending Buffer whose `semester_id` doesn't match the viewing Semester (issue #334).

    Deliberately shaped like the project's other bare error envelopes
    (`{"error": ...}`, no `context` block) — `ApiView.handle_no_permission()`'s
    401, `AdminApiView.handle_admin_required()`'s 403, `ApiView.dispatch()`'s
    malformed-body 400 and `ApiNotFoundView`'s 404 all skip `context` too,
    since none of them can assume a request has enough state to build one
    safely (`build_context()` itself calls `get_viewing_semester(request)`,
    which is exactly the thing a wrong `semester_id` casts doubt on). A
    wrong `semester_id` is a genuine 4xx, never a per-row Validation
    Error: it means the tab that submitted this Buffer is looking at a
    different Semester than the one the server now has selected — a
    cross-tab condition the client should treat as unrecoverable for this
    submission, distinct from a stale `semester_updated_at` (which
    `write_response()`'s `ok: false` + `fallout.is_stale`/`non_field_errors`
    reports instead, per the issue: reported, never refused). Picked 409
    Conflict over 400 because the payload itself is well-formed — it's
    the server's current state that has moved out from under it.
    """
    return JsonResponse({'error': 'wrong_semester', 'message': message}, status=409)


class SetlistPreviewApiView(AdminPreviewApiView):
    """`POST /api/setlist/preview/`: the Setlist edit surface's Preview, run for real and rolled back (issue #334, ADR 0008)."""

    def run_preview(self, request):
        """Build the Setlist edit Buffer from the JSON body and return its rendered Fallout envelope.

        Delegates all parsing to `build_setlist_buffer_from_request()` —
        the same function `SetlistSaveApiView.post()` calls — so a
        Preview and a Save of the identical body can never disagree about
        what Buffer they're describing. A `SetlistBufferValidationError`
        renders as `ok: false` with per-row `errors`/`non_field_errors`
        and the raw submitted body echoed back as `values` (issue #334
        user story 18: a validation failure still shows every submitted
        value, even though normalization never finished). A `semester_id`
        that doesn't match the viewing Semester is answered before
        `preview_setlist_edits()` is ever called, as the shared 409 (a
        hard-fail, not a per-row error) — `preview_setlist_edits()` itself
        would otherwise swallow that exact condition into a
        `SetlistEditFallout.is_blocked` Fallout, which is the right shape
        for its pre-SPA template caller but not for this endpoint's
        documented 4xx contract.
        """
        viewing_semester = services.get_viewing_semester(request)
        try:
            buffer = build_setlist_buffer_from_request(request, viewing_semester=viewing_semester)
        except SetlistBufferValidationError as error:
            return self.write_response(
                request,
                ok=False,
                errors=error.row_errors,
                non_field_errors=error.non_field_errors,
                fallout=None,
                values=error.raw_body,
            )

        if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
            return _wrong_semester_response(
                "This Setlist edit Buffer's Semester doesn't match the Semester you're currently viewing."
            )

        fallout = services.preview_setlist_edits(buffer, viewing_semester=viewing_semester)
        return self.write_response(
            request,
            ok=True,
            fallout=serializers.serialize_setlist_edit_fallout(fallout),
            values=serializers.serialize_setlist_edit_buffer(buffer),
        )


class SetlistSaveApiView(AdminApiView, View):
    """`POST /api/setlist/save/`: the Setlist edit surface's Save — the real, committing write (issue #334)."""

    def post(self, request):
        """Build the Setlist edit Buffer from the JSON body and apply it, or report why it couldn't be applied.

        Calls the same `build_setlist_buffer_from_request()` the Preview
        endpoint calls, then the unchanged `apply_setlist_edits()` — no
        second construction path, no second write path. A wrong
        `semester_id` answers the shared 409 before `apply_setlist_edits()`
        is even called (mirroring the Preview endpoint's pre-check); a
        `StaleSetlistSemesterError` — a genuine race, since the client is
        expected to have already seen `is_stale` from its last Preview and
        disabled Save — is reported as `ok: false` with a `non_field_errors`
        message rather than a hard 4xx, per the issue's "stale is reported,
        never refused" rule; `apply_setlist_edits()` has already rolled
        its own transaction back by the time this except runs, so nothing
        is left half-applied. `values` is omitted on every response here,
        per #326's rule that a write response doesn't echo the Buffer back
        (unlike Preview, which deliberately does).
        """
        viewing_semester = services.get_viewing_semester(request)
        try:
            buffer = build_setlist_buffer_from_request(request, viewing_semester=viewing_semester)
        except SetlistBufferValidationError as error:
            return self.write_response(
                request,
                ok=False,
                errors=error.row_errors,
                non_field_errors=error.non_field_errors,
                fallout=None,
                values=None,
            )

        if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
            return _wrong_semester_response(
                "This Setlist edit Buffer's Semester doesn't match the Semester you're currently viewing."
            )

        try:
            services.apply_setlist_edits(buffer, viewing_semester=viewing_semester)
        except WrongViewingSemesterError as error:
            return _wrong_semester_response(str(error))
        except StaleSetlistSemesterError as error:
            return self.write_response(
                request,
                ok=False,
                non_field_errors=[str(error)],
                fallout=None,
                values=None,
            )

        return self.write_response(request, ok=True, values=None)


class SetlistSpotifyImportApiView(AdminApiView, View):
    """`POST /api/setlist/spotify/`: fetches a public Spotify playlist as + Add sheet candidates (issue #335).

    Writes nothing anywhere: `scheduling.spotify.import_playlist()` only
    reads from Spotify, and this view persists no `Song` — an imported row
    exists only once the admin ticks it into the edit Buffer and Saves.
    Answers its own shape (`songs`/`skipped_count`/`skipped_reasons`/`message`),
    not the write envelope: the envelope boundary rule (issue #307)
    reserves that shape for an endpoint that takes a Pending Buffer, and
    this endpoint answers a question instead. Still carries `context`, via
    `read_response()`. A missing/blank `url`, an unconfigured Spotify
    credential (`SpotifyImportUnavailable`) and every other
    `SpotifyImportError` (a malformed link, a private/missing playlist, an
    auth failure, a rate limit, a transport error) all degrade to a
    readable `message` in a 200 response rather than a non-2xx status, so
    the sheet renders the failure inline instead of treating it as a
    fetch failure (issue #335 user stories 27-28).
    """

    def post(self, request):
        """Fetch `request`'s JSON `url` as a playlist and return its candidates, or a readable `message` on failure."""
        body = self.parse_json_body(request)
        url = body.get('url') if isinstance(body, dict) else None
        if not isinstance(url, str) or not url.strip():
            return self.read_response(
                request, serializers.serialize_spotify_import([], skipped_count=0, skipped_reasons={}, message=spotify.INVALID_LINK_MESSAGE)
            )

        try:
            result = spotify.import_playlist(url)
        except spotify.SpotifyImportError as error:
            return self.read_response(
                request, serializers.serialize_spotify_import([], skipped_count=0, skipped_reasons={}, message=str(error))
            )

        viewing_semester = services.get_viewing_semester(request)
        candidates = services.spotify_import_candidates_for(viewing_semester, result.songs)
        return self.read_response(
            request,
            serializers.serialize_spotify_import(
                candidates, skipped_count=result.skipped_count, skipped_reasons=result.skipped_reasons, message=''
            ),
        )


class ScheduleApiView(ApiView, View):
    """`GET /api/schedule/`: the whole Schedule read model in one round trip (issue #331).

    Member-facing, not admin-gated: the admin-conditional content (the
    pending-count chip, `covering_for`, `can_edit_assignments`) is decided
    inside `serializers.serialize_schedule()`, not by gating the endpoint.
    `?rehearsal=<id>` selects which Rehearsal the "This rehearsal" sub-view
    details; omitted, it falls back to the viewer's landing Rehearsal. Both
    sub-views come back in the one response — switching between them is
    client-side state, never a second fetch.
    """

    def get(self, request):
        """Return the Schedule envelope, 404ing when `?rehearsal=` names a Rehearsal outside the viewing Semester."""
        semester = services.get_viewing_semester(request)
        rehearsal_id = self._parse_rehearsal_id(request)
        try:
            data = serializers.serialize_schedule(request, semester, rehearsal_id=rehearsal_id)
        except Rehearsal.DoesNotExist:
            raise Http404 from None
        return self.read_response(request, data)

    def _parse_rehearsal_id(self, request):
        """Return the `?rehearsal=` query param as an int, or None if absent; 404 for a non-numeric value."""
        raw_id = request.GET.get('rehearsal')
        if raw_id is None:
            return None
        try:
            return int(raw_id)
        except ValueError:
            raise Http404 from None


def _declarable_rehearsal_or_404(request, rehearsal_id):
    """Return the viewing Semester's Rehearsal `rehearsal_id` names that may be declared against, or 404 (issue #331).

    Mirrors `scheduling/views.py`'s `_declarable_rehearsal_or_404`:
    `future_rehearsals_for()` is the single definition of "declarable", so
    a request naming a past Rehearsal or the Dress Rehearsal 404s here
    rather than reaching `declare_conflict()`'s ValueError (ADR 0006).
    """
    rehearsals = {
        rehearsal.pk: rehearsal for rehearsal in services.future_rehearsals_for(services.get_viewing_semester(request))
    }
    rehearsal = rehearsals.get(rehearsal_id)
    if rehearsal is None:
        raise Http404('No Rehearsal here can be declared against.')
    return rehearsal


def _future_rehearsal_with_conflict_or_404(request, rehearsal_id):
    """Return the viewing Semester's future Rehearsal with an existing Conflict for `request.user`, or 404 (issue #331).

    Mirrors `scheduling/views.py`'s `_future_rehearsal_with_conflict_or_404`
    for the withdraw endpoint: date and ownership are re-checked here
    regardless of request origin.
    """
    semester = services.get_viewing_semester(request)
    rehearsal = get_object_or_404(Rehearsal, pk=rehearsal_id, semester=semester)
    if not Conflict.objects.filter(person=request.user, rehearsal=rehearsal).exists():
        raise Http404('No existing Conflict for this Rehearsal.')
    if rehearsal.date < timezone.localdate():
        raise Http404('Past Rehearsals cannot be withdrawn.')
    return rehearsal


class ConflictDeclareApiView(ApiView, View):
    """`POST /api/schedule/<rehearsal_id>/conflict/`: declares or edits the viewer's own Conflict for one Rehearsal (issue #331).

    A plain form-shaped write, not a Pending Buffer endpoint (#334 owns
    that envelope) — a validation failure comes back at HTTP 200 with
    per-field errors, per the issue's "Writes" decision.
    """

    def post(self, request, rehearsal_id):
        """Persist the submitted declaration, or return per-field errors with the typed reason preserved."""
        rehearsal = _declarable_rehearsal_or_404(request, rehearsal_id)
        payload = self.parse_json_body(request)
        form = DeclareConflictForm(payload, rehearsal=rehearsal)
        if not form.is_valid():
            return self.write_response(request, ok=False, errors=form.errors, values=payload)
        services.declare_conflict(
            person=request.user,
            rehearsal=rehearsal,
            declaration_type=form.cleaned_data['declaration_type'],
            declared_time=form.declared_time,
            reason=form.cleaned_data['reason'],
        )
        conflict_row = services.conflict_rows_by_rehearsal(rehearsal.semester, request.user)[rehearsal.pk]
        return self.write_response(request, ok=True, data=serializers.serialize_availability(rehearsal, conflict_row))


class ConflictWithdrawApiView(ApiView, View):
    """`POST /api/schedule/<rehearsal_id>/conflict/withdraw/`: deletes the viewer's own Conflict for one Rehearsal (issue #331).

    Future-only, enforced server-side (mirrors `ConflictDeleteView`) — a
    past declaration stays put as a record, and nothing else deletes a
    Conflict.
    """

    def post(self, request, rehearsal_id):
        """Delete `request.user`'s Conflict (and its ConflictWindows, via cascade) for this future Rehearsal, or 404."""
        rehearsal = _future_rehearsal_with_conflict_or_404(request, rehearsal_id)
        Conflict.objects.filter(person=request.user, rehearsal=rehearsal).delete()
        return self.write_response(request, ok=True, data=None)


class BandApiView(ApiView, View):
    """`GET /api/members/`: the Band page's whole read model — the viewing Semester's whole Roster, in one round trip (issue #333).

    Every Membership row is included regardless of invite/password state
    (issue #455) — Membership alone is "who's in the band this semester"
    (per `CONTEXT.md`'s own definition), and invite status is an
    orthogonal, admin-only display fact surfaced via `invite_status` on
    each row rather than a reason to hide the row outright. Previously
    this excluded anyone without a usable password, which meant a person
    an admin added-without-inviting during roster setup was a real
    Membership row invisible on their own Band page.
    """

    def get(self, request):
        """Return the Band envelope for `get_viewing_semester(request)`, or its empty shape when nothing is published/selected.

        For an admin viewer, also surfaces `unassigned_role_holders` — the
        admin-only gap-flag between `SongRoleAssignment` and `Membership`
        (see `services.unassigned_role_holders_for`'s docstring) — so a
        casting done ahead of a roster row doesn't stay invisible.
        """
        semester = services.get_viewing_semester(request)
        if semester is None:
            memberships = Membership.objects.none()
        else:
            memberships = services.roster_for(Membership.objects.filter(semester=semester))
        is_admin = bool(getattr(request.user, 'is_admin', False))
        gap_holders = services.unassigned_role_holders_for(semester) if is_admin else None
        data = serializers.serialize_band(memberships, semester, unassigned_role_holders=gap_holders, is_admin=is_admin)
        return self.read_response(request, data)


class RosterEditApiView(AdminApiView, View):
    """`GET /api/members/roster/`: the Roster editor's whole read model for the viewing Semester (issue #336).

    Unlike `BandApiView` (active Roster only), this returns every
    Membership — invited-but-not-yet-active people included — since the
    editor is exactly the surface that needs to rename them or offer
    "Invite again". Carries no Role data (issue #379): a Person's declared
    Roles are set only on their Person page (#378), never here.
    """

    def get(self, request):
        """Return the Roster editor envelope, or its empty shape when no Semester is being viewed."""
        semester = services.get_viewing_semester(request)
        if semester is None:
            data = {
                'semester_id': None, 'semester_updated_at': None,
                'active_count': 0, 'invited_count': 0, 'members': [],
            }
            return self.read_response(request, data)
        memberships = services.roster_for(Membership.objects.filter(semester=semester))
        mismatched_person_ids = services.mismatched_person_ids_for(semester)
        data = serializers.serialize_roster_edit(semester, memberships, mismatched_person_ids=mismatched_person_ids)
        return self.read_response(request, data)


class RosterCandidatesApiView(AdminApiView, View):
    """`GET /api/members/roster/candidates/`: the `+ Add people` sheet's two ticket-source lists (issue #336).

    Answers a question rather than taking a Buffer, so per the envelope
    boundary rule this wears the read envelope, not the write one.
    """

    def get(self, request):
        """Return the prior Semester's Roster proposal and the unrostered active People, or the empty shape."""
        semester = services.get_viewing_semester(request)
        if semester is None:
            data = {'import_source_semester_name': None, 'import_candidates': [], 'unrostered_people': []}
            return self.read_response(request, data)
        proposal = services.import_roster_from_semester(semester)
        unrostered_people = services.unrostered_people_for(semester)
        data = serializers.serialize_roster_candidates(proposal, unrostered_people)
        return self.read_response(request, data)


class RoleDeclareApiView(AdminApiView, View):
    """`POST /api/members/roster/roles/`: get-or-creates a Role by name for the `+ Role` chip's "declare a new one" path (issue #336).

    Wraps `create_or_reactivate_role()` unchanged — it commits immediately,
    outside any Pending Buffer, so a Role invented mid-edit survives
    discarding the batch. Own shape, plus `context`, per the envelope
    boundary rule: this answers "what Role resulted from this name", it
    doesn't apply a Buffer.
    """

    def post(self, request):
        """Validate the submitted name and return the resulting Role, or a 400 for a blank one."""
        payload = self.parse_json_body(request)
        name = payload.get('name')
        if not isinstance(name, str) or not name.strip():
            return JsonResponse({'context': self.build_context(request), 'error': 'invalid_name'}, status=400)
        result = services.create_or_reactivate_role(name.strip())
        return self.read_response(request, serializers.serialize_role_declaration(result))


class RosterResendInviteApiView(AdminApiView, View):
    """`POST /api/members/roster/<pk>/resend-invite/` and `POST /api/members/<pk>/invite/`: (re)send a pending invite (issue #336, #327, #397).

    One view, two routes: the Roster editor's "Invite again" control and
    the Person page's "Invite"/"Invite again" action both call this —
    never a second implementation. It equally serves the *first* invite
    for someone `identity.services.add_person()` created without ever
    emailing them (issue #397): `resend_invite()` only refuses a Person
    who already has a usable password, so it doesn't care whether
    `invited_at` was set before this call. An immediate act, not a Buffer
    row: it changes no Roster state, so there is nothing to stage and
    nothing for the Save popup to describe.
    """

    def post(self, request, pk):
        """Re-send (or send for the first time) `pk`'s invite, returning their fresh Person payload, or the refusal if they already have a password or the email fails to send."""
        person = get_object_or_404(Person, pk=pk)
        try:
            resend_invite(person)
        except (AlreadyHasPasswordError, PersonIsDeactivatedError) as error:
            return self.write_response(request, ok=False, non_field_errors=[str(error)])
        except EmailDeliveryError:
            return self.write_response(
                request, ok=False, non_field_errors=[f"Couldn't send the invite email to {person.email}."],
            )
        semester = services.get_viewing_semester(request)
        membership = Membership.objects.filter(person=person, semester=semester).first() if semester is not None else None
        data = serializers.serialize_person(
            person, semester=semester, is_self=False, can_edit_roles=True, membership=membership,
        )
        return self.write_response(request, ok=True, data=data)


def _wrong_roster_semester_response(message: str) -> JsonResponse:
    """Return the shared 409 for a Roster edit Buffer whose `semester_id` doesn't match the viewing Semester (issue #336, mirrors `_wrong_semester_response`)."""
    return JsonResponse({'error': 'wrong_semester', 'message': message}, status=409)


class RosterPreviewApiView(AdminPreviewApiView):
    """`POST /api/members/roster/preview/`: the Roster edit surface's Preview, run for real and rolled back (issue #336, ADR 0008)."""

    def run_preview(self, request):
        """Build the Roster edit Buffer from the JSON body and return its rendered Fallout envelope.

        Mirrors `SetlistPreviewApiView.run_preview()` exactly: a
        `RosterBufferValidationError` renders as `ok: false` with per-row
        `errors`/`non_field_errors` and the raw submitted body echoed back
        as `values`; a `semester_id` that doesn't match the viewing
        Semester is answered as the shared 409 before
        `preview_roster_edits()` is ever called, so that endpoint's
        `is_blocked` Fallout shape never has to double as this endpoint's
        4xx contract. `preview_roster_edits()` runs `apply_roster_edits()`
        for real, including creating and mailing any staged invite via
        `transaction.on_commit()` — the rollback `PreviewMixin.post()`
        performs discards both for free (ADR 0008).
        """
        viewing_semester = services.get_viewing_semester(request)
        try:
            buffer = build_roster_buffer_from_request(request, viewing_semester=viewing_semester)
        except RosterBufferValidationError as error:
            return self.write_response(
                request, ok=False, errors=error.row_errors, non_field_errors=error.non_field_errors,
                fallout=None, values=error.raw_body,
            )

        if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
            return _wrong_roster_semester_response(
                "This Roster edit Buffer's Semester doesn't match the Semester you're currently viewing."
            )

        fallout = services.preview_roster_edits(
            buffer, viewing_semester=viewing_semester, requesting_admin=request.user,
        )
        return self.write_response(
            request, ok=True,
            fallout=serializers.serialize_roster_edit_fallout(fallout),
            values=serializers.serialize_roster_edit_buffer(buffer),
        )


class RosterSaveApiView(AdminApiView, View):
    """`POST /api/members/roster/save/`: the Roster edit surface's Save — the real, committing write (issue #336)."""

    def post(self, request):
        """Build the Roster edit Buffer from the JSON body and apply it, or report why it couldn't be applied.

        Calls the same `build_roster_buffer_from_request()` the Preview
        endpoint calls, then the unchanged `apply_roster_edits()`. A wrong
        `semester_id` answers the shared 409 before `apply_roster_edits()`
        is even called; `SelfRemovalError` and `StaleRosterSemesterError`
        are reported as `ok: false` with a `non_field_errors` message — a
        blocking Validation Error, never a hard 4xx, since a hand-crafted
        self-removal must be *refused*, not merely 403'd (issue #336 user
        story 15). `values` is omitted on every response here, per #326's
        rule that a write response doesn't echo the Buffer back.
        """
        viewing_semester = services.get_viewing_semester(request)
        try:
            buffer = build_roster_buffer_from_request(request, viewing_semester=viewing_semester)
        except RosterBufferValidationError as error:
            return self.write_response(
                request, ok=False, errors=error.row_errors, non_field_errors=error.non_field_errors,
                fallout=None, values=None,
            )

        if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
            return _wrong_roster_semester_response(
                "This Roster edit Buffer's Semester doesn't match the Semester you're currently viewing."
            )

        try:
            services.apply_roster_edits(buffer, viewing_semester=viewing_semester, requesting_admin=request.user)
        except WrongViewingSemesterError as error:
            return _wrong_roster_semester_response(str(error))
        except (SelfRemovalError, StaleRosterSemesterError) as error:
            return self.write_response(request, ok=False, non_field_errors=[str(error)], fallout=None, values=None)

        return self.write_response(request, ok=True, values=None)


class PersonApiView(ApiView, View):
    """`GET /api/members/<pk>/`: one Person's page, in one round trip (issue #333).

    Three viewer states, computed here and handed to the serializer: a
    teammate (read-only), self (adds email and Recordings), and an admin
    viewing a teammate (the teammate payload, plus `can_edit_roles`) — see
    `docs/person-page-visibility.md`. `pk` 404s when it names a Person with
    no Membership in the viewing Semester, except your own pk, which keeps
    the unsaved-Membership path so a newly invited member can declare Roles
    before being rostered.
    """

    def get(self, request, pk):
        """Return `pk`'s Person envelope, 404ing for a teammate outside the viewing Semester (ADR 0001)."""
        semester = services.get_viewing_semester(request)
        person = self._get_person_or_404(request, pk, semester)
        is_self = person.pk == request.user.pk
        is_admin = bool(getattr(request.user, 'is_admin', False))
        can_edit_roles = is_self or is_admin
        membership = self._get_or_build_membership(person, semester) if semester is not None else None
        data = serializers.serialize_person(
            person, semester=semester, is_self=is_self, can_edit_roles=can_edit_roles, membership=membership,
        )
        return self.read_response(request, data)

    def _get_person_or_404(self, request, pk, semester):
        """Return your own Person unchecked, or a teammate holding a viewing-Semester Membership, else 404 (mirrors `MemberDetailView`)."""
        if pk == request.user.pk:
            return request.user
        if semester is None:
            raise Http404('No Semester is being viewed.')
        membership = get_object_or_404(
            Membership.objects.filter(semester=semester).select_related('person'), person_id=pk,
        )
        return membership.person

    def _get_or_build_membership(self, person, semester):
        """Return `person`'s Membership for `semester`, or an unsaved one if they hold none yet."""
        return Membership.objects.filter(person=person, semester=semester).first() or Membership(
            person=person, semester=semester,
        )


class PersonRolesApiView(ApiView, View):
    """`POST /api/members/<pk>/roles/`: saves standing declared Roles for your own pk, or (issue #232, #378) an admin's on anyone's.

    Not `AdminApiView`: a non-admin may hit this for their own pk. A
    teammate's page has no mutation surface for a non-admin viewer, so the
    guard 404s exactly as `MemberDetailView`'s POST does, rather than
    rendering a rejected form.

    Writes `PersonRole` (ADR-0014), not `MembershipRole` — a standing,
    person-level fact that needs no Semester in scope, so this endpoint no
    longer requires (or creates) a Membership. Not run through this repo's
    Buffer-preview-apply ceremony: it renumbers nothing, and its only side
    effect (the `is_role_mismatch` resweep, issue #377) already fires via
    `PersonRole`'s own signals regardless of how the write is framed — see
    the PR description for the fuller Buffer/no-Buffer reasoning.
    """

    def post(self, request, pk):
        """Validate and persist the submitted `role_ids` as `pk`'s complete standing `PersonRole` set."""
        is_admin = bool(getattr(request.user, 'is_admin', False))
        if pk != request.user.pk and not is_admin:
            raise Http404("A member can only edit their own declared Roles unless they're an admin.")
        person = request.user if pk == request.user.pk else get_object_or_404(Person, pk=pk)
        payload = self.parse_json_body(request)
        role_ids = payload.get('role_ids', [])
        try:
            services.sync_person_roles(person, role_ids)
        except (services.PersonRoleValidationError, ValueError, TypeError):
            return self.write_response(
                request, ok=False, non_field_errors=['One or more selected roles are not valid.'],
            )
        semester = services.get_viewing_semester(request)
        membership = Membership.objects.filter(person=person, semester=semester).first() if semester is not None else None
        data = serializers.serialize_person(
            person, semester=semester, is_self=(person.pk == request.user.pk), can_edit_roles=True,
            membership=membership,
        )
        return self.write_response(request, ok=True, data=data)


class PersonAdminStatusApiView(AdminApiView, View):
    """`POST /api/members/<pk>/admin-status/`: an admin grants or revokes another Person's admin access (issue #467).

    Replaces the legacy `identity.views.PersonToggleAdminView` (no
    self-check, no last-admin check) as `/accounts/manage/people/`
    retires (issue #342, ADR 0017). A direct `apply_admin_status_change()`
    call, not a Pending Buffer: ADR 0008's Buffer -> preview -> apply shape
    is for a multi-field edit with derived Fallout, and flipping one flag
    has neither.
    """

    def post(self, request, pk):
        """Set `pk`'s `is_admin` to the submitted value, or report the guard that refused it.

        A refusal (self-revoke, or revoking the last active admin) is
        rendered as `ok: false` with a `non_field_errors` message, never a
        4xx — a hand-crafted or stale-UI POST hitting either guard must be
        *refused*, not merely rejected as malformed.
        """
        target = get_object_or_404(Person, pk=pk)
        payload = self.parse_json_body(request)
        is_admin = bool(payload.get('is_admin'))
        try:
            apply_admin_status_change(target=target, is_admin=is_admin, requesting_admin=request.user)
        except (CannotRevokeOwnAdminStatusError, CannotRevokeLastActiveAdminError) as error:
            return self.write_response(request, ok=False, non_field_errors=[str(error)])
        semester = services.get_viewing_semester(request)
        membership = Membership.objects.filter(person=target, semester=semester).first() if semester is not None else None
        data = serializers.serialize_person(
            target, semester=semester, is_self=False, can_edit_roles=True, membership=membership,
        )
        return self.write_response(request, ok=True, data=data)


class PersonDeactivationApiView(AdminApiView, View):
    """`POST /api/members/<pk>/deactivate/`: an admin deactivates another Person (issue #469, ADR 0017).

    A direct `apply_person_deactivation()` call, not a Pending Buffer:
    there is no server-computed derivation to preview, only a write plus a
    client-side confirmation dialog built from the person page's
    already-loaded future scheduling footprint (issue #468).
    """

    def post(self, request, pk):
        """Deactivate `pk`, or report the guard that refused it.

        A refusal (self-deactivation, or deactivating the last active
        admin) is rendered as `ok: false` with a `non_field_errors`
        message, never a 4xx, matching `PersonAdminStatusApiView`.
        """
        target = get_object_or_404(Person, pk=pk)
        try:
            target = apply_person_deactivation(target=target, requesting_admin=request.user)
        except (CannotDeactivateSelfError, CannotDeactivateLastActiveAdminError) as error:
            return self.write_response(request, ok=False, non_field_errors=[str(error)])
        semester = services.get_viewing_semester(request)
        membership = Membership.objects.filter(person=target, semester=semester).first() if semester is not None else None
        data = serializers.serialize_person(
            target, semester=semester, is_self=False, can_edit_roles=True, membership=membership,
        )
        return self.write_response(request, ok=True, data=data)


class PersonReactivationApiView(AdminApiView, View):
    """`POST /api/members/<pk>/reactivate/`: an admin reactivates a deactivated Person (issue #469, ADR 0017).

    The pure inverse of `PersonDeactivationApiView`: no guard, no
    confirmation dialog needed client-side, since there is nothing to warn
    about.
    """

    def post(self, request, pk):
        """Reactivate `pk`."""
        target = get_object_or_404(Person, pk=pk)
        apply_person_reactivation(target)
        semester = services.get_viewing_semester(request)
        membership = Membership.objects.filter(person=target, semester=semester).first() if semester is not None else None
        data = serializers.serialize_person(
            target, semester=semester, is_self=False, can_edit_roles=True, membership=membership,
        )
        return self.write_response(request, ok=True, data=data)


class RecordingPresignApiView(ApiView, View):
    """`POST /api/members/recordings/presign/`: reserves a direct-to-R2 upload slot (issue #333, ADR 0004).

    Answers a question rather than taking a Pending Buffer, so — per #307's
    envelope boundary rule — this wears the read envelope, not the write
    one, even though it's a POST.
    """

    def post(self, request):
        """Validate the requested content_type/file_size and return a presigned upload reservation, or a 4xx."""
        payload = self.parse_json_body(request)
        try:
            reservation = services.reserve_recording_upload(payload.get('content_type'), payload.get('file_size'))
        except RecordingUploadError as error:
            return JsonResponse({'context': self.build_context(request), 'error': str(error)}, status=400)
        data = {
            'upload_url': reservation.upload_url,
            'fields': reservation.fields,
            'object_key': reservation.object_key,
        }
        return self.read_response(request, data)


class RecordingSlotsApiView(ApiView, View):
    """`GET /api/members/recordings/slots/`: the requester's own upload-slot list (issue: UI overhaul round 2).

    Backs the reusable Recording-upload popup, called from surfaces that
    have no reason to load the whole Person payload just to get
    `upload_slots` — the Song page's "+" and Profile's own "Add Recording"
    button both open this one popup. Reuses `serialize_person_recordings()`
    unchanged, so this is never a second definition of what counts as an
    upload slot.
    """

    def get(self, request):
        """Return the requester's own Recordings block, or an empty one with no Semester being viewed."""
        semester = services.get_viewing_semester(request)
        data = (
            serializers.serialize_person_recordings(request.user, semester)
            if semester is not None
            else {'count': 0, 'items': [], 'upload_slots': []}
        )
        return self.read_response(request, data)


class RecordingConfirmApiView(ApiView, View):
    """`POST /api/members/recordings/confirm/`: confirms an already-uploaded Recording onto a RehearsalSong slot (issue #333).

    Reuses `confirm_recording_upload()` unchanged, including its
    server-observed content-type/length re-validation, the `recordings/`
    key-prefix check and the duplicate-key check. Returns the requesting
    Person's updated self-only Recordings block, so the Profile page's
    upload card never has to re-fetch the whole Person payload.
    """

    def post(self, request):
        """Validate the confirm submission, persist the Recording, and return the requester's updated Recordings block."""
        semester = services.get_viewing_semester(request)
        if semester is None:
            return self.write_response(request, ok=False, non_field_errors=['No Semester is being edited.'])
        payload = self.parse_json_body(request)
        rehearsal_song = get_object_or_404(
            RehearsalSong, pk=payload.get('rehearsal_song_id'), rehearsal__semester=semester,
        )
        try:
            services.confirm_recording_upload(
                rehearsal_song, request.user, payload.get('object_key'), note=payload.get('note', ''),
            )
        except RecordingUploadError as error:
            return self.write_response(request, ok=False, non_field_errors=[str(error)])
        data = serializers.serialize_person_recordings(request.user, semester)
        return self.write_response(request, ok=True, data=data)


class RecordingDeleteApiView(ApiView, View):
    """`POST /api/members/recordings/<pk>/delete/`: deletes one of the requester's own Recordings (issue #333).

    Ownership stays scoped by `uploaded_by`: a non-uploader's request 404s
    rather than 403ing, so the response never confirms the row exists.
    Returns the requester's updated Recordings block rather than
    redirecting, since a delete on the Profile page has nowhere sensible to
    redirect to (the old view's hardcoded `/songs/<pk>/` redirect was wrong
    from here).
    """

    def post(self, request, pk):
        """Delete the requester's own target Recording and return their updated Recordings block."""
        recording = get_object_or_404(Recording, pk=pk, uploaded_by=request.user)
        recording.delete()
        semester = services.get_viewing_semester(request)
        data = serializers.serialize_person_recordings(request.user, semester)
        return self.write_response(request, ok=True, data=data)


class ScheduleEditorApiView(AdminApiView, View):
    """`GET /api/schedule/editor/`: the whole rehearsal editor's read model, in one round trip (issue #337).

    Admin-only, unlike `ScheduleApiView`: this is the `Edit schedule` route,
    reached only from the Schedule surface's admin action. The
    `context` block's `viewing_semester.updated_at` is what the editor's
    write endpoints stamp a submitted Buffer against, so this view carries
    no separate staleness field of its own.
    """

    def get(self, request):
        """Return the schedule-editor envelope for `get_viewing_semester(request)`, or its empty shape when nothing is selected."""
        semester = services.get_viewing_semester(request)
        return self.read_response(request, serializers.serialize_schedule_editor(semester))


class ScheduleEditorPreviewApiView(AdminPreviewApiView):
    """`POST /api/schedule/editor/preview/`: the rehearsal editor's Preview, run for real and rolled back (issue #337, ADR 0008).

    Fires exactly once, when the Save popup opens (issue #337's "the
    debounced preview fetch goes away" decision) — there is no ambient
    Fallout region on this surface to keep fed.
    """

    def run_preview(self, request):
        """Build the Rehearsal edit Buffer from the JSON body and return its rendered Fallout envelope.

        Mirrors `SetlistPreviewApiView.run_preview()` exactly:
        `build_rehearsal_buffer_from_request()` is the same function
        `ScheduleEditorSaveApiView.post()` calls, so Preview and Save of an
        identical body can never disagree about what Buffer they
        describe. A wrong `semester_id` is answered as the shared 409
        before `preview_rehearsal_edits()` is ever called, rather than
        being swallowed into an `is_blocked` Fallout.
        """
        viewing_semester = services.get_viewing_semester(request)
        try:
            buffer = build_rehearsal_buffer_from_request(request, viewing_semester=viewing_semester)
        except RehearsalBufferValidationError as error:
            return self.write_response(
                request,
                ok=False,
                errors=error.row_errors,
                non_field_errors=error.non_field_errors,
                fallout=None,
                values=error.raw_body,
            )

        if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
            return _wrong_semester_response(
                "This Rehearsal edit Buffer's Semester doesn't match the Semester you're currently viewing."
            )

        fallout = services.preview_rehearsal_edits(buffer, viewing_semester=viewing_semester)
        return self.write_response(
            request,
            ok=True,
            fallout=serializers.serialize_rehearsal_edit_fallout(fallout),
            values=serializers.serialize_rehearsal_edit_buffer(buffer),
        )


class ScheduleEditorSaveApiView(AdminApiView, View):
    """`POST /api/schedule/editor/save/`: the rehearsal editor's Save — the real, committing write (issue #337)."""

    def post(self, request):
        """Build the Rehearsal edit Buffer from the JSON body and apply it, or report why it couldn't be applied.

        Mirrors `SetlistSaveApiView.post()`: the same
        `build_rehearsal_buffer_from_request()` the Preview endpoint calls,
        then the unchanged `apply_rehearsal_edits()`. A `PastRehearsalEditError`
        or `RunningOrderValidationError` is a genuine 4xx-shaped hard
        failure in the service layer, but is reported here the same way a
        `StaleRehearsalSemesterError` is — `ok: false` with
        `non_field_errors` — since none of the three ever leaves partial
        writes behind (`apply_rehearsal_edits()`'s own transaction has
        already rolled back by the time any of these `except` clauses
        run), and a client already renders `non_field_errors` for exactly
        this kind of surface-wide refusal.
        """
        viewing_semester = services.get_viewing_semester(request)
        try:
            buffer = build_rehearsal_buffer_from_request(request, viewing_semester=viewing_semester)
        except RehearsalBufferValidationError as error:
            return self.write_response(
                request,
                ok=False,
                errors=error.row_errors,
                non_field_errors=error.non_field_errors,
                fallout=None,
                values=None,
            )

        if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
            return _wrong_semester_response(
                "This Rehearsal edit Buffer's Semester doesn't match the Semester you're currently viewing."
            )

        try:
            services.apply_rehearsal_edits(buffer, viewing_semester=viewing_semester)
        except WrongViewingSemesterError as error:
            return _wrong_semester_response(str(error))
        except (StaleRehearsalSemesterError, PastRehearsalEditError, RunningOrderValidationError) as error:
            return self.write_response(
                request, ok=False, non_field_errors=[str(error)], fallout=None, values=None,
            )

        return self.write_response(request, ok=True, values=None)


class RehearsalPatternSaveApiView(AdminApiView, View):
    """`POST /api/schedule/editor/pattern/save/`: persists the generate-dates modal's Pattern editor state (issue #337, #222).

    Writes no Rehearsal — `save_rehearsal_pattern()` is input history with
    no downstream authority (CONTEXT.md). Never surfaced to the admin as
    its own button: the modal's own "Preview" action calls this first, so
    the Pattern is remembered between runs, then calls the generation-diff
    endpoint only if this succeeds.
    """

    def post(self, request):
        """Save the submitted Pattern, or report a Validation Error / day-of-week collision."""
        semester = services.get_viewing_semester(request)
        if semester is None:
            return self.write_response(request, ok=False, non_field_errors=['No Semester is being edited.'])
        body = self.parse_json_body(request)
        try:
            pattern_input = build_rehearsal_pattern_input_from_body(body)
        except RehearsalPatternInputError as error:
            return self.write_response(request, ok=False, non_field_errors=error.non_field_errors)
        try:
            services.save_rehearsal_pattern(semester, pattern_input)
        except RehearsalPatternCollisionError as error:
            return self.write_response(request, ok=False, non_field_errors=[str(error)])
        return self.write_response(request, ok=True, values=None)


class RehearsalGenerationDiffApiView(AdminApiView, View):
    """`POST /api/schedule/editor/generate/diff/`: the four-bucket diff for the modal's current Pattern editor state (issue #337, #222).

    `preview_rehearsal_generation()` is a pure read that writes nothing at
    all — this endpoint therefore answers a question rather than taking a
    Pending Buffer (#307's envelope boundary rule), wearing the read
    envelope (`{context, data}`) despite being a POST, the same as
    `RecordingPresignApiView`. The Pattern itself is never saved here —
    `RehearsalPatternSaveApiView` owns that, called first by the modal's
    own "Preview" action.
    """

    def post(self, request):
        """Return the four-bucket diff for the submitted Pattern editor state, or a 400 naming why it couldn't be computed."""
        semester = services.get_viewing_semester(request)
        if semester is None:
            return JsonResponse({'error': 'No Semester is being edited.'}, status=400)
        body = self.parse_json_body(request)
        try:
            pattern_input = build_rehearsal_pattern_input_from_body(body)
            date_range = build_generation_date_range_from_body(body)
        except RehearsalPatternInputError as error:
            return JsonResponse(
                {'context': self.build_context(request), 'error': '; '.join(error.non_field_errors)}, status=400,
            )
        try:
            diff = services.preview_rehearsal_generation(semester, pattern_input, date_range=date_range)
        except RehearsalPatternCollisionError as error:
            return JsonResponse({'context': self.build_context(request), 'error': str(error)}, status=400)
        return self.read_response(request, serializers.serialize_rehearsal_generation_diff(diff))


class ScheduleEditorDealApiView(AdminApiView, View):
    """`POST /api/schedule/editor/deal/`: proposes a fresh balanced Running Order deal for the viewing Semester (issue #337, #223).

    A pure read against the database's current Rehearsals and setlist, not
    the admin's on-screen Buffer — backs both "Generate schedule" and
    "Re-roll" (a re-roll is simply calling this again). Wears the read
    envelope, per #307's envelope boundary rule, since there is no
    `apply_schedule_generation` (see `RehearsalDeal`'s docstring): the
    result fills the Pending Buffer client-side, and only
    `apply_rehearsal_edits()` ever writes it.
    """

    def post(self, request):
        """Return the fresh deal, or a 400 naming why it was refused."""
        semester = services.get_viewing_semester(request)
        if semester is None:
            return JsonResponse({'error': 'No Semester is being edited.'}, status=400)
        try:
            deal = services.deal_running_orders(semester)
        except (EmptySetlistError, NoEligibleRehearsalsError, DealInfeasibleError) as error:
            return JsonResponse({'context': self.build_context(request), 'error': str(error)}, status=400)
        return self.read_response(request, serializers.serialize_rehearsal_deal(deal))


class ScheduleEditorShuffleApiView(AdminApiView, View):
    """`POST /api/schedule/editor/rehearsal/<rehearsal_id>/shuffle/`: proposes a reorder of one Rehearsal's own Running Order (issue #337, #223).

    `rehearsal_id` is scoped to the viewing Semester, 404ing otherwise —
    there is no submitted Buffer here to reject as a Validation Error
    instead. A Rehearsal with no Running Order rows yet returns an empty
    `rows` list, a no-op the client renders as such rather than an error.
    """

    def post(self, request, rehearsal_id):
        """Return the reordered rows for `rehearsal_id`, scoped to the viewing Semester."""
        semester = services.get_viewing_semester(request)
        if semester is None:
            return JsonResponse({'error': 'No Semester is being edited.'}, status=400)
        rehearsal = get_object_or_404(Rehearsal, pk=rehearsal_id, semester=semester)
        rows = services.shuffle_rehearsal_running_order(rehearsal)
        return self.read_response(request, serializers.serialize_shuffle_rows(rows))


class ScheduleEditorStatsApiView(AdminPreviewApiView):
    """`POST /api/schedule/editor/stats/`: the "Randomize Rehearsal Plan" stats panel, recomputed live off the admin's own unsaved Buffer (ADR 0008).

    Takes the exact same JSON body as `/api/schedule/editor/preview/`
    (`build_rehearsal_buffer_from_request()` is the same builder both
    call), but answers a different question: not "what would saving cost"
    but "what does this plan look like right now" — unresolved Conflict
    overlaps, the old-vs-new longest per-Rehearsal wait, and the
    busiest/quietest Songs. Fired debounced on every edit the ScheduleEdit
    route makes to its Buffer (date/time/dress-flag/running-order/add/
    delete), not only on Save, so it wears its own POST-only Preview
    sibling rather than piggybacking on the Save-popup-only
    `ScheduleEditorPreviewApiView`. Runs the real `apply_rehearsal_edits()`
    (via `services.compute_schedule_editor_live_stats()`) inside
    `PreviewMixin`'s transaction, which always rolls it back — nothing this
    endpoint does can ever commit.
    """

    def run_preview(self, request):
        """Build the Rehearsal edit Buffer from the JSON body and return its live stats, or why it couldn't be computed.

        Mirrors `ScheduleEditorPreviewApiView.run_preview()`'s error
        handling exactly, since both endpoints share the same Buffer
        builder and the same underlying `apply_rehearsal_edits()` call: a
        malformed body is a row-keyed Validation Error, a wrong
        `semester_id` is the shared 409, and a `StaleRehearsalSemesterError`/
        `PastRehearsalEditError`/`RunningOrderValidationError` from the
        real apply is reported as `ok: false` with `non_field_errors`
        rather than a stats payload — the panel shows its last-known
        numbers rather than a crash when an edit is transiently invalid
        (e.g. a row still mid-edit with no date yet).
        """
        viewing_semester = services.get_viewing_semester(request)
        try:
            buffer = build_rehearsal_buffer_from_request(request, viewing_semester=viewing_semester)
        except RehearsalBufferValidationError as error:
            return self.write_response(
                request,
                ok=False,
                errors=error.row_errors,
                non_field_errors=error.non_field_errors,
                fallout=None,
                values=error.raw_body,
            )

        if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
            return _wrong_semester_response(
                "This Rehearsal edit Buffer's Semester doesn't match the Semester you're currently viewing."
            )

        try:
            stats = services.compute_schedule_editor_live_stats(buffer, viewing_semester=viewing_semester)
        except WrongViewingSemesterError as error:
            return _wrong_semester_response(str(error))
        except (StaleRehearsalSemesterError, PastRehearsalEditError, RunningOrderValidationError) as error:
            return self.write_response(request, ok=False, non_field_errors=[str(error)], fallout=None, values=None)

        return self.write_response(
            request, ok=True, fallout=None, values=None, data=serializers.serialize_schedule_editor_live_stats(stats),
        )


def _editable_assignment_rehearsal_or_404(request, rehearsal_id):
    """Return the viewing Semester's Rehearsal `rehearsal_id` names that also offers edit mode on its assignment grid, or 404 (issue #338, ADR-0009).

    Mirrors `scheduling/views.py`'s `_editable_assignment_rehearsal_or_404()`:
    `services.assignment_grid_is_editable()` stays the single definition
    of "editable" — a hand-crafted request naming a past-dated,
    non-Dress Rehearsal 404s rather than silently applying a removal or
    add the grid never offered a control for.
    """
    semester = services.get_viewing_semester(request)
    rehearsal = get_object_or_404(Rehearsal, pk=rehearsal_id, semester=semester)
    if not services.assignment_grid_is_editable(rehearsal):
        raise Http404('This Rehearsal is not editable.')
    return rehearsal


class AssignmentPickerApiView(AdminApiView, View):
    """`GET /api/schedule/<rehearsal_id>/assignments/picker/<song_id>/<role_id>/`: the "+" picker's fetched-on-open contents (issue #338).

    Fetched only when a cell's "+" is opened, over the existing roster
    read — an unopened cell issues no request, so a twelve-song six-role
    grid never renders seventy-two live widgets (issue #338's Implementation
    Decisions). Answers a question rather than taking a Pending Buffer, so
    per #307's envelope boundary rule this wears the read envelope
    (`self.read_response()`), never the write one — there is no `values`
    or `errors` field that could ever be populated here.
    """

    def get(self, request, rehearsal_id, song_id, role_id):
        """Return the picker's contents for one (Song, Role) cell on an editable grid, or 404."""
        rehearsal = _editable_assignment_rehearsal_or_404(request, rehearsal_id)
        semester = services.get_viewing_semester(request)
        song = get_object_or_404(Song, pk=song_id, semester=semester)
        role = get_object_or_404(Role, pk=role_id)
        rehearsal_song = None
        if not rehearsal.is_full_setlist:
            rehearsal_song = get_object_or_404(RehearsalSong, rehearsal=rehearsal, song=song)
        picker = services.assignment_picker_for(song, role, semester, rehearsal_song=rehearsal_song)
        return self.read_response(request, serializers.serialize_assignment_picker(picker, rehearsal))


class AssignmentPreviewApiView(AdminPreviewApiView):
    """`POST /api/schedule/<rehearsal_id>/assignments/preview/`: the assignment editor's Preview, run for real and rolled back (issue #338, ADR 0008, ADR 0009).

    Fires exactly once, when the Save popup opens — issue #338's
    "Implementation Decisions" explicitly retires the old debounced
    per-popover-close preview fetch, since there is no ambient Fallout
    region on this surface left to keep fed once the grid moved to the
    SPA.
    """

    def run_preview(self, request, rehearsal_id):
        """Build the assignment edit Buffer from the JSON body and return its rendered Fallout envelope for `rehearsal_id`.

        Mirrors `ScheduleEditorPreviewApiView.run_preview()` exactly:
        `build_assignment_buffer_from_request()` is the same function
        `AssignmentSaveApiView.post()` calls, so Preview and Save of an
        identical body can never disagree about what Buffer they
        describe. A wrong `semester_id`, or a Rehearsal that isn't
        editable, is answered before `preview_song_role_assignments()` is
        ever called, rather than being swallowed into an `is_blocked`
        Fallout.
        """
        rehearsal = _editable_assignment_rehearsal_or_404(request, rehearsal_id)
        viewing_semester = services.get_viewing_semester(request)
        try:
            buffer = build_assignment_buffer_from_request(request, viewing_semester=viewing_semester)
        except AssignmentBufferValidationError as error:
            return self.write_response(
                request, ok=False, errors=None, non_field_errors=error.non_field_errors, fallout=None, values=None,
            )

        if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
            return _wrong_semester_response(
                "This assignment edit Buffer's Semester doesn't match the Semester you're currently viewing."
            )

        fallout = services.preview_song_role_assignments(buffer, rehearsal=rehearsal, viewing_semester=viewing_semester)
        return self.write_response(
            request,
            ok=True,
            fallout=serializers.serialize_assignment_edit_fallout(fallout),
            values=serializers.serialize_assignment_edit_buffer(buffer),
        )


class AssignmentSaveApiView(AdminApiView, View):
    """`POST /api/schedule/<rehearsal_id>/assignments/save/`: the assignment editor's Save — the real, committing write (issue #338)."""

    def post(self, request, rehearsal_id):
        """Build the assignment edit Buffer from the JSON body and apply it, or report why it couldn't be applied.

        Mirrors `ScheduleEditorSaveApiView.post()`: the same
        `build_assignment_buffer_from_request()` the Preview endpoint
        calls, then the unchanged `apply_song_role_assignments()`. A
        `StaleAssignmentSemesterError` and `MissingSongRoleRequirementError`
        are reported as `ok: false` with `non_field_errors` rather than a
        hard 4xx, since `apply_*()`'s own transaction has already rolled
        back whatever it had applied by the time this `except` runs.
        `values` is omitted on every response here, per #326's rule that a
        write response doesn't echo the Buffer back.
        """
        rehearsal = _editable_assignment_rehearsal_or_404(request, rehearsal_id)
        viewing_semester = services.get_viewing_semester(request)
        try:
            buffer = build_assignment_buffer_from_request(request, viewing_semester=viewing_semester)
        except AssignmentBufferValidationError as error:
            return self.write_response(
                request, ok=False, errors=None, non_field_errors=error.non_field_errors, fallout=None, values=None,
            )

        if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
            return _wrong_semester_response(
                "This assignment edit Buffer's Semester doesn't match the Semester you're currently viewing."
            )

        try:
            services.apply_song_role_assignments(buffer, viewing_semester=viewing_semester, rehearsal=rehearsal)
        except WrongViewingSemesterError as error:
            return _wrong_semester_response(str(error))
        except (StaleAssignmentSemesterError, MissingSongRoleRequirementError) as error:
            return self.write_response(request, ok=False, non_field_errors=[str(error)], fallout=None, values=None)

        return self.write_response(request, ok=True, values=None)


def _reorderable_rehearsal_or_404(request, rehearsal_id):
    """Return the viewing Semester's Rehearsal `rehearsal_id` names that offers a Running Order to reorder, or 404 ("Edit Rehearsal" consolidation).

    Reuses `services.assignment_grid_is_editable()` — the same
    editability rule the assignment grid uses, since "Edit Rehearsal" now
    fronts both — but additionally refuses the Dress Rehearsal: it holds
    no `RehearsalSong` rows to reorder at all (ADR-0003), a structural
    exclusion rather than a Validation Error the client would have to
    render.
    """
    rehearsal = _editable_assignment_rehearsal_or_404(request, rehearsal_id)
    if rehearsal.is_full_setlist:
        raise Http404("The Dress Rehearsal has no Running Order of its own to reorder (ADR 0003).")
    return rehearsal


class RunningOrderReorderPreviewApiView(AdminPreviewApiView):
    """`POST /api/schedule/<rehearsal_id>/running-order/preview/`: the "Edit Rehearsal" drag-and-drop's Preview, run for real and rolled back (ADR 0008).

    A thin sibling of `AssignmentPreviewApiView`, sharing its Rehearsal's
    write surface (`apply_rehearsal_edits()`/`preview_rehearsal_edits()`,
    the same functions the bulk `ScheduleEditorPreviewApiView` calls) but
    with its own request-parsing function
    (`build_rehearsal_reorder_buffer_from_request()`) scoped to a pure
    reorder of one already-existing Rehearsal, never a whole grid's worth
    of rows.
    """

    def run_preview(self, request, rehearsal_id):
        """Build the reorder-only Rehearsal edit Buffer from the JSON body and return its rendered Fallout envelope for `rehearsal_id`.

        Mirrors `AssignmentPreviewApiView.run_preview()`: the same
        `build_rehearsal_reorder_buffer_from_request()`
        `RunningOrderReorderSaveApiView.post()` calls, so Preview and Save
        of an identical body can never disagree about what Buffer they
        describe.
        """
        rehearsal = _reorderable_rehearsal_or_404(request, rehearsal_id)
        viewing_semester = services.get_viewing_semester(request)
        try:
            buffer = build_rehearsal_reorder_buffer_from_request(request, rehearsal=rehearsal)
        except RehearsalBufferValidationError as error:
            return self.write_response(
                request, ok=False, errors=None, non_field_errors=error.non_field_errors, fallout=None, values=None,
            )

        if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
            return _wrong_semester_response(
                "This Rehearsal edit Buffer's Semester doesn't match the Semester you're currently viewing."
            )

        fallout = services.preview_rehearsal_edits(buffer, viewing_semester=viewing_semester)
        return self.write_response(
            request,
            ok=True,
            fallout=serializers.serialize_rehearsal_edit_fallout(fallout),
            values=None,
        )


class RunningOrderReorderSaveApiView(AdminApiView, View):
    """`POST /api/schedule/<rehearsal_id>/running-order/save/`: the "Edit Rehearsal" drag-and-drop's Save — the real, committing write."""

    def post(self, request, rehearsal_id):
        """Build the reorder-only Rehearsal edit Buffer from the JSON body and apply it, or report why it couldn't be applied.

        Mirrors `AssignmentSaveApiView.post()`: the same
        `build_rehearsal_reorder_buffer_from_request()` the Preview
        endpoint calls, then the unchanged `apply_rehearsal_edits()`. A
        `StaleRehearsalSemesterError`, `PastRehearsalEditError` or
        `RunningOrderValidationError` is reported as `ok: false` with
        `non_field_errors`, matching `ScheduleEditorSaveApiView.post()` —
        none leaves partial writes behind, since `apply_rehearsal_edits()`'s
        own transaction has already rolled back by the time any of these
        `except` clauses run.
        """
        rehearsal = _reorderable_rehearsal_or_404(request, rehearsal_id)
        viewing_semester = services.get_viewing_semester(request)
        try:
            buffer = build_rehearsal_reorder_buffer_from_request(request, rehearsal=rehearsal)
        except RehearsalBufferValidationError as error:
            return self.write_response(
                request, ok=False, errors=None, non_field_errors=error.non_field_errors, fallout=None, values=None,
            )

        if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
            return _wrong_semester_response(
                "This Rehearsal edit Buffer's Semester doesn't match the Semester you're currently viewing."
            )

        try:
            services.apply_rehearsal_edits(buffer, viewing_semester=viewing_semester)
        except WrongViewingSemesterError as error:
            return _wrong_semester_response(str(error))
        except (StaleRehearsalSemesterError, PastRehearsalEditError, RunningOrderValidationError) as error:
            return self.write_response(
                request, ok=False, non_field_errors=[str(error)], fallout=None, values=None,
            )

        return self.write_response(request, ok=True, values=None)


class SemesterManagementRowsApiView(AdminApiView, View):
    """`GET /api/semesters/management-rows/`: every Semester's row for the Manage-semesters sheet, in one round trip (issue #329)."""

    def get(self, request):
        """Return every `SemesterManagementRow` for the requesting admin."""
        rows = services.semester_management_rows(request)
        return self.read_response(request, serializers.serialize_semester_management_rows(rows))


class SemesterPublishImpactApiView(AdminApiView, View):
    """`GET /api/semesters/<pk>/publish-impact/`: what publishing `pk` would do to the incumbent Live Semester (issue #329)."""

    def get(self, request, pk):
        """Return `pk`'s `SemesterPublishImpact`, or 404 if the Semester no longer exists."""
        semester = get_object_or_404(Semester, pk=pk)
        impact = services.semester_publish_impact(semester)
        return self.read_response(request, serializers.serialize_semester_publish_impact(impact))


class SemesterDeletionSummaryApiView(AdminApiView, View):
    """`GET /api/semesters/<pk>/deletion-summary/`: what deleting `pk` would destroy, for the Delete popup (issue #329).

    Wraps `semester_deletion_summary()` unchanged — the four counts are
    computed there and must not be recomputed anywhere else.
    """

    def get(self, request, pk):
        """Return `pk`'s `SemesterDeletionSummary`, or 404 if the Semester no longer exists."""
        semester = get_object_or_404(Semester, pk=pk)
        summary = services.semester_deletion_summary(semester)
        return self.read_response(request, serializers.serialize_semester_deletion_summary(summary))


class SemesterSelectApiView(AdminApiView, View):
    """`POST /api/semesters/select/`: records this session's Viewing Semester selection, or clears it (issue #329).

    Takes `{"semester_id": <int> | null}` and calls `set_viewing_semester()`
    and nothing else — mirrors the pre-SPA `SemesterSelectView`'s "an
    unknown pk clears the selection" silent-fallback behavior rather than
    404ing, so a stale client-side option list can't turn into an error.
    Returns the envelope with no extra `data`: the shell's context (its
    `viewing_semester`/`semester_options`) is what actually changes.
    """

    def post(self, request):
        """Parse `semester_id` off the JSON body, select (or clear) it, and return the updated envelope."""
        body = self.parse_json_body(request)
        semester_id = body.get('semester_id') if isinstance(body, dict) else None
        if semester_id is not None and (isinstance(semester_id, bool) or not isinstance(semester_id, int)):
            return JsonResponse({'context': self.build_context(request), 'error': 'malformed_payload'}, status=400)
        semester = Semester.objects.filter(pk=semester_id).first() if semester_id is not None else None
        services.set_viewing_semester(request, semester)
        return self.write_response(request, ok=True, values=None)


class SemesterCreateApiView(AdminApiView, View):
    """`POST /api/semesters/create/`: creates a new draft Semester and selects it as this session's Viewing Semester (issue #329).

    A blank or case-insensitive-duplicate `name` is `InvalidSemesterNameError`,
    reported as a per-field error at HTTP 200 (a rejected input, not a
    client protocol error) — every other malformed field (a missing name,
    or a non-integer/negative timing default) is a genuine 4xx, since 4xx
    stays reserved for auth, staleness and malformed payloads. Also marks
    the new Semester as just-created in the session (issue #332), so the
    admin's very next Home read shows the one-off "created / Draft" status
    card.
    """

    #: The six timing-default fields `create_semester()` takes as `**timing_defaults`, matching `SemesterSetupForm`.
    TIMING_DEFAULT_FIELDS = (
        'default_rehearsal_duration_minutes',
        'default_setup_grace_minutes',
        'default_teardown_grace_minutes',
        'default_song_slot_count',
        'default_arrival_buffer_minutes',
        'default_departure_buffer_minutes',
    )

    def post(self, request):
        """Create the submitted Semester, select it, and return the envelope — or a 400/200-with-field-error."""
        body = self.parse_json_body(request)
        if not isinstance(body, dict):
            return JsonResponse({'context': self.build_context(request), 'error': 'malformed_payload'}, status=400)

        name = body.get('name')
        if not isinstance(name, str):
            return JsonResponse({'context': self.build_context(request), 'error': 'malformed_payload'}, status=400)

        timing_defaults = {}
        for field in self.TIMING_DEFAULT_FIELDS:
            value = body.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return JsonResponse(
                    {'context': self.build_context(request), 'error': 'malformed_payload'}, status=400,
                )
            timing_defaults[field] = value

        try:
            semester = services.create_semester(name=name, **timing_defaults)
        except InvalidSemesterNameError as error:
            return self.write_response(request, ok=False, errors={'name': [str(error)]})

        services.set_viewing_semester(request, semester)
        services.mark_semester_just_created(request, semester)
        return self.write_response(request, ok=True, values=None)


class SemesterPublishApiView(AdminApiView, View):
    """`POST /api/semesters/<pk>/publish/`: publishes `pk`, making it the Live Semester (issue #329).

    Re-publishing the already-live Semester is a harmless re-stamp,
    allowed through this same path — rollback is publishing an older
    Semester here. There is no unpublish endpoint (ADR 0010).
    """

    def post(self, request, pk):
        """Publish `pk` and return the envelope, or 404 if it no longer exists."""
        semester = get_object_or_404(Semester, pk=pk)
        services.publish_semester(semester)
        return self.write_response(request, ok=True, values=None)


class SemesterDeleteApiView(AdminApiView, View):
    """`POST /api/semesters/<pk>/delete/`: hard-deletes `pk` and its cascade (issue #329, ADR 0011).

    The Live Semester refusal lives inside `delete_semester()` itself, not
    just here (ADR 0011) — reported as `ok: false` with `non_field_errors`
    rather than a 4xx, since a hand-crafted delete of the Live Semester
    must be *refused*, not merely protocol-rejected.
    """

    def post(self, request, pk):
        """Delete `pk`, or report the Live-Semester refusal, or 404 if it no longer exists."""
        semester = get_object_or_404(Semester, pk=pk)
        try:
            services.delete_semester(semester)
        except LiveSemesterDeletionError as error:
            return self.write_response(request, ok=False, non_field_errors=[str(error)])
        return self.write_response(request, ok=True, values=None)


class SemesterDefaultsReapplyPreviewApiView(AdminPreviewApiView):
    """`POST /api/semesters/reapply-defaults/preview/`: the Reapply-defaults surface's Preview, run for real and rolled back (issue #329, ADR 0008)."""

    def run_preview(self, request):
        """Build the Reapply-defaults Buffer from the JSON body and return its rendered Fallout envelope.

        Delegates all parsing to `build_semester_defaults_reapply_buffer_from_request()` —
        the same function `SemesterDefaultsReapplySaveApiView.post()`
        calls. A `SemesterDefaultsReapplyBufferValidationError` (a missing
        or malformed `semester_id`/`semester_updated_at`) renders as
        `ok: false` with `non_field_errors`; there is no `values` echo on
        that path, since this Buffer carries nothing to echo beyond the
        two identity fields the client already has. Unlike the Setlist/
        Roster/Rehearsal Preview endpoints, there is no wrong-semester 409
        check here — this surface is addressed by `semester_id` alone,
        with no session-scoped Viewing Semester ambiguity to guard
        against (`SemesterDefaultsReapplyBuffer`'s own docstring).
        `preview_semester_defaults_reapply()` reports a
        `StaleSemesterDefaultsError`/`SemesterDefaultsReapplyBlockedError`
        as `fallout.is_blocked`/`is_stale` itself, so there is no `except`
        clause to write here either.
        """
        viewing_semester = services.get_viewing_semester(request)
        try:
            buffer = build_semester_defaults_reapply_buffer_from_request(request, viewing_semester=viewing_semester)
        except SemesterDefaultsReapplyBufferValidationError as error:
            return self.write_response(
                request, ok=False, non_field_errors=error.non_field_errors, fallout=None, values=None,
            )

        fallout = services.preview_semester_defaults_reapply(buffer)
        return self.write_response(
            request, ok=True, fallout=serializers.serialize_semester_defaults_fallout(fallout),
        )


class SemesterDefaultsReapplySaveApiView(AdminApiView, View):
    """`POST /api/semesters/reapply-defaults/save/`: the Reapply-defaults surface's Save — the real, committing write (issue #329)."""

    def post(self, request):
        """Build the Reapply-defaults Buffer from the JSON body and apply it, or report why it couldn't be applied.

        Calls the same `build_semester_defaults_reapply_buffer_from_request()`
        the Preview endpoint calls, then the unchanged
        `apply_semester_defaults_reapply()`. A `StaleSemesterDefaultsError`
        or `SemesterDefaultsReapplyBlockedError` is reported as
        `ok: false` with `non_field_errors`, mirroring the other Save
        endpoints' staleness/blocked handling — `apply_semester_defaults_reapply()`'s
        own transaction has already rolled back by the time either
        `except` clause runs.
        """
        viewing_semester = services.get_viewing_semester(request)
        try:
            buffer = build_semester_defaults_reapply_buffer_from_request(request, viewing_semester=viewing_semester)
        except SemesterDefaultsReapplyBufferValidationError as error:
            return self.write_response(
                request, ok=False, non_field_errors=error.non_field_errors, fallout=None, values=None,
            )

        try:
            services.apply_semester_defaults_reapply(buffer)
        except (StaleSemesterDefaultsError, SemesterDefaultsReapplyBlockedError) as error:
            return self.write_response(request, ok=False, non_field_errors=[str(error)], fallout=None, values=None)

        return self.write_response(request, ok=True, values=None)


def _adjudicatable_rehearsal_or_404(semester, rehearsal_id):
    """Return `semester`'s Rehearsal `rehearsal_id` names, or raise 404 — never the Dress Rehearsal (issue #340, ADR 0006).

    Scoped to `semester` the same way every other per-Rehearsal `/api/`
    route is; additionally excludes the Dress Rehearsal outright, since it
    can hold no Conflict at all (ADR 0006) and so has nothing to
    adjudicate — a stricter 404 than the pre-SPA
    `ConflictAdjudicationDetailView`, which only scoped by Semester.
    """
    return get_object_or_404(Rehearsal, pk=rehearsal_id, semester=semester, is_full_setlist=False)


def _feasibility_name_lookups(feasibility_by_conflict_id: dict) -> tuple[dict, dict]:
    """Return `(song_titles_by_id, role_names_by_id)`, batched across every feasibility row's overlap target (issue #340).

    One `Song` query and one `Role` query total, regardless of how many
    Conflicts are on the Rehearsal — avoids an N+1 across
    `ConflictFeasibilityRow.overlap_song_id`/`overlap_role_id`.
    """
    song_ids = {row.overlap_song_id for row in feasibility_by_conflict_id.values() if row.overlap_song_id}
    role_ids = {row.overlap_role_id for row in feasibility_by_conflict_id.values() if row.overlap_role_id}
    song_titles_by_id = dict(Song.objects.filter(pk__in=song_ids).values_list('pk', 'title'))
    role_names_by_id = dict(Role.objects.filter(pk__in=role_ids).values_list('pk', 'name'))
    return song_titles_by_id, role_names_by_id


class ConflictAdjudicationIndexApiView(AdminApiView, View):
    """`GET /api/conflicts/`: the admin adjudication index's whole read model, in one round trip (issue #191, #340).

    Lists the viewing Semester's future, non-Dress Rehearsals, each
    carrying its pending/approved/rejected Conflict counts — the sole
    surviving surface for this read since issue #341 deleted the old
    `ConflictAdjudicationIndexView` and its template.
    """

    def get(self, request):
        """Return the adjudication index envelope, or its empty shape when no Semester is being viewed."""
        semester = services.get_viewing_semester(request)
        if semester is None:
            return self.read_response(request, {'rows': []})
        rows = services.conflict_adjudication_index_for(semester)
        return self.read_response(request, {'rows': serializers.serialize_conflict_adjudication_index(rows)})


class ConflictAdjudicationDetailApiView(AdminApiView, View):
    """`GET /api/conflicts/<rehearsal_id>/`: one Rehearsal's whole adjudication table, in one round trip (issue #192, #194, #340).

    Feasibility is computed against the *currently saved* Conflict
    statuses — mirroring what `_current_adjudication_fallout()` served
    pre-SPA on a plain GET, with no pending edits in play.
    """

    def get(self, request, rehearsal_id):
        """Return the adjudication-table envelope for `rehearsal_id`, 404ing outside the viewing Semester or on the Dress Rehearsal."""
        semester = services.get_viewing_semester(request)
        rehearsal = _adjudicatable_rehearsal_or_404(semester, rehearsal_id)
        detail_rows = services.conflict_adjudication_rows_for(rehearsal)
        approved_ids = {row.conflict.pk for row in detail_rows if row.status == Conflict.APPROVED}
        feasibility_rows = services.conflict_feasibility_for(rehearsal, approved_ids)
        feasibility_by_conflict_id = {row.conflict_id: row for row in feasibility_rows}
        song_titles_by_id, role_names_by_id = _feasibility_name_lookups(feasibility_by_conflict_id)
        data = serializers.serialize_conflict_adjudication_detail(
            rehearsal, detail_rows, feasibility_rows,
            semester=semester, song_titles_by_id=song_titles_by_id, role_names_by_id=role_names_by_id,
        )
        return self.read_response(request, data)


def _wrong_adjudication_semester_response(message: str) -> JsonResponse:
    """Return the shared 409 for an Adjudication Buffer whose `semester_id` doesn't match the viewing Semester (issue #340, mirrors `_wrong_roster_semester_response`)."""
    return JsonResponse({'error': 'wrong_semester', 'message': message}, status=409)


class ConflictAdjudicationPreviewApiView(AdminPreviewApiView):
    """`POST /api/conflicts/<rehearsal_id>/preview/`: feasibility verdicts and Fallout for a candidate Buffer, run for real and rolled back (issue #194, #340, ADR 0008)."""

    def run_preview(self, request, rehearsal_id):
        """Build the Adjudication Buffer from the JSON body and return its rendered Fallout envelope.

        Mirrors `RosterPreviewApiView.run_preview()`: an
        `AdjudicationBufferValidationError` renders as `ok: false` with
        per-row `errors`/`non_field_errors` and the raw submitted body
        echoed back as `values`; a `semester_id` that doesn't match the
        viewing Semester is answered as the shared 409 before
        `preview_adjudications()` is ever called. `preview_adjudications()`
        is itself a pure read (issue #194), so `PreviewMixin`'s rollback
        has nothing to undo here beyond the Rehearsal 404 lookup.
        """
        viewing_semester = services.get_viewing_semester(request)
        rehearsal = _adjudicatable_rehearsal_or_404(viewing_semester, rehearsal_id)
        try:
            buffer = build_adjudication_buffer_from_request(request, rehearsal_id=rehearsal_id)
        except AdjudicationBufferValidationError as error:
            return self.write_response(
                request, ok=False, errors=error.row_errors, non_field_errors=error.non_field_errors,
                fallout=None, values=error.raw_body,
            )

        if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
            return _wrong_adjudication_semester_response(
                "This adjudication Buffer's Semester doesn't match the Semester you're currently viewing."
            )

        fallout = services.preview_adjudications(buffer, rehearsal=rehearsal, viewing_semester=viewing_semester)
        song_titles_by_id, role_names_by_id = _feasibility_name_lookups(fallout.feasibility_by_conflict_id)
        return self.write_response(
            request, ok=True,
            fallout=serializers.serialize_adjudication_fallout(
                fallout, song_titles_by_id=song_titles_by_id, role_names_by_id=role_names_by_id,
            ),
            values=None,
        )


class ConflictAdjudicationSaveApiView(AdminApiView, View):
    """`POST /api/conflicts/<rehearsal_id>/save/`: the adjudication table's Save — the real, committing write (issue #192, #340)."""

    def post(self, request, rehearsal_id):
        """Build the Adjudication Buffer from the JSON body and apply it, or report why it couldn't be applied.

        Calls the same `build_adjudication_buffer_from_request()` the
        Preview endpoint calls, then the unchanged `apply_adjudications()`.
        A wrong `semester_id` answers the shared 409 before
        `apply_adjudications()` is even called. Refuses outright (`ok:
        false`, before any write) when the submitted Buffer carries no
        entries at all — issue #340 user story 38, "Save refused while
        nothing is pending" — since an empty Buffer has nothing for
        `apply_adjudications()` to usefully commit.
        """
        viewing_semester = services.get_viewing_semester(request)
        _adjudicatable_rehearsal_or_404(viewing_semester, rehearsal_id)
        try:
            buffer = build_adjudication_buffer_from_request(request, rehearsal_id=rehearsal_id)
        except AdjudicationBufferValidationError as error:
            return self.write_response(
                request, ok=False, errors=error.row_errors, non_field_errors=error.non_field_errors,
                fallout=None, values=None,
            )

        if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
            return _wrong_adjudication_semester_response(
                "This adjudication Buffer's Semester doesn't match the Semester you're currently viewing."
            )

        if not buffer.entries:
            return self.write_response(
                request, ok=False,
                non_field_errors=['There is nothing to save — no adjudication decision was submitted.'],
                fallout=None, values=None,
            )

        try:
            services.apply_adjudications(buffer, viewing_semester=viewing_semester)
        except WrongAdjudicationSemesterError as error:
            return _wrong_adjudication_semester_response(str(error))
        except (StaleAdjudicationSemesterError, UnknownConflictError) as error:
            return self.write_response(request, ok=False, non_field_errors=[str(error)], fallout=None, values=None)

        return self.write_response(request, ok=True, values=None)
