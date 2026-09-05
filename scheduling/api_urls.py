"""`scheduling`'s `/api/` routes (issue #326), included by `config/api_urls.py`.

Issue #330 added the first two: the Setlist and Song detail reads. Issue
#334 adds the Setlist edit surface's Preview and Save — the shared
Pending-Buffer-over-HTTP mechanism's one proven concrete surface; the
other five admin edit surfaces (#335-#340) each add their own
`preview/`/`save/` pair later, following this one's shape. `#331`
(Schedule), `#332` (Home) and `#333` (Band/Person) are separate,
unrelated tickets.
"""

from django.urls import path

from scheduling import api_views

urlpatterns = [
    path('setlist/', api_views.SetlistApiView.as_view(), name='api-setlist'),
    path('setlist/preview/', api_views.SetlistPreviewApiView.as_view(), name='api-setlist-preview'),
    path('setlist/save/', api_views.SetlistSaveApiView.as_view(), name='api-setlist-save'),
    path('songs/<int:pk>/', api_views.SongDetailApiView.as_view(), name='api-song-detail'),
]
