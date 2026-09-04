from django.urls import path

from . import views

app_name = 'scheduling'

urlpatterns = [
    path('', views.OverviewView.as_view(), name='overview'),
    path('schedule/', views.ScheduleView.as_view(), name='schedule'),
    path('schedule/edit/', views.ScheduleEditView.as_view(), name='schedule-edit'),
    path('schedule/edit/preview/', views.ScheduleEditPreviewView.as_view(), name='schedule-edit-preview'),
    path(
        'schedule/edit/confirm-destroy/',
        views.ScheduleEditDestroyConfirmView.as_view(), name='schedule-edit-confirm-destroy',
    ),
    path('schedule/edit/generate/', views.RehearsalPatternModalView.as_view(), name='schedule-edit-generate'),
    path(
        'schedule/edit/generate/save/',
        views.RehearsalPatternSaveView.as_view(), name='schedule-edit-generate-save',
    ),
    path(
        'schedule/edit/generate/preview/',
        views.RehearsalGenerationPreviewView.as_view(), name='schedule-edit-generate-preview',
    ),
    path('schedule/edit/deal/', views.ScheduleEditDealView.as_view(), name='schedule-edit-deal'),
    path(
        'schedule/edit/rehearsal/<int:rehearsal_id>/shuffle/',
        views.ScheduleEditShuffleView.as_view(), name='schedule-edit-shuffle',
    ),
    path('schedule/<int:rehearsal_id>/conflict/', views.ConflictDeclareView.as_view(), name='conflict-declare'),
    path('schedule/<int:rehearsal_id>/conflict/delete/', views.ConflictDeleteView.as_view(), name='conflict-delete'),
    path(
        'schedule/<int:rehearsal_id>/assignments/save/',
        views.AssignmentEditSaveView.as_view(), name='schedule-assignments-save',
    ),
    path(
        'schedule/<int:rehearsal_id>/assignments/picker/<int:song_id>/<int:role_id>/',
        views.AssignmentPickerView.as_view(), name='schedule-assignments-picker',
    ),
    path(
        'schedule/<int:rehearsal_id>/assignments/preview/',
        views.AssignmentPreviewView.as_view(), name='schedule-assignments-preview',
    ),
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
    path(
        'songs/<int:pk>/requirements/edit/',
        views.SongRequirementsEditView.as_view(), name='song-requirements-edit',
    ),
    path(
        'songs/<int:pk>/requirements/roles/add/',
        views.SongRequirementAddRoleView.as_view(), name='song-requirements-add-role',
    ),
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
    path('manage/semesters/setup/', views.SemesterSetupView.as_view(), name='manage-semester-setup'),
    path(
        'manage/semesters/setup/<int:pk>/roster/',
        views.SemesterSetupRosterView.as_view(), name='manage-semester-setup-roster',
    ),
    path(
        'manage/semesters/setup/<int:pk>/setlist/',
        views.SemesterSetupSetlistView.as_view(), name='manage-semester-setup-setlist',
    ),
    path(
        'manage/semesters/setup/<int:pk>/finish/',
        views.SemesterSetupFinishView.as_view(), name='manage-semester-setup-finish',
    ),
    path('manage/semesters/', views.SemesterManageView.as_view(), name='manage-semesters'),
    path('manage/semesters/<int:pk>/publish/', views.SemesterPublishView.as_view(), name='manage-semesters-publish'),
    path('manage/semesters/<int:pk>/delete/', views.SemesterDeleteView.as_view(), name='manage-semesters-delete'),
    path('manage/conflicts/', views.ConflictAdjudicationIndexView.as_view(), name='manage-conflicts'),
    path(
        'manage/conflicts/<int:rehearsal_id>/',
        views.ConflictAdjudicationDetailView.as_view(), name='manage-conflicts-detail',
    ),
    path(
        'manage/conflicts/<int:rehearsal_id>/preview/',
        views.AdjudicationPreviewView.as_view(), name='manage-conflicts-preview',
    ),
]
