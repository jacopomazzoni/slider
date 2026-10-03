from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class SignUpViewTests(TestCase):
    def test_signup_page_shows_password_toggle_without_validator_help_text(self):
        response = self.client.get(reverse('signup'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'password-toggle-button', html=False)
        self.assertNotContains(response, "Your password can't be too similar")

    def test_signup_accepts_simple_matching_password(self):
        response = self.client.post(
            reverse('signup'),
            {
                'email': 'newuser@example.com',
                'username': 'newuser',
                'password1': 'abc123',
                'password2': 'abc123',
            },
        )
        self.assertEqual(response.status_code, 302)
        created_user = get_user_model().objects.get(username='newuser')
        self.assertEqual(created_user.email, 'newuser@example.com')
        self.assertTrue(created_user.check_password('abc123'))

    def test_signup_rejects_passwords_longer_than_20_characters(self):
        too_long_password = 'a' * 21
        response = self.client.post(
            reverse('signup'),
            {
                'email': 'toolong@example.com',
                'username': 'toolong',
                'password1': too_long_password,
                'password2': too_long_password,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'at most 20 characters')
