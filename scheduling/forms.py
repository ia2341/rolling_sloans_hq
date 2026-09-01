"""Member-facing forms (issue #58)."""

from typing import ClassVar

from django import forms

from scheduling.models import ConflictWindow, Rehearsal


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
