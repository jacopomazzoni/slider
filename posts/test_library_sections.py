import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import (CalendarSlideConfig, GeneratedSlideConfig, Post, SlideLibraryConfig,
                     TransitDashboardConfig, WeatherSlideConfig, default_library_sections)
from .site_migration import build_site_manifest, replace_database_records
from .updates import private_path
from .views import slide_source_context


class LibrarySectionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('editor', password='test-pass')
        self.client.force_login(self.user)
        self.order = ['weather', 'media', 'transit', 'calendar', 'dateline', 'fallback', 'ticker']

    def save_order(self, order):
        return self.client.post(reverse('reorder_sections'), json.dumps({'section_order': order}), content_type='application/json')

    def test_order_persists_and_is_shared_by_library_and_display(self):
        self.assertEqual(self.save_order(self.order).status_code, 200)
        self.assertEqual(SlideLibraryConfig.load().ordered_sections, self.order)
        page = self.client.get(reverse('manage_slides'))
        self.assertEqual(page.context['library_section_order'], self.order)
        self.assertContains(page, 'library-expand-all')
        self.assertContains(page, 'library-collapse-all')
        for section in self.order:
            self.assertContains(page, f'data-section="{section}"')

    def test_invalid_orders_do_not_replace_saved_order(self):
        self.save_order(self.order)
        for order in [[], self.order[:-1], ['media'] * 7, self.order[:-1] + ['bad'], [None] * 7, {}]:
            self.assertEqual(self.save_order(order).status_code, 400)
        self.assertEqual(SlideLibraryConfig.load().ordered_sections, self.order)
        self.assertEqual(self.client.post(reverse('reorder_sections'), 'broken', content_type='application/json').status_code, 400)

    def test_authentication_method_and_csrf_are_required(self):
        self.assertEqual(self.client.get(reverse('reorder_sections')).status_code, 405)
        self.client.logout()
        self.assertEqual(self.save_order(self.order).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(reverse('reorder_sections'), '{}', content_type='application/json').status_code, 403)

    def test_sequence_skips_hidden_empty_and_non_playback_sections(self):
        self.save_order(self.order)
        WeatherSlideConfig.load()
        WeatherSlideConfig.objects.update(is_visible=True)
        GeneratedSlideConfig.objects.update_or_create(scraper_name='dateline', defaults={'is_visible': False})
        CalendarSlideConfig.load()
        CalendarSlideConfig.objects.update(is_visible=True, public_url='')
        TransitDashboardConfig.load()
        TransitDashboardConfig.objects.update(is_visible=True)
        context = slide_source_context()
        self.assertEqual([section['key'] for section in context['display_sections']], ['weather', 'transit'])
        self.assertEqual(context['section_next_urls']['weather'], reverse('transit_view'))
        self.assertEqual(context['section_next_urls']['transit'], reverse('weather_view'))
        self.assertRedirects(self.client.get(reverse('slidedisplay')), reverse('weather_view'), fetch_redirect_response=False)

    @patch.object(Post, 'ensure_media_assets')
    def test_start_display_uses_first_section_and_media_return_does_not_loop(self, _assets):
        Post.objects.create(title='Test', content_type='custom', description='Hello')
        self.save_order(self.order)
        WeatherSlideConfig.load()
        WeatherSlideConfig.objects.update(is_visible=True)
        self.assertRedirects(self.client.get(reverse('slidedisplay')), reverse('weather_view'), fetch_redirect_response=False)
        response = self.client.get(reverse('slidedisplay') + '?section=media')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-section="media"')

    def test_round_trip_export_and_old_archive_defaults(self):
        self.save_order(self.order)
        manifest = build_site_manifest()
        replace_database_records(manifest)
        self.assertEqual(SlideLibraryConfig.load().ordered_sections, self.order)
        manifest.pop('slide_library_config')
        replace_database_records(manifest)
        self.assertEqual(SlideLibraryConfig.load().ordered_sections, default_library_sections())

    def test_paused_pages_do_not_install_section_keyboard_navigation(self):
        for name in ['weather_view_paused', 'calendar_view_paused', 'dateline_paused', 'transit_mobile']:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'js/section_navigation.js')

    def test_private_hook_is_not_publishable(self):
        self.assertTrue(private_path('scripts/extra_startup.sh'))
        self.assertFalse(private_path('scripts/extra_startup.sh.example'))
