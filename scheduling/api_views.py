"""`/api/` views for the Setlist and Song detail (issue #330), and the Band/Person surfaces (issue #333).

All are `ApiView`s, not `AdminApiView`s: every route here is member-facing,
and the only admin-conditional content (the ADR-0009 `next_rehearsal`
pointer, and `can_edit_roles` on the Person page) is decided by the
serializer or the view's own per-request check, not by gating the whole
endpoint — a non-admin still needs to read these surfaces.
"""

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View

from config.views import ApiView
from identity.models import Person
from scheduling import serializers, services
from scheduling.forms import MembershipRolesForm
from scheduling.models import Membership, Recording, RehearsalSong, Song
from scheduling.services import RecordingUploadError


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


class BandApiView(ApiView, View):
    """`GET /api/members/`: the Band page's whole read model — the viewing Semester's active Roster, in one round trip (issue #333).

    Active only: an invited-but-not-yet-active Person (no password set
    yet) stays off this list, reappearing only in the Roster editor (#336).
    """

    def get(self, request):
        """Return the Band envelope for `get_viewing_semester(request)`, or its empty shape when nothing is published/selected."""
        semester = services.get_viewing_semester(request)
        if semester is None:
            memberships = Membership.objects.none()
        else:
            memberships = services.active_roster_for(Membership.objects.filter(semester=semester))
        data = serializers.serialize_band(memberships, semester)
        return self.read_response(request, data)


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
    """`POST /api/members/<pk>/roles/`: saves declared Roles for your own pk, or (issue #232) an admin's on anyone's (issue #333).

    Not `AdminApiView`: a non-admin may hit this for their own pk. A
    teammate's page has no mutation surface for a non-admin viewer, so the
    guard 404s exactly as `MemberDetailView`'s POST does, rather than
    rendering a rejected form.
    """

    def post(self, request, pk):
        """Validate and persist the submitted `role_ids` onto `pk`'s Membership, creating it on a first submission."""
        is_admin = bool(getattr(request.user, 'is_admin', False))
        if pk != request.user.pk and not is_admin:
            raise Http404("A member can only edit their own declared Roles unless they're an admin.")
        person = request.user if pk == request.user.pk else get_object_or_404(Person, pk=pk)
        semester = services.get_viewing_semester(request)
        if semester is None:
            return self.write_response(request, ok=False, non_field_errors=['No Semester is being edited.'])
        payload = self.parse_json_body(request)
        role_ids = payload.get('role_ids', [])
        membership, _ = Membership.objects.get_or_create(person=person, semester=semester)
        form = MembershipRolesForm(data={'roles': role_ids}, instance=membership)
        if not form.is_valid():
            return self.write_response(request, ok=False, errors=form.errors)
        form.save()
        data = serializers.serialize_person(
            person, semester=semester, is_self=(person.pk == request.user.pk), can_edit_roles=True,
            membership=membership,
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
