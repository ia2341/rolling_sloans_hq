from django.urls import path

from . import views

app_name = 'scheduling'

urlpatterns = [
    path('', views.OverviewView.as_view(), name='overview'),
    path('schedule/', views.ScheduleView.as_view(), name='schedule'),
    path('setlist/', views.SetlistView.as_view(), name='setlist'),
    path('songs/<int:pk>/', views.SongDetailView.as_view(), name='song-detail'),
    path('me/profile/', views.ProfileView.as_view(), name='profile'),
    path('me/conflicts/', views.ConflictsView.as_view(), name='conflicts'),
    path('me/conflicts/<int:rehearsal_id>/edit/', views.ConflictEditView.as_view(), name='conflict-edit'),
    path('me/conflicts/<int:rehearsal_id>/delete/', views.ConflictDeleteView.as_view(), name='conflict-delete'),
    path('me/recordings/', views.RecordingUploadView.as_view(), name='recordings'),
    path('me/recordings/presign/', views.RecordingPresignView.as_view(), name='recordings-presign'),
    path('me/recordings/<int:pk>/delete/', views.RecordingDeleteView.as_view(), name='recordings-delete'),
    path('manage/schedule/', views.RehearsalManageView.as_view(), name='manage-schedule'),
    path('manage/schedule/<int:pk>/edit/', views.RehearsalEditView.as_view(), name='manage-schedule-edit'),
    path('manage/setlist/', views.SongManageView.as_view(), name='manage-setlist'),
    path('manage/setlist/<int:pk>/edit/', views.SongEditView.as_view(), name='manage-setlist-edit'),
    path('manage/setlist/<int:pk>/delete/', views.SongDeleteView.as_view(), name='manage-setlist-delete'),
    path(
        'manage/setlist/<int:pk>/move-up/',
        views.SongMoveView.as_view(), {'direction': views.SongMoveView.UP}, name='manage-setlist-move-up',
    ),
    path(
        'manage/setlist/<int:pk>/move-down/',
        views.SongMoveView.as_view(), {'direction': views.SongMoveView.DOWN}, name='manage-setlist-move-down',
    ),
    path('manage/assignments/', views.SongRoleAssignmentManageView.as_view(), name='manage-assignments'),
    path(
        'manage/assignments/<int:pk>/delete/',
        views.SongRoleAssignmentDeleteView.as_view(), name='manage-assignments-delete',
    ),
]
