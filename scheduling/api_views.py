"""`/api/` read views for the Setlist and Song detail — the SPA's first two surfaces (issue #330).

Both are `ApiView`s, not `AdminApiView`s: they are member-facing reads, and
the only admin-conditional content (the ADR-0009 pointer's `next_rehearsal`
key) is decided by the serializer, not by gating the whole endpoint.
"""

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View

from config.views import ApiView
from scheduling import serializers, services
from scheduling.forms import DeclareConflictForm
from scheduling.models import Conflict, Rehearsal, Song


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
