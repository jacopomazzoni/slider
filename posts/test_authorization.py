"""Permission matrix for every named custom endpoint, including direct POSTs."""
from unittest.mock import patch

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.permissions import is_site_admin
from .models import Post
from .urls import urlpatterns


# Argument values point at real objects so a missing guard cannot hide behind a 404.
EDITOR_ROUTES = {
    'add_slide': (), 'manage_slides': (), 'reorder_slides': (), 'reorder_sections': (),
    'edit_slide_image': ('slide',), 'edit_html_slide': ('slide',),
    'edit_rich_text_slide': ('slide',), 'edit_google_slides_slide': ('slide',),
    'delete_image': ('slide',), 'update_slide_title': ('slide',),
    'update_slide_duration': ('slide',), 'update_slide_visibility': ('slide',),
    'update_generated_slide_config': ('dateline',), 'update_weather_slide_config': (),
    'update_calendar_slide_config': (), 'update_transit_dashboard_config': (),
    'update_empty_display_config': (), 'update_breaking_news_ticker_config': (),
    'rich_text_qr': (),
}
ADMIN_ROUTES = {
    'settings': (), 'export_site_migration': (), 'import_site_migration': (),
    'update_site_appearance': (), 'update_screen_power_schedule': (),
    'reset_user_password': (), 'toggle_superuser': ('user',),
    'update_check': (), 'update_install': (), 'signup': (),
}
PUBLIC_ROUTES = {
    'slidedisplay', 'paused_post_view', 'breaking_news_ticker_feed', 'dateline',
    'dateline_paused', 'getjson', 'weather_view', 'weather_view_paused',
    'calendar_view', 'calendar_view_paused', 'transit_view', 'transit_view_paused',
    'transit_mobile', 'transit_mobile_map_data', 'transit_mobile_live_data',
    'transit_mobile_qr', 'transit_map_data', 'transit_live_data',
}
FORM_ROUTES = {
    'add_slide', 'edit_slide_image', 'edit_html_slide', 'edit_rich_text_slide',
    'edit_google_slides_slide', 'signup',
}
READ_ROUTES = {'manage_slides', 'settings', 'export_site_migration', 'update_check'}


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class EndpointAuthorizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.admin = users.create_superuser('auth-admin', password='test')
        cls.editor = users.create_user('auth-editor', password='test')
        cls.staff = users.create_user('auth-staff', password='test', is_staff=True)
        cls.inactive_admin = users.create_superuser('auth-inactive', password='test', is_active=False)
        cls.slide = Post.objects.create(title='Private edit', content_type=Post.CONTENT_HTML,
                                       description='<script>window.example = true;</script>')

    def url(self, name, args):
        values = {'slide': self.slide.pk, 'user': self.editor.pk}
        return reverse(name, args=[values.get(arg, arg) for arg in args])

    def test_all_custom_endpoints_have_an_explicit_access_classification(self):
        named = {pattern.name for pattern in urlpatterns if pattern.name}
        self.assertEqual(named, set(EDITOR_ROUTES) | (set(ADMIN_ROUTES) - {'signup'}) | PUBLIC_ROUTES)

    def test_anonymous_get_and_post_cannot_access_any_editor_endpoint(self):
        for name, args in EDITOR_ROUTES.items():
            for method in ('get', 'post'):
                with self.subTest(route=name, method=method):
                    response = getattr(self.client, method)(self.url(name, args))
                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(response.url.startswith(reverse('login') + '?next='))
        self.assertTrue(Post.objects.filter(pk=self.slide.pk).exists())

    def test_all_admin_endpoints_deny_anonymous_editors_and_staff(self):
        payload = {'username': 'intruder', 'email': 'intruder@example.com',
                   'password1': 'test', 'password2': 'test',
                   'user': self.editor.pk, 'new_password1': 'changed', 'new_password2': 'changed'}
        with patch('posts.update_views.launch_update') as launch:
            for user in (None, self.editor, self.staff):
                self.client.logout()
                if user:
                    self.client.force_login(user)
                for name, args in ADMIN_ROUTES.items():
                    for method in ('get', 'post'):
                        with self.subTest(user=user, route=name, method=method):
                            response = getattr(self.client, method)(self.url(name, args), payload)
                            expected = (403, 405) if name in ('update_check', 'update_install') else (302, 403)
                            self.assertIn(response.status_code, expected)
                            if response.status_code == 302:
                                self.assertTrue(response.url.startswith(('/?next=', reverse('login') + '?next=')))
            launch.assert_not_called()
        self.assertFalse(get_user_model().objects.filter(username='intruder').exists())
        self.editor.refresh_from_db()
        self.assertFalse(self.editor.is_superuser)
        self.assertTrue(self.editor.check_password('test'))

    @override_settings(AUTHENTICATION_BACKENDS=['django.contrib.auth.backends.AllowAllUsersModelBackend'])
    def test_inactive_superuser_is_denied_even_with_a_permissive_auth_backend(self):
        self.client.force_login(self.inactive_admin)
        self.assertFalse(is_site_admin(self.inactive_admin))
        for name, args in ADMIN_ROUTES.items():
            with self.subTest(route=name):
                response = self.client.post(self.url(name, args))
                self.assertIn(response.status_code, (302, 403, 405))

    def test_mutations_require_post_and_csrf_even_for_superusers(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        all_routes = EDITOR_ROUTES | ADMIN_ROUTES | {'logout': ()}
        for name, args in all_routes.items():
            if name in READ_ROUTES:
                continue
            with self.subTest(route=name):
                self.assertEqual(client.post(self.url(name, args)).status_code, 403)
                if name not in FORM_ROUTES:
                    self.assertEqual(client.get(self.url(name, args)).status_code, 405)

    def test_admin_can_create_user_with_csrf_and_cannot_inject_privileges(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.get(reverse('signup')).status_code, 200)
        response = client.post(reverse('signup'), {
            'username': 'new-operator', 'email': 'new@example.com',
            'password1': 'test', 'password2': 'test', 'is_superuser': True, 'is_staff': True,
            'csrfmiddlewaretoken': client.cookies['csrftoken'].value,
        })
        self.assertRedirects(response, reverse('settings'), fetch_redirect_response=False)
        user = get_user_model().objects.get(username='new-operator')
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertEqual(client.session['_auth_user_id'], str(self.admin.pk))

    def test_signup_link_is_only_visible_inside_admin_settings(self):
        for user in (None, self.editor, self.staff):
            self.client.logout()
            if user:
                self.client.force_login(user)
            self.assertNotContains(self.client.get(reverse('home')), 'href="' + reverse('signup') + '"')
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('settings')), 'href="' + reverse('signup') + '"')

    def test_logout_forms_have_csrf_and_get_does_not_end_session(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.editor)
        response = client.get(reverse('home'))
        soup = BeautifulSoup(response.content, 'html.parser')
        forms = soup.select('form[action="' + reverse('logout') + '"]')
        self.assertEqual(len(forms), 3)  # Desktop menu, mobile menu, and home card.
        for form in forms:
            self.assertEqual(form['method'], 'post')
            self.assertIsNotNone(form.select_one('input[name=csrfmiddlewaretoken]'))
        self.assertEqual(client.get(reverse('logout')).status_code, 405)
        self.assertIn('_auth_user_id', client.session)
        self.assertEqual(client.post(reverse('logout')).status_code, 403)
        response = client.post(reverse('logout'), {'csrfmiddlewaretoken': client.cookies['csrftoken'].value})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('_auth_user_id', client.session)

    def test_editor_retains_slide_editing_and_html_scripts_are_origin_isolated(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('update_slide_title', args=[self.slide.pk]), {'title': 'Updated'})
        self.assertEqual(response.status_code, 302)
        self.slide.refresh_from_db()
        self.assertEqual(self.slide.title, 'Updated')
        self.client.logout()
        response = self.client.get(reverse('paused_post_view', args=[self.slide.pk]))
        self.assertEqual(response.status_code, 200)
        frame = BeautifulSoup(response.content, 'html.parser').select_one('.html-slide-frame')
        self.assertIn('allow-scripts', frame['sandbox'])
        self.assertNotIn('allow-same-origin', frame['sandbox'])

    def test_kiosk_and_mobile_shells_remain_public(self):
        for name in ('slidedisplay', 'dateline_paused', 'weather_view_paused',
                     'calendar_view_paused', 'transit_view_paused', 'transit_mobile'):
            with self.subTest(route=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_django_admin_and_password_change_require_login(self):
        for name in ('admin:index', 'password_change'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)
            self.assertEqual(self.client.post(reverse(name)).status_code, 302)
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 302)

    def test_password_reset_without_valid_token_cannot_set_a_password(self):
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        url = reverse('password_reset_confirm', args=[urlsafe_base64_encode(force_bytes(self.admin.pk)), 'invalid'])
        self.client.post(url, {'new_password1': 'changed', 'new_password2': 'changed'})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password('test'))
