"""`scheduling`'s `/api/` routes (issue #326), included by `config/api_urls.py`.

Issue #330 adds the Setlist and Song detail reads. Issue #331 adds the
Schedule read and its two Conflict writes. Every other concrete
`scheduling` `/api/` endpoint is a later ticket (#332 Home, #333
Band/Person, #335-#340 admin edit surfaces).
"""

from django.urls import path

from scheduling import api_views

urlpatterns = [
    path('setlist/', api_views.SetlistApiView.as_view(), name='api-setlist'),
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
]
