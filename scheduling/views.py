"""Member read routes (issue #56), self-service routes (issues #57, #58, #61), and admin management routes (issue #60)."""

import json

from django.contrib import messages
from django.db import models, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DetailView, TemplateView

from config.views import AdminRequiredMixin, BaseView
from scheduling.forms import (
    BulkConflictForm,
    ConflictWindowFormSet,
    MembershipRolesForm,
    RecordingUploadForm,
    RehearsalForm,
    SongForm,
    SongRoleAssignmentForm,
)
from scheduling.models import (
    Conflict,
    ConflictWindow,
    Membership,
    Recording,
    Rehearsal,
    RehearsalSong,
    Semester,
    Song,
    SongRoleAssignment,
)
from scheduling.services import (
    RecordingUploadError,
    assignment_matrix_for,
    attendance_suggestion_for,
    breaks_for,
    confirm_recording_upload,
    get_current_semester,
    next_attended_rehearsal_for,
    rehearsal_count_target,
    rehearsal_schedule_for,
    reserve_recording_upload,
    songs_with_progress_for,
    upcoming_rehearsals_for,
)


def _scoped_to_current_semester(model, semester):
    """Return `model`'s current-Semester queryset, or an empty one if there's no current Semester yet."""
    return model.objects.filter(semester=semester) if semester else model.objects.none()


def _lock_semester(semester):
    """Row-lock `semester` for the duration of the enclosing transaction.

    Must be called inside `transaction.atomic()`. Serializes concurrent
    Song-position mutations (create, move) against the same Semester so two
    overlapping requests can't compute/apply stale positions and collide on
    `unique_song_position_per_semester`.
    """
    return Semester.objects.select_for_update().get(pk=semester.pk)


class OverviewView(BaseView, TemplateView):
    """`/`: a logged-in member's personalized Next Rehearsal card, 3-rehearsal preview, and song-progress table."""

    template_name = 'scheduling/overview.html'

    def get_context_data(self, **kwargs):
        """Add the Next Rehearsal card (issue #94) and semester-wide song-progress table (issue #93)."""
        context = super().get_context_data(**kwargs)
        semester = get_current_semester()
        context['semester'] = semester
        context['next_rehearsal'] = None
        context['next_rehearsal_suggestion'] = None
        context['upcoming_rehearsals'] = []
        context['songs'] = []
        if semester is not None:
            next_rehearsal = next_attended_rehearsal_for(self.request.user, semester=semester)
            context['next_rehearsal'] = next_rehearsal
            if next_rehearsal is not None:
                context['next_rehearsal_suggestion'] = attendance_suggestion_for(next_rehearsal, self.request.user)
            context['upcoming_rehearsals'] = [
                (rehearsal, attendance_suggestion_for(rehearsal, self.request.user))
                for rehearsal in upcoming_rehearsals_for(semester)
            ]
            context['songs'] = songs_with_progress_for(semester, self.request.user)
        return context


class ScheduleView(BaseView, TemplateView):
    """`/schedule/`: the shared rehearsal-detail view, plus the All-Rehearsals list (issues #95, #97).

    Defaults (`?view=next`, or no `?view=` at all) to a Rehearsal's Song x
    Role x Person assignment matrix — the member's own next Rehearsal
    unless `?rehearsal=<id>` drills into a specific one. `?view=all` instead
    lists the current Semester's full schedule, split into a collapsed past
    section and an expanded future section, each row linking to its own
    `?rehearsal=<id>` detail. Read-only and identical for admins and
    members — admin write affordances are a future hook point (issue #69).
    """

    template_name = 'scheduling/schedule.html'

    VIEW_ALL = 'all'
    VIEW_NEXT = 'next'

    def get_context_data(self, **kwargs):
        """Add either the All-Rehearsals schedule, or the resolved Rehearsal's matrix plus the member's own attendance/breaks (issues #95, #96, #97)."""
        context = super().get_context_data(**kwargs)
        semester = get_current_semester()
        context['semester'] = semester
        context['view_mode'] = self._resolve_view()
        context['rehearsal'] = None
        context['matrix'] = None
        context['my_song_ids'] = set()
        context['my_attendance_suggestion'] = None
        context['my_breaks'] = []
        context['schedule'] = None
        if semester is not None:
            if context['view_mode'] == self.VIEW_ALL:
                context['schedule'] = rehearsal_schedule_for(semester, self.request.user)
            else:
                rehearsal = self._resolve_rehearsal(semester)
                context['rehearsal'] = rehearsal
                if rehearsal is not None:
                    matrix = assignment_matrix_for(rehearsal)
                    context['matrix'] = matrix
                    context['my_song_ids'] = set(
                        SongRoleAssignment.objects.filter(
                            person=self.request.user, song__in=[row.song for row in matrix.rows],
                        ).values_list('song_id', flat=True)
                    )
                    context['my_attendance_suggestion'] = attendance_suggestion_for(rehearsal, self.request.user)
                    context['my_breaks'] = breaks_for(rehearsal, self.request.user)
        return context

    def _resolve_view(self):
        """Return VIEW_ALL for `?view=all`, else VIEW_NEXT (the default rehearsal-detail view)."""
        return self.VIEW_ALL if self.request.GET.get('view') == self.VIEW_ALL else self.VIEW_NEXT

    def _resolve_rehearsal(self, semester):
        """Return the `?rehearsal=<id>` Rehearsal (404 outside the current Semester), or the member's next Rehearsal."""
        raw_id = self.request.GET.get('rehearsal')
        if raw_id is None:
            return next_attended_rehearsal_for(self.request.user, semester=semester)
        rehearsal_id = self._parse_rehearsal_id(raw_id)
        return get_object_or_404(_scoped_to_current_semester(Rehearsal, semester), pk=rehearsal_id)

    def _parse_rehearsal_id(self, raw_id):
        """Return `raw_id` as an int, or raise Http404 for a non-numeric value."""
        try:
            return int(raw_id)
        except ValueError:
            raise Http404 from None


class SetlistView(BaseView, TemplateView):
    """Lists the current Semester's Songs in concert-position order, with rehearsal-count progress per Song."""

    template_name = 'scheduling/setlist.html'

    def get_context_data(self, **kwargs):
        """Add the current Semester's Songs, each annotated with its rehearsal-count actual/target."""
        context = super().get_context_data(**kwargs)
        semester = get_current_semester()
        context['semester'] = semester
        songs = list(_scoped_to_current_semester(Song, semester))
        for song in songs:
            song.rehearsal_count_actual = song.rehearsalsong_set.count()
            song.rehearsal_count_target = rehearsal_count_target(song)
        context['songs'] = songs
        return context


class SongDetailView(BaseView, DetailView):
    """A single Song's role assignments, rehearsal-count progress, and recordings."""

    model = Song
    template_name = 'scheduling/song_detail.html'
    context_object_name = 'song'

    def get_queryset(self):
        """Restrict lookups to the current Semester's Songs, so an older Song 404s."""
        return _scoped_to_current_semester(Song, get_current_semester())

    def get_context_data(self, **kwargs):
        """Add the Song's SongRoleAssignments, Recordings, and rehearsal-count target vs. actual."""
        context = super().get_context_data(**kwargs)
        song = self.object
        context['assignments'] = SongRoleAssignment.objects.filter(song=song)
        context['recordings'] = Recording.objects.filter(rehearsal_song__song=song)
        context['rehearsal_count_target'] = rehearsal_count_target(song)
        context['rehearsal_count_actual'] = song.rehearsalsong_set.count()
        return context


class ProfileView(BaseView, View):
    """`/me/profile/`: a member views/edits their own declared Roles for the current Semester."""

    template_name = 'scheduling/profile.html'

    def get(self, request):
        """Render the member's current declared Roles for the current Semester."""
        semester = get_current_semester()
        return render(request, self.template_name, self._build_context(semester))

    def post(self, request):
        """Validate and persist the member's declared Roles, or re-render the form with errors."""
        semester = get_current_semester()
        if semester is None:
            return render(request, self.template_name, self._build_context(semester))
        form = MembershipRolesForm(request.POST, instance=self._get_or_build_membership(semester))
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated.')
            return redirect('scheduling:profile')
        return render(request, self.template_name, {'form': form, 'semester': semester})

    def _build_context(self, semester):
        """Build the GET-time context for `semester`: the bound form plus Roles/Songs stats, or neither if there's no Semester yet."""
        if semester is None:
            return {'semester': None}
        membership = self._get_or_build_membership(semester)
        return {
            'form': MembershipRolesForm(instance=membership),
            'semester': semester,
            'roles_count': membership.membershiprole_set.count() if membership.pk else 0,
            'songs_played_count': SongRoleAssignment.objects.filter(
                person=self.request.user, song__semester=semester,
            ).values('song').distinct().count(),
        }

    def _get_or_build_membership(self, semester):
        """Return the member's Membership for `semester`, or an unsaved one if none exists yet."""
        membership = Membership.objects.filter(person=self.request.user, semester=semester).first()
        return membership or Membership(person=self.request.user, semester=semester)


class ConflictsView(BaseView, View):
    """`/me/conflicts/`: bulk-toggles full-conflict status across the current Semester's Rehearsals (issue #58).

    Only ever touches FULL_CONFLICT rows for `request.user` — a partial
    Conflict (with its ConflictWindows) is left alone here and is only
    editable through ConflictDetailView, since a checkbox can't represent
    a set of time windows.
    """

    template_name = 'scheduling/conflicts.html'

    def get(self, request):
        """Render the bulk-toggle form, preselected with the member's currently full-conflict Rehearsals."""
        return render(request, self.template_name, self._build_context())

    def post(self, request):
        """Apply the submitted full-conflict toggles, or re-render with errors."""
        semester = get_current_semester()
        if semester is None:
            return render(request, self.template_name, self._build_context())
        rehearsals = _scoped_to_current_semester(Rehearsal, semester)
        form = BulkConflictForm(request.POST, rehearsals=rehearsals)
        if form.is_valid():
            self._apply_bulk_toggle(rehearsals, form.cleaned_data['full_conflict_rehearsals'])
            messages.success(request, 'Conflicts updated.')
            return redirect('scheduling:conflicts')
        return render(request, self.template_name, {'form': form, 'semester': semester, 'rehearsals': rehearsals})

    def _build_context(self):
        """Build the GET-time context: the bound form plus the current Semester's Rehearsals, or neither."""
        semester = get_current_semester()
        if semester is None:
            return {'semester': None}
        rehearsals = _scoped_to_current_semester(Rehearsal, semester)
        currently_full = rehearsals.filter(conflict__person=self.request.user, conflict__type=Conflict.FULL_CONFLICT)
        form = BulkConflictForm(rehearsals=rehearsals, initial={'full_conflict_rehearsals': currently_full})
        return {'form': form, 'semester': semester, 'rehearsals': rehearsals}

    def _apply_bulk_toggle(self, rehearsals, full_conflict_rehearsals):
        """Create a FULL_CONFLICT Conflict for each selected Rehearsal with none yet; drop full-conflict rows for the rest.

        An existing PARTIAL Conflict is left untouched even when its
        Rehearsal is selected: promoting it here would delete its
        ConflictWindow rows (per Conflict.save()'s partial-to-full cascade),
        silently losing the member's saved partial-conflict times.
        """
        selected_ids = {rehearsal.pk for rehearsal in full_conflict_rehearsals}
        for rehearsal in rehearsals:
            existing = Conflict.objects.filter(person=self.request.user, rehearsal=rehearsal).first()
            if rehearsal.pk in selected_ids:
                if existing is None:
                    Conflict.objects.create(person=self.request.user, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)
            elif existing is not None and existing.type == Conflict.FULL_CONFLICT:
                existing.delete()


class ConflictDetailView(BaseView, View):
    """`/me/conflicts/<rehearsal_id>/`: enters partial-conflict time windows for one Rehearsal (issue #58).

    Keyed by Rehearsal, not by Conflict id: the view only ever reads or
    writes `request.user`'s own Conflict for that Rehearsal, so there is no
    identifier a member could submit to reach another member's Conflict —
    the per-(person, rehearsal) scoping is structural, not a checked
    permission. `is_admin` plays no part in that scoping (there is no admin
    override in this slice), so a future one can be layered on without
    touching this logic.
    """

    template_name = 'scheduling/conflict_detail.html'

    def get(self, request, rehearsal_id):
        """Render the member's existing partial-conflict windows for this Rehearsal, or a blank formset."""
        rehearsal = self._get_rehearsal(rehearsal_id)
        formset = ConflictWindowFormSet(
            queryset=self._windows_queryset(rehearsal), form_kwargs={'rehearsal': rehearsal},
        )
        return render(request, self.template_name, {'rehearsal': rehearsal, 'formset': formset})

    def post(self, request, rehearsal_id):
        """Validate and persist the submitted windows, or re-render the formset with errors."""
        rehearsal = self._get_rehearsal(rehearsal_id)
        formset = ConflictWindowFormSet(
            request.POST, queryset=self._windows_queryset(rehearsal), form_kwargs={'rehearsal': rehearsal},
        )
        if formset.is_valid():
            self._save_windows(rehearsal, formset)
            messages.success(request, 'Conflict updated.')
            return redirect('scheduling:conflict-detail', rehearsal_id=rehearsal.pk)
        return render(request, self.template_name, {'rehearsal': rehearsal, 'formset': formset})

    def _get_rehearsal(self, rehearsal_id):
        """Return the current Semester's Rehearsal with this id, or 404 (mirrors SongDetailView's scoping)."""
        return get_object_or_404(_scoped_to_current_semester(Rehearsal, get_current_semester()), pk=rehearsal_id)

    def _windows_queryset(self, rehearsal):
        """Return request.user's existing ConflictWindows for `rehearsal`, if any."""
        return ConflictWindow.objects.filter(conflict__person=self.request.user, conflict__rehearsal=rehearsal)

    def _save_windows(self, rehearsal, formset):
        """Persist the formset's kept windows under a PARTIAL Conflict, or drop the Conflict if none remain."""
        conflict = Conflict.objects.filter(person=self.request.user, rehearsal=rehearsal).first()
        kept_forms = [form for form in formset.forms if form.cleaned_data and not form.cleaned_data.get('DELETE')]
        if kept_forms:
            if conflict is None:
                conflict = Conflict.objects.create(person=self.request.user, rehearsal=rehearsal, type=Conflict.PARTIAL)
            elif conflict.type != Conflict.PARTIAL:
                conflict.type = Conflict.PARTIAL
                conflict.save()
            windows = formset.save(commit=False)
            for window in windows:
                window.conflict = conflict
                window.save()
            for window in formset.deleted_objects:
                window.delete()
        elif conflict is not None:
            conflict.delete()


class RehearsalManageView(AdminRequiredMixin, View):
    """`/manage/schedule/`: an admin lists and creates the current Semester's Rehearsals (issue #60, #17 story 10)."""

    template_name = 'scheduling/manage_schedule.html'

    def get(self, request):
        """Render the current Semester's Rehearsals alongside an empty create form."""
        return render(request, self.template_name, self._build_context())

    def post(self, request):
        """Validate the create form and save a new Rehearsal in the current Semester, or re-render with errors."""
        semester = get_current_semester()
        if semester is None:
            messages.error(request, 'Create a Semester before scheduling Rehearsals.')
            return redirect('scheduling:manage-schedule')
        form = RehearsalForm(request.POST, instance=Rehearsal(semester=semester))
        if form.is_valid():
            form.save()
            messages.success(request, 'Rehearsal created.')
            return redirect('scheduling:manage-schedule')
        return render(request, self.template_name, self._build_context(form))

    def _build_context(self, form=None):
        """Build context: the current Semester's Rehearsals plus the create form (fresh if none is given)."""
        semester = get_current_semester()
        return {
            'semester': semester,
            'rehearsals': _scoped_to_current_semester(Rehearsal, semester),
            'form': form or RehearsalForm(),
        }


class RehearsalEditView(AdminRequiredMixin, View):
    """`/manage/schedule/<pk>/edit/`: an admin edits an existing Rehearsal (issue #60, #17 story 10)."""

    template_name = 'scheduling/manage_schedule_edit.html'

    def get(self, request, pk):
        """Render the edit form pre-filled with the target Rehearsal's current values."""
        rehearsal = self._get_rehearsal(pk)
        return render(request, self.template_name, {'rehearsal': rehearsal, 'form': RehearsalForm(instance=rehearsal)})

    def post(self, request, pk):
        """Validate and save the edit, or re-render with errors."""
        rehearsal = self._get_rehearsal(pk)
        form = RehearsalForm(request.POST, instance=rehearsal)
        if form.is_valid():
            form.save()
            messages.success(request, 'Rehearsal updated.')
            return redirect('scheduling:manage-schedule')
        return render(request, self.template_name, {'rehearsal': rehearsal, 'form': form})

    def _get_rehearsal(self, pk):
        """Return the current Semester's Rehearsal with this id, or 404 (mirrors ConflictDetailView's scoping)."""
        return get_object_or_404(_scoped_to_current_semester(Rehearsal, get_current_semester()), pk=pk)


class SongManageView(AdminRequiredMixin, View):
    """`/manage/setlist/`: an admin lists and adds the current Semester's Songs (issue #60, #17 story 11)."""

    template_name = 'scheduling/manage_setlist.html'

    def get(self, request):
        """Render the current Semester's Songs in position order alongside an empty create form."""
        return render(request, self.template_name, self._build_context())

    def post(self, request):
        """Validate the create form and append a new Song at the end of the current Semester's setlist."""
        semester = get_current_semester()
        if semester is None:
            messages.error(request, 'Create a Semester before adding Songs.')
            return redirect('scheduling:manage-setlist')
        with transaction.atomic():
            semester = _lock_semester(semester)
            instance = Song(semester=semester, position=self._next_position(semester))
            form = SongForm(request.POST, instance=instance)
            if form.is_valid():
                form.save()
                messages.success(request, 'Song added.')
                return redirect('scheduling:manage-setlist')
        return render(request, self.template_name, self._build_context(form))

    def _next_position(self, semester):
        """Return one past the current Semester's highest Song position (1 if it has no Songs yet)."""
        highest = Song.objects.filter(semester=semester).aggregate(highest=models.Max('position'))['highest']
        return (highest or 0) + 1

    def _build_context(self, form=None):
        """Build context: the current Semester's Songs plus the create form (fresh if none is given)."""
        semester = get_current_semester()
        return {
            'semester': semester,
            'songs': _scoped_to_current_semester(Song, semester),
            'form': form or SongForm(),
        }


class SongEditView(AdminRequiredMixin, View):
    """`/manage/setlist/<pk>/edit/`: an admin edits an existing Song's title/artist/length/notes (issue #60, #17 story 11)."""

    template_name = 'scheduling/manage_setlist_edit.html'

    def get(self, request, pk):
        """Render the edit form pre-filled with the target Song's current values."""
        song = self._get_song(pk)
        return render(request, self.template_name, {'song': song, 'form': SongForm(instance=song)})

    def post(self, request, pk):
        """Validate and save the edit, or re-render with errors."""
        song = self._get_song(pk)
        form = SongForm(request.POST, instance=song)
        if form.is_valid():
            form.save()
            messages.success(request, 'Song updated.')
            return redirect('scheduling:manage-setlist')
        return render(request, self.template_name, {'song': song, 'form': form})

    def _get_song(self, pk):
        """Return the current Semester's Song with this id, or 404 (mirrors ConflictDetailView's scoping)."""
        return get_object_or_404(_scoped_to_current_semester(Song, get_current_semester()), pk=pk)


class SongDeleteView(AdminRequiredMixin, View):
    """`/manage/setlist/<pk>/delete/`: an admin removes a Song from the setlist (issue #60, #17 story 11)."""

    def post(self, request, pk):
        """Delete the current Semester's target Song and redirect back to the setlist with a success message."""
        song = get_object_or_404(_scoped_to_current_semester(Song, get_current_semester()), pk=pk)
        song.delete()
        messages.success(request, 'Song removed.')
        return redirect('scheduling:manage-setlist')


class SongMoveView(AdminRequiredMixin, View):
    """`/manage/setlist/<pk>/move-up|down/`: an admin swaps a Song's position with its neighbor (issue #60, #17 story 11).

    Reuses the deferred `unique_song_position_per_semester` constraint the
    same way `Song.Meta` already relies on: both rows' positions are
    swapped inside one atomic transaction, so the transient collision
    between them is never checked mid-transaction.
    """

    UP = 'up'
    DOWN = 'down'

    def post(self, request, pk, direction):
        """Swap the current Semester's target Song's position with its previous/next neighbor, if one exists."""
        song = get_object_or_404(_scoped_to_current_semester(Song, get_current_semester()), pk=pk)
        with transaction.atomic():
            _lock_semester(song.semester)
            song.refresh_from_db()
            neighbor = self._neighbor(song, direction)
            if neighbor is not None:
                self._swap_positions(song, neighbor)
                messages.success(request, 'Setlist reordered.')
        return redirect('scheduling:manage-setlist')

    def _neighbor(self, song, direction):
        """Return the Song immediately before/after `song` in its Semester's position order, or None at either end."""
        songs = list(Song.objects.filter(semester=song.semester).order_by('position'))
        index = songs.index(song)
        if direction == self.UP and index > 0:
            return songs[index - 1]
        if direction == self.DOWN and index < len(songs) - 1:
            return songs[index + 1]
        return None

    def _swap_positions(self, song_a, song_b):
        """Swap two Songs' positions. Must be called within a transaction holding the Semester's row lock."""
        song_a.position, song_b.position = song_b.position, song_a.position
        song_a.save(update_fields=['position'])
        song_b.save(update_fields=['position'])


class SongRoleAssignmentManageView(AdminRequiredMixin, View):
    """`/manage/assignments/`: an admin lists and creates SongRoleAssignments, surfacing mismatches (issue #60, #17 story 12)."""

    template_name = 'scheduling/manage_assignments.html'

    def get(self, request):
        """Render the current Semester's SongRoleAssignments alongside an empty create form."""
        return render(request, self.template_name, self._build_context())

    def post(self, request):
        """Validate the create form and save a new SongRoleAssignment, or re-render with errors."""
        semester = get_current_semester()
        if semester is None:
            messages.error(request, 'Create a Semester with Songs before assigning Roles.')
            return redirect('scheduling:manage-assignments')
        songs = _scoped_to_current_semester(Song, semester)
        form = SongRoleAssignmentForm(request.POST, songs=songs)
        if form.is_valid():
            form.save()
            messages.success(request, 'Assignment created.')
            return redirect('scheduling:manage-assignments')
        return render(request, self.template_name, self._build_context(form))

    def _build_context(self, form=None):
        """Build context: the current Semester's SongRoleAssignments plus the create form (fresh if none is given)."""
        semester = get_current_semester()
        songs = _scoped_to_current_semester(Song, semester)
        assignments = SongRoleAssignment.objects.filter(song__in=songs).select_related('song', 'role', 'person')
        return {
            'semester': semester,
            'assignments': assignments,
            'form': form or SongRoleAssignmentForm(songs=songs),
        }


class SongRoleAssignmentDeleteView(AdminRequiredMixin, View):
    """`/manage/assignments/<pk>/delete/`: an admin removes a SongRoleAssignment (issue #60, #17 story 12)."""

    def post(self, request, pk):
        """Delete the current Semester's target SongRoleAssignment and redirect with a success message."""
        songs = _scoped_to_current_semester(Song, get_current_semester())
        assignment = get_object_or_404(SongRoleAssignment, pk=pk, song__in=songs)
        assignment.delete()
        messages.success(request, 'Assignment removed.')
        return redirect('scheduling:manage-assignments')


class RecordingUploadView(BaseView, View):
    """`/me/recordings/`: picks a RehearsalSong and confirms an already-uploaded Recording (issue #61).

    Two-step flow per ADR-0004 / issue #11: the client gets a presigned
    R2 POST policy from RecordingPresignView, uploads the file straight to
    R2, then submits here (a normal form POST, not JSON) with the resulting
    object_key to create the Recording row.

    An optional `?song=<id>` param (issue #102) restricts the RehearsalSong
    dropdown to that Song's own slots within the current Semester; omitting
    it keeps the original flat, semester-wide dropdown. The picker form has
    no `action` attribute, so the confirm POST resubmits to the same URL and
    the param survives into `post()` without needing a hidden field.
    """

    template_name = 'scheduling/recordings.html'

    def get(self, request):
        """Render the RehearsalSong picker, optionally pre-filtered to `?song=<id>`."""
        return self._render(RecordingUploadForm(rehearsal_songs=self._rehearsal_songs(request)))

    def post(self, request):
        """Validate the confirm submission and persist the Recording, or re-render with errors."""
        form = RecordingUploadForm(request.POST, rehearsal_songs=self._rehearsal_songs(request))
        if not form.is_valid():
            return self._render(form)
        try:
            confirm_recording_upload(
                form.cleaned_data['rehearsal_song'],
                request.user,
                form.cleaned_data['object_key'],
                note=form.cleaned_data['note'],
            )
        except RecordingUploadError as error:
            form.add_error(None, str(error))
            return self._render(form)
        messages.success(request, 'Recording uploaded.')
        return redirect('scheduling:recordings')

    def _render(self, form):
        """Render the picker/confirm template with `form` (bound or unbound)."""
        return render(self.request, self.template_name, {'form': form})

    def _rehearsal_songs(self, request):
        """Return the current Semester's RehearsalSongs, filtered to `?song=<id>` when given.

        Empty queryset if there's no current Semester, or if `?song=<id>` matches no
        RehearsalSong (e.g. a Song with no scheduled slots yet) — never an error.
        """
        semester = get_current_semester()
        if semester is None:
            return RehearsalSong.objects.none()
        rehearsal_songs = RehearsalSong.objects.filter(rehearsal__semester=semester)
        raw_song_id = request.GET.get('song')
        if raw_song_id is not None:
            song_id = self._parse_song_id(raw_song_id)
            rehearsal_songs = rehearsal_songs.filter(song_id=song_id)
        return rehearsal_songs

    def _parse_song_id(self, raw_song_id):
        """Return `raw_song_id` as an int, or raise Http404 for a non-numeric value."""
        try:
            return int(raw_song_id)
        except ValueError:
            raise Http404 from None


class RecordingPresignView(BaseView, View):
    """`/me/recordings/presign/`: a hand-rolled JSON endpoint reserving a direct-to-R2 upload slot (issue #61).

    No DRF, per the issue: this is the app's one JSON endpoint, so it's a
    plain JsonResponse view rather than reaching for a serializer framework.
    """

    def post(self, request):
        """Validate the requested content_type/file_size and return a presigned upload reservation, or a 4xx."""
        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({'error': 'Malformed JSON body.'}, status=400)
        content_type = payload.get('content_type')
        file_size = payload.get('file_size')
        try:
            reservation = reserve_recording_upload(content_type, file_size)
        except RecordingUploadError as error:
            return JsonResponse({'error': str(error)}, status=400)
        return JsonResponse({
            'upload_url': reservation.upload_url,
            'fields': reservation.fields,
            'object_key': reservation.object_key,
        })
