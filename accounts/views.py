from django.shortcuts import redirect

from django.urls import reverse_lazy
from django.views.generic import CreateView
from .forms import SignUpForm
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.auth.views import PasswordResetConfirmView
from django.views.decorators.http import require_POST
from .permissions import is_site_admin

#login and signup
class SignUpView(UserPassesTestMixin, CreateView):
    form_class = SignUpForm
    success_url = reverse_lazy("settings")
    template_name = "registration/signup.html"

    def test_func(self):
        return is_site_admin(self.request.user)

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.activity_succeeded = True
        self.request.activity_detail = f'Created user: {self.object.get_username()}.'
        return response


class LoggedPasswordResetConfirmView(PasswordResetConfirmView):
    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.activity_succeeded = True
        self.request.activity_detail = f'Password reset for {self.user.get_username()}.'
        return response

@login_required
@require_POST
def logout_view(request):
    logout(request)
    return redirect('home')
