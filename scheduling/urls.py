from django.urls import path

from . import views

app_name = 'scheduling'

urlpatterns = [
    path('schedule/', views.ScheduleView.as_view(), name='schedule'),
    path('setlist/', views.SetlistView.as_view(), name='setlist'),
    path('songs/<int:pk>/', views.SongDetailView.as_view(), name='song-detail'),
    path('me/profile/', views.ProfileView.as_view(), name='profile'),
    path('me/conflicts/', views.ConflictsView.as_view(), name='conflicts'),
    path('me/conflicts/<int:rehearsal_id>/', views.ConflictDetailView.as_view(), name='conflict-detail'),
    path('me/recordings/', views.RecordingUploadView.as_view(), name='recordings'),
    path('me/recordings/presign/', views.RecordingPresignView.as_view(), name='recordings-presign'),
]
