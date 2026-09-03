"""Member-facing (issues #57, #58, #61) and admin-facing (issue #60) forms."""

from typing import ClassVar

from django import forms
from django.db import transaction

from scheduling.fields import SongLengthField
from scheduling.models import (
    Membership,
    MembershipRole,
    Rehearsal,
    RehearsalSong,
    Role,
    Song,
    SongRoleAssignment,
)
from scheduling.services import (
    CONFLICT_DECLARATION_CHOICES,
    CONFLICT_EARLY_DEPARTURE,
    CONFLICT_LATE_ARRIVAL,
)


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


class SongForm(forms.ModelForm):
    """Creates/edits a Song's title/artist/length/notes within its (already-set) Semester (issue #60).

    `semester` and `position` are deliberately excluded: the view sets
    `semester` on the instance before binding, and `position` is only ever
    changed through the dedicated reorder endpoints, never through this
    form.

    `length` overrides the model field's default widget with
    `SongLengthField`, which reads and renders `M:SS` — Django's default
    would take `3:45` as three hours forty-five minutes (issue #177).
    """

    length = SongLengthField(label='Length')

    class Meta:
        model = Song
        fields: ClassVar[list[str]] = ['title', 'artist', 'length', 'notes']


class SongEditForm(forms.ModelForm):
    """One row of the setlist edit grid: title/artist/length/notes on an existing Song (issue #178).

    Shares `SongForm`'s field set and `M:SS` length widget; kept as a
    separate class because it is always used inside `SetlistEditFormSet`
    (extra=0, no add/delete this ticket) rather than standalone.
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


class SongRoleAssignmentForm(forms.ModelForm):
    """Assigns a Person to a Role on a Song, restricted to the viewing Semester's Songs (issue #60).

    `is_role_mismatch` is excluded: SongRoleAssignment.save() always
    recomputes it from the Person's current Membership, so it's never a
    form input.
    """

    class Meta:
        model = SongRoleAssignment
        fields: ClassVar[list[str]] = ['song', 'role', 'person']

    def __init__(self, *args, songs=None, **kwargs):
        """Restrict the `song` choices to `songs` (the viewing Semester's) and `role` to active Roles."""
        super().__init__(*args, **kwargs)
        self.fields['song'].queryset = songs if songs is not None else Song.objects.none()
        self.fields['role'].queryset = Role.objects.filter(is_active=True)


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
