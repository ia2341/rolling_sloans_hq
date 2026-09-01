"""Member-facing (issues #57, #58, #61) and admin-facing (issue #60) forms."""

from typing import ClassVar

from django import forms
from django.db import transaction

from scheduling.models import (
    ConflictWindow,
    Membership,
    MembershipRole,
    Rehearsal,
    RehearsalSong,
    Role,
    Song,
    SongRoleAssignment,
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


class BulkConflictForm(forms.Form):
    """Toggles full-conflict status across the current Semester's Rehearsals in one POST (issue #58).

    Not a ModelForm: this writes across many (person, rehearsal)-keyed
    Conflict rows in one submission, with no single model instance to bind
    to, so a plain Form fits the shape better.
    """

    full_conflict_rehearsals = forms.ModelMultipleChoiceField(
        queryset=Rehearsal.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, rehearsals=None, **kwargs):
        """Restrict the `full_conflict_rehearsals` choices to `rehearsals` (the current Semester's)."""
        super().__init__(*args, **kwargs)
        self.fields['full_conflict_rehearsals'].queryset = rehearsals if rehearsals is not None else Rehearsal.objects.none()


class ConflictWindowForm(forms.ModelForm):
    """One partial-conflict time window, validated against its Rehearsal's span (issue #58).

    The parent Conflict may not exist in the database yet (a member's first
    partial-conflict submission for a Rehearsal), so validation can't rely
    on ConflictWindow.clean()'s conflict_id lookup; the Rehearsal is passed
    in directly and checked here instead.
    """

    class Meta:
        model = ConflictWindow
        fields: ClassVar[list[str]] = ['unavailable_start', 'unavailable_end']

    def __init__(self, *args, rehearsal=None, **kwargs):
        """Stash `rehearsal` for span validation in clean()."""
        super().__init__(*args, **kwargs)
        self.rehearsal = rehearsal

    def clean(self):
        """Reject a window outside the Rehearsal's time span as a field error, not a 500."""
        cleaned_data = super().clean()
        start = cleaned_data.get('unavailable_start')
        end = cleaned_data.get('unavailable_end')
        if self.rehearsal and start and end:
            if start >= end:
                message = 'End time must be after start time.'
                self.add_error('unavailable_start', message)
                self.add_error('unavailable_end', message)
                return cleaned_data
            in_span = self.rehearsal.start_time <= start <= self.rehearsal.end_time
            in_span = in_span and self.rehearsal.start_time <= end <= self.rehearsal.end_time
            if not in_span:
                message = "Must fall within the Rehearsal's time span."
                self.add_error('unavailable_start', message)
                self.add_error('unavailable_end', message)
        return cleaned_data


ConflictWindowFormSet = forms.modelformset_factory(
    ConflictWindow, form=ConflictWindowForm, extra=1, can_delete=True,
)


class RehearsalForm(forms.ModelForm):
    """Creates/edits a Rehearsal within its (already-set) Semester (issue #60).

    `semester` is deliberately excluded: the view sets it on the instance
    before binding (a fresh Rehearsal for create, the existing one for
    edit), so it's never attacker-controlled via POST data.
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
    """

    class Meta:
        model = Song
        fields: ClassVar[list[str]] = ['title', 'artist', 'length', 'notes']


class SongRoleAssignmentForm(forms.ModelForm):
    """Assigns a Person to a Role on a Song, restricted to the current Semester's Songs (issue #60).

    `is_role_mismatch` is excluded: SongRoleAssignment.save() always
    recomputes it from the Person's current Membership, so it's never a
    form input.
    """

    class Meta:
        model = SongRoleAssignment
        fields: ClassVar[list[str]] = ['song', 'role', 'person']

    def __init__(self, *args, songs=None, **kwargs):
        """Restrict the `song` choices to `songs` (the current Semester's) and `role` to active Roles."""
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
        """Restrict the `rehearsal_song` choices to `rehearsal_songs` (the current Semester's)."""
        super().__init__(*args, **kwargs)
        self.fields['rehearsal_song'].queryset = (
            rehearsal_songs if rehearsal_songs is not None else RehearsalSong.objects.none()
        )
