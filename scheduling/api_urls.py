"""`scheduling`'s `/api/` routes (issue #326), included by `config/api_urls.py`.

Issue #330 added the first two: the Setlist and Song detail reads. Issue
#331 adds the Schedule read and its two Conflict writes. Issue #333 adds
the Band and Person surfaces, plus their upload-confirm/delete/presign
endpoints. Issue #334 adds the Setlist edit surface's Preview and Save —
the shared Pending-Buffer-over-HTTP mechanism's one proven concrete
surface; the other five admin edit surfaces (#335-#340) each add their
own `preview/`/`save/` pair later, following this one's shape. Issue #336
adds the Roster edit surface's own read/preview/save/candidates/roles/
resend-invite endpoints, the second full surface to follow that shape.
Issue #335 adds no new `preview/`/`save/` pair of its own — it reuses
#334's — only the read-only Spotify-fetch endpoint the setlist editor's
`+ Add songs` sheet calls before a track ever joins the Buffer. Issue
#332 adds the root `''` route: Home's Next-rehearsal, Upcoming-rehearsals,
Song-progress and setup-checklist read model, one round trip like every
other page-shaped surface here.

The Recordings routes deliberately nest under `members/` rather than
mirroring the old `/me/recordings/` prefix: Recordings is no longer its own
destination (issue #333) and these three endpoints only ever exist to
serve the Profile page's Upload-a-take card.

Issue #338 adds the assignment editor's `picker/`/`preview/`/`save/`
trio, per-Rehearsal siblings of `schedule/<id>/conflict/`. The grid
itself adds no new read: it comes from `schedule/`'s existing
`AssignmentMatrix` (issue #331), per #307's "one endpoint per surface"
rule.
"""

from django.urls import path

from scheduling import api_views

urlpatterns = [
    path('', api_views.HomeApiView.as_view(), name='api-home'),
    path('setlist/', api_views.SetlistApiView.as_view(), name='api-setlist'),
    path('setlist/preview/', api_views.SetlistPreviewApiView.as_view(), name='api-setlist-preview'),
    path('setlist/save/', api_views.SetlistSaveApiView.as_view(), name='api-setlist-save'),
    path('setlist/spotify/', api_views.SetlistSpotifyImportApiView.as_view(), name='api-setlist-spotify'),
    path('songs/<int:pk>/', api_views.SongDetailApiView.as_view(), name='api-song-detail'),
    path(
        'songs/<int:pk>/requirements/preview/',
        api_views.SongRoleRequirementPreviewApiView.as_view(), name='api-song-requirements-preview',
    ),
    path(
        'songs/<int:pk>/requirements/save/',
        api_views.SongRoleRequirementSaveApiView.as_view(), name='api-song-requirements-save',
    ),
    path('schedule/', api_views.ScheduleApiView.as_view(), name='api-schedule'),
    path(
        'schedule/<int:rehearsal_id>/conflict/',
        api_views.ConflictDeclareApiView.as_view(),
        name='api-conflict-declare',
    ),
    path(
        'schedule/<int:rehearsal_id>/conflict/withdraw/',
        api_views.ConflictWithdrawApiView.as_view(),
        name='api-conflict-withdraw',
    ),
    path('members/', api_views.BandApiView.as_view(), name='api-members'),
    path('members/roster/', api_views.RosterEditApiView.as_view(), name='api-roster-edit'),
    path('members/roster/preview/', api_views.RosterPreviewApiView.as_view(), name='api-roster-preview'),
    path('members/roster/save/', api_views.RosterSaveApiView.as_view(), name='api-roster-save'),
    path('members/roster/candidates/', api_views.RosterCandidatesApiView.as_view(), name='api-roster-candidates'),
    path('members/roster/roles/', api_views.RoleDeclareApiView.as_view(), name='api-roster-declare-role'),
    path(
        'members/roster/<int:pk>/resend-invite/',
        api_views.RosterResendInviteApiView.as_view(), name='api-roster-resend-invite',
    ),
    path('members/recordings/presign/', api_views.RecordingPresignApiView.as_view(), name='api-recordings-presign'),
    path('members/recordings/confirm/', api_views.RecordingConfirmApiView.as_view(), name='api-recordings-confirm'),
    path(
        'members/recordings/<int:pk>/delete/',
        api_views.RecordingDeleteApiView.as_view(), name='api-recordings-delete',
    ),
    path('members/<int:pk>/', api_views.PersonApiView.as_view(), name='api-member-detail'),
    path('members/<int:pk>/roles/', api_views.PersonRolesApiView.as_view(), name='api-member-roles'),
    path('schedule/editor/', api_views.ScheduleEditorApiView.as_view(), name='api-schedule-editor'),
    path(
        'schedule/editor/preview/',
        api_views.ScheduleEditorPreviewApiView.as_view(), name='api-schedule-editor-preview',
    ),
    path('schedule/editor/save/', api_views.ScheduleEditorSaveApiView.as_view(), name='api-schedule-editor-save'),
    path(
        'schedule/editor/pattern/save/',
        api_views.RehearsalPatternSaveApiView.as_view(), name='api-schedule-editor-pattern-save',
    ),
    path(
        'schedule/editor/generate/diff/',
        api_views.RehearsalGenerationDiffApiView.as_view(), name='api-schedule-editor-generate-diff',
    ),
    path('schedule/editor/deal/', api_views.ScheduleEditorDealApiView.as_view(), name='api-schedule-editor-deal'),
    path(
        'schedule/editor/rehearsal/<int:rehearsal_id>/shuffle/',
        api_views.ScheduleEditorShuffleApiView.as_view(), name='api-schedule-editor-shuffle',
    ),
    path(
        'schedule/editor/stats/',
        api_views.ScheduleEditorStatsApiView.as_view(), name='api-schedule-editor-stats',
    ),
    path(
        'schedule/<int:rehearsal_id>/assignments/picker/<int:song_id>/<int:role_id>/',
        api_views.AssignmentPickerApiView.as_view(), name='api-schedule-assignments-picker',
    ),
    path(
        'schedule/<int:rehearsal_id>/assignments/preview/',
        api_views.AssignmentPreviewApiView.as_view(), name='api-schedule-assignments-preview',
    ),
    path(
        'schedule/<int:rehearsal_id>/assignments/save/',
        api_views.AssignmentSaveApiView.as_view(), name='api-schedule-assignments-save',
    ),
    path(
        'schedule/<int:rehearsal_id>/running-order/preview/',
        api_views.RunningOrderReorderPreviewApiView.as_view(), name='api-schedule-running-order-preview',
    ),
    path(
        'schedule/<int:rehearsal_id>/running-order/save/',
        api_views.RunningOrderReorderSaveApiView.as_view(), name='api-schedule-running-order-save',
    ),
    path(
        'semesters/management-rows/',
        api_views.SemesterManagementRowsApiView.as_view(), name='api-semesters-management-rows',
    ),
    path(
        'semesters/<int:pk>/publish-impact/',
        api_views.SemesterPublishImpactApiView.as_view(), name='api-semesters-publish-impact',
    ),
    path(
        'semesters/<int:pk>/deletion-summary/',
        api_views.SemesterDeletionSummaryApiView.as_view(), name='api-semesters-deletion-summary',
    ),
    path('semesters/select/', api_views.SemesterSelectApiView.as_view(), name='api-semesters-select'),
    path('semesters/create/', api_views.SemesterCreateApiView.as_view(), name='api-semesters-create'),
    path('semesters/<int:pk>/publish/', api_views.SemesterPublishApiView.as_view(), name='api-semesters-publish'),
    path('semesters/<int:pk>/delete/', api_views.SemesterDeleteApiView.as_view(), name='api-semesters-delete'),
    path(
        'semesters/reapply-defaults/preview/',
        api_views.SemesterDefaultsReapplyPreviewApiView.as_view(), name='api-semesters-reapply-defaults-preview',
    ),
    path(
        'semesters/reapply-defaults/save/',
        api_views.SemesterDefaultsReapplySaveApiView.as_view(), name='api-semesters-reapply-defaults-save',
    ),
    path('conflicts/', api_views.ConflictAdjudicationIndexApiView.as_view(), name='api-conflicts-index'),
    path(
        'conflicts/<int:rehearsal_id>/',
        api_views.ConflictAdjudicationDetailApiView.as_view(), name='api-conflicts-detail',
    ),
    path(
        'conflicts/<int:rehearsal_id>/preview/',
        api_views.ConflictAdjudicationPreviewApiView.as_view(), name='api-conflicts-preview',
    ),
    path(
        'conflicts/<int:rehearsal_id>/save/',
        api_views.ConflictAdjudicationSaveApiView.as_view(), name='api-conflicts-save',
    ),
]
