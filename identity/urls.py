from django.urls import path

from . import views

app_name = 'identity'

urlpatterns = [
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path(
        'password-reset/',
        views.PasswordResetRequestView.as_view(),
        name='password-reset',
    ),
    path(
        'set-password/<uidb64>/<token>/',
        views.SetPasswordConfirmView.as_view(),
        name='set-password-confirm',
    ),
    path('manage/people/', views.PeopleView.as_view(), name='people'),
    path(
        'manage/people/<int:pk>/toggle-admin/',
        views.PersonToggleAdminView.as_view(),
        name='people-toggle-admin',
    ),
    path(
        'manage/people/<int:pk>/resend-invite/',
        views.PersonResendInviteView.as_view(),
        name='people-resend-invite',
    ),
]
