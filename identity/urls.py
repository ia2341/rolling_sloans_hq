from django.urls import path

from . import views

app_name = 'identity'

urlpatterns = [
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path(
        'set-password/<uidb64>/<token>/',
        views.SetPasswordConfirmView.as_view(),
        name='set-password-confirm',
    ),
    path(
        'set-password/done/',
        views.SetPasswordCompleteView.as_view(),
        name='set-password-complete',
    ),
]
