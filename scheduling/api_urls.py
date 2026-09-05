"""`scheduling`'s `/api/` routes (issue #326), included by `config/api_urls.py`.

Issue #330 added the Setlist and Song detail reads. Issue #333 adds the
Band and Person surfaces, plus their upload-confirm/delete/presign
endpoints. Every other concrete `scheduling` `/api/` endpoint is a later
ticket (#331 Schedule, #332 Home, #335-#340 admin edit surfaces).

The Recordings routes deliberately nest under `members/` rather than
mirroring the old `/me/recordings/` prefix: Recordings is no longer its own
destination (issue #333) and these three endpoints only ever exist to
serve the Profile page's Upload-a-take card.
"""

from django.urls import path

from scheduling import api_views

urlpatterns = [
    path('setlist/', api_views.SetlistApiView.as_view(), name='api-setlist'),
    path('songs/<int:pk>/', api_views.SongDetailApiView.as_view(), name='api-song-detail'),
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
