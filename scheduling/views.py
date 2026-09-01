"""Member read routes (issue #56) and conflicts self-service (issue #58)."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DetailView, TemplateView

from config.views import BaseView
from scheduling.forms import BulkConflictForm, ConflictWindowFormSet
from scheduling.models import (
    Conflict,
    ConflictWindow,
    Recording,
    Rehearsal,
    Song,
    SongRoleAssignment,
)
from scheduling.services import get_current_semester, rehearsal_count_target


def _scoped_to_current_semester(model, semester):
    """Return `model`'s current-Semester queryset, or an empty one if there's no current Semester yet."""
    return model.objects.filter(semester=semester) if semester else model.objects.none()


class ScheduleView(BaseView, TemplateView):
    """Lists the current Semester's Rehearsals."""

    template_name = 'scheduling/schedule.html'

    def get_context_data(self, **kwargs):
        """Add the current Semester's Rehearsals, ordered per Rehearsal.Meta.ordering."""
        context = super().get_context_data(**kwargs)
        semester = get_current_semester()
        context['semester'] = semester
        context['rehearsals'] = _scoped_to_current_semester(Rehearsal, semester)
        return context


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
        """Create/promote a FULL_CONFLICT Conflict for each selected Rehearsal; drop full-conflict rows for the rest."""
        selected_ids = {rehearsal.pk for rehearsal in full_conflict_rehearsals}
        for rehearsal in rehearsals:
            existing = Conflict.objects.filter(person=self.request.user, rehearsal=rehearsal).first()
            if rehearsal.pk in selected_ids:
                if existing is None:
                    Conflict.objects.create(person=self.request.user, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)
                elif existing.type != Conflict.FULL_CONFLICT:
                    existing.type = Conflict.FULL_CONFLICT
                    existing.save()
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
