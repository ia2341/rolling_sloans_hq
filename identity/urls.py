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
    path(
        'password-reset/',
        views.PasswordResetRequestView.as_view(),
        name='password-reset',
    ),
    path(
        'password-reset/done/',
        views.PasswordResetDoneView.as_view(),
        name='password-reset-done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        views.PasswordResetConfirmView.as_view(),
        name='password-reset-confirm',
    ),
    path(
        'reset/done/',
        views.PasswordResetCompleteView.as_view(),
        name='password-reset-complete',
    ),
    path(
        'password-change/',
        views.PasswordChangeView.as_view(),
        name='password-change',
    ),
    path(
        'password-change/done/',
        views.PasswordChangeDoneView.as_view(),
        name='password-change-done',
    ),
    path('manage/people/', views.PeopleView.as_view(), name='people'),
    path(
        'manage/people/<int:pk>/toggle-admin/',
        views.PersonToggleAdminView.as_view(),
        name='people-toggle-admin',
    ),
]
