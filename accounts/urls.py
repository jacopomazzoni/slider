from django.urls import path
from django.contrib.auth import views as auth_views

from .views import SignUpView, logout_view
from . import views
from .forms import SimpleSetPasswordForm


urlpatterns = [
    path("signup/", SignUpView.as_view(), name="signup"),
    path(
        'reset/<uidb64>/<token>/',
        views.LoggedPasswordResetConfirmView.as_view(
            form_class=SimpleSetPasswordForm,
            template_name='registration/password_reset_confirm.html',
        ),
        name='password_reset_confirm',
    ),
    path('logout/', views.logout_view, name='logout'),
]
