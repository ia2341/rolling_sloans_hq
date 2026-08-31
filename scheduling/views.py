"""Member read routes (issue #56): /schedule/, /setlist/, /songs/<id>/."""

from django.views.generic import DetailView, TemplateView

from config.views import BaseView
from scheduling.models import Recording, Rehearsal, Song, SongRoleAssignment
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
