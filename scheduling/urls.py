from django.urls import path

from . import views

app_name = 'scheduling'

urlpatterns = [
    path('', views.OverviewView.as_view(), name='overview'),
    path('schedule/', views.ScheduleView.as_view(), name='schedule'),
    path('setlist/', views.SetlistView.as_view(), name='setlist'),
    path('setlist/edit/', views.SetlistEditView.as_view(), name='setlist-edit'),
    path(
        'setlist/edit/confirm-delete/',
        views.SetlistDeleteConfirmView.as_view(), name='setlist-edit-confirm-delete',
    ),
    path('songs/<int:pk>/', views.SongDetailView.as_view(), name='song-detail'),
    path('members/', views.MembersView.as_view(), name='members'),
    path('members/<int:pk>/', views.MemberDetailView.as_view(), name='member-detail'),
    path('me/conflicts/', views.ConflictsView.as_view(), name='conflicts'),
    path('me/conflicts/<int:rehearsal_id>/edit/', views.ConflictEditView.as_view(), name='conflict-edit'),
    path('me/conflicts/<int:rehearsal_id>/delete/', views.ConflictDeleteView.as_view(), name='conflict-delete'),
    path('me/recordings/', views.RecordingUploadView.as_view(), name='recordings'),
    path('me/recordings/presign/', views.RecordingPresignView.as_view(), name='recordings-presign'),
    path('me/recordings/<int:pk>/delete/', views.RecordingDeleteView.as_view(), name='recordings-delete'),
    path('manage/semester/', views.SemesterSelectView.as_view(), name='manage-semester-select'),
    path('manage/semesters/', views.SemesterManageView.as_view(), name='manage-semesters'),
    path('manage/semesters/<int:pk>/publish/', views.SemesterPublishView.as_view(), name='manage-semesters-publish'),
    path('manage/semesters/<int:pk>/delete/', views.SemesterDeleteView.as_view(), name='manage-semesters-delete'),
    path('manage/schedule/', views.RehearsalManageView.as_view(), name='manage-schedule'),
    path('manage/schedule/<int:pk>/edit/', views.RehearsalEditView.as_view(), name='manage-schedule-edit'),
    path('manage/assignments/', views.SongRoleAssignmentManageView.as_view(), name='manage-assignments'),
    path(
        'manage/assignments/<int:pk>/delete/',
        views.SongRoleAssignmentDeleteView.as_view(), name='manage-assignments-delete',
    ),
]
