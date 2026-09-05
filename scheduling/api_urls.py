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
`#332` (Home) is a separate, unrelated ticket. Issue #335 adds no new
`preview/`/`save/` pair of its own — it reuses #334's — only the
read-only Spotify-fetch endpoint the setlist editor's `+ Add songs`
sheet calls before a track ever joins the Buffer.

The Recordings routes deliberately nest under `members/` rather than
mirroring the old `/me/recordings/` prefix: Recordings is no longer its own
destination (issue #333) and these three endpoints only ever exist to
serve the Profile page's Upload-a-take card.
"""

from django.urls import path

from scheduling import api_views

urlpatterns = [
    path('setlist/', api_views.SetlistApiView.as_view(), name='api-setlist'),
    path('setlist/preview/', api_views.SetlistPreviewApiView.as_view(), name='api-setlist-preview'),
    path('setlist/save/', api_views.SetlistSaveApiView.as_view(), name='api-setlist-save'),
    path('setlist/spotify/', api_views.SetlistSpotifyImportApiView.as_view(), name='api-setlist-spotify'),
    path('songs/<int:pk>/', api_views.SongDetailApiView.as_view(), name='api-song-detail'),
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
