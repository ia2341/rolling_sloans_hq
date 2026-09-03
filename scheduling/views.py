"""Member read routes (issue #56), self-service routes (issues #57, #58, #61), and admin management routes (issue #60)."""

import json

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import DetailView, TemplateView

from config.views import AdminRequiredMixin, BaseView
from scheduling.forms import (
    DeclareConflictForm,
    MembershipRolesForm,
    RecordingUploadForm,
    RehearsalForm,
    SetlistEditFormSet,
    SongRoleAssignmentForm,
)
from scheduling.models import (
    Conflict,
    Membership,
    Recording,
    Rehearsal,
    RehearsalSong,
    Semester,
    Song,
    SongRoleAssignment,
)
from scheduling.services import (
    CONFLICT_EARLY_DEPARTURE,
    CONFLICT_LATE_ARRIVAL,
    LiveSemesterDeletionError,
    RecordingUploadError,
    assigned_songs_for,
    assignment_matrix_for,
    attendance_suggestion_for,
    breaks_for,
    confirm_recording_upload,
    conflict_history_for,
    create_recording_playback_url,
    declare_conflict,
    declared_roles_for,
    delete_semester,
    delete_songs_with_recordings,
    fill_status_for,
    future_rehearsals_for,
    get_live_semester,
    get_viewing_semester,
    next_attended_rehearsal_for,
    performers_for,
    publish_semester,
    recording_count_for,
    recording_groups_for,
    rehearsal_count_target,
    rehearsal_schedule_for,
    reorder_songs,
    reserve_recording_upload,
    roster_for,
    semester_deletion_summary,
    semester_options_for,
    set_viewing_semester,
    song_deletion_summaries,
    song_rehearsal_progress,
    songs_with_progress_for,
    upcoming_rehearsals_for,
)


def _scoped_to_viewing_semester(model, semester):
    """Return `model`'s queryset scoped to the viewing Semester, or an empty one when there is no Semester to view.

    `semester` is always `services.get_viewing_semester(request)`'s answer,
    so an admin viewing a draft reads and writes the draft's rows and a
    member only ever reaches the Live Semester's (ADR-0010). The `None` case
    is the pre-publish empty state, which every caller renders as zero rows.
    """
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
        """Add the Next Rehearsal card (issue #94), song-progress table (issue #93) and admin Semester panel (issue #169)."""
        context = super().get_context_data(**kwargs)
        semester = get_viewing_semester(self.request)
        context['semester'] = semester
        context['semester_options'] = semester_options_for(self.request)
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


class SemesterSelectView(AdminRequiredMixin, View):
    """`/manage/semester/`: an admin records which Semester this session is scoped to (issue #169).

    A plain POST-and-redirect form, deliberately not an HTMX or JS
    interaction: which Semester an admin is editing must never be ambiguous
    because a script failed to load. An empty value clears the selection,
    which is also how the shell's banner offers a way back to the Live
    Semester; a pk matching no Semester clears it too, so a stale form
    silently yields the live view rather than an error page.
    """

    def post(self, request):
        """Set (or clear) the session's Semester selection and redirect back to the submitting page."""
        semester = self._submitted_semester(request)
        set_viewing_semester(request, semester)
        if semester is not None:
            messages.success(request, f'Now viewing {semester.name}.')
        return redirect(self._redirect_target(request))

    def _submitted_semester(self, request):
        """Return the submitted Semester, or None when the field is empty, non-numeric or names a deleted row."""
        submitted = request.POST.get('semester') or ''
        if not submitted.isdigit():
            return None
        return Semester.objects.filter(pk=submitted).first()

    def _redirect_target(self, request):
        """Return the submitted `next` when it is a safe same-site path, else the Overview."""
        target = request.POST.get('next') or ''
        if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return target
        return 'scheduling:overview'


class ScheduleView(BaseView, TemplateView):
    """`/schedule/`: the shared rehearsal-detail view, plus the All-Rehearsals list (issues #95, #97).

    Defaults (`?view=next`, or no `?view=` at all) to a Rehearsal's Song x
    Role x Person assignment matrix — the member's own next Rehearsal
    unless `?rehearsal=<id>` drills into a specific one. `?view=all` instead
    lists the viewing Semester's full schedule, split into a collapsed past
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
        semester = get_viewing_semester(self.request)
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
        """Return the `?rehearsal=<id>` Rehearsal (404 outside the viewing Semester), or the member's next Rehearsal."""
        raw_id = self.request.GET.get('rehearsal')
        if raw_id is None:
            return next_attended_rehearsal_for(self.request.user, semester=semester)
        rehearsal_id = self._parse_rehearsal_id(raw_id)
        return get_object_or_404(_scoped_to_viewing_semester(Rehearsal, semester), pk=rehearsal_id)

    def _parse_rehearsal_id(self, raw_id):
        """Return `raw_id` as an int, or raise Http404 for a non-numeric value."""
        try:
            return int(raw_id)
        except ValueError:
            raise Http404 from None


class SetlistView(BaseView, TemplateView):
    """Sortable Songs table: order/title, artist, performers, rehearsals-remaining, and recording count (issue #103)."""

    template_name = 'scheduling/setlist.html'

    def get_context_data(self, **kwargs):
        """Add the viewing Semester's Songs, each annotated with performers, rehearsal progress, and recording count."""
        context = super().get_context_data(**kwargs)
        semester = get_viewing_semester(self.request)
        context['semester'] = semester
        songs = list(_scoped_to_viewing_semester(Song, semester).order_by('position'))
        for song in songs:
            song.performers = performers_for(song)
            song.progress = song_rehearsal_progress(song)
            song.recording_count = recording_count_for(song)
        context['songs'] = songs
        return context


class SetlistEditView(AdminRequiredMixin, View):
    """`/setlist/edit/`: an admin's in-place editable grid for the viewing Semester's setlist (issues #178, #179).

    A sibling of `SetlistView` rather than a `/manage/` screen, because the
    point of this ticket is that an admin fixes a mistake on the page they
    spotted it on. GET renders the grid — as a bare fragment for the
    htmx-driven "Edit setlist" button's in-place swap, or as a full page
    (banner and all) for a direct/no-JS request. POST commits the whole
    buffer — edits, reorder, adds and deletes together — as one atomic
    write, or writes nothing and re-renders the full page with every
    submitted value preserved: per-field errors on a validation failure, or
    a stale-stamp notice when another admin's save landed first (the
    optimistic-concurrency stamp from #178's map).
    """

    fragment_template_name = 'scheduling/_setlist_edit.html'
    page_template_name = 'scheduling/setlist_edit.html'
    STALE_MESSAGE = 'The setlist changed while you were editing — reload and reapply.'
    MALFORMED_ORDER_MESSAGE = 'The setlist could not be saved — reload and reapply.'

    def get(self, request):
        """Render the edit grid: a bare fragment for htmx, a full page otherwise."""
        semester = get_viewing_semester(request)
        songs = _scoped_to_viewing_semester(Song, semester).order_by('position')
        formset = SetlistEditFormSet(queryset=songs, prefix='song')
        return self._render(request, semester, formset)

    def post(self, request):
        """Validate and save the whole buffer atomically, honoring the Semester's optimistic-concurrency stamp."""
        semester = get_viewing_semester(request)
        if semester is None:
            return redirect('scheduling:setlist')
        songs = _scoped_to_viewing_semester(Song, semester).order_by('position')
        formset = SetlistEditFormSet(request.POST, queryset=songs, prefix='song')
        if formset.is_valid():
            stale, malformed = self._save_if_current(semester, formset, request.POST.get('semester_updated_at', ''))
            if not stale and not malformed:
                messages.success(request, 'Setlist updated.')
                return redirect('scheduling:setlist')
            messages.error(request, self.STALE_MESSAGE if stale else self.MALFORMED_ORDER_MESSAGE)
        return self._render(request, semester, formset, status=200)

    def _save_if_current(self, semester, formset, submitted_stamp):
        """Save `formset` and bump the Semester's stamp if `submitted_stamp` still matches; return (stale, malformed).

        Locks the Semester row for the duration of the check-and-save so a
        concurrent save can't slip in between the comparison and the write.
        Rolls back and writes nothing when the stamp is stale, or when
        `_save_buffer` rejects the submitted `song_order` as malformed,
        without issuing any further query inside the doomed transaction.
        """
        stale = False
        malformed = False
        with transaction.atomic():
            locked = _lock_semester(semester)
            if not self._stamp_matches(locked, submitted_stamp):
                stale = True
                transaction.set_rollback(True)
            elif not self._save_buffer(locked, formset):
                malformed = True
                transaction.set_rollback(True)
            else:
                locked.updated_at = timezone.now()
                locked.save(update_fields=['updated_at'])
        return stale, malformed

    def _save_buffer(self, semester, formset):
        """Apply the buffer's edits, adds, reorder and deletes as one write (issue #179); return whether it saved.

        Runs inside the caller's locked transaction. A row's formset slot
        (`song-N-*`) never moves on drag — only Django's own initial/extra
        boundary can tell an existing Song's submitted id from a new row's,
        and that boundary is a fixed index cutoff, not a per-row flag,
        so renaming an existing row's slot on every drag would risk landing
        it past `INITIAL_FORMS` and silently duplicating it as new. Visual
        order instead travels as the repeated `song_order` field's *request
        order* (each value naming a slot's prefix), which is exactly the
        buffer's row order because SortableJS physically moves each row's
        DOM node — including its `song_order` input — on drop.

        Before any write, `song_order` is checked to be an exact
        duplicate-free permutation of the formset's own form prefixes —
        every row's `song_order` input travels with it regardless of
        whether that row is deleted or an untouched blank add, so the
        full prefix set (not just the surviving ones) is what the grid's
        JS actually submits. An unknown, duplicate, or missing prefix
        returns `False` and writes nothing, rather than silently omitting
        a surviving Song's edits or assigning conflicting positions.
        Every surviving row named there — changed, unchanged or
        brand-new — is then saved with a throwaway position first
        (position isn't a form field, so a new instance has none yet);
        `reorder_songs()` renumbers that exact order to a contiguous
        1..N, on the surviving Song ids alone, so valid deletions remain
        supported. Deletions (`delete_songs_with_recordings`) run after
        survivors are saved so a row moved out from under a doomed
        Song's old position never collides — the deferred unique
        constraint makes the whole sequence collision-free either way.
        """
        deleted_forms = formset.deleted_forms
        deleted_songs = [form.instance for form in deleted_forms if form.instance.pk]
        extra_forms = set(formset.extra_forms)
        forms_by_prefix = {form.prefix: form for form in formset.forms}

        order_tokens = formset.data.getlist('song_order')
        if sorted(order_tokens) != sorted(forms_by_prefix):
            return False

        ordered_ids = []
        for token in order_tokens:
            form = forms_by_prefix[token]
            if form in deleted_forms:
                continue
            if form in extra_forms and not form.has_changed():
                continue
            song = form.save(commit=False)
            song.semester = semester
            song.position = 0
            song.save()
            ordered_ids.append(song.pk)

        if deleted_songs:
            delete_songs_with_recordings(deleted_songs)

        reorder_songs(semester, ordered_ids)
        return True

    def _stamp_matches(self, semester, submitted_stamp):
        """Return whether `submitted_stamp` (an isoformat string) still matches `semester.updated_at`."""
        parsed = parse_datetime(submitted_stamp or '')
        return parsed is not None and parsed == semester.updated_at

    def _render(self, request, semester, formset, status=200):
        """Render the fragment for an htmx request, else the full page; both carry the same buffer."""
        context = self._build_context(semester, formset)
        if request.headers.get('HX-Request') == 'true':
            return render(request, self.fragment_template_name, context, status=status)
        return render(request, self.page_template_name, context, status=status)

    def _build_context(self, semester, formset):
        """Build the shared context for both the fragment and full-page renders."""
        return {
            'semester': semester,
            'formset': formset,
            'stamp': semester.updated_at.isoformat() if semester else '',
        }


class SetlistDeleteConfirmView(AdminRequiredMixin, View):
    """`/setlist/edit/confirm-delete/`: names the doomed Songs' recording/uploader counts before a Save (issue #179).

    Fetched by the edit grid's JS only when the buffer contains at least
    one deletion, with the struck rows' Song ids as `song_id` POST values.
    A pure counts read — it writes nothing and rolls nothing back — so it
    is not subject to ADR-0008's preview machinery and doesn't wait on
    #144. Scoped to the viewing Semester like every other read here, so a
    tampered id from another Semester is silently dropped rather than
    leaking a count across Semesters.
    """

    template_name = 'scheduling/_setlist_delete_confirm.html'

    def post(self, request):
        """Render the confirmation fragment naming each requested Song's recording/uploader counts."""
        semester = get_viewing_semester(request)
        song_ids = request.POST.getlist('song_id')
        songs = _scoped_to_viewing_semester(Song, semester).filter(pk__in=song_ids).order_by('position')
        summaries = song_deletion_summaries(songs)
        return render(request, self.template_name, {'summaries': summaries})


class MembersView(BaseView, TemplateView):
    """`/members/`: the Band Members roster for the viewing Semester — name, declared Roles, Song count (issue #137).

    Read-only and identical for admins and members: no email column and no
    admin badge, both of which stay confined to the admin-only people
    management page. Admin edit affordances are a future hook point
    (issue #130).
    """

    template_name = 'scheduling/members.html'

    def get_context_data(self, **kwargs):
        """Add the viewing Semester and its roster, or an empty roster when there's no viewing Semester yet."""
        context = super().get_context_data(**kwargs)
        semester = get_viewing_semester(self.request)
        context['semester'] = semester
        context['members'] = roster_for(_scoped_to_viewing_semester(Membership, semester))
        return context


class MemberDetailView(BaseView, View):
    """`/members/<int:pk>/`: one Person's page for the viewing Semester (issue #138).

    Two rendering modes, and no third: read-only for a teammate's pk,
    editable in place for `request.user.pk`. The editable mode carries the
    always-inline `MembershipRolesForm`, with no edit toggle, and is the
    only mode with any mutation surface at all — a POST to another
    Person's pk is a 404, not a rejected form. Issue #130 adds the third,
    admin-editable mode here.

    Every field this renders has an explicit verdict in
    `docs/person-page-visibility.md`; ADR 0005 keeps Conflict and derived
    attendance data off the page for everyone, its owner included, because
    the boundary is drawn around the surface rather than the viewer.

    A Person with no viewing-Semester `Membership` 404s — except your own
    pk, which builds an unsaved `Membership` instead, so a newly-invited
    member can declare Roles before an admin rosters them. With no current
    Semester at all nobody holds such a Membership, so a teammate's pk
    404s by the same rule while your own page renders an empty state.
    """

    template_name = 'scheduling/member_detail.html'

    def get(self, request, pk):
        """Render `pk`'s page: read-only for a teammate, or your own with the inline Roles form."""
        semester = get_viewing_semester(self.request)
        person = self._get_person_or_404(request, pk, semester)
        return render(request, self.template_name, self._build_context(request, person, semester))

    def post(self, request, pk):
        """Persist your own declared Roles, or 404 — a teammate's page has no mutation surface."""
        if pk != request.user.pk:
            raise Http404('A member can only edit their own declared Roles.')
        semester = get_viewing_semester(request)
        if semester is None:
            return render(request, self.template_name, self._build_context(request, request.user, semester))
        membership = self._get_or_build_membership(request.user, semester)
        form = MembershipRolesForm(request.POST, instance=membership)
        if form.is_valid():
            form.instance = self._membership_for_writing(request.user, semester)
            form.save()
            messages.success(request, 'Profile updated.')
            return redirect('scheduling:member-detail', pk=request.user.pk)
        context = self._build_context(request, request.user, semester)
        context['form'] = form
        return render(request, self.template_name, context)

    def _get_person_or_404(self, request, pk, semester):
        """Return your own Person unchecked, or a teammate holding a viewing-Semester Membership, else 404."""
        if pk == request.user.pk:
            return request.user
        membership = get_object_or_404(
            _scoped_to_viewing_semester(Membership, semester).select_related('person'), person_id=pk,
        )
        return membership.person

    def _build_context(self, request, person, semester):
        """Build the render context for `person`, adding the inline Roles form only on your own page."""
        is_self = person.pk == request.user.pk
        context = {'person': person, 'is_self': is_self, 'semester': semester, 'membership': None}
        if semester is None:
            return context
        membership = self._get_or_build_membership(person, semester)
        context['membership'] = membership
        context['declared_roles'] = declared_roles_for(membership)
        context['assignments'] = assigned_songs_for(person, semester) if membership.pk else []
        if is_self:
            context['form'] = MembershipRolesForm(instance=membership)
        return context

    def _get_or_build_membership(self, person, semester):
        """Return `person`'s Membership for `semester`, or an unsaved one if they hold none yet."""
        membership = Membership.objects.filter(person=person, semester=semester).first()
        return membership or Membership(person=person, semester=semester)

    def _membership_for_writing(self, person, semester):
        """Return the saved Membership to write the submitted Roles onto, creating it on a first submission.

        The read path deliberately hands back an *unsaved* Membership for a
        not-yet-rostered member, so merely viewing the page rosters nobody
        — but two concurrent first submissions would then each try to
        insert it, and the loser would 500 on
        `unique_membership_per_person_per_semester`. `get_or_create`
        absorbs that race, and the form only ever carries `roles` (its
        `Meta.fields` is empty), so re-pointing it at the row that won
        writes the same Roles either way.
        """
        membership, _ = Membership.objects.get_or_create(person=person, semester=semester)
        return membership


class SongDetailView(BaseView, DetailView):
    """A single Song's role assignments, rehearsal-count progress, and recordings."""

    model = Song
    template_name = 'scheduling/song_detail.html'
    context_object_name = 'song'

    def get_queryset(self):
        """Restrict lookups to the viewing Semester's Songs, so an older Song 404s."""
        return _scoped_to_viewing_semester(Song, get_viewing_semester(self.request))

    def get_context_data(self, **kwargs):
        """Add the Song's SongRoleAssignments, Role fill status, Recordings grouped by RehearsalSong slot, and rehearsal-count target vs. actual."""
        context = super().get_context_data(**kwargs)
        song = self.object
        context['assignments'] = SongRoleAssignment.objects.filter(song=song)
        context['fill_statuses'] = fill_status_for(song)
        context['recording_groups'] = [
            {
                'rehearsal_song': group.rehearsal_song,
                'recordings': [
                    {
                        'recording': recording,
                        'playback_url': create_recording_playback_url(recording),
                        'can_delete': recording.uploaded_by_id == self.request.user.pk,
                    }
                    for recording in group.recordings
                ],
            }
            for group in recording_groups_for(song)
        ]
        context['rehearsal_count_target'] = rehearsal_count_target(song)
        context['rehearsal_count_actual'] = song.rehearsalsong_set.count()
        return context


def _declare_prefix(rehearsal):
    """Return the per-row form prefix for `rehearsal`'s Upcoming Rehearsals declare form."""
    return f'rehearsal-{rehearsal.pk}'


def _history_edit_prefix(rehearsal):
    """Return the per-row form prefix for `rehearsal`'s History edit form (distinct from its declare prefix)."""
    return f'history-{rehearsal.pk}'


def _declared_time_initial(row):
    """Return {'arrival_time': ...} or {'departure_time': ...} to pre-fill a History edit form from `row`, or {}."""
    if row.declaration_type == CONFLICT_LATE_ARRIVAL:
        return {'arrival_time': row.declared_time}
    if row.declaration_type == CONFLICT_EARLY_DEPARTURE:
        return {'departure_time': row.declared_time}
    return {}


def _build_conflicts_context(request, error_rehearsal=None, error_form=None, selected_rehearsal_id=None):
    """Build /me/conflicts/'s shared context for GET and every POST failure re-render (issues #98, #99, #100).

    Takes the whole `request` rather than just the Person, since the page is
    scoped to `get_viewing_semester(request)` and the rows are always
    `request.user`'s own — the two can't come from different places.

    `error_rehearsal`/`error_form` inject a just-submitted invalid form back
    into its own row, wherever that Rehearsal's row lives — the Upcoming
    Rehearsals list (a declare submission) or the History list (an edit
    submission); a Rehearsal never appears in both, so no row is ambiguous.

    `selected_rehearsal_id` marks the row matching `?rehearsal=<id>` (issue
    #100) as selected, wherever it lives, the same way error_rehearsal does;
    it need not match any row (a stale or bogus id), in which case nothing
    is marked selected.
    """
    person = request.user
    semester = get_viewing_semester(request)
    if semester is None:
        return {'semester': None}
    rehearsals = future_rehearsals_for(semester)
    existing_conflicts = {
        conflict.rehearsal_id: conflict for conflict in Conflict.objects.filter(person=person, rehearsal__in=rehearsals)
    }
    rows = [
        _build_declare_row(rehearsal, existing_conflicts.get(rehearsal.pk), error_rehearsal, error_form, selected_rehearsal_id)
        for rehearsal in rehearsals
    ]
    history = [
        _build_history_row(row, error_rehearsal, error_form, selected_rehearsal_id)
        for row in conflict_history_for(semester, person)
    ]
    return {'semester': semester, 'rows': rows, 'history': history}


def _build_declare_row(rehearsal, conflict, error_rehearsal, error_form, selected_rehearsal_id=None):
    """Return one Upcoming Rehearsals row: its Rehearsal, plus either its existing Conflict or its declare form.

    An already-declared Rehearsal is never marked selected here even when it
    matches `?rehearsal=<id>` — issue #100 directs that case to its History
    row instead, per the disabled-row rule (issue #98).
    """
    if conflict is not None:
        return {'rehearsal': rehearsal, 'conflict': conflict, 'form': None, 'is_selected': False}
    is_selected = rehearsal.pk == selected_rehearsal_id
    if error_rehearsal is not None and error_rehearsal.pk == rehearsal.pk:
        form = error_form
    else:
        form = DeclareConflictForm(rehearsal=rehearsal, prefix=_declare_prefix(rehearsal))
    return {'rehearsal': rehearsal, 'conflict': None, 'form': form, 'is_selected': is_selected}


def _build_history_row(row, error_rehearsal, error_form, selected_rehearsal_id=None):
    """Return one History row: `row`'s display fields, plus an edit form when its Rehearsal is still future (issue #99)."""
    context_row = {
        'rehearsal': row.rehearsal,
        'conflict': row.conflict,
        'type_label': row.type_label,
        'declared_time': row.declared_time,
        'reason': row.conflict.reason,
        'is_future': row.is_future,
        'is_selected': row.rehearsal.pk == selected_rehearsal_id,
        'form': None,
    }
    if not row.is_future:
        return context_row
    if error_rehearsal is not None and error_rehearsal.pk == row.rehearsal.pk:
        context_row['form'] = error_form
    else:
        context_row['form'] = DeclareConflictForm(
            rehearsal=row.rehearsal,
            initial={'declaration_type': row.declaration_type, 'reason': row.conflict.reason, **_declared_time_initial(row)},
            prefix=_history_edit_prefix(row.rehearsal),
        )
    return context_row


def _parse_selected_rehearsal_id(raw_id):
    """Return `?rehearsal=<id>` (issue #100) parsed as an int, or None for a missing/non-numeric value."""
    if raw_id is None:
        return None
    try:
        return int(raw_id)
    except ValueError:
        return None


def _future_rehearsal_with_conflict_or_404(request, rehearsal_id, action):
    """Return the viewing Semester's future Rehearsal with an existing Conflict for request.user, or 404.

    Shared by ConflictEditView and ConflictDeleteView: the hidden Edit/Delete
    controls on a past History row are not the actual enforcement, so both
    views re-check date/ownership server-side regardless of request origin
    (issue #99). `action` ('edited'/'deleted') only shapes the 404 message.
    """
    rehearsal = get_object_or_404(
        _scoped_to_viewing_semester(Rehearsal, get_viewing_semester(request)), pk=rehearsal_id,
    )
    if not Conflict.objects.filter(person=request.user, rehearsal=rehearsal).exists():
        raise Http404('No existing Conflict for this Rehearsal.')
    if rehearsal.date < timezone.localdate():
        raise Http404(f'Past Rehearsals cannot be {action}.')
    return rehearsal


class ConflictsView(BaseView, View):
    """`/me/conflicts/`: the unified Conflicts page's Upcoming Rehearsals declare flow (issues #98, #99).

    Lists every future Rehearsal (date >= today) in the viewing Semester.
    A Rehearsal with no existing Conflict for `request.user` gets an inline
    declare form (full absence / late arrival / early departure); one that
    already has a Conflict renders as a disabled row pointing to History
    (built alongside this view's GET context; edited/deleted by
    ConflictEditView/ConflictDeleteView below).
    """

    template_name = 'scheduling/conflicts.html'

    def get(self, request):
        """Render every future Rehearsal, each paired with its declare form or its existing Conflict, plus History.

        `?rehearsal=<id>` (issue #100, matching My Schedule's "Add a
        conflict" link) marks the matching row selected, wherever it lives,
        for the page's client-side scroll/expand/highlight.
        """
        selected_rehearsal_id = _parse_selected_rehearsal_id(request.GET.get('rehearsal'))
        context = _build_conflicts_context(request, selected_rehearsal_id=selected_rehearsal_id)
        return render(request, self.template_name, context)

    def post(self, request):
        """Declare a Conflict for the Rehearsal named in the POST body, or re-render that row with its errors.

        The Dress Rehearsal is out of the lookup's reach (is_full_setlist=False),
        so a hand-crafted POST naming it 404s here rather than reaching
        declare_conflict()'s ValueError as a 500 (ADR-0006).
        """
        semester = get_viewing_semester(request)
        rehearsal = get_object_or_404(
            _scoped_to_viewing_semester(Rehearsal, semester).filter(
                date__gte=timezone.localdate(), is_full_setlist=False,
            ),
            pk=request.POST.get('rehearsal_id'),
        )
        if Conflict.objects.filter(person=request.user, rehearsal=rehearsal).exists():
            raise Http404('A Conflict already exists for this Rehearsal.')
        form = DeclareConflictForm(request.POST, rehearsal=rehearsal, prefix=_declare_prefix(rehearsal))
        if form.is_valid():
            try:
                declare_conflict(
                    person=request.user,
                    rehearsal=rehearsal,
                    declaration_type=form.cleaned_data['declaration_type'],
                    declared_time=form.declared_time,
                    reason=form.cleaned_data['reason'],
                    allow_edit=False,
                )
            except IntegrityError:
                # A concurrent request won the race past the exists() check above.
                raise Http404('A Conflict already exists for this Rehearsal.') from None
            messages.success(request, 'Conflict declared.')
            return redirect('scheduling:conflicts')
        context = _build_conflicts_context(request, error_rehearsal=rehearsal, error_form=form)
        return render(request, self.template_name, context)


class ConflictEditView(BaseView, View):
    """`/me/conflicts/<rehearsal_id>/edit/`: edits `request.user`'s existing Conflict from History (issue #99).

    Reuses declare_conflict's type-to-model mapping against the Rehearsal's
    existing (person, rehearsal)-unique Conflict, so this is always an edit
    in place, never a second row. Future-only, and that's enforced here
    server-side (a 404), independent of the template hiding History's Edit
    control for a past Rehearsal — a crafted request must be rejected the
    same way.
    """

    template_name = 'scheduling/conflicts.html'

    def post(self, request, rehearsal_id):
        """Validate and persist the resubmitted declaration against the existing Conflict, or re-render with errors."""
        rehearsal = self._get_editable_rehearsal(request, rehearsal_id)
        form = DeclareConflictForm(request.POST, rehearsal=rehearsal, prefix=_history_edit_prefix(rehearsal))
        if form.is_valid():
            declare_conflict(
                person=request.user,
                rehearsal=rehearsal,
                declaration_type=form.cleaned_data['declaration_type'],
                declared_time=form.declared_time,
                reason=form.cleaned_data['reason'],
            )
            messages.success(request, 'Conflict updated.')
            return redirect('scheduling:conflicts')
        context = _build_conflicts_context(request, error_rehearsal=rehearsal, error_form=form)
        return render(request, self.template_name, context)

    def _get_editable_rehearsal(self, request, rehearsal_id):
        """Return the viewing Semester's future Rehearsal with an existing Conflict for request.user, or 404."""
        return _future_rehearsal_with_conflict_or_404(request, rehearsal_id, action='edited')


class ConflictDeleteView(BaseView, View):
    """`/me/conflicts/<rehearsal_id>/delete/`: removes `request.user`'s Conflict from History (issue #99).

    Future-only, enforced server-side (a 404) for the same reason as
    ConflictEditView — the hidden Delete control on a past row is not the
    actual enforcement.
    """

    def post(self, request, rehearsal_id):
        """Delete request.user's Conflict (and any ConflictWindows, via cascade) for this future Rehearsal, or 404."""
        rehearsal = _future_rehearsal_with_conflict_or_404(request, rehearsal_id, action='deleted')
        Conflict.objects.filter(person=request.user, rehearsal=rehearsal).delete()
        messages.success(request, 'Conflict removed.')
        return redirect('scheduling:conflicts')


class RehearsalManageView(AdminRequiredMixin, View):
    """`/manage/schedule/`: an admin lists and creates the viewing Semester's Rehearsals (issue #60, #17 story 10)."""

    template_name = 'scheduling/manage_schedule.html'

    def get(self, request):
        """Render the viewing Semester's Rehearsals alongside an empty create form."""
        return render(request, self.template_name, self._build_context())

    def post(self, request):
        """Validate the create form and save a new Rehearsal in the viewing Semester, or re-render with errors."""
        semester = get_viewing_semester(request)
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
        """Build context: the viewing Semester's Rehearsals plus the create form (fresh if none is given)."""
        semester = get_viewing_semester(self.request)
        return {
            'semester': semester,
            'rehearsals': _scoped_to_viewing_semester(Rehearsal, semester),
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
        """Return the viewing Semester's Rehearsal with this id, or 404 (mirrors SongDetailView's scoping)."""
        return get_object_or_404(_scoped_to_viewing_semester(Rehearsal, get_viewing_semester(self.request)), pk=pk)


class SongRoleAssignmentManageView(AdminRequiredMixin, View):
    """`/manage/assignments/`: an admin lists and creates SongRoleAssignments, surfacing mismatches (issue #60, #17 story 12)."""

    template_name = 'scheduling/manage_assignments.html'

    def get(self, request):
        """Render the viewing Semester's SongRoleAssignments alongside an empty create form."""
        return render(request, self.template_name, self._build_context())

    def post(self, request):
        """Validate the create form and save a new SongRoleAssignment, or re-render with errors."""
        semester = get_viewing_semester(request)
        if semester is None:
            messages.error(request, 'Create a Semester with Songs before assigning Roles.')
            return redirect('scheduling:manage-assignments')
        songs = _scoped_to_viewing_semester(Song, semester)
        form = SongRoleAssignmentForm(request.POST, songs=songs)
        if form.is_valid():
            form.save()
            messages.success(request, 'Assignment created.')
            return redirect('scheduling:manage-assignments')
        return render(request, self.template_name, self._build_context(form))

    def _build_context(self, form=None):
        """Build context: the viewing Semester's SongRoleAssignments plus the create form (fresh if none is given)."""
        semester = get_viewing_semester(self.request)
        songs = _scoped_to_viewing_semester(Song, semester)
        assignments = SongRoleAssignment.objects.filter(song__in=songs).select_related('song', 'role', 'person')
        return {
            'semester': semester,
            'assignments': assignments,
            'form': form or SongRoleAssignmentForm(songs=songs),
        }


class SongRoleAssignmentDeleteView(AdminRequiredMixin, View):
    """`/manage/assignments/<pk>/delete/`: an admin removes a SongRoleAssignment (issue #60, #17 story 12)."""

    def post(self, request, pk):
        """Delete the viewing Semester's target SongRoleAssignment and redirect with a success message."""
        songs = _scoped_to_viewing_semester(Song, get_viewing_semester(request))
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
    dropdown to that Song's own slots within the viewing Semester; omitting
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
        """Render the picker/confirm template with `form`, its option count, and any `?song=` scope.

        The empty-dropdown message has to differ by entry point: semester-wide
        when the picker is unfiltered, but scoped to the one Song when
        `?song=<id>` narrowed it — otherwise a single unscheduled Song's page
        wrongly reports that *no* Song is scheduled (issue #121).
        """
        raw_song_id = self.request.GET.get('song')
        return render(self.request, self.template_name, {
            'form': form,
            'has_rehearsal_song_options': form.fields['rehearsal_song'].queryset.exists(),
            'is_scoped_to_one_song': raw_song_id is not None,
            'requested_song': self._requested_song(raw_song_id),
        })

    def _requested_song(self, raw_song_id):
        """Return the viewing Semester's `?song=<id>` Song, or None when unscoped or no such Song exists.

        Short-circuits before parsing when there's no viewing Semester, mirroring
        `_rehearsal_songs()` — otherwise a malformed `?song=` would start 404ing on
        a Semester-less database, where it used to render normally.
        """
        semester = get_viewing_semester(self.request)
        if raw_song_id is None or semester is None:
            return None
        return Song.objects.filter(pk=self._parse_song_id(raw_song_id), semester=semester).first()

    def _rehearsal_songs(self, request):
        """Return the viewing Semester's RehearsalSongs, filtered to `?song=<id>` when given.

        Empty queryset if there's no viewing Semester, or if `?song=<id>` matches no
        RehearsalSong (e.g. a Song with no scheduled slots yet) — never an error.
        """
        semester = get_viewing_semester(self.request)
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


class RecordingDeleteView(BaseView, View):
    """`/me/recordings/<pk>/delete/`: a member deletes their own Recording from a Song's detail page (issue #104).

    Ownership-gated server-side (not just template-hidden): the lookup is
    scoped to `uploaded_by=request.user`, so a non-uploader's request 404s
    rather than deleting another member's Recording, mirroring the
    "no cross-member deletion" rule the delete control's template-side
    hiding is only a UX shortcut for.
    """

    def post(self, request, pk):
        """Delete the requesting member's own target Recording and redirect back to its Song's detail page."""
        recording = get_object_or_404(Recording, pk=pk, uploaded_by=request.user)
        song_id = recording.rehearsal_song.song_id
        recording.delete()
        messages.success(request, 'Recording deleted.')
        return redirect('scheduling:song-detail', pk=song_id)


class SemesterManageView(AdminRequiredMixin, View):
    """`/manage/semesters/`: an admin lists every Semester with its Live/Draft/Previously published state (issue #170)."""

    template_name = 'scheduling/manage_semesters.html'

    def get(self, request):
        """Render every Semester, newest-created first, alongside the Live Semester for status labeling."""
        semesters = Semester.objects.order_by('-created_at', '-id')
        return render(request, self.template_name, {
            'semesters': semesters,
            'live_semester': get_live_semester(),
        })


class SemesterPublishView(AdminRequiredMixin, View):
    """`/manage/semesters/<pk>/publish/`: an admin publishes a Semester, making it the Live Semester (issue #170).

    Publishing sets `published_at` to now and does nothing else — it is
    visibility only, never gating or locking edits inside any Semester.
    Pressing this on the already-live Semester is harmless (ADR-0010).
    """

    def post(self, request, pk):
        """Publish the target Semester and redirect back to the Semesters list with a success message."""
        semester = get_object_or_404(Semester, pk=pk)
        publish_semester(semester)
        messages.success(request, f'{semester} published.')
        return redirect('scheduling:manage-semesters')


class SemesterDeleteView(AdminRequiredMixin, View):
    """`/manage/semesters/<pk>/delete/`: an admin confirms and hard-deletes a non-Live Semester (issue #171).

    GET renders one confirmation naming the counts of everything the delete
    would destroy (no export/keep branch, per the spec); POST performs it.
    The Live Semester is refused by `delete_semester()` itself, not just
    here, so a POST that races a publish still 400s instead of deleting.
    """

    template_name = 'scheduling/manage_semesters_delete.html'

    def get(self, request, pk):
        """Render the confirmation naming the Semester's member/song/rehearsal/recording counts."""
        semester = get_object_or_404(Semester, pk=pk)
        if semester == get_live_semester():
            raise Http404('The Live Semester cannot be deleted.')
        return render(request, self.template_name, {
            'semester': semester,
            'summary': semester_deletion_summary(semester),
        })

    def post(self, request, pk):
        """Delete the target Semester, or reject the Live Semester with a 400, and redirect with a message."""
        semester = get_object_or_404(Semester, pk=pk)
        try:
            delete_semester(semester)
        except LiveSemesterDeletionError as error:
            return HttpResponseBadRequest(str(error))
        messages.success(request, f'{semester} deleted.')
        return redirect('scheduling:manage-semesters')
