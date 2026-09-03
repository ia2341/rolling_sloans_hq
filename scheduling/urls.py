from django.urls import path

from . import views

app_name = 'scheduling'

urlpatterns = [
    path('', views.OverviewView.as_view(), name='overview'),
    path('schedule/', views.ScheduleView.as_view(), name='schedule'),
    path('schedule/<int:rehearsal_id>/conflict/', views.ConflictDeclareView.as_view(), name='conflict-declare'),
    path('schedule/<int:rehearsal_id>/conflict/delete/', views.ConflictDeleteView.as_view(), name='conflict-delete'),
    path('setlist/', views.SetlistView.as_view(), name='setlist'),
    path('setlist/edit/', views.SetlistEditView.as_view(), name='setlist-edit'),
    path(
        'setlist/edit/confirm-delete/',
        views.SetlistDeleteConfirmView.as_view(), name='setlist-edit-confirm-delete',
    ),
    path(
        'setlist/edit/import/',
        views.SetlistImportView.as_view(), name='setlist-edit-import',
    ),
    path('songs/<int:pk>/', views.SongDetailView.as_view(), name='song-detail'),
    path('members/', views.MembersView.as_view(), name='members'),
    path('members/import/', views.RosterImportView.as_view(), name='members-roster-import'),
    path('members/invite/', views.RosterInviteView.as_view(), name='members-roster-invite'),
    path('members/roles/add/', views.RosterAddRoleView.as_view(), name='members-add-role'),
    path('members/preview/', views.RosterPreviewView.as_view(), name='members-preview'),
    path(
        'members/preview/confirm-removal/',
        views.RosterRemovalConfirmView.as_view(), name='members-preview-confirm-removal',
    ),
    path('members/<int:pk>/', views.MemberDetailView.as_view(), name='member-detail'),
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
    path('manage/conflicts/', views.ConflictAdjudicationIndexView.as_view(), name='manage-conflicts'),
    path(
        'manage/conflicts/<int:rehearsal_id>/',
        views.ConflictAdjudicationDetailView.as_view(), name='manage-conflicts-detail',
    ),
]
