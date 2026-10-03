from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm

from .passwords import PASSWORD_MAX_LENGTH, password_widget_attrs, validate_basic_password


User = get_user_model()


class SignUpForm(forms.ModelForm):
    email = forms.EmailField()
    password1 = forms.CharField(
        label='Password',
        strip=False,
        max_length=PASSWORD_MAX_LENGTH,
        widget=forms.PasswordInput(attrs=password_widget_attrs()),
    )
    password2 = forms.CharField(
        label='Confirm password',
        strip=False,
        max_length=PASSWORD_MAX_LENGTH,
        widget=forms.PasswordInput(attrs=password_widget_attrs()),
    )

    class Meta:
        model = User
        fields = ('email', 'username')

    def clean_password1(self):
        return validate_basic_password(self.cleaned_data.get('password1'))

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')

        if password1 and password2 and password1 != password2:
            self.add_error('password2', "The two password fields didn't match.")

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
        return user


class SimpleSetPasswordForm(SetPasswordForm):
    new_password1 = forms.CharField(
        label='New password',
        strip=False,
        max_length=PASSWORD_MAX_LENGTH,
        widget=forms.PasswordInput(attrs=password_widget_attrs()),
    )
    new_password2 = forms.CharField(
        label='Confirm new password',
        strip=False,
        max_length=PASSWORD_MAX_LENGTH,
        widget=forms.PasswordInput(attrs=password_widget_attrs()),
    )

    def clean_new_password1(self):
        return validate_basic_password(self.cleaned_data.get('new_password1'))
