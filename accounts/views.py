from django.shortcuts import redirect

from django.urls import reverse_lazy
from django.views.generic import CreateView
from .forms import SignUpForm
from django.contrib.auth import logout
from django.contrib.auth.views import PasswordResetConfirmView

#login and signup
class SignUpView(CreateView):
    form_class = SignUpForm
    success_url = reverse_lazy("login")
    template_name = "registration/signup.html"

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

def logout_view(request):
    logout(request)
    return redirect('home')
