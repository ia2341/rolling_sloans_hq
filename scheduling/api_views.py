"""`/api/` views for the Setlist and Song detail surfaces (issues #330, #334).

Reads (`SetlistApiView`, `SongDetailApiView`) are `ApiView`s, not
`AdminApiView`s: they are member-facing, and the only admin-conditional
content (the ADR-0009 pointer's `next_rehearsal` key) is decided by the
serializer, not by gating the whole endpoint.

The Setlist edit surface's Preview and Save (`SetlistPreviewApiView`,
`SetlistSaveApiView`) are admin-only writes, added by issue #334 as the
Setlist's proof-of-concept for the shared Pending-Buffer-over-HTTP shape:
`build_setlist_buffer_from_request()` is the ONE place a submitted JSON
body becomes a `SetlistEditBuffer`, and both views call it — never a
second, forked parsing path (ADR 0008's "preview and save cannot
disagree" rule, re-shaped across an HTTP boundary rather than weakened by
one).
"""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View

from config.views import AdminApiView, AdminPreviewApiView, ApiView
from scheduling import serializers, services
from scheduling.api_builders import (
    SetlistBufferValidationError,
    build_setlist_buffer_from_request,
)
from scheduling.models import Song
from scheduling.services import StaleSetlistSemesterError, WrongViewingSemesterError


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
