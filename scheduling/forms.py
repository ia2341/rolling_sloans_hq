"""Member-facing (issues #57, #58, #61) and admin-facing (issue #60) forms.

Every other Django Form/FormSet this module used to define existed solely
to serve a page under `scheduling/views.py`, all retired by issue #341's
cutover to the React SPA — the new `/api/` surfaces validate their own
request bodies directly (see `scheduling/api_views.py` and
`scheduling/serializers.py`), never through a Django Form. `DeclareConflictForm`
below is the one survivor, still imported by `scheduling/api_views.py`,
which reuses it as-is rather than reimplementing the same validation
twice. `MembershipRolesForm` used to live here too; issue #378 (ADR-0014)
retargeted Role-editing on `/members/<pk>/` at the person-level
`PersonRole` model, via `scheduling.services.sync_person_roles()` instead
of a Django Form, so it was removed rather than left unused.
"""

from django import forms

from scheduling.services import (
    CONFLICT_DECLARATION_CHOICES,
    CONFLICT_EARLY_DEPARTURE,
    CONFLICT_LATE_ARRIVAL,
)


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
