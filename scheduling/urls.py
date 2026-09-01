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
