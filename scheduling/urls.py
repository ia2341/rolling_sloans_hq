from django.urls import path

from . import views

app_name = 'scheduling'

urlpatterns = [
    path('schedule/', views.ScheduleView.as_view(), name='schedule'),
    path('setlist/', views.SetlistView.as_view(), name='setlist'),
    path('songs/<int:pk>/', views.SongDetailView.as_view(), name='song-detail'),
    path('me/profile/', views.ProfileView.as_view(), name='profile'),
]
