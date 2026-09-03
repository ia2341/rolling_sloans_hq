"""Member read routes (issue #56), self-service routes (issues #57, #58, #61), and admin management routes (issue #60)."""

import json
import re

from django.contrib import messages
from django.db import transaction
from django.http import (
    Http404,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import DetailView, TemplateView

from config.views import AdminRequiredMixin, BaseView, PreviewMixin
from identity.models import Person
from identity.services import invite_person
from scheduling.forms import (
    AdjudicationFormSet,
    DeclareConflictForm,
    MembershipRolesForm,
    RecordingUploadForm,
    RehearsalForm,
    RosterAddFormSet,
    RosterAddRoleForm,
    RosterAddRowForm,
    RosterEditFormSet,
    RosterEditRowForm,
    RosterInviteForm,
    SemesterSetupForm,
    SetlistEditEmptyFormSet,
    SetlistEditFormSet,
    SongRoleAssignmentForm,
    SpotifyImportForm,
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
    AdjudicationBuffer,
    AdjudicationEntry,
    InvalidSemesterNameError,
    LiveSemesterDeletionError,
    RecordingUploadError,
    RosterEditBuffer,
    RosterEditEntry,
    SelfRemovalError,
    StaleAdjudicationSemesterError,
    StaleRosterSemesterError,
    UnknownConflictError,
    WrongAdjudicationSemesterError,
    WrongViewingSemesterError,
    apply_adjudications,
    apply_roster_edits,
    assigned_songs_for,
    assignment_matrix_for,
    attendance_suggestion_for,
    breaks_for,
    confirm_recording_upload,
    conflict_adjudication_index_for,
    conflict_adjudication_rows_for,
    conflict_rows_by_rehearsal,
    create_or_reactivate_role,
    create_recording_playback_url,
    create_semester,
    declare_conflict,
    declared_roles_for,
    delete_semester,
    delete_songs_with_recordings,
    fill_status_for,
    future_rehearsals_for,
    get_live_semester,
    get_viewing_semester,
    import_roster_from_semester,
    landing_rehearsal_for,
    mismatched_person_ids_for,
    next_attended_rehearsal_for,
    performers_for,
    preview_roster_edits,
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
    unrostered_people_for,
    upcoming_rehearsals_for,
)
from scheduling.spotify import SpotifyImportError, import_playlist


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
        """Add the Next Rehearsal card (issue #94), song-progress table (issue #93) and admin panel (issues #169, #199)."""
        context = super().get_context_data(**kwargs)
        semester = get_viewing_semester(self.request)
        context['semester'] = semester
        context['semester_options'] = semester_options_for(self.request)
        context['live_semester'] = get_live_semester()
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


VIEW_ALL = 'all'
VIEW_NEXT = 'next'
"""`/schedule/`'s two views, named once for every place that has to agree on them.

Module-level rather than `ScheduleView` attributes because the declare
and delete endpoints resolve the same values out of the hidden `view`
field they post back, to re-render or redirect to the view the member
submitted from (issue #190).
"""


class ScheduleView(BaseView, TemplateView):
    """`/schedule/`: the single member-facing page — rehearsal detail, the All-Rehearsals list, and your own availability (issues #95, #97, #190).

    Defaults (`?view=next`, or no `?view=` at all) to a Rehearsal's Song x
    Role x Person assignment matrix — `landing_rehearsal_for()`'s anchor
    unless `?rehearsal=<id>` drills into a specific one — with a "Your
    availability" block for that Rehearsal beside the attendance
    suggestion and breaks. `?view=all` instead lists the viewing
    Semester's full schedule, split into a collapsed past section and an
    expanded future section, each row carrying the same availability
    summary and linking to its own `?rehearsal=<id>` detail.

    Availability folded in here rather than sitting beside the schedule
    (issue #190): a separate section would have rendered the same
    Rehearsals twice on one page. The Conflicts page it replaced is gone
    outright, with no redirect. Everything availability-related on this
    page is `request.user`'s own — an admin viewing it reads their own
    declarations and nobody else's, per ADR 0005.
    """

    template_name = 'scheduling/schedule.html'

    def get_context_data(self, **kwargs):
        """Add either the All-Rehearsals schedule or the resolved Rehearsal's matrix, each with the viewer's own availability."""
        context = super().get_context_data(**kwargs)
        semester = get_viewing_semester(self.request)
        view_mode = _resolve_view_mode(self.request.GET.get('view'))
        rehearsal = self._resolve_rehearsal(semester) if view_mode == VIEW_NEXT else None
        context.update(_build_schedule_context(self.request, semester, view_mode, rehearsal))
        return context

    def _resolve_rehearsal(self, semester):
        """Return the `?rehearsal=<id>` Rehearsal (404 outside the viewing Semester), or this member's landing Rehearsal."""
        if semester is None:
            return None
        raw_id = self.request.GET.get('rehearsal')
        if raw_id is None:
            return landing_rehearsal_for(self.request.user, semester)
        rehearsal_id = self._parse_rehearsal_id(raw_id)
        return get_object_or_404(_scoped_to_viewing_semester(Rehearsal, semester), pk=rehearsal_id)

    def _parse_rehearsal_id(self, raw_id):
        """Return `raw_id` as an int, or raise Http404 for a non-numeric value."""
        try:
            return int(raw_id)
        except ValueError:
            raise Http404 from None


def _resolve_view_mode(raw_value):
    """Return VIEW_ALL for the literal 'all', else VIEW_NEXT (the default rehearsal-detail view).

    Reads a raw string rather than the request so the `?view=` query
    parameter and the hidden `view` field a declare/delete form posts back
    resolve through exactly the same rule — a failed submission must
    re-render the view the member submitted from.
    """
    return VIEW_ALL if raw_value == VIEW_ALL else VIEW_NEXT


def _build_schedule_context(request, semester, view_mode, rehearsal, error_rehearsal=None, error_form=None):
    """Build `/schedule/`'s context for a GET and for every declare/edit failure re-render (issue #190).

    Takes the whole `request` because every availability read on this page
    is `request.user`'s own — the viewer and the Person the rows are about
    can never come from different places (ADR 0005).

    `error_rehearsal`/`error_form` inject a just-submitted invalid
    declaration back into its own rehearsal's availability block, wherever
    that Rehearsal is rendered in `view_mode`.
    """
    context = {
        'semester': semester,
        'view_mode': view_mode,
        'rehearsal': None,
        'matrix': None,
        'my_song_ids': set(),
        'my_attendance_suggestion': None,
        'my_breaks': [],
        'my_availability': None,
        'schedule': None,
    }
    if semester is None:
        return context
    conflict_rows = conflict_rows_by_rehearsal(semester, request.user)
    today = timezone.localdate()
    if view_mode == VIEW_ALL:
        schedule = rehearsal_schedule_for(semester, request.user)
        context['schedule'] = {
            section: [
                {
                    'rehearsal': row.rehearsal,
                    'attendance_suggestion': row.attendance_suggestion,
                    'availability': _availability_for(
                        row.rehearsal, conflict_rows.get(row.rehearsal.pk), today, error_rehearsal, error_form,
                    ),
                }
                for row in rows
            ]
            for section, rows in (('past', schedule.past), ('future', schedule.future))
        }
        return context
    context['rehearsal'] = rehearsal
    if rehearsal is None:
        return context
    matrix = assignment_matrix_for(rehearsal)
    context['matrix'] = matrix
    context['my_song_ids'] = set(
        SongRoleAssignment.objects.filter(
            person=request.user, song__in=[row.song for row in matrix.rows],
        ).values_list('song_id', flat=True)
    )
    context['my_attendance_suggestion'] = attendance_suggestion_for(rehearsal, request.user)
    context['my_breaks'] = breaks_for(rehearsal, request.user)
    context['my_availability'] = _availability_for(
        rehearsal, conflict_rows.get(rehearsal.pk), today, error_rehearsal, error_form,
    )
    return context


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
        """Render the edit grid: a bare fragment for htmx, a full page otherwise.

        An empty setlist opens with one blank row already present (issue
        #180), so a brand-new Semester isn't a dead end — otherwise there
        would be nothing for the grid's own "+ Add song" to add to.
        """
        semester = get_viewing_semester(request)
        songs = _scoped_to_viewing_semester(Song, semester).order_by('position')
        formset_class = SetlistEditFormSet if songs.exists() else SetlistEditEmptyFormSet
        formset = formset_class(queryset=songs, prefix='song')
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


def _parse_roster_int(raw_value):
    """Return `raw_value` as an int, or -1 (matching no real row/Semester) when it isn't one.

    Shared by `MembersView`, the Roster add list (issue #229) and the
    Roster Preview surface (issue #228) so the three never drift on how a
    malformed hidden field is coerced.
    """
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return -1


def _add_initial(semester, imported_roles_by_person_id=None, current_state_by_person_id=None):
    """Build the Roster add list's initial rows: one per unrostered Person, optionally pre-ticked from an import proposal (issue #229).

    `imported_roles_by_person_id`, when given, maps a Person id to the
    Roles `import_roster_from_semester()` proposes for them; a Person
    present in it renders pre-ticked with those Roles. `current_state_by_person_id`
    carries whatever an admin had already hand-ticked/unticked before
    pressing Import (`_submitted_add_state_by_person_id()`), and is used
    as the fallback for any Person the import proposal doesn't cover, so
    Import overlays rather than replaces hand-made edits. With neither
    argument (the plain edit-mode render, no import pressed) every row
    renders unticked.
    """
    imported_roles_by_person_id = imported_roles_by_person_id or {}
    current_state_by_person_id = current_state_by_person_id or {}
    rows = []
    for person in unrostered_people_for(semester):
        roles = imported_roles_by_person_id.get(person.pk)
        if roles is not None:
            rows.append({'person_id': person.pk, 'add': True, 'roles': roles})
            continue
        current = current_state_by_person_id.get(person.pk)
        if current is not None:
            rows.append({'person_id': person.pk, 'add': current['add'], 'roles': current['role_ids']})
            continue
        rows.append({'person_id': person.pk, 'add': False, 'roles': []})
    return rows


def _submitted_add_state_by_person_id(request):
    """Return `{person_id: {'add': bool, 'role_ids': [...]}}` from an add-list formset carried in `request.GET`, or `{}` if none was submitted.

    Reads raw per-field values the same way `_edit_rows()` does, rather
    than requiring `is_valid()`, so a formset the admin hasn't finished
    filling out can still be read back.
    """
    prefix = 'roster_add'
    if f'{prefix}-TOTAL_FORMS' not in request.GET:
        return {}
    formset = RosterAddFormSet(request.GET, prefix=prefix)
    state = {}
    for form in formset:
        person_id = _parse_roster_int(form['person_id'].value())
        if person_id == -1:
            continue
        state[person_id] = {
            'add': bool(form['add'].value()),
            'role_ids': form['roles'].value() or [],
        }
    return state


def _add_rows(add_formset):
    """Pair each add-list formset row with its Person, so an invalid re-render can still show the row's name."""
    form_person_ids = [(form, _parse_roster_int(form['person_id'].value())) for form in add_formset]
    people_by_id = Person.objects.in_bulk([person_id for _, person_id in form_person_ids])
    return [{'form': form, 'person': people_by_id.get(person_id)} for form, person_id in form_person_ids]


def _build_roster_buffer(formset, submitted_semester_id, submitted_stamp):
    """Turn a valid RosterEditFormSet into a RosterEditBuffer, carrying the Semester state it was rendered against.

    Shared by `MembersView.post()` and `RosterPreviewView.run_preview()`
    (issue #228) — the Preview and Save endpoints must parse the exact
    same POST body into the exact same Buffer shape, per ADR 0008.
    `submitted_semester_id`/`submitted_stamp` are the hidden fields
    stamped at render time, not the live session's viewing Semester —
    `apply_roster_edits()`/`preview_roster_edits()` are where those are
    compared against current state.
    """
    person_ids = {row['person_id'] for row in formset.cleaned_data}
    people_by_id = Person.objects.in_bulk(person_ids)
    entries = []
    removed_person_ids = set()
    for row in formset.cleaned_data:
        person = people_by_id.get(row['person_id'])
        if person is None:
            continue
        if row['remove']:
            removed_person_ids.add(person.pk)
            continue
        entries.append(RosterEditEntry(
            person=person, name=row['name'], role_ids=frozenset(role.pk for role in row['roles']),
        ))
    return RosterEditBuffer(
        semester_id=_parse_roster_int(submitted_semester_id),
        semester_updated_at=parse_datetime(submitted_stamp) or timezone.now(),
        entries=entries,
        removed_person_ids=frozenset(removed_person_ids),
    )


class SetlistImportView(AdminRequiredMixin, View):
    """`/setlist/edit/import/`: turns a pasted Spotify playlist link into filled buffer rows (issue #184).

    A fetch-and-inject helper for the edit grid already open, the same
    shape as `SetlistDeleteConfirmView` — not a second write path. It
    writes nothing: `import_playlist()` only reads from Spotify, and the
    rows this renders are unsaved `Song` instances the client appends to
    its own buffer; only `SetlistEditView`'s Save persists anything, so a
    bad import costs a Cancel rather than a cleanup. A malformed link
    (caught by `SpotifyImportForm` before any request), an unconfigured
    import, or any other `SpotifyImportError` (private/missing playlist,
    auth failure, rate limit, transport error) all render the same
    fragment with a readable `error` instead of raising, leaving the
    admin's buffer untouched.
    """

    template_name = 'scheduling/_setlist_edit_import_result.html'

    def post(self, request):
        """Validate the playlist link, import it, and render new buffer rows or a readable error."""
        semester = get_viewing_semester(request)
        if semester is None:
            return HttpResponseBadRequest()
        form = SpotifyImportForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'error': form.errors['playlist_url'][0]})
        try:
            result = import_playlist(form.cleaned_data['playlist_url'])
        except SpotifyImportError as error:
            return render(request, self.template_name, {'error': str(error)})

        next_index = self._parse_next_index(request.POST.get('next_index', ''))
        row_forms = [
            self._row_form(imported_song, next_index + offset)
            for offset, imported_song in enumerate(result.songs)
        ]
        return render(request, self.template_name, {
            'forms': row_forms,
            'added_count': len(row_forms),
            'skipped_count': result.skipped_count,
            'skipped_reasons': result.skipped_reasons,
        })

    def _parse_next_index(self, raw_value):
        """Return `raw_value` as a non-negative int, or 0 for a missing/malformed value."""
        try:
            value = int(raw_value)
        except ValueError:
            return 0
        return max(value, 0)

    def _row_form(self, imported_song, index):
        """Build one unbound `SetlistEditFormSet`-shaped row at slot `song-{index}`, filled from `imported_song`.

        Mirrors `SetlistEditFormSet.empty_form`'s own construction (same
        `add_fields()` call, so the `id`/`DELETE` fields the grid's row
        partial expects are present) but at a real slot index with the
        imported track's values as initial data, rather than a blank
        `__prefix__` row for the client to fill in by hand.
        """
        blank_formset = SetlistEditFormSet(queryset=Song.objects.none(), prefix='song')
        form = blank_formset.form(
            auto_id=blank_formset.auto_id,
            prefix=blank_formset.add_prefix(index),
            empty_permitted=True,
            use_required_attribute=False,
            initial={
                'title': imported_song.title,
                'artist': imported_song.artist,
                'length': imported_song.length,
                # Always blank, never `imported_song.notes` — notes have no Spotify
                # equivalent, and the column must plainly read as the admin's (issue #184).
                'notes': '',
            },
        )
        blank_formset.add_fields(form, None)
        return form


_EDIT_TEMPLATE_NAME = 'scheduling/members_edit.html'
_EDIT_FRAGMENT_TEMPLATE_NAME = 'scheduling/_members_edit.html'


def _edit_initial(semester):
    """Build the edit formset's initial data: one row per existing Membership, ordered by Person name."""
    memberships = roster_for(_scoped_to_viewing_semester(Membership, semester))
    return [
        {
            'person_id': membership.person_id,
            'name': membership.person.name,
            'roles': [
                membership_role.role_id for membership_role in membership.membershiprole_set.all()
            ],
            'remove': False,
        }
        for membership in memberships
    ]


def _edit_rows(formset, semester, requesting_admin_id):
    """Pair each formset row with its Person id, so a bound-or-not row can flag itself/its mismatch state.

    Reads `person_id`'s raw submitted value rather than `cleaned_data`, so
    this pairing survives an otherwise-invalid formset — the same
    every-value-preserved re-render `SetlistEditView` gives a rejected
    buffer.
    """
    mismatched_person_ids = mismatched_person_ids_for(semester)
    rows = []
    for form in formset:
        person_id = _parse_roster_int(form['person_id'].value())
        rows.append({
            'form': form,
            'is_self': person_id == requesting_admin_id,
            'is_mismatched': person_id in mismatched_person_ids,
        })
    return rows


def _is_htmx(request):
    """Return whether `request` is an htmx-driven in-place swap rather than a direct/no-JS navigation."""
    return request.headers.get('HX-Request') == 'true'


def _render_roster_edit(request, semester, formset, add_formset, *, semester_id, stamp, status=200, invite_form=None):
    """Render Roster edit mode: the bare edit-table-plus-add-list fragment for htmx, the full page otherwise.

    Shared by `MembersView` and `RosterInviteView` (issue #230), so an
    invalid invite re-renders the exact same edit surface Save's own
    invalid-formset path does, rather than a second near-duplicate
    template context.
    """
    context = {
        'semester': semester,
        'formset': formset,
        'rows': _edit_rows(formset, semester, request.user.pk),
        'add_formset': add_formset,
        'add_rows': _add_rows(add_formset),
        'import_source_semester': import_roster_from_semester(semester).source_semester,
        'roster_semester_id': semester_id,
        'roster_semester_updated_at': stamp,
        'invite_form': invite_form or RosterInviteForm(),
    }
    template = _EDIT_FRAGMENT_TEMPLATE_NAME if _is_htmx(request) else _EDIT_TEMPLATE_NAME
    return render(request, template, context, status=status)


class MembersView(BaseView, View):
    """`/members/`: the Band Members roster, plus an admin's in-place "Edit roster" mode (issues #137, #227).

    Read mode is byte-identical for admins and members — no email column,
    no admin badge — apart from the admin-only "Edit roster" button.
    Deliberately **not** a separate route (that shape is `manage/`, which
    this map exists to retire): `?mode=edit` toggles the edit table on the
    same URL the reader is already on, htmx-swapped in place like
    `SetlistEditView`'s grid but without a sibling URL of its own. `GET`
    ignores `?mode=edit` for a non-admin, so a crafted query string can't
    show a member the edit affordance. `POST` (Save Changes) is the only
    mutation surface and is admin-gated by hand, since `AdminRequiredMixin`
    would also lock a member out of the shared read-mode `GET`; an
    anonymous POST is redirected to login by `BaseView` before `dispatch`
    reaches this check.
    """

    template_name = 'scheduling/members.html'
    edit_template_name = _EDIT_TEMPLATE_NAME
    edit_fragment_template_name = _EDIT_FRAGMENT_TEMPLATE_NAME
    read_fragment_template_name = 'scheduling/_members_read.html'

    def dispatch(self, request, *args, **kwargs):
        """Return 403 for a logged-in non-admin's POST; defer to the login-gated dispatch chain otherwise."""
        if request.method == 'POST' and request.user.is_authenticated and not request.user.is_admin:
            return HttpResponseForbidden()
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        """Render the read-mode roster, or an admin's `?mode=edit` edit table plus add list."""
        semester = get_viewing_semester(request)
        if request.user.is_admin and request.GET.get('mode') == 'edit' and semester is not None:
            formset = RosterEditFormSet(initial=_edit_initial(semester), prefix='roster')
            add_formset = RosterAddFormSet(initial=_add_initial(semester), prefix='roster_add')
            return _render_roster_edit(
                request, semester, formset, add_formset,
                semester_id=semester.pk, stamp=semester.updated_at.isoformat(),
            )
        return self._render_read(request, semester)

    def post(self, request):
        """Validate and apply the whole Roster edit Buffer (edit rows plus add-list ticks) atomically, or re-render with errors."""
        semester = get_viewing_semester(request)
        if semester is None:
            return redirect('scheduling:members')
        submitted_semester_id = request.POST.get('roster_semester_id', '')
        submitted_stamp = request.POST.get('roster_semester_updated_at', '')
        formset = RosterEditFormSet(request.POST, prefix='roster')
        add_formset = RosterAddFormSet(request.POST, prefix='roster_add')
        if formset.is_valid() and add_formset.is_valid():
            buffer = self._build_buffer(formset, add_formset, submitted_semester_id, submitted_stamp)
            try:
                apply_roster_edits(buffer, viewing_semester=semester, requesting_admin=request.user)
            except (WrongViewingSemesterError, StaleRosterSemesterError, SelfRemovalError) as error:
                messages.error(request, str(error))
                return _render_roster_edit(
                    request, semester, formset, add_formset,
                    semester_id=submitted_semester_id, stamp=submitted_stamp, status=200,
                )
            messages.success(request, 'Roster updated.')
            return redirect('scheduling:members')
        return _render_roster_edit(
            request, semester, formset, add_formset,
            semester_id=submitted_semester_id, stamp=submitted_stamp, status=200,
        )

    def _build_buffer(self, formset, add_formset, submitted_semester_id, submitted_stamp):
        """Turn the valid edit and add-list formsets into one RosterEditBuffer, carrying the Semester state they were rendered against.

        `submitted_semester_id`/`submitted_stamp` are the hidden fields
        stamped at render time, not the live session's viewing Semester —
        `apply_roster_edits()` is the one place that compares them against
        current state, raising `WrongViewingSemesterError`/
        `StaleRosterSemesterError` if either has moved since. A ticked
        add-list row becomes an ordinary `RosterEditEntry` alongside the
        edit table's rows: `apply_roster_edits()` get-or-creates the
        Membership either way, so an add is indistinguishable from an edit
        of an existing row by the time it reaches the service layer. Not
        `_build_roster_buffer()` (issue #228): that shared function only
        covers the edit table, which is all Preview fires against — Save
        is the only surface that also has to fold in the add list.
        """
        person_ids = {row['person_id'] for row in formset.cleaned_data}
        person_ids |= {row['person_id'] for row in add_formset.cleaned_data if row['add']}
        people_by_id = Person.objects.in_bulk(person_ids)
        entries = []
        removed_person_ids = set()
        for row in formset.cleaned_data:
            person = people_by_id.get(row['person_id'])
            if person is None:
                continue
            if row['remove']:
                removed_person_ids.add(person.pk)
                continue
            entries.append(RosterEditEntry(
                person=person, name=row['name'], role_ids=frozenset(role.pk for role in row['roles']),
            ))
        for row in add_formset.cleaned_data:
            if not row['add']:
                continue
            person = people_by_id.get(row['person_id'])
            if person is None:
                continue
            entries.append(RosterEditEntry(
                person=person, name=person.name, role_ids=frozenset(role.pk for role in row['roles']),
            ))
        return RosterEditBuffer(
            semester_id=_parse_roster_int(submitted_semester_id),
            semester_updated_at=parse_datetime(submitted_stamp) or timezone.now(),
            entries=entries,
            removed_person_ids=frozenset(removed_person_ids),
        )

    def _render_read(self, request, semester):
        """Render read mode: the bare roster fragment for htmx, the full page otherwise."""
        context = {
            'semester': semester,
            'members': roster_for(_scoped_to_viewing_semester(Membership, semester)),
        }
        template = self.read_fragment_template_name if _is_htmx(request) else self.template_name
        return render(request, template, context)


class RosterInviteView(AdminRequiredMixin, View):
    """`/members/invite/`: the Roster editor's "Invite someone new" affordance, one of two writes that escape the Save Buffer (issue #230).

    Reuses `invite_person()` unchanged, including its atomicity (the
    set-password email sends *inside* the transaction, so a delivery
    failure rolls the `Person` row back and leaves the address free for a
    retry) — then rosters the new Person into the viewing Semester as a
    second write in the same outer transaction. Both commit and the email
    sends immediately, independent of the Roster edit Buffer: discarding
    that Buffer afterward cannot un-invent either write. `RosterInviteForm`
    rejects an email already belonging to a Person before any write is
    attempted, so a collision never reaches `invite_person()` and never
    re-sends a set-password link to somebody who already has one.
    """

    def post(self, request):
        """Validate the invite form, invite and roster the new Person immediately, and redirect back into edit mode."""
        semester = get_viewing_semester(request)
        if semester is None:
            return redirect('scheduling:members')
        form = RosterInviteForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                person = invite_person(name=form.cleaned_data['name'], email=form.cleaned_data['email'])
                Membership.objects.create(person=person, semester=semester)
            messages.success(request, f"Invited {form.cleaned_data['email']} and added them to the Roster.")
            return redirect(f"{reverse('scheduling:members')}?mode=edit")
        formset = RosterEditFormSet(initial=_edit_initial(semester), prefix='roster')
        add_formset = RosterAddFormSet(initial=_add_initial(semester), prefix='roster_add')
        return _render_roster_edit(
            request, semester, formset, add_formset,
            semester_id=semester.pk, stamp=semester.updated_at.isoformat(),
            invite_form=form,
        )


class RosterAddRoleView(AdminRequiredMixin, View):
    """`/members/roles/add/`: the Roster editor's inline "Add Role" control, the other write that escapes the Save Buffer (issue #230).

    Calls `create_or_reactivate_role()` (issue #225) unchanged — the single
    Role-creation path — and commits immediately, outside the Buffer:
    discarding the Buffer afterward must not un-invent a Role a row already
    ticked. Swaps only the triggering row's Role checkbox group, rebuilt
    from the same `RosterEditRowForm`/`RosterAddRowForm` the live formset
    renders (so field names/ids and any htmx wiring on the widget stay
    identical), never the row's other cells. There is no matching "remove"
    endpoint here: retiring a Role stays a deliberate act in the Django
    admin.
    """

    template_name = 'scheduling/_roster_role_checkboxes.html'

    def post(self, request):
        """Create/reactivate the named Role, tick it onto the triggering row, and re-render that row's checkbox group."""
        form = RosterAddRoleForm(request.POST)
        if not form.is_valid():
            return HttpResponseBadRequest()
        kind = form.cleaned_data['kind']
        prefix = form.cleaned_data['prefix']
        result = create_or_reactivate_role(form.cleaned_data['role_name'])
        ticked_ids = {_parse_roster_int(value) for value in request.POST.getlist(f'{prefix}-roles')}
        ticked_ids.discard(-1)
        ticked_ids.add(result.role.pk)
        row_form_class = RosterEditRowForm if kind == 'roster' else RosterAddRowForm
        row_form = row_form_class(prefix=prefix, initial={'roles': sorted(ticked_ids)})
        return render(request, self.template_name, {
            'field': row_form['roles'],
            'message': self._message_for(result),
        })

    def _message_for(self, result):
        """Return the admin-facing message naming how create_or_reactivate_role() resolved the Role."""
        if result.created:
            return f'Added "{result.role.name}".'
        if result.reactivated:
            return f'Reactivated "{result.role.name}".'
        return f'Matched existing "{result.role.name}".'


class RosterImportView(AdminRequiredMixin, View):
    """`/members/import/`: prefill the Roster add list's ticks from the prior Semester's Roster, writing nothing (issue #229).

    A sibling read of `MembersView`'s edit mode, not a mutation: it swaps
    only the add-list fragment (`hx-target="#roster-add-list"`), so the
    edit table above it is left alone. The add-list button carries
    `hx-include="#roster-add-list"`, so any row an admin already
    hand-ticked (or hand-unticked, for someone the import proposal also
    covers) reaches this view as `request.GET` and is read back via
    `_submitted_add_state_by_person_id()` — Import overlays the prior
    Semester's proposal onto that state rather than replacing it outright.
    `apply_roster_edits()`'s later "Save Changes" POST is the only write
    path either surface ever commits through — pressing Import again
    simply re-derives the same proposal over whatever is currently ticked,
    and, per issue #225, `import_roster_from_semester()` returns copied
    Role values, never references into the prior Semester's rows.
    """

    template_name = 'scheduling/_members_add_list.html'

    def get(self, request):
        """Render the add-list fragment with the import proposal overlaid on any already-submitted ticks/Roles."""
        semester = get_viewing_semester(request)
        if semester is None:
            return HttpResponseForbidden()
        proposal = import_roster_from_semester(semester)
        imported_roles_by_person_id = {imported.person.pk: imported.roles for imported in proposal.people}
        current_state_by_person_id = _submitted_add_state_by_person_id(request)
        add_formset = RosterAddFormSet(
            initial=_add_initial(semester, imported_roles_by_person_id, current_state_by_person_id),
            prefix='roster_add',
        )
        return render(request, self.template_name, {
            'add_formset': add_formset,
            'add_rows': _add_rows(add_formset),
            'import_source_semester': proposal.source_semester,
        })


class RosterPreviewView(PreviewMixin, AdminRequiredMixin, View):
    """`/members/preview/`: an admin's Preview of a Roster edit Buffer, computed without committing it (issue #228, ADR 0008).

    A POST-only sibling of `/members/`'s Save endpoint, bound to the exact
    same `RosterEditFormSet` and the exact same POST body — same field
    names, management form and hidden staleness fields — as the Save
    endpoint, per ADR 0008's "one parsing and validation path" rule.
    `PreviewMixin` owns the savepoint/rollback shape; this view supplies
    only the form and the `preview_roster_edits()` call. Fired by the edit
    table's Role checkboxes and `remove` toggles on `change` (never by
    typing in the name field), targeting the `#roster-fallout` region with
    an `outerHTML` swap synced against any other in-flight Preview.
    """

    template_name = 'scheduling/_roster_preview.html'

    def run_preview(self, request):
        """Bind the Roster edit formset and render its Fallout, or a Validation Error banner if it doesn't bind."""
        semester = get_viewing_semester(request)
        if semester is None:
            return render(request, self.template_name, {
                'formset_errors': ['No Semester is being edited.'],
                'fallout': None,
            })
        formset = RosterEditFormSet(request.POST, prefix='roster')
        if not formset.is_valid():
            return render(request, self.template_name, {
                'formset_errors': self._formset_errors(formset),
                'fallout': None,
            })
        submitted_semester_id = request.POST.get('roster_semester_id', '')
        submitted_stamp = request.POST.get('roster_semester_updated_at', '')
        buffer = _build_roster_buffer(formset, submitted_semester_id, submitted_stamp)
        fallout = preview_roster_edits(buffer, viewing_semester=semester, requesting_admin=request.user)
        return render(request, self.template_name, {'formset_errors': [], 'fallout': fallout})

    def _formset_errors(self, formset):
        """Return a flat list of 'Row N (field): message' strings naming an invalid formset's per-row errors."""
        errors = []
        for index, form in enumerate(formset.forms):
            for field, field_errors in form.errors.items():
                for message in field_errors:
                    errors.append(f'Row {index + 1} ({field}): {message}')
        errors.extend(formset.non_form_errors())
        return errors


class RosterRemovalConfirmView(PreviewMixin, AdminRequiredMixin, View):
    """`/members/preview/confirm-removal/`: the one-dialog-per-batch removal confirmation (issue #228, ADR 0008).

    Runs the same `preview_roster_edits()` computation as the on-page
    Preview (fetched by the edit table's Save button, only when at least
    one `remove` checkbox is checked), so the confirm dialog can never
    disagree with what the Preview already showed. Renders just the
    removal-related subset: each removed Person's name and email, plus the
    batch's loud Fallout lines.
    """

    template_name = 'scheduling/_roster_removal_confirm.html'

    def run_preview(self, request):
        """Bind the Roster edit formset and render the removal confirmation dialog's body."""
        semester = get_viewing_semester(request)
        if semester is None:
            return HttpResponseBadRequest('No Semester is being edited.')
        formset = RosterEditFormSet(request.POST, prefix='roster')
        if not formset.is_valid():
            return HttpResponseBadRequest('The Roster edit Buffer is invalid.')
        submitted_semester_id = request.POST.get('roster_semester_id', '')
        submitted_stamp = request.POST.get('roster_semester_updated_at', '')
        buffer = _build_roster_buffer(formset, submitted_semester_id, submitted_stamp)
        fallout = preview_roster_edits(buffer, viewing_semester=semester, requesting_admin=request.user)
        return render(request, self.template_name, {'fallout': fallout})


class MemberDetailView(BaseView, View):
    """`/members/<int:pk>/`: one Person's page for the viewing Semester (issue #138).

    Two rendering modes, and no third: read-only for a teammate's pk,
    editable in place for `request.user.pk` **or an admin viewing anyone's
    pk** (issue #232). The editable mode carries the always-inline
    `MembershipRolesForm`, with no edit toggle, and is the only mode with
    any mutation surface at all — a POST from a non-admin to another
    Person's pk is a 404, not a rejected form. This is the only admin write
    on this page: no batch, no Preview, and removal stays list-only on
    `/members/`.

    Every field this renders has an explicit verdict in
    `docs/person-page-visibility.md`; ADR 0005 keeps Conflict and derived
    attendance data off the page for everyone, its owner and an admin
    viewer included, because the boundary is drawn around the surface
    rather than the viewer.

    A Person with no viewing-Semester `Membership` 404s — except your own
    pk, which builds an unsaved `Membership` instead, so a newly-invited
    member can declare Roles before an admin rosters them. With no current
    Semester at all nobody holds such a Membership, so a teammate's pk
    404s by the same rule while your own page renders an empty state.
    """

    template_name = 'scheduling/member_detail.html'

    def get(self, request, pk):
        """Render `pk`'s page: read-only for a teammate, or editable for your own pk or an admin's."""
        semester = get_viewing_semester(self.request)
        person = self._get_person_or_404(request, pk, semester)
        return render(request, self.template_name, self._build_context(request, person, semester))

    def post(self, request, pk):
        """Persist declared Roles for your own pk or, if you're an admin, anyone's; 404 otherwise.

        A teammate's page has no mutation surface for a non-admin viewer —
        the guard 404s rather than rendering a rejected form, exactly as it
        did before an admin could reach this branch at all.
        """
        if pk != request.user.pk and not request.user.is_admin:
            raise Http404("A member can only edit their own declared Roles unless they're an admin.")
        semester = get_viewing_semester(request)
        person = self._get_person_or_404(request, pk, semester)
        if semester is None:
            return render(request, self.template_name, self._build_context(request, person, semester))
        membership = self._get_or_build_membership(person, semester)
        form = MembershipRolesForm(request.POST, instance=membership)
        if form.is_valid():
            form.instance = self._membership_for_writing(person, semester)
            form.save()
            messages.success(request, 'Profile updated.')
            return redirect('scheduling:member-detail', pk=pk)
        context = self._build_context(request, person, semester)
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
        """Build the render context for `person`, adding the inline Roles form on your own page or an admin's view of anyone's."""
        is_self = person.pk == request.user.pk
        context = {'person': person, 'is_self': is_self, 'semester': semester, 'membership': None}
        if semester is None:
            return context
        membership = self._get_or_build_membership(person, semester)
        context['membership'] = membership
        context['declared_roles'] = declared_roles_for(membership)
        context['assignments'] = assigned_songs_for(person, semester) if membership.pk else []
        if is_self or request.user.is_admin:
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


_CONFLICT_STATUS_TEXT = {
    Conflict.PENDING: 'Awaiting a decision.',
    Conflict.APPROVED: 'Approved.',
    Conflict.REJECTED: 'Rejected.',
}
"""What the owner reads as their own adjudication outcome (issues #189, #190).

Spelled out rather than taken from `get_status_display()` so `pending`
cannot be misread as `rejected`: "Awaiting a decision." says nobody has
looked yet, where a bare "Pending" beside a bare "Rejected" reads as two
shades of the same no. Rendered only on the owner's own row — nobody
else sees any of it, an admin viewing this page included (ADR 0005).
"""


def _conflict_prefix(rehearsal):
    """Return the per-rehearsal form prefix for `rehearsal`'s availability declare/edit form.

    One prefix, not the separate declare/edit pair the Conflicts page
    needed: a Rehearsal now carries exactly one availability block, whose
    form declares a first Conflict or edits the existing one through the
    same endpoint (issue #190).
    """
    return f'conflict-{rehearsal.pk}'


def _declared_time_initial(row):
    """Return {'arrival_time': ...} or {'departure_time': ...} to pre-fill an edit form from `row`, or {}."""
    if row.declaration_type == CONFLICT_LATE_ARRIVAL:
        return {'arrival_time': row.declared_time}
    if row.declaration_type == CONFLICT_EARLY_DEPARTURE:
        return {'departure_time': row.declared_time}
    return {}


def _availability_for(rehearsal, conflict_row, today, error_rehearsal=None, error_form=None):
    """Return one Rehearsal's "Your availability" block for the viewer (issue #190).

    `conflict_row` is that Rehearsal's `ConflictHistoryRow` from
    `conflict_rows_by_rehearsal()`, or None when the viewer has declared
    nothing against it. The block carries the declaration, the owner's own
    adjudication verdict and the admin's note, and — on a future,
    non-Dress Rehearsal only — the form that declares or edits it.

    A past Rehearsal keeps its declaration visible but gets no form, and
    the Dress Rehearsal gets the mandatory-attendance line in place of one
    (ADR 0006), so a member reads the rule rather than hitting an error.
    Neither omission is the enforcement: `ConflictDeclareView` and
    `ConflictDeleteView` re-check server-side.
    """
    is_future = rehearsal.date >= today
    conflict = conflict_row.conflict if conflict_row is not None else None
    availability = {
        'rehearsal': rehearsal,
        'conflict': conflict,
        'type_label': conflict_row.type_label if conflict_row is not None else None,
        'declared_time': conflict_row.declared_time if conflict_row is not None else None,
        'status_text': _CONFLICT_STATUS_TEXT.get(conflict.status) if conflict is not None else None,
        'is_future': is_future,
        'is_dress': rehearsal.is_full_setlist,
        'is_editable': is_future and not rehearsal.is_full_setlist,
        'form': None,
    }
    if not availability['is_editable']:
        return availability
    if error_rehearsal is not None and error_rehearsal.pk == rehearsal.pk:
        availability['form'] = error_form
    else:
        availability['form'] = DeclareConflictForm(
            rehearsal=rehearsal,
            initial=_declaration_initial(conflict_row),
            prefix=_conflict_prefix(rehearsal),
        )
    return availability


def _declaration_initial(conflict_row):
    """Return the initial data pre-filling an edit of `conflict_row`'s declaration, or {} for a fresh declare form."""
    if conflict_row is None:
        return {}
    return {
        'declaration_type': conflict_row.declaration_type,
        'reason': conflict_row.conflict.reason,
        **_declared_time_initial(conflict_row),
    }


def _declarable_rehearsal_or_404(request, rehearsal_id):
    """Return the viewing Semester's Rehearsal that `rehearsal_id` names and may be declared against, or 404.

    `future_rehearsals_for()` is the single definition of "declarable" —
    dated today or later, and never the Dress Rehearsal (ADR 0006) — so a
    hand-crafted POST naming a past Rehearsal or the Dress Rehearsal 404s
    here rather than reaching `declare_conflict()`'s ValueError as a 500.
    The template omitting the form on those rows is not the enforcement.
    """
    rehearsals = {rehearsal.pk: rehearsal for rehearsal in future_rehearsals_for(get_viewing_semester(request))}
    rehearsal = rehearsals.get(rehearsal_id)
    if rehearsal is None:
        raise Http404('No Rehearsal here can be declared against.')
    return rehearsal


def _future_rehearsal_with_conflict_or_404(request, rehearsal_id, action):
    """Return the viewing Semester's future Rehearsal with an existing Conflict for request.user, or 404.

    Backs the delete endpoint: the template hiding Delete on a past row is
    not the actual enforcement, so date and ownership are re-checked here
    regardless of request origin (issues #99, #190). `action` ('deleted')
    only shapes the 404 message.
    """
    rehearsal = get_object_or_404(
        _scoped_to_viewing_semester(Rehearsal, get_viewing_semester(request)), pk=rehearsal_id,
    )
    if not Conflict.objects.filter(person=request.user, rehearsal=rehearsal).exists():
        raise Http404('No existing Conflict for this Rehearsal.')
    if rehearsal.date < timezone.localdate():
        raise Http404(f'Past Rehearsals cannot be {action}.')
    return rehearsal


def _schedule_redirect(request, rehearsal):
    """Redirect back to whichever `/schedule/` view the submission came from, after a successful write.

    The hidden `view` field decides, run through `_resolve_view_mode()`, so
    a crafted value can only ever resolve to one of the page's own two
    views — never an arbitrary URL.
    """
    url = reverse('scheduling:schedule')
    if _resolve_view_mode(request.POST.get('view')) == VIEW_ALL:
        return redirect(f'{url}?view={VIEW_ALL}')
    return redirect(f'{url}?rehearsal={rehearsal.pk}')


class ConflictDeclareView(BaseView, View):
    """`/schedule/<rehearsal_id>/conflict/`: declares or edits `request.user`'s Conflict for one Rehearsal (issue #190).

    The write endpoint behind the availability block's inline form,
    replacing the deleted `/me/conflicts/` POST and its separate edit
    route. `declare_conflict()` is `update_or_create`-shaped against the
    `(person, rehearsal)`-unique Conflict, so a first submission and a
    later correction are the same call and never a second row — which is
    also why a rejected declaration stays editable rather than having to
    be re-declared.
    """

    template_name = 'scheduling/schedule.html'

    def post(self, request, rehearsal_id):
        """Persist the submitted declaration against `rehearsal_id`, or re-render the page with the form's errors in place."""
        rehearsal = _declarable_rehearsal_or_404(request, rehearsal_id)
        form = DeclareConflictForm(request.POST, rehearsal=rehearsal, prefix=_conflict_prefix(rehearsal))
        if form.is_valid():
            declare_conflict(
                person=request.user,
                rehearsal=rehearsal,
                declaration_type=form.cleaned_data['declaration_type'],
                declared_time=form.declared_time,
                reason=form.cleaned_data['reason'],
            )
            messages.success(request, 'Availability updated.')
            return _schedule_redirect(request, rehearsal)
        view_mode = _resolve_view_mode(request.POST.get('view'))
        context = _build_schedule_context(
            request,
            get_viewing_semester(request),
            view_mode,
            rehearsal if view_mode == VIEW_NEXT else None,
            error_rehearsal=rehearsal,
            error_form=form,
        )
        return render(request, self.template_name, context)


class ConflictDeleteView(BaseView, View):
    """`/schedule/<rehearsal_id>/conflict/delete/`: withdraws `request.user`'s Conflict for one Rehearsal (issue #190).

    Future-only and enforced server-side, so a plan that fell through
    leaves no false absence standing while a past declaration stays put as
    a record. Nothing else deletes a Conflict — an admin's rejection
    preserves it (issue #189), so this is the owner's own withdrawal and
    only that.
    """

    def post(self, request, rehearsal_id):
        """Delete request.user's Conflict (and any ConflictWindows, via cascade) for this future Rehearsal, or 404."""
        rehearsal = _future_rehearsal_with_conflict_or_404(request, rehearsal_id, action='deleted')
        Conflict.objects.filter(person=request.user, rehearsal=rehearsal).delete()
        messages.success(request, 'Conflict removed.')
        return _schedule_redirect(request, rehearsal)


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


TIMING_DEFAULT_CONSTANTS = {
    'default_rehearsal_duration_minutes': 240,
    'default_song_slot_count': 6,
    'default_setup_grace_minutes': 10,
    'default_teardown_grace_minutes': 10,
    'default_arrival_buffer_minutes': 5,
    'default_departure_buffer_minutes': 5,
}
"""The wizard's timing-default fallback when there is no prior Semester to prefill from (issue #198 §6, #200).

A UI convenience belonging to the wizard, not the domain: `create_semester()`
takes whatever timing defaults its caller passes and has no fallback of its
own.
"""

_SEMESTER_NAME_PATTERN = re.compile(r'^(Fall|Spring)\s+(\d{4})$', re.IGNORECASE)


def _suggested_semester_name(prior_semester):
    """Return a suggested next name parsed from `prior_semester`'s name, or '' when it can't be inferred.

    A two-line UI convenience with zero downstream authority (issue #200,
    mirroring #198 decision #4's date-range prefill): "Fall <year>"
    suggests "Spring <year + 1>" and vice versa. Anything else — no prior
    Semester, or a name that doesn't parse — leaves the field blank rather
    than guessing or erroring.
    """
    if prior_semester is None:
        return ''
    match = _SEMESTER_NAME_PATTERN.match(prior_semester.name.strip())
    if not match:
        return ''
    season, year = match.group(1).capitalize(), int(match.group(2))
    if season == 'Fall':
        return f'Spring {year + 1}'
    return f'Fall {year}'


class SemesterSetupView(AdminRequiredMixin, View):
    """`/manage/semesters/setup/`: Semester setup steps 1-2, the wizard's only required screen (issue #200).

    A name plus the six timing defaults in one submission: GET prefills
    both from the most recently created Semester (falling back to
    `TIMING_DEFAULT_CONSTANTS` when there is none), and POST creates the
    draft immediately via `create_semester()`, switches this admin's
    session selection to it, and redirects to the finish screen. Nothing
    here is held hostage to finishing the rest of the wizard — steps 3-5
    (roster, setlist, rehearsal dates) are separate, independently
    skippable tickets not yet built, so this screen goes straight from
    submit to finish.

    Reached two ways with the same form and the same code path: a direct
    GET renders the full page (the no-JS fallback, and the bookmarkable
    entry point), while the Home panel's Alpine component fetches this
    same URL with `X-Requested-With: XMLHttpRequest` and gets back only
    the form fragment to show in its modal — never a second template for
    the step (issue #198 §14's "over server-rendered step partials").
    """

    template_name = 'scheduling/semester_setup.html'
    fragment_template_name = 'scheduling/_semester_setup_form.html'

    def _render(self, request, form):
        """Render the fragment alone for a modal fetch, or the full page for a direct GET/POST."""
        template_name = self.fragment_template_name if self._is_fragment_request(request) else self.template_name
        return render(request, template_name, {'form': form})

    def _is_fragment_request(self, request):
        """Return whether `request` is the Home panel's modal fetch, asking for the form fragment alone."""
        return request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def get(self, request):
        """Render the form, prefilled from the most recently created Semester if one exists."""
        prior_semester = Semester.objects.order_by('-created_at', '-id').first()
        initial = {'name': _suggested_semester_name(prior_semester)}
        if prior_semester is not None:
            for field in TIMING_DEFAULT_CONSTANTS:
                initial[field] = getattr(prior_semester, field)
        else:
            initial.update(TIMING_DEFAULT_CONSTANTS)
        form = SemesterSetupForm(initial=initial)
        return self._render(request, form)

    def post(self, request):
        """Validate and create the draft Semester, switch the session's viewing Semester, and redirect to finish."""
        form = SemesterSetupForm(request.POST)
        if form.is_valid():
            try:
                semester = create_semester(name=form.cleaned_data['name'], **form.timing_defaults())
            except InvalidSemesterNameError as error:
                form.add_error('name', str(error))
            else:
                set_viewing_semester(request, semester)
                messages.success(request, f'{semester.name} created as a draft.')
                return redirect('scheduling:manage-semester-setup-finish', pk=semester.pk)
        return self._render(request, form)


class SemesterSetupFinishView(AdminRequiredMixin, View):
    """`/manage/semesters/setup/<pk>/finish/`: Semester setup's finish screen (issue #200).

    Names what's still empty on the new draft — computed live from
    `semester_deletion_summary()`'s counts, never stored, per #198 decision
    #10's rejection of any persisted per-step completion state. There is no
    "resume setup": an abandoned draft is finished from the ordinary tabs,
    and this screen's only job is to hand the admin back to Home having
    seen what those tabs still have to do.
    """

    template_name = 'scheduling/semester_setup_finish.html'

    def get(self, request, pk):
        """Render the new Semester's still-empty summary, or 404 if it's since been deleted."""
        semester = get_object_or_404(Semester, pk=pk)
        summary = semester_deletion_summary(semester)
        return render(request, self.template_name, {
            'semester': semester,
            'roster_is_empty': summary.member_count == 0,
            'setlist_is_empty': summary.song_count == 0,
            'schedule_is_empty': summary.rehearsal_count == 0,
        })


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


class ConflictAdjudicationIndexView(AdminRequiredMixin, TemplateView):
    """`/manage/conflicts/`: an admin's starting point for adjudicating Conflicts (issue #191, ADR 0005).

    Lists the viewing Semester's future, non-Dress Rehearsals — the same
    "declarable" set `future_rehearsals_for()` computes — each carrying its
    own pending-Conflict count so an admin can see where the work is
    without opening every date. A Rehearsal with zero Conflicts still
    appears: absence isn't how "nothing to do" gets communicated here.
    """

    template_name = 'scheduling/manage_conflicts.html'

    def get_context_data(self, **kwargs):
        """Add the viewing Semester and its adjudication-index rows."""
        context = super().get_context_data(**kwargs)
        semester = get_viewing_semester(self.request)
        context['semester'] = semester
        context['rows'] = conflict_adjudication_index_for(semester) if semester else []
        return context


class ConflictAdjudicationDetailView(AdminRequiredMixin, View):
    """`/manage/conflicts/<rehearsal_id>/`: one Rehearsal's Conflicts, decided together under one Save Changes (issue #192).

    Reachable from the index and from an unconditional link on
    `/schedule/` (issue #191). Every row on the Rehearsal is editable in
    the same request — including a row already approved or rejected, in
    either direction — and one Save Changes commits the whole table
    atomically via `apply_adjudications()`; leaving without saving writes
    nothing, since GET never touches the database. A validation failure
    (an over-long note, a Conflict id from another Rehearsal, a stale or
    mismatched Semester stamp) writes nothing and re-renders with every
    submitted decision and note preserved.
    """

    template_name = 'scheduling/manage_conflicts_detail.html'

    def get(self, request, rehearsal_id):
        """Render the target Rehearsal's Conflicts, scoped to the viewing Semester (404 outside it)."""
        semester = get_viewing_semester(request)
        rehearsal = get_object_or_404(_scoped_to_viewing_semester(Rehearsal, semester), pk=rehearsal_id)
        rows = conflict_adjudication_rows_for(rehearsal)
        formset = AdjudicationFormSet(initial=self._initial(rows), prefix='adjudication')
        return self._render(request, semester, rehearsal, rows, formset)

    def post(self, request, rehearsal_id):
        """Validate and apply the whole adjudication Buffer atomically, or re-render with errors."""
        semester = get_viewing_semester(request)
        rehearsal = get_object_or_404(_scoped_to_viewing_semester(Rehearsal, semester), pk=rehearsal_id)
        rows = conflict_adjudication_rows_for(rehearsal)
        formset = AdjudicationFormSet(request.POST, prefix='adjudication')
        submitted_semester_id = request.POST.get('semester_id', '')
        submitted_stamp = request.POST.get('semester_updated_at', '')
        if formset.is_valid():
            buffer = self._build_buffer(rehearsal, formset, submitted_semester_id, submitted_stamp)
            try:
                apply_adjudications(buffer, viewing_semester=semester)
            except (WrongAdjudicationSemesterError, StaleAdjudicationSemesterError, UnknownConflictError) as error:
                messages.error(request, str(error))
                return self._render(
                    request, semester, rehearsal, rows, formset,
                    semester_id=submitted_semester_id, stamp=submitted_stamp, status=200,
                )
            messages.success(request, 'Conflicts updated.')
            return redirect('scheduling:manage-conflicts-detail', rehearsal_id=rehearsal.pk)
        return self._render(
            request, semester, rehearsal, rows, formset,
            semester_id=submitted_semester_id, stamp=submitted_stamp, status=200,
        )

    def _initial(self, rows):
        """Build the formset's initial data: one row per Conflict, at its current status with an empty note."""
        return [
            {'conflict_id': row.conflict.pk, 'status': row.status, 'note': ''}
            for row in rows
        ]

    def _build_buffer(self, rehearsal, formset, submitted_semester_id, submitted_stamp):
        """Turn a valid AdjudicationFormSet into an AdjudicationBuffer, carrying the Semester state it was rendered against.

        `submitted_semester_id`/`submitted_stamp` are the hidden fields
        stamped at render time, not the live session's viewing Semester —
        `apply_adjudications()` is the one place that compares them
        against current state, raising `WrongAdjudicationSemesterError`/
        `StaleAdjudicationSemesterError` if either has moved since.
        """
        entries = [
            AdjudicationEntry(
                conflict_id=row['conflict_id'], status=row['status'], note=row['note'],
            )
            for row in formset.cleaned_data
        ]
        return AdjudicationBuffer(
            rehearsal_id=rehearsal.pk,
            semester_id=_parse_roster_int(submitted_semester_id),
            semester_updated_at=parse_datetime(submitted_stamp) or timezone.now(),
            entries=entries,
        )

    def _render(self, request, semester, rehearsal, rows, formset, semester_id=None, stamp=None, status=200):
        """Render the table, pairing each row with its formset form by shared position."""
        return render(request, self.template_name, {
            'semester': semester,
            'rehearsal': rehearsal,
            'pairs': list(zip(rows, formset.forms, strict=True)),
            'management_form': formset.management_form,
            'semester_id': semester.pk if semester_id is None else semester_id,
            'stamp': semester.updated_at.isoformat() if stamp is None else stamp,
        }, status=status)
