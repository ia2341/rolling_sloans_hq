from django.urls import path

from . import views

app_name = 'identity'

urlpatterns = [
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
