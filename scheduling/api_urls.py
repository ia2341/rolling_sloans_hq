"""`scheduling`'s `/api/` routes (issue #326), included by `config/api_urls.py`.

Issue #330 adds the first two: the Setlist and Song detail reads. Every
other concrete `scheduling` `/api/` endpoint is a later ticket (#331
Schedule, #332 Home, #333 Band/Person, #335-#340 admin edit surfaces).
"""

from django.urls import path

from scheduling import api_views

urlpatterns = [
    path('setlist/', api_views.SetlistApiView.as_view(), name='api-setlist'),
    path('songs/<int:pk>/', api_views.SongDetailApiView.as_view(), name='api-song-detail'),
]
