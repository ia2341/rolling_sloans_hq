"""`scheduling`'s `/api/` routes (issue #326), included by `config/api_urls.py`.

Issue #330 added the first two: the Setlist and Song detail reads. Issue
#331 adds the Schedule read and its two Conflict writes. Issue #333 adds
the Band and Person surfaces, plus their upload-confirm/delete/presign
endpoints. Issue #334 adds the Setlist edit surface's Preview and Save —
the shared Pending-Buffer-over-HTTP mechanism's one proven concrete
surface; the other five admin edit surfaces (#335-#340) each add their
own `preview/`/`save/` pair later, following this one's shape. `#332`
(Home) is a separate, unrelated ticket.

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
    path('members/recordings/presign/', api_views.RecordingPresignApiView.as_view(), name='api-recordings-presign'),
    path('members/recordings/confirm/', api_views.RecordingConfirmApiView.as_view(), name='api-recordings-confirm'),
    path(
        'members/recordings/<int:pk>/delete/',
        api_views.RecordingDeleteApiView.as_view(), name='api-recordings-delete',
    ),
    path('members/<int:pk>/', api_views.PersonApiView.as_view(), name='api-member-detail'),
    path('members/<int:pk>/roles/', api_views.PersonRolesApiView.as_view(), name='api-member-roles'),
]
