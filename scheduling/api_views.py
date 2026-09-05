"""`/api/` read views for the Setlist and Song detail — the SPA's first two surfaces (issue #330).

Both are `ApiView`s, not `AdminApiView`s: they are member-facing reads, and
the only admin-conditional content (the ADR-0009 pointer's `next_rehearsal`
key) is decided by the serializer, not by gating the whole endpoint.
"""

from django.shortcuts import get_object_or_404
from django.views import View

from config.views import ApiView
from scheduling import serializers, services
from scheduling.models import Song


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
