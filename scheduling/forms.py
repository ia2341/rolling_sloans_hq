"""Member-facing (issues #57, #58, #61) and admin-facing (issue #60) forms."""

from datetime import datetime, timedelta
from typing import ClassVar

from django import forms
from django.db import transaction
from django.urls import reverse_lazy
from django.utils import timezone

from identity.models import Person
from scheduling.fields import SongLengthField
from scheduling.models import (
    Conflict,
    Membership,
    MembershipRole,
    Rehearsal,
    RehearsalSong,
    Role,
    Song,
)
from scheduling.services import (
    CONFLICT_DECLARATION_CHOICES,
    CONFLICT_EARLY_DEPARTURE,
    CONFLICT_LATE_ARRIVAL,
    REHEARSAL_OVERRIDE_FIELDS,
)
from scheduling.spotify import SpotifyImportError, extract_playlist_id


class MembershipRolesForm(forms.ModelForm):
    """Edits a Membership's declared Roles for its Semester.

    Bound to `Membership` for the POST/redirect/GET convention, but the
    only field is `roles`, a virtual multi-select synced against
    `MembershipRole` rows in `save()` since that's a through model with no
    other data of its own.
    """

    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.filter(is_active=True),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Membership
        fields: ClassVar[list[str]] = []

    def __init__(self, *args, **kwargs):
        """Seed `roles`' initial value from the instance's current MembershipRoles, if it's saved."""
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['roles'].initial = Role.objects.filter(membershiprole__membership=self.instance)

    def save(self, commit=True):
        """Persist the Membership (creating it on first save) and sync its MembershipRole rows atomically."""
        if commit:
            with transaction.atomic():
                membership = super().save(commit=True)
                self._sync_roles(membership)
        else:
            membership = super().save(commit=False)
            self.save_m2m = lambda: self._sync_roles(membership)
        return membership

    def _sync_roles(self, membership):
        """Replace membership's MembershipRole rows with exactly the submitted roles."""
        selected_roles = self.cleaned_data['roles']
        MembershipRole.objects.filter(membership=membership).exclude(role__in=selected_roles).delete()
        existing_role_ids = set(
            MembershipRole.objects.filter(membership=membership).values_list('role_id', flat=True)
        )
        for role in selected_roles:
            if role.id not in existing_role_ids:
                MembershipRole.objects.create(membership=membership, role=role)


class DeclareConflictForm(forms.Form):
    """One Conflicts-page row's inline conflict declaration: a fresh one, or an edit of an existing one (issues #98, #99).

    Not a ModelForm: one submission maps to a Conflict plus an optional
    ConflictWindow across three different shapes (see
    scheduling.services.declare_conflict), with no single model instance to
    bind to. Carries separate arrival_time/departure_time fields, rather
    than one generic time field, so the page's conditional show/hide can
    key off which one applies to the selected declaration_type.
    """

    declaration_type = forms.ChoiceField(choices=CONFLICT_DECLARATION_CHOICES, widget=forms.RadioSelect)
    arrival_time = forms.TimeField(required=False, label='Arrive late at')
    departure_time = forms.TimeField(required=False, label='Leave early at')
    reason = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, rehearsal=None, **kwargs):
        """Stash `rehearsal` for span validation in clean()."""
        super().__init__(*args, **kwargs)
        self.rehearsal = rehearsal

    def clean(self):
        """Require the matching time field for late_arrival/early_departure, and that it falls within the Rehearsal's span."""
        cleaned_data = super().clean()
        declaration_type = cleaned_data.get('declaration_type')
        if declaration_type == CONFLICT_LATE_ARRIVAL:
            self._require_arrival_time(cleaned_data)
        if declaration_type == CONFLICT_EARLY_DEPARTURE:
            self._require_departure_time(cleaned_data)
        return cleaned_data

    def _require_arrival_time(self, cleaned_data):
        """Add a field error if arrival_time is blank, or set but not strictly after the Rehearsal's start (matching the model's strict-inequality rule)."""
        time_value = cleaned_data.get('arrival_time')
        if not time_value:
            self.add_error('arrival_time', 'Enter the time you will arrive.')
        elif self.rehearsal and not (self.rehearsal.start_time < time_value <= self.rehearsal.end_time):
            self.add_error('arrival_time', "Must fall within the Rehearsal's time span, after it starts.")

    def _require_departure_time(self, cleaned_data):
        """Add a field error if departure_time is blank, or set but not strictly before the Rehearsal's end (matching the model's strict-inequality rule)."""
        time_value = cleaned_data.get('departure_time')
        if not time_value:
            self.add_error('departure_time', 'Enter the time you will leave.')
        elif self.rehearsal and not (self.rehearsal.start_time <= time_value < self.rehearsal.end_time):
            self.add_error('departure_time', "Must fall within the Rehearsal's time span, before it ends.")

    @property
    def declared_time(self):
        """Return whichever of arrival_time/departure_time applies to the selected declaration_type, else None."""
        declaration_type = self.cleaned_data.get('declaration_type')
        if declaration_type == CONFLICT_LATE_ARRIVAL:
            return self.cleaned_data.get('arrival_time')
        if declaration_type == CONFLICT_EARLY_DEPARTURE:
            return self.cleaned_data.get('departure_time')
        return None


class RehearsalForm(forms.ModelForm):
    """Creates/edits a Rehearsal within its (already-set) Semester (issue #60).

    `semester` is deliberately excluded: the view sets it on the instance
    before binding (a fresh Rehearsal for create, the existing one for
    edit), so it's never attacker-controlled via POST data.

    There is deliberately no `clean()` here guarding the flip to
    `is_full_setlist=True` on a Rehearsal with declared Conflicts (issue
    #150): `Rehearsal.clean()` owns that rule, and `_post_clean()` surfaces
    it as an `is_full_setlist` field error on this form. Duplicating it
    would render the same message twice, since `Model.full_clean()` doesn't
    filter `clean()`'s errors against fields the form already flagged.
    """

    class Meta:
        model = Rehearsal
        fields: ClassVar[list[str]] = [
            'date', 'start_time', 'end_time', 'setup_grace_minutes', 'teardown_grace_minutes', 'is_full_setlist',
        ]


class RehearsalEditRowForm(forms.ModelForm):
    """One row of `/schedule/edit/`'s grid: date, times, the Dress toggle, and the four grace/buffer overrides (issue #219).

    `semester` is excluded from `Meta.fields` for the same reason
    `RehearsalForm` excludes it — it travels as a constructor kwarg instead,
    used here for the override placeholders and the derived-end-time check,
    and applied to new instances by the view before `save()`. `end_time`
    and the four overrides are all optional: a blank override means
    "inherit the Semester default" (rendered as placeholder text by
    `__init__`, never a filled-in value); `apply_rehearsal_edits()` is
    where blank overrides actually resolve to a concrete value, since only
    it can tell a new row from an existing one across every one of this
    surface's callers.
    """

    class Meta:
        model = Rehearsal
        fields: ClassVar[list[str]] = [
            'date', 'start_time', 'end_time', 'is_full_setlist',
            'setup_grace_minutes', 'teardown_grace_minutes',
            'arrival_buffer_minutes', 'departure_buffer_minutes',
        ]

    def __init__(self, *args, semester=None, **kwargs):
        """Stash `semester`, make end_time/the overrides optional, and placeholder each override with the Semester's default."""
        super().__init__(*args, **kwargs)
        self.semester = semester
        self.fields['end_time'].required = False
        for field_name, default_field_name in REHEARSAL_OVERRIDE_FIELDS:
            self.fields[field_name].required = False
            if semester is not None:
                self.fields[field_name].widget.attrs['placeholder'] = str(getattr(semester, default_field_name))

    def clean_date(self):
        """Reject a date before today: the past is edited in the Django admin, not this grid (issue #219)."""
        date_value = self.cleaned_data['date']
        if date_value < timezone.localdate():
            raise forms.ValidationError(
                'Rehearsals dated in the past are managed from the Django admin, not this grid.'
            )
        return date_value

    def clean(self):
        """Reject an end time at or before start time, a missing one on an existing row, or one whose derivation would cross midnight."""
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        date_value = cleaned_data.get('date')
        if end_time is not None:
            if start_time is not None and end_time <= start_time:
                self.add_error('end_time', 'End time must be after start time.')
        elif self.instance.pk:
            self.add_error('end_time', 'End time is required.')
        elif (
            start_time is not None and date_value is not None and self.semester is not None
            and self._derived_end_time(date_value, start_time) is None
        ):
            self.add_error(
                'end_time',
                "Left blank, this row's end time would be derived past midnight from the Semester's "
                'default duration; set it explicitly instead.',
            )
        return cleaned_data

    def _derived_end_time(self, date_value, start_time):
        """Return the end time the Semester's default duration would derive for `date_value`/`start_time`, or None if it crosses midnight."""
        start_dt = datetime.combine(date_value, start_time)
        end_dt = start_dt + timedelta(minutes=self.semester.default_rehearsal_duration_minutes)
        return end_dt.time() if end_dt.date() == start_dt.date() else None


class RehearsalEditFormSetBase(forms.BaseModelFormSet):
    """Adds the one cross-row check no single `RehearsalEditRowForm` can make: no two pending rows share a date (issue #219).

    `semester` is excluded from the form, so Django's own formset
    `validate_unique()` skips `unique_rehearsal_date_per_semester`
    entirely (any unique check naming an excluded field is dropped) —
    every row here shares the same Semester regardless, so the check
    collapses to "no two pending dates are equal", checked by hand.
    """

    def clean(self):
        """Flag every row past the first one that shares an already-seen date with a non-field-specific form error."""
        super().clean()
        if any(self.errors):
            return
        seen_dates = {}
        for form in self.forms:
            if form in self.deleted_forms:
                continue
            date_value = form.cleaned_data.get('date') if form.cleaned_data else None
            if date_value is None:
                continue
            if date_value in seen_dates:
                message = 'Another pending row is already dated here; each Rehearsal needs a distinct date.'
                form.add_error('date', message)
                seen_dates[date_value].add_error('date', message)
            else:
                seen_dates[date_value] = form


# `/schedule/edit/`'s buffer: every future-or-today Rehearsal on the viewing Semester, one row each, plus
# whatever the grid's own "+ Add rehearsal" appends past TOTAL_FORMS later (issue #221). `extra=0`: mirrors
# `SetlistEditFormSet` — added rows arrive by the client bumping TOTAL_FORMS, not by this factory's `extra`.
RehearsalEditFormSet = forms.modelformset_factory(
    Rehearsal, form=RehearsalEditRowForm, formset=RehearsalEditFormSetBase, extra=0,
)

# Same buffer, `extra=1`: a Semester with zero future Rehearsals still needs one blank row present, so
# "Edit rehearsals" isn't a dead end on a brand-new Semester (issue #219) — the same reasoning as
# `SetlistEditEmptyFormSet`.
RehearsalEditEmptyFormSet = forms.modelformset_factory(
    Rehearsal, form=RehearsalEditRowForm, formset=RehearsalEditFormSetBase, extra=1,
)


class SongEditForm(forms.ModelForm):
    """One row of the setlist edit grid: title/artist/length/notes on an existing Song (issue #178).

    `semester` and `position` are deliberately excluded: the view sets
    `semester` on new rows before binding, and `position` is derived from
    the buffer's row order and written by `reorder_songs()`, never through
    this form.

    `length` overrides the model field's default widget with
    `SongLengthField`, which reads and renders `M:SS` — Django's default
    would take `3:45` as three hours forty-five minutes (issue #177).
    """

    length = SongLengthField(label='Length')

    class Meta:
        model = Song
        fields: ClassVar[list[str]] = ['title', 'artist', 'length', 'notes']


# The setlist edit grid's buffer: every existing Song on the viewing Semester, one `SongEditForm` row each,
# plus whatever rows the grid's JS appends (cloned from `empty_form`) or strikes for deletion (issue #179).
# `extra=0`: added rows arrive purely by the client bumping TOTAL_FORMS past INITIAL_FORMS, the same
# mechanism Django's own admin inlines use for a dynamic "add another" row.
SetlistEditFormSet = forms.modelformset_factory(
    Song, form=SongEditForm, extra=0, can_delete=True,
)

# Same buffer, `extra=1`: the empty-setlist GET (issue #180) needs one blank row already present so an
# admin can start typing immediately, rather than having to click "+ Add song" on a setlist with nothing
# in it yet. Only ever bound to an empty queryset — with `INITIAL_FORMS=0`, that one row lands past the
# initial/extra boundary exactly like a JS-added row, so `_save_buffer` treats an untouched one as a no-op.
SetlistEditEmptyFormSet = forms.modelformset_factory(
    Song, form=SongEditForm, extra=1, can_delete=True,
)


class SpotifyImportForm(forms.Form):
    """Validates a pasted Spotify playlist link before any network call (issue #184).

    `clean_playlist_url` runs the same well-formedness check
    `spotify.import_playlist()` runs first regardless, exposed here so a
    malformed or non-Spotify link lands as a field error on this form
    rather than only surfacing after a fetch to the import endpoint.
    """

    playlist_url = forms.CharField(label='Spotify playlist link')

    def clean_playlist_url(self):
        """Return the submitted URL unchanged, or raise a field error for anything that isn't a playlist link."""
        url = self.cleaned_data['playlist_url']
        try:
            extract_playlist_id(url)
        except SpotifyImportError as error:
            raise forms.ValidationError(str(error)) from error
        return url


class SemesterSetupForm(forms.Form):
    """Steps 1-2 of Semester setup: a name plus the six timing defaults, in one submission (issue #200).

    Not a `ModelForm`: the write goes through `services.create_semester()`,
    which also owns the blank/duplicate-name rejection (surfaced here as a
    field error by the view, so there's exactly one place that decision is
    made). This form only validates shape — a non-blank name, and six
    non-negative integers, plainly labelled instead of by model field name.
    """

    name = forms.CharField(max_length=255, label='Semester name')
    default_rehearsal_duration_minutes = forms.IntegerField(min_value=0, label='Rehearsal duration (minutes)')
    default_setup_grace_minutes = forms.IntegerField(min_value=0, label='Setup grace period (minutes)')
    default_teardown_grace_minutes = forms.IntegerField(min_value=0, label='Teardown grace period (minutes)')
    default_song_slot_count = forms.IntegerField(min_value=0, label='Song slot count')
    default_arrival_buffer_minutes = forms.IntegerField(min_value=0, label='Arrival buffer (minutes)')
    default_departure_buffer_minutes = forms.IntegerField(min_value=0, label='Departure buffer (minutes)')

    def timing_defaults(self):
        """Return the six cleaned timing-default fields as a dict, suitable for `create_semester(**...)`."""
        return {field: self.cleaned_data[field] for field in self.fields if field != 'name'}


class RosterEditRowForm(forms.Form):
    """One row of the Roster edit table: an existing Membership's Person, editable name and declared Roles (issue #227).

    A plain `Form` rather than a `ModelForm` bound to `Membership`, since
    the row edits fields spanning two models (`Person.name`,
    `MembershipRole` via `roles`) that no single model instance owns.
    `person_id` is carried as a hidden field so the view can turn a valid
    row back into a `RosterEditEntry` without re-deriving which Person it
    belongs to, and so an invalid submission can still be read back
    field-by-field (via `form['person_id'].value()`) to preserve per-row
    display state. `remove` has no widget rendered for the requesting
    admin's own row (`_members_edit.html`), with `apply_roster_edits()`'s
    `SelfRemovalError` as the backstop against a hand-crafted POST.
    """

    # `PREVIEW_TRIGGER_ATTRS` is applied to both `roles` and `remove`'s widgets: htmx POSTs the whole
    # form to the Roster Preview endpoint on change, syncing against any in-flight request from another
    # row's toggle so a fast sequence discards a superseded response rather than applying it late
    # (issue #228). `name` deliberately carries none of this — typing must never trigger a Preview.
    PREVIEW_TRIGGER_ATTRS: ClassVar[dict] = {
        'hx-post': reverse_lazy('scheduling:members-preview'),
        'hx-trigger': 'change',
        'hx-target': '#roster-fallout',
        'hx-swap': 'outerHTML',
        'hx-sync': 'closest form:replace',
        'hx-include': 'closest form',
    }

    person_id = forms.IntegerField(widget=forms.HiddenInput)
    name = forms.CharField(max_length=255)
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.filter(is_active=True),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs=PREVIEW_TRIGGER_ATTRS),
    )
    remove = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={**PREVIEW_TRIGGER_ATTRS, 'class': 'roster-remove-checkbox'}),
    )


# The Roster edit table's buffer: one `RosterEditRowForm` per existing Membership, with no add-row this
# ticket (adding a Person to the Roster is a later slice of map #185, per issue #227's acceptance criteria).
RosterEditFormSet = forms.formset_factory(RosterEditRowForm, extra=0)


class AdjudicationRowForm(forms.Form):
    """One row of a Rehearsal's adjudication table: an existing Conflict's verdict and optional note (issue #192).

    `conflict_id` is hidden so the view can turn a valid row back into an
    `AdjudicationEntry` without re-deriving which Conflict it belongs to —
    `apply_adjudications()` is the one place that checks it actually
    belongs to the target Rehearsal. `status` offers all three verdicts
    (not just approve/reject) so an untouched pending row round-trips
    unchanged. `note` is never required — a note is offered on an approval
    exactly as readily as on a rejection, and an admin deciding a dozen
    rows in one batch must not be made to type something in every one.

    `preview_url`, when passed, wires `status`'s widget to POST the whole
    form to the Feasibility Preview endpoint on change — never `note`,
    which must never trigger a Preview (issue #194). It's a constructor
    kwarg rather than a class-level `reverse_lazy()` attribute because the
    URL is per-Rehearsal; the view passes it via `form_kwargs` when
    instantiating the formset.
    """

    conflict_id = forms.IntegerField(widget=forms.HiddenInput)
    status = forms.ChoiceField(choices=Conflict.STATUS_CHOICES)
    note = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, preview_url=None, **kwargs):
        """Wire `status`'s widget to fire a Preview POST on change, when `preview_url` is given."""
        super().__init__(*args, **kwargs)
        if preview_url:
            self.fields['status'].widget.attrs.update({
                'hx-post': preview_url,
                'hx-trigger': 'change',
                'hx-target': '#adjudication-preview',
                'hx-swap': 'outerHTML',
                'hx-sync': 'closest form:replace',
                'hx-include': 'closest form',
            })


# One row per existing Conflict on the target Rehearsal — no add/remove, unlike RosterEditFormSet's
# sibling shape, since a row here always names a Conflict that already exists (issue #192).
AdjudicationFormSet = forms.formset_factory(AdjudicationRowForm, extra=0)


class RosterAddRowForm(forms.Form):
    """One row of the Roster add list: a not-yet-rostered Person, whether to add them, and the Roles to declare (issue #229).

    A plain `Form`, not a `ModelForm`: `add` and `roles` map onto a
    `Membership`/`MembershipRole` pair that doesn't exist yet, so there's
    no instance to bind to. `person_id` is a hidden field carrying which
    Person this row proposes, the same pairing convention
    `RosterEditRowForm` uses, so an invalid submission can still be read
    back field-by-field to preserve per-row display state. Ticking `roles`
    with `add` left unticked is legal and simply declares nothing — only a
    ticked `add` turns this row into a `RosterEditEntry` for
    `apply_roster_edits()`.
    """

    person_id = forms.IntegerField(widget=forms.HiddenInput)
    add = forms.BooleanField(required=False)
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.filter(is_active=True),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )


# The Roster add list's buffer: one `RosterAddRowForm` per Person not yet on the Semester's Roster (issue #229).
RosterAddFormSet = forms.formset_factory(RosterAddRowForm, extra=0)


class RosterInviteForm(forms.Form):
    """The Roster editor's "Invite someone new" form: name + email, one of the two writes that escape the Save Buffer (issue #230).

    A plain `Form`, not `identity.forms.PersonInviteForm`: that form's
    default unique-email validation message doesn't tell the admin what to
    do about the collision, and issue #230 requires a specific message
    pointing them at the add list instead of silently repurposing the
    invite as "roster this existing human" — which would muddy
    `invite_person()`'s rollback-on-send-failure contract and re-send a
    set-password link to somebody who already has one.
    """

    name = forms.CharField(max_length=255)
    email = forms.EmailField()

    def clean_email(self):
        """Reject an email already belonging to a Person, pointing the admin at the add list instead."""
        email = self.cleaned_data['email']
        if Person.objects.filter(email=email).exists():
            raise forms.ValidationError(
                'That email already belongs to a Person — tick them in the add list instead of inviting them again.'
            )
        return email


class RosterAddRoleForm(forms.Form):
    """The inline "Add Role" control's POST body: which row triggered it, and the Role name to create/reactivate (issue #230).

    `kind` distinguishes a Roster edit-table row from an add-list row —
    the two live formsets (`RosterEditFormSet`/`RosterAddFormSet`) a row
    can belong to — so the view can rebuild the row with the same Form
    class the live formset renders, keeping field names/ids and any htmx
    wiring on the widget identical after the swap. `prefix` is that row's
    own formset prefix (e.g. `"roster-0"`), carried so the rebuilt
    checkbox group binds to the exact field name the rest of the row
    already uses.
    """

    KIND_CHOICES: ClassVar[list] = [('roster', 'roster'), ('roster_add', 'roster_add')]

    kind = forms.ChoiceField(choices=KIND_CHOICES)
    prefix = forms.CharField(max_length=255)
    role_name = forms.CharField(max_length=255)

    def clean_role_name(self):
        """Strip surrounding whitespace and reject a blank Role name."""
        name = self.cleaned_data['role_name'].strip()
        if not name:
            raise forms.ValidationError('A Role name is required.')
        return name


class SongRequirementEditRowForm(forms.Form):
    """One row of the Song requirements edit table for an existing SongRoleRequirement (issue #209).

    A plain `Form`, not a `ModelForm`: this table only retargets counts or
    deletes rows — per #197's boundary, this page sets targets, it never
    assigns Roles — so a row's Role is fixed and carried as a hidden
    `role_id`, the same identity-pairing convention `RosterEditRowForm`
    uses so an invalid submission can still be read back field-by-field to
    preserve per-row display state.
    """

    role_id = forms.IntegerField(widget=forms.HiddenInput)
    count = forms.IntegerField(min_value=1)
    remove = forms.BooleanField(required=False)


# The Song requirements edit table's buffer: one `SongRequirementEditRowForm` per existing
# SongRoleRequirement (issue #209).
SongRequirementEditFormSet = forms.formset_factory(SongRequirementEditRowForm, extra=0)


class SongRequirementAddRowForm(forms.Form):
    """A "+ Add requirement" row: a Role to require plus its target count (issue #209).

    `role` is scoped to active Roles only, per the issue's picker rule —
    no inviting an admin to plan around a retired instrument — and, via
    `excluded_role_ids`, minus whichever Roles the Song already has a
    (surviving) Requirement for, so the unique (Song, Role) constraint is
    unreachable by the normal path. Excluding Roles picked by *other*
    add-rows in the same pending batch is enforced client-side (the
    row-adding JS); a duplicate arriving anyway is still caught,
    defensively, by `BaseSongRequirementAddFormSet.clean()` below, since
    the database constraint must never be the first thing that tells the
    admin about it.
    """

    role = forms.ModelChoiceField(
        queryset=Role.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'song-requirement-role-select'}),
    )
    count = forms.IntegerField(min_value=1)

    def __init__(self, *args, excluded_role_ids=(), **kwargs):
        """Restrict `role`'s choices to active Roles not already required on this Song."""
        super().__init__(*args, **kwargs)
        self.fields['role'].queryset = Role.objects.filter(is_active=True).exclude(pk__in=excluded_role_ids)


class BaseSongRequirementAddFormSet(forms.BaseFormSet):
    """Rejects a duplicate Role across "+ Add requirement" rows as a Validation Error (issue #209)."""

    def clean(self):
        """Raise a non-form error if two add-rows target the same Role."""
        if any(self.errors):
            return
        seen_role_ids = set()
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get('DELETE'):
                continue
            role = form.cleaned_data.get('role')
            if role is None:
                continue
            if role.pk in seen_role_ids:
                raise forms.ValidationError('Each Role can only have one Requirement per Song.')
            seen_role_ids.add(role.pk)


# The "+ Add requirement" list's buffer: zero or more `SongRequirementAddRowForm` rows, appended by the
# edit table's JS (issue #209). `can_delete=True` lets an admin undo an add-row they no longer want before
# Save, the same convention `SetlistEditFormSet` uses for a struck row.
SongRequirementAddFormSet = forms.formset_factory(
    SongRequirementAddRowForm, formset=BaseSongRequirementAddFormSet, extra=0, can_delete=True,
)


class SongRequirementAddRoleForm(forms.Form):
    """The Song requirements editor's inline "Add Role" control's POST body: which add-row triggered it, and the Role name to create/reactivate (issue #209).

    Mirrors `RosterAddRoleForm`'s shape: `prefix` is the triggering
    add-row's own formset prefix, carried so the rebuilt `role` field binds
    to the exact field name the rest of the row already uses.
    """

    prefix = forms.CharField(max_length=255)
    role_name = forms.CharField(max_length=255)

    def clean_role_name(self):
        """Strip surrounding whitespace and reject a blank Role name."""
        name = self.cleaned_data['role_name'].strip()
        if not name:
            raise forms.ValidationError('A Role name is required.')
        return name


class RecordingUploadForm(forms.Form):
    """Picks the RehearsalSong to upload against and confirms an already-uploaded R2 object (issue #61).

    Used for both halves of the two-step upload: on GET only
    `rehearsal_song` is rendered (to build the picker), and on the confirm
    POST all three fields are submitted together once the client has
    already put the file in R2 under `object_key`.
    """

    rehearsal_song = forms.ModelChoiceField(queryset=RehearsalSong.objects.none())
    object_key = forms.CharField(widget=forms.HiddenInput)
    note = forms.CharField(required=False, widget=forms.Textarea)

    def __init__(self, *args, rehearsal_songs=None, **kwargs):
        """Restrict the `rehearsal_song` choices to `rehearsal_songs` (the viewing Semester's)."""
        super().__init__(*args, **kwargs)
        self.fields['rehearsal_song'].queryset = (
            rehearsal_songs if rehearsal_songs is not None else RehearsalSong.objects.none()
        )
