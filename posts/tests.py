import json
import subprocess
import sys
from datetime import time, timedelta
from io import BytesIO
from pathlib import Path
import tempfile
import zipfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .media_processing import RENDITION_LAYOUT_VERSION, apply_image_edits
from .forms import TransitDashboardConfigForm
from .models import (
    BreakingNewsTickerConfig,
    CalendarSlideConfig,
    EmptyDisplayConfig,
    GeneratedSlideConfig,
    Post,
    ScreenPowerSchedule,
    SiteAppearanceSettings,
    TransitDashboardConfig,
    TransitRoute,
    WeatherSlideConfig,
)
from . import tasks
from . import views
from .site_migration import DATELINE_ARCHIVE_PATH
from scrape import Announcement


def build_test_image_upload(name="slide.png", size=(3840, 2160), color="#225577"):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def build_test_video_upload(name="clip.mp4"):
    return SimpleUploadedFile(name, b"fake-video-stream", content_type="video/mp4")


class ManageSlidesRouteTests(TestCase):
    def test_slide_library_renders_transit_animation_controls(self):
        user = get_user_model().objects.create_superuser(
            username="transit-admin", email="admin@example.com", password="test-pass-123",
        )
        route = TransitRoute.objects.create(code="TST", name="Test Shuttle", color="#123456")
        config = TransitDashboardConfig.objects.get_or_create(pk=TransitDashboardConfig.singleton_id)[0]
        config.selected_routes.set([route])
        self.client.force_login(user)

        response = self.client.get(reverse("manage_slides"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Map Zoom Animation")
        self.assertContains(response, 'name="animation_enabled"')
        self.assertContains(response, 'name="animation_easing"')
        self.assertContains(response, 'type="range" name="initial_delay_seconds" min="0" max="20"')
        self.assertContains(response, 'type="range" name="animation_end_offset_seconds" min="0" max="20"')
        self.assertContains(response, "transit-route-marker")
        self.assertContains(response, "TST · Test Shuttle")
        self.assertContains(response, "value > 0 ? 'E' : 'W'")
        self.assertContains(response, "value > 0 ? 'N' : 'S'")

    def test_manage_slides_reverse_uses_new_endpoint(self):
        self.assertEqual(reverse("manage_slides"), "/slide-library/")

    def test_legacy_manage_slides_redirects_to_slide_library(self):
        response = self.client.get("/manage-slides/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/slide-library/")

    def test_legacy_allimages_redirects_to_manage_slides(self):
        response = self.client.get("/allimages/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/slide-library/")

    def test_add_slide_reverse_uses_new_endpoint(self):
        self.assertEqual(reverse("add_slide"), "/add-slide/")

    def test_legacy_post_redirects_to_add_slide(self):
        response = self.client.get("/post/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/add-slide/")

    def test_settings_reverse_uses_new_endpoint(self):
        self.assertEqual(reverse("settings"), "/settings/")


class TransitIncomingArrivalTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.route = TransitRoute.objects.create(
            code="TEST", name="Test Route", color="#123456", provider_route_ids=[11, 12],
        )
        TransitDashboardConfig.objects.get_or_create(pk=TransitDashboardConfig.singleton_id)
        TransitDashboardConfig.objects.get(pk=TransitDashboardConfig.singleton_id).selected_routes.set([self.route])

    def test_paused_view_exposes_saved_side_panel_preferences(self):
        config = TransitDashboardConfig.objects.get(pk=TransitDashboardConfig.singleton_id)
        config.show_incoming_buses = False
        config.show_service_alerts = True
        config.side_panel_order = TransitDashboardConfig.PANEL_ALERTS_FIRST
        config.save()

        response = self.client.get(reverse("transit_view_paused"))

        self.assertContains(response, 'data-show-incoming="false"')
        self.assertContains(response, 'data-show-alerts="true"')
        self.assertContains(response, 'data-panel-order="alerts_first"')
        self.assertContains(response, 'data-map-layer="OpenStreetMap.Mapnik"')
        self.assertContains(response, 'data-display-duration="30"')
        self.assertContains(response, 'data-initial-delay="0"')
        self.assertContains(response, 'data-animation-end-offset="1"')
        self.assertContains(response, 'data-animation-enabled="true"')
        self.assertContains(response, 'data-animation-easing="smooth"')
        self.assertContains(response, 'data-initial-zoom-offset="0"')
        self.assertContains(response, 'data-initial-x-offset-meters="0"')
        self.assertContains(response, 'data-initial-y-offset-meters="0"')
        self.assertContains(response, 'data-final-zoom-offset="0"')
        self.assertContains(response, 'data-final-x-offset-meters="0"')
        self.assertContains(response, 'data-final-y-offset-meters="0"')
        self.assertContains(response, '<time class="map-status"')
        self.assertNotContains(response, "TAPS news")
        self.assertNotContains(response, "Select routes")

    def test_mobile_link_and_view_are_separate_from_slideshow(self):
        response = self.client.get(reverse("transit_view_paused"))
        self.assertContains(response, "http://pi-serv.rex-powan.ts.net/transit/mobile/")
        self.assertContains(response, reverse("transit_mobile_qr"))
        mobile = self.client.get(reverse("transit_mobile"))
        self.assertContains(mobile, 'class="mobile-view"')
        self.assertContains(mobile, 'id="route-picker"')
        self.assertContains(mobile, reverse("transit_mobile_map_data"))
        self.assertNotContains(mobile, 'http-equiv="refresh"')
        self.assertNotContains(mobile, 'class="mobile-qr"')
        self.assertContains(mobile, 'data-animation-enabled="false"')

    def test_initial_view_controls_remain_independent_of_animation(self):
        from bs4 import BeautifulSoup
        from django.forms.models import model_to_dict
        user = get_user_model().objects.create_user(username='transit-controls', password='test')
        self.client.force_login(user)
        response = self.client.get(reverse('manage_slides'))
        soup = BeautifulSoup(response.content, 'html.parser')
        for field in ('zoom', 'x', 'y'):
            self.assertIsNone(soup.select_one(f'#id_transit_initial_{field}_offset').find_parent(attrs={'data-animation-control': True}))
            self.assertIsNotNone(soup.select_one(f'#id_transit_{field}_offset').find_parent(attrs={'data-animation-control': True}))
        config = TransitDashboardConfig.load()
        data = model_to_dict(config)
        data.update(animation_enabled=False, initial_zoom_offset=2, initial_x_offset_meters=400, initial_y_offset_meters=-300)
        data['selected_routes'] = [self.route.pk]
        form = TransitDashboardConfigForm(data=data, instance=config)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        display = self.client.get(reverse('transit_view_paused'))
        self.assertContains(display, 'data-animation-enabled="false"')
        self.assertContains(display, 'data-initial-x-offset-meters="400"')

    def test_updated_timestamps_include_seconds(self):
        for name in ('transit_view_paused', 'transit_mobile'):
            self.assertContains(self.client.get(reverse(name)), 'second: "2-digit"')
        html = render_to_string('dateline_reader.html', {'paused_mode': True})
        self.assertIn('timeStyle: "medium"', html)

    def test_mobile_catalog_includes_unselected_active_routes_without_changing_display(self):
        extra = TransitRoute.objects.create(code="EXTRA", name="Extra Route", color="#445566", provider_route_ids=[99])
        routes, ids = views._transit_selected_routes(mobile=True)
        self.assertIn(extra, routes)
        self.assertIn(99, ids)
        display_routes, display_ids = views._transit_selected_routes()
        self.assertNotIn(extra, display_routes)
        self.assertNotIn(99, display_ids)

    def test_qr_is_locally_generated_png_for_the_saved_destination(self):
        import qrcode
        from .qr_codes import qr_variants
        qr_variants.cache_clear()
        appearance = SiteAppearanceSettings.load()
        appearance.public_base_url = 'https://example.com/campus'
        appearance.save()
        original_add_data = qrcode.QRCode.add_data
        targets = []
        def capture_data(qr, data, *args, **kwargs):
            targets.append(data)
            return original_add_data(qr, data, *args, **kwargs)
        with patch.object(qrcode.QRCode, "add_data", capture_data):
            response = self.client.get(reverse("transit_mobile_qr"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b'\x89PNG'))
        self.assertIn("https://example.com/campus/transit/mobile/", targets)
        self.assertEqual(response['Cache-Control'], 'no-cache')

    def test_qr_variants_have_integer_modules_and_quiet_zones(self):
        from io import BytesIO
        from PIL import Image
        import qrcode
        from .qr_codes import qr_variants, QR_TARGET_PIXELS
        text = 'http://pi-serv.rex-powan.ts.net/transit/mobile/'
        revision, modules, variants = qr_variants(text)
        reference = qrcode.QRCode(border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
        reference.add_data(text)
        reference.make(fit=True)
        matrix = reference.get_matrix()
        for target in QR_TARGET_PIXELS:
            self.assertTrue(any(width >= target for width in variants))
        for width, data in variants.items():
            image = Image.open(BytesIO(data)).convert('L')
            self.assertEqual(image.size, (width, width))
            self.assertEqual(width % modules, 0)
            scale = width // modules
            for y, row in enumerate(matrix):
                for x, black in enumerate(row):
                    block = image.crop((x * scale, y * scale, (x + 1) * scale, (y + 1) * scale))
                    self.assertEqual(block.getextrema(), (0, 0) if black else (255, 255))
        response = self.client.get(reverse('transit_mobile_qr'), {'size': next(iter(variants)), 'v': revision})
        self.assertEqual(response['Cache-Control'], 'public, max-age=86400')
        conditional = self.client.get(reverse('transit_mobile_qr'), {'size': next(iter(variants))}, HTTP_IF_NONE_MATCH=response['ETag'])
        self.assertEqual(conditional.status_code, 304)
        for size in ('bad', '-1', '99999999'):
            self.assertEqual(self.client.get(reverse('transit_mobile_qr'), {'size': size}).status_code, 400)

    def test_saved_url_change_revisions_qr_without_restart(self):
        before = self.client.get(reverse('transit_view_paused')).context['transit_qr_default']
        appearance = SiteAppearanceSettings.load()
        appearance.public_base_url = 'https://example.com'
        appearance.save()
        after = self.client.get(reverse('transit_view_paused'))
        self.assertNotEqual(before, after.context['transit_qr_default'])
        self.assertContains(after, 'https://example.com/transit/mobile/')

    def test_animation_end_offset_must_leave_room_after_initial_delay(self):
        data = {
            "duration_seconds": "30",
            "selected_routes": [],
            "map_layer": "OpenStreetMap.Mapnik",
            "animation_enabled": "on",
            "route_opacity_percent": "100",
            "animation_easing": TransitDashboardConfig.EASING_SMOOTH,
            "initial_delay_seconds": "10",
            "animation_end_offset_seconds": "5",
            "initial_zoom_offset": "0",
            "initial_x_offset_meters": "0",
            "initial_y_offset_meters": "0",
            "zoom_offset": "0",
            "x_offset_meters": "0",
            "y_offset_meters": "0",
            "side_panel_order": TransitDashboardConfig.PANEL_INCOMING_FIRST,
        }
        self.assertTrue(TransitDashboardConfigForm(data=data).is_valid())
        data["animation_end_offset_seconds"] = "20"
        form = TransitDashboardConfigForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("animation_end_offset_seconds", form.errors)
        data["animation_enabled"] = ""
        self.assertTrue(TransitDashboardConfigForm(data=data).is_valid())

    def test_live_data_returns_nearest_inbound_campus_eta_per_route(self):
        payloads = {
            "get_routes": {"get_routes": [
                {"id": 11, "name": "Test Route Inbound", "stops": ["101", "202"]},
                {"id": 12, "name": "Test Route Outbound", "stops": ["101"]},
            ]},
            "get_stops": {"get_stops": [
                {"id": 101, "name": "University Union", "lat": 42.0877, "lng": -75.9697},
                {"id": 202, "name": "Distant terminal", "lat": 42.12, "lng": -75.97},
            ]},
            "get_vehicles": {"get_vehicles": []},
            "get_stop_etas": {"get_stop_etas": [
                {"id": 101, "enRoute": [
                    {"routeID": 11, "minutes": 6},
                    {"routeID": 11, "minutes": 3},
                    {"routeID": 12, "minutes": 1},
                ]},
                {"id": 202, "enRoute": [{"routeID": 11, "minutes": 1}]},
            ]},
            "get_service_announcements": {"get_service_announcements": []},
        }

        def api_response(service, *, ttl, **kwargs):
            return payloads[service], True

        with patch.object(views, "_transit_api", side_effect=api_response):
            response = self.client.get(reverse("transit_live_data"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["vehiclesAvailable"])
        self.assertEqual(response.json()["incoming"], [{
            "routeCode": "TEST",
            "routeName": "Test Route",
            "color": "#123456",
            "stopName": "University Union",
            "minutes": 3,
        }])

    def test_vehicle_feed_failure_is_distinct_from_working_arrival_feed(self):
        def api_response(service, *, ttl, **kwargs):
            return {service: []}, service != "get_vehicles"

        with patch.object(views, "_transit_api", side_effect=api_response):
            response = self.client.get(reverse("transit_live_data"))

        self.assertTrue(response.json()["liveAvailable"])
        self.assertFalse(response.json()["vehiclesAvailable"])

    def test_legacy_manage_users_redirects_to_settings(self):
        response = self.client.get("/manage-users/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/settings/")


class ScreenPowerScheduleViewTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.superuser = self.user_model.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password123",
        )
        self.staff_user = self.user_model.objects.create_user(
            username="staffer",
            email="staff@example.com",
            password="password123",
            is_staff=True,
        )
        self.managed_user = self.user_model.objects.create_user(
            username="managed",
            email="managed@example.com",
            password="old-password123",
        )

    def test_settings_requires_superuser(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("settings"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].startswith(reverse("home")))

    def test_settings_shows_screen_power_schedule_form(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Site Settings")
        self.assertContains(response, "Screen Power Schedule")
        self.assertContains(response, "Password Management")
        self.assertContains(response, "Site Migration")
        self.assertContains(response, "Save Current Color")
        self.assertContains(response, "Create User")
        self.assertContains(response, 'name="screen_on_time"', html=False)
        self.assertContains(response, 'name="screen_off_time"', html=False)
        self.assertContains(response, 'name="new_password1"', html=False)
        self.assertContains(response, 'password-toggle-button', html=False)
        self.assertNotContains(response, "Your password can't be too similar")

    def test_update_screen_power_schedule_persists_times(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("update_screen_power_schedule"),
            {
                "screen_on_time": "07:15",
                "screen_off_time": "21:45",
            },
        )
        self.assertEqual(response.status_code, 302)

        schedule = ScreenPowerSchedule.load()
        self.assertEqual(schedule.screen_on_time, time(7, 15))
        self.assertEqual(schedule.screen_off_time, time(21, 45))
        self.assertEqual(ScreenPowerSchedule.objects.count(), 1)

    def test_reset_user_password_updates_selected_user(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("reset_user_password"),
            {
                "user": self.managed_user.pk,
                "new_password1": "new-secure-pass123",
                "new_password2": "new-secure-pass123",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.managed_user.refresh_from_db()
        self.assertTrue(self.managed_user.check_password("new-secure-pass123"))

    def test_reset_user_password_rejects_passwords_longer_than_20_chars(self):
        self.client.force_login(self.superuser)
        too_long_password = "a" * 21
        response = self.client.post(
            reverse("reset_user_password"),
            {
                "user": self.managed_user.pk,
                "new_password1": too_long_password,
                "new_password2": too_long_password,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Password could not be updated.")
        self.assertContains(response, "at most 20 characters")

    def test_update_site_appearance_persists_theme_color(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("update_site_appearance"),
            {
                "theme_color": "#114466",
                "public_base_url": "https://example.com/",
                "favorite_theme_colors": '["#114466","#AABBCC"]',
            },
        )
        self.assertEqual(response.status_code, 302)
        appearance = SiteAppearanceSettings.load()
        self.assertEqual(appearance.theme_color, "#114466")
        self.assertEqual(appearance.public_base_url, "https://example.com")
        self.assertEqual(appearance.favorite_theme_colors, ["#114466", "#AABBCC"])

    def test_public_url_rejects_non_web_schemes_and_credentials(self):
        from .forms import SiteAppearanceForm
        for url in ('ftp://example.com', 'https://user:secret@example.com', 'https://example.com/?key=x', 'https://example.com/#map'):
            form = SiteAppearanceForm(data={'public_base_url': url, 'theme_color': '#005A43'})
            self.assertFalse(form.is_valid())
            self.assertIn('public_base_url', form.errors)


class ScreenPowerTaskTests(TestCase):
    @patch("posts.tasks.cec_control.power_on")
    def test_turn_tv_on_uses_shared_cec_controller(self, mock_run):
        tasks.turn_tv_on()
        mock_run.assert_called_once_with()

    @patch("posts.tasks.cec_control.power_off")
    def test_turn_tv_off_uses_shared_cec_controller(self, mock_run):
        tasks.turn_tv_off()
        mock_run.assert_called_once_with()


class EmptyDisplayFallbackTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.superuser = self.user_model.objects.create_superuser(
            username="fallbackadmin",
            email="fallbackadmin@example.com",
            password="password123",
        )

    def test_update_empty_display_config_persists_mode(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("update_empty_display_config"),
            {"mode": EmptyDisplayConfig.WEATHER},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(EmptyDisplayConfig.load().mode, EmptyDisplayConfig.WEATHER)

    def test_slidedisplay_redirects_to_available_generated_slide_by_default(self):
        GeneratedSlideConfig.objects.update_or_create(
            scraper_name=GeneratedSlideConfig.DATELINE,
            defaults={"is_visible": False},
        )
        weather = WeatherSlideConfig.load()
        weather.is_visible = True
        weather.save()
        calendar = CalendarSlideConfig.load()
        calendar.is_visible = False
        calendar.public_url = ""
        calendar.save()

        response = self.client.get(reverse("slidedisplay"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], reverse("weather_view"))

    def test_slidedisplay_shows_message_only_when_no_other_sources_are_available(self):
        GeneratedSlideConfig.objects.update_or_create(
            scraper_name=GeneratedSlideConfig.DATELINE,
            defaults={"is_visible": False},
        )
        weather = WeatherSlideConfig.load()
        weather.is_visible = False
        weather.save()
        calendar = CalendarSlideConfig.load()
        calendar.is_visible = False
        calendar.public_url = ""
        calendar.save()

        response = self.client.get(reverse("slidedisplay"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No content uploaded yet.")

    def test_slidedisplay_respects_explicit_message_fallback(self):
        empty_display = EmptyDisplayConfig.load()
        empty_display.mode = EmptyDisplayConfig.MESSAGE
        empty_display.save()

        response = self.client.get(reverse("slidedisplay"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No content uploaded yet.")


class SlidePlaybackSettingsTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username="editor",
            email="editor@example.com",
            password="password123",
        )
        self.post = Post.objects.create(
            title="Test Slide",
            content_type="custom",
            description="Hello",
            duration_seconds=8,
            transition_type=Post.TRANSITION_CROSSFADE,
        )

    def test_update_slide_duration_persists_transition_type(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("update_slide_duration", args=[self.post.pk]),
            {
                "duration_seconds": "12",
                "transition_type": Post.TRANSITION_FADE_WHITE,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.post.refresh_from_db()
        self.assertEqual(self.post.duration_seconds, 12)
        self.assertEqual(self.post.transition_type, Post.TRANSITION_FADE_WHITE)

    def test_display_template_emits_transition_type(self):
        html = render_to_string(
            "display.html",
            {
                "posts": [self.post],
                "dateline_config": type("Cfg", (), {"is_visible": False})(),
                "weather_config": type("Cfg", (), {"is_visible": False})(),
                "calendar_slide_available": False,
            },
        )
        self.assertIn('data-transition-type="crossfade"', html)

    def test_display_template_emits_arrow_key_navigation(self):
        html = render_to_string(
            "display.html",
            {
                "posts": [self.post],
                "dateline_config": type("Cfg", (), {"is_visible": False})(),
                "weather_config": type("Cfg", (), {"is_visible": False})(),
                "calendar_slide_available": False,
            },
        )
        self.assertIn('window.addEventListener("keydown", handleKeyNavigation);', html)
        self.assertIn('event.key !== "ArrowRight" && event.key !== "ArrowLeft"', html)

    def test_manage_slides_template_emits_transition_choices(self):
        html = render_to_string(
            "uploaded_images.html",
            {
                "object_list": [self.post],
                "slide_transition_choices": Post.TRANSITION_CHOICES,
                "dateline_config": type(
                    "Cfg",
                    (),
                    {
                        "scraper_name": "dateline",
                        "is_visible": False,
                        "generated_slide_count": 3,
                        "duration_seconds": 8,
                        "transition_type": Post.TRANSITION_FADE_GRAY,
                    },
                )(),
                "weather_config": type("Cfg", (), {"is_visible": False, "overlay_source": "rainviewer", "map_layer": "osm_standard", "duration_seconds": 8})(),
                "calendar_config": type("Cfg", (), {"is_visible": False, "public_url": "", "duration_seconds": 8})(),
            },
        )
        self.assertIn('id="id_dateline_transition_type"', html)
        self.assertIn('name="transition_type"', html)
        self.assertIn("Fade to Gray", html)
        self.assertIn("Crossfade", html)


class EditRichTextSlideTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='rich-editor', password='test')
        self.slide = Post.objects.create(
            title='Existing announcement', content_type=Post.CONTENT_RICH_TEXT,
            description='<p>Hello</p><span data-qr-text="https://example.com" data-qr-size="192">QR code</span>',
            text_color='#123456', background_color='#FFFFFF', is_visible=False, display_order=7,
        )
        self.url = reverse('edit_rich_text_slide', args=[self.slide.pk])

    def test_edit_link_and_prefilled_editor(self):
        self.client.force_login(self.user)
        library = self.client.get(reverse('manage_slides'))
        self.assertContains(library, self.url)
        self.assertContains(library, 'Edit Rich Text')
        response = self.client.get(self.url)
        self.assertContains(response, '<h1 class="page-title">Edit Rich Text</h1>')
        self.assertContains(response, 'Save Changes')
        self.assertContains(response, 'id="insert-qr"')
        self.assertNotContains(response, 'data-tab-panel="media"')
        self.assertEqual(response.context['rich_text_form']['description'].value(), self.slide.description)
        self.assertEqual(response.context['rich_text_form']['text_color'].value(), '#123456')

    def test_save_updates_existing_slide_and_preserves_qr_order_visibility(self):
        from .rich_text import clean_rich_text
        self.client.force_login(self.user)
        original_description = self.slide.description
        response = self.client.post(self.url, {
            'rich-title': 'Updated announcement', 'rich-description': original_description,
            'rich-link': 'https://example.com/details', 'rich-text_color': '#112233',
            'rich-background_color': '#DDEEFF', 'rich-duration_seconds': '22',
            'rich-transition_type': Post.TRANSITION_FADE_BLACK,
        })
        self.assertRedirects(response, reverse('manage_slides'))
        self.assertEqual(Post.objects.count(), 1)
        self.slide.refresh_from_db()
        self.assertEqual(self.slide.description, clean_rich_text(original_description))
        self.assertEqual(self.slide.title, 'Updated announcement')
        self.assertEqual(self.slide.duration_seconds, 22)
        self.assertEqual(self.slide.text_color, '#112233')
        self.assertEqual(self.slide.background_color, '#DDEEFF')
        self.assertEqual(self.slide.display_order, 7)
        self.assertFalse(self.slide.is_visible)

    def test_invalid_edit_does_not_overwrite_saved_slide(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {'rich-title': 'Invalid', 'rich-description': ''})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['rich_text_form'].errors)
        self.slide.refresh_from_db()
        self.assertEqual(self.slide.title, 'Existing announcement')

    def test_requires_login_and_rejects_other_slide_types(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url, {}).status_code, 302)
        self.client.force_login(self.user)
        other = Post.objects.create(title='HTML', content_type=Post.CONTENT_HTML, description='<p>Hello</p>')
        self.assertEqual(self.client.get(reverse('edit_rich_text_slide', args=[other.pk])).status_code, 404)


class AddSlideViewTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username="creator",
            email="creator@example.com",
            password="password123",
        )

    def test_add_slide_page_shows_tabs(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("add_slide"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add Slide")
        self.assertContains(response, "Media")
        self.assertContains(response, "Rich Text")
        self.assertContains(response, "YouTube")
        self.assertContains(response, "Google Slides")
        self.assertContains(response, "Custom HTML")
        self.assertContains(response, "Choose File")
        self.assertContains(response, 'id="insert-qr"')
        self.assertContains(response, reverse('rich_text_qr'))

    def test_rich_qr_generation_requires_login_and_post(self):
        url = reverse('rich_text_qr')
        self.assertEqual(self.client.post(url, {'text': 'hello'}).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 405)
        for data in ({'text': ''}, {'text': 'x' * 513}, {'text': 'hello', 'size': '999999'}):
            self.assertEqual(self.client.post(url, data).status_code, 400)

    def test_rich_qr_survives_save_and_renders_in_display(self):
        from .rich_text import clean_rich_text, render_rich_text
        from bs4 import BeautifulSoup
        self.client.force_login(self.user)
        response = self.client.post(reverse('rich_text_qr'), {'text': 'https://example.com/?a=1&b=2', 'size': '192'})
        self.assertEqual(response.status_code, 200)
        markup = response.json()['html']
        self.assertIn('data:image/png;base64,', markup)
        response = self.client.post(reverse('add_slide'), {
            'rich_submit': '1', 'rich-title': 'QR announcement', 'rich-description': markup,
            'rich-text_color': '#112233', 'rich-background_color': '#ffffff',
            'rich-duration_seconds': '15', 'rich-transition_type': Post.TRANSITION_FADE_BLACK,
        })
        self.assertEqual(response.status_code, 302)
        post = Post.objects.get(title='QR announcement')
        self.assertNotIn('<img', post.description)
        self.assertLess(len(post.description), 200)
        self.assertEqual(clean_rich_text(post.description), post.description)
        rendered = render_rich_text(post.description)
        soup = BeautifulSoup(rendered, 'html.parser')
        self.assertEqual(soup.span['data-qr-text'], 'https://example.com/?a=1&b=2')
        self.assertTrue(soup.img['src'].startswith('data:image/png;base64,'))
        display = render_to_string('display.html', {'posts': [post]})
        self.assertIn('data-qr-modules=', display)

    def test_rich_qr_does_not_allow_injected_image_or_script(self):
        from .rich_text import clean_rich_text, render_rich_text
        from django.core.exceptions import ValidationError
        from bs4 import BeautifulSoup
        markup = '<p onclick="alert(1)">Hello<img src="https://evil.test/x" onerror="alert(1)"></p><span data-qr-text="&lt;script&gt;alert(1)&lt;/script&gt;" style="position:fixed">QR</span>'
        saved = clean_rich_text(markup)
        rendered = BeautifulSoup(render_rich_text(saved), 'html.parser')
        self.assertFalse(rendered.select('[onclick], [onerror], script'))
        self.assertTrue(all(image['src'].startswith('data:image/png;base64,') for image in rendered.find_all('img')))
        with self.assertRaises(ValidationError):
            clean_rich_text('<span data-qr-text="hello">QR</span>' * 9)

    def test_rich_text_upload_persists_colors(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("add_slide"),
            {
                "rich_submit": "1",
                "rich-title": "Campus Update",
                "rich-description": "<p>Important update</p>",
                "rich-link": "https://example.com/update",
                "rich-text_color": "#112233",
                "rich-background_color": "#ddeeff",
                "rich-duration_seconds": "15",
                "rich-transition_type": Post.TRANSITION_FADE_BLACK,
            },
        )
        self.assertEqual(response.status_code, 302)
        post = Post.objects.get(title="Campus Update")
        self.assertEqual(post.content_type, Post.CONTENT_RICH_TEXT)
        self.assertEqual(post.text_color, "#112233")
        self.assertEqual(post.background_color, "#ddeeff")
        self.assertEqual(post.duration_seconds, 15)
        self.assertEqual(post.transition_type, Post.TRANSITION_FADE_BLACK)

    def test_custom_html_upload_persists_markup_without_filtering(self):
        self.client.force_login(self.user)
        markup = "<section><script>window.slideBooted = true;</script><h1>HTML slide</h1></section>"
        response = self.client.post(
            reverse("add_slide"),
            {
                "html_submit": "1",
                "html-title": "Custom Embed",
                "html-description": markup,
                "html-duration_seconds": "18",
                "html-transition_type": Post.TRANSITION_CROSSFADE,
            },
        )
        self.assertEqual(response.status_code, 302)
        post = Post.objects.get(title="Custom Embed")
        self.assertEqual(post.content_type, Post.CONTENT_HTML)
        self.assertEqual(post.description, markup)

    def test_custom_html_slide_can_be_edited_after_creation(self):
        post = Post.objects.create(
            title="Custom Embed",
            content_type=Post.CONTENT_HTML,
            description="<h1>Old</h1>",
            duration_seconds=8,
            transition_type=Post.TRANSITION_CROSSFADE,
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("edit_html_slide", args=[post.pk]),
            {
                "title": "Custom Embed Updated",
                "description": "<style>body{background:black}</style><h1>New</h1>",
                "duration_seconds": "14",
                "transition_type": Post.TRANSITION_FADE_WHITE,
            },
        )
        self.assertEqual(response.status_code, 302)

        post.refresh_from_db()
        self.assertEqual(post.title, "Custom Embed Updated")
        self.assertIn("<h1>New</h1>", post.description)
        self.assertEqual(post.duration_seconds, 14)
        self.assertEqual(post.transition_type, Post.TRANSITION_FADE_WHITE)

    def test_youtube_upload_persists_clip_settings(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("add_slide"),
            {
                "youtube_submit": "1",
                "youtube-title": "Morning Update",
                "youtube-youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "youtube-youtube_start_seconds": "12",
                "youtube-youtube_end_seconds": "25",
                "youtube-youtube_quality": Post.YOUTUBE_QUALITY_1080,
                "youtube-youtube_show_captions": "on",
                "youtube-duration_seconds": "13",
                "youtube-transition_type": Post.TRANSITION_CROSSFADE,
            },
        )
        self.assertEqual(response.status_code, 302)
        post = Post.objects.get(title="Morning Update")
        self.assertEqual(post.content_type, Post.CONTENT_YOUTUBE)
        self.assertEqual(post.youtube_start_seconds, 12)
        self.assertEqual(post.youtube_end_seconds, 25)
        self.assertEqual(post.youtube_quality, Post.YOUTUBE_QUALITY_1080)
        self.assertTrue(post.youtube_show_captions)
        self.assertEqual(post.preview_url, "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg")

    def test_google_slides_upload_persists_range_and_computed_duration(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("add_slide"),
            {
                "google_slides_submit": "1",
                "gslides-title": "Faculty Deck",
                "gslides-google_slides_url": "https://docs.google.com/presentation/d/e/2PACX-demo123/embed?start=false&loop=false&delayms=3000",
                "gslides-google_slides_start_slide": "3",
                "gslides-google_slides_end_slide": "5",
                "gslides-google_slides_advance_seconds": "9",
                "gslides-transition_type": Post.TRANSITION_FADE_WHITE,
            },
        )
        self.assertEqual(response.status_code, 302)

        post = Post.objects.get(title="Faculty Deck")
        self.assertEqual(post.content_type, Post.CONTENT_GOOGLE_SLIDES)
        self.assertEqual(post.google_slides_start_slide, 3)
        self.assertEqual(post.google_slides_end_slide, 5)
        self.assertEqual(post.google_slides_advance_seconds, 9)
        self.assertEqual(post.duration_seconds, 27)
        self.assertEqual(post.transition_type, Post.TRANSITION_FADE_WHITE)
        self.assertIn("/presentation/d/e/2PACX-demo123/embed", post.google_slides_url)
        self.assertIn("delayms=9000", post.google_slides_embed_url)
        self.assertIn("#slide=id.p3", post.google_slides_embed_url)

    def test_google_slides_edit_updates_range_and_duration(self):
        post = Post.objects.create(
            title="Campus Deck",
            content_type=Post.CONTENT_GOOGLE_SLIDES,
            google_slides_url="https://docs.google.com/presentation/d/e/2PACX-olddeck/embed?start=false&loop=false&delayms=5000",
            google_slides_start_slide=1,
            google_slides_end_slide=2,
            google_slides_advance_seconds=5,
            transition_type=Post.TRANSITION_CROSSFADE,
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("edit_google_slides_slide", args=[post.pk]),
            {
                "title": "Campus Deck Updated",
                "google_slides_url": "https://docs.google.com/presentation/d/e/2PACX-newdeck/pub?start=false&loop=false&delayms=3000",
                "google_slides_start_slide": "4",
                "google_slides_end_slide": "7",
                "google_slides_advance_seconds": "6",
                "transition_type": Post.TRANSITION_FADE_BLACK,
            },
        )
        self.assertEqual(response.status_code, 302)

        post.refresh_from_db()
        self.assertEqual(post.title, "Campus Deck Updated")
        self.assertEqual(post.google_slides_start_slide, 4)
        self.assertEqual(post.google_slides_end_slide, 7)
        self.assertEqual(post.google_slides_advance_seconds, 6)
        self.assertEqual(post.duration_seconds, 24)
        self.assertEqual(post.transition_type, Post.TRANSITION_FADE_BLACK)


class MediaDerivativeTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_root.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.override.enable()
        self.addCleanup(self.override.disable)

        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username="assets",
            email="assets@example.com",
            password="password123",
        )

    def test_image_slide_generates_thumbnail_and_renditions(self):
        post = Post.objects.create(
            title="Campus Poster",
            content_type=Post.CONTENT_IMAGE,
            cover=build_test_image_upload(),
        )

        post.refresh_from_db()
        self.assertTrue(post.preview_image.name.endswith("thumbnail_250w.webp"))
        self.assertGreaterEqual(post.media_revision, 1)
        self.assertEqual(post.media_variants["layout_version"], RENDITION_LAYOUT_VERSION)
        self.assertTrue(post.media_variants["display"])
        self.assertTrue(post.media_variants["editor_preview"]["path"].endswith("editor_preview_600w.webp"))
        self.assertTrue(any(variant["width"] == 1920 for variant in post.media_variants["display"]))
        self.assertTrue((Path(self.media_root.name) / post.preview_image.name).exists())

    def test_image_renditions_preserve_full_poster_without_padding(self):
        post = Post.objects.create(
            title="Tall-ish Poster",
            content_type=Post.CONTENT_IMAGE,
            cover=build_test_image_upload(name="tallish.png", size=(15300, 9900)),
        )

        post.refresh_from_db()
        rendition = next(variant for variant in post.media_variants["display"] if variant["label"] == "1080p")
        self.assertEqual(rendition["height"], 1080)
        self.assertLess(rendition["width"], 1920)

        with Image.open(Path(self.media_root.name) / rendition["path"]) as generated:
            self.assertEqual(generated.size, (rendition["width"], rendition["height"]))
            corner_pixel = generated.convert("RGB").getpixel((0, 0))
            self.assertTrue(all(abs(actual - expected) <= 3 for actual, expected in zip(corner_pixel, (34, 85, 119))))

    def test_missing_generated_image_file_rebuilds_assets(self):
        post = Post.objects.create(
            title="Recover Poster",
            content_type=Post.CONTENT_IMAGE,
            cover=build_test_image_upload(name="recover.png"),
        )

        post.refresh_from_db()
        revision_before = post.media_revision
        rendition = next(variant for variant in post.media_variants["display"] if variant["label"] == "1080p")
        missing_path = Path(self.media_root.name) / rendition["path"]
        missing_path.unlink()

        post.ensure_media_assets()
        post.refresh_from_db()

        self.assertGreater(post.media_revision, revision_before)
        rebuilt_rendition = next(variant for variant in post.media_variants["display"] if variant["label"] == "1080p")
        self.assertTrue((Path(self.media_root.name) / rebuilt_rendition["path"]).exists())

    def test_display_template_starts_images_from_display_rendition_not_thumbnail(self):
        post = Post.objects.create(
            title="Huge Poster",
            content_type=Post.CONTENT_IMAGE,
            cover=build_test_image_upload(name="huge.png"),
        )

        html = render_to_string(
            "display.html",
            {
                "posts": [post],
                "dateline_config": type("Cfg", (), {"is_visible": False})(),
                "weather_config": type("Cfg", (), {"is_visible": False})(),
                "calendar_slide_available": False,
            },
        )

        self.assertIn(f'src="{post.initial_display_url}"', html)
        self.assertIn('srcset="', html)
        self.assertIn("screen_1920x1080.webp", html)
        self.assertNotIn(f'src="{post.preview_url}"', html)

    def test_manage_slides_uses_sharp_library_preview_and_title_header(self):
        post = Post.objects.create(
            title="Preview Poster",
            content_type=Post.CONTENT_IMAGE,
            cover=build_test_image_upload(name="preview.png"),
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("manage_slides"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<th>Title</th>", html=False)
        self.assertContains(response, f'src="{post.slide_library_preview_url}"', html=False)
        self.assertNotContains(response, f'src="{post.preview_url}"', html=False)
        self.assertContains(response, reverse("edit_slide_image", args=[post.pk]))

    def test_image_edit_view_uses_lightweight_editor_preview(self):
        post = Post.objects.create(
            title="Editor Preview Poster",
            content_type=Post.CONTENT_IMAGE,
            cover=build_test_image_upload(name="editor-preview.png"),
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("edit_slide_image", args=[post.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "editor_preview_600w.webp")

    def test_image_edit_view_includes_processing_modal_and_crop_cleanup_logic(self):
        post = Post.objects.create(
            title="Editor Modal Poster",
            content_type=Post.CONTENT_IMAGE,
            cover=build_test_image_upload(name="editor-modal.png"),
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("edit_slide_image", args=[post.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Images processing, please wait")
        self.assertContains(response, "const shouldShow = Boolean(cropRect) && cropMode;")

    def test_manage_slides_hides_custom_html_code_and_shows_edit_action(self):
        post = Post.objects.create(
            title="Secret HTML",
            content_type=Post.CONTENT_HTML,
            description="<script>window.secretValue = 42;</script><h1>Hidden code</h1>",
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("manage_slides"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "&lt; html /&gt;", html=False)
        self.assertContains(response, reverse("edit_html_slide", args=[post.pk]))
        self.assertNotContains(response, "window.secretValue")

    def test_manage_slides_shows_google_slides_badges_and_edit_action(self):
        post = Post.objects.create(
            title="Semester Deck",
            content_type=Post.CONTENT_GOOGLE_SLIDES,
            google_slides_url="https://docs.google.com/presentation/d/e/2PACX-semester/embed?start=false&loop=false&delayms=4000",
            google_slides_start_slide=2,
            google_slides_end_slide=4,
            google_slides_advance_seconds=7,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("manage_slides"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Google Slides")
        self.assertContains(response, "Slides 2-4")
        self.assertContains(response, "21s total")
        self.assertContains(response, reverse("edit_google_slides_slide", args=[post.pk]))

    def test_display_template_mounts_google_slides_iframe(self):
        post = Post.objects.create(
            title="Lobby Deck",
            content_type=Post.CONTENT_GOOGLE_SLIDES,
            google_slides_url="https://docs.google.com/presentation/d/e/2PACX-lobby/embed?start=false&loop=false&delayms=3000",
            google_slides_start_slide=5,
            google_slides_end_slide=5,
            google_slides_advance_seconds=12,
        )

        html = render_to_string(
            "display.html",
            {
                "posts": [post],
                "dateline_config": type("Cfg", (), {"is_visible": False})(),
                "weather_config": type("Cfg", (), {"is_visible": False})(),
                "calendar_slide_available": False,
            },
        )

        self.assertIn('class="google-slides-shell"', html)
        self.assertIn(post.google_slides_embed_url.replace("&", "&amp;"), html)

    @patch("posts.models.build_video_thumbnail")
    def test_video_slide_generates_preview_thumbnail_only(self, mock_build_video_thumbnail):
        mock_build_video_thumbnail.return_value = {
            "thumbnail": "thumbnail_250w.jpg",
            "display": [],
            "animated": False,
            "kind": "video",
        }

        post = Post.objects.create(
            title="Morning Bulletin",
            content_type=Post.CONTENT_VIDEO,
            cover=build_test_video_upload(),
        )

        post.refresh_from_db()
        self.assertTrue(post.preview_image.name.endswith("thumbnail_250w.jpg"))
        self.assertEqual(post.media_variants["kind"], "video")
        self.assertEqual(post.media_variants["display"], [])
        self.assertTrue(post.display_renditions[0]["url"].endswith("clip.mp4?v=1"))

    def test_youtube_slide_builds_embed_url(self):
        post = Post.objects.create(
            title="Clip",
            content_type=Post.CONTENT_YOUTUBE,
            youtube_url="https://youtu.be/dQw4w9WgXcQ",
            youtube_start_seconds=5,
            youtube_end_seconds=17,
            youtube_quality=Post.YOUTUBE_QUALITY_720,
            youtube_show_captions=True,
        )

        self.assertEqual(post.youtube_video_id, "dQw4w9WgXcQ")
        self.assertIn("youtube-nocookie.com/embed/dQw4w9WgXcQ", post.youtube_embed_url)
        self.assertIn("start=5", post.youtube_embed_url)
        self.assertIn("end=17", post.youtube_embed_url)
        self.assertIn("vq=hd720", post.youtube_embed_url)
        self.assertIn("cc_load_policy=1", post.youtube_embed_url)

    def test_update_slide_title_renames_slide(self):
        post = Post.objects.create(
            title="Old Slide Name",
            content_type=Post.CONTENT_RICH_TEXT,
            description="Body copy",
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("update_slide_title", args=[post.pk]),
            {"title": "New Slide Name"},
        )
        self.assertEqual(response.status_code, 302)
        post.refresh_from_db()
        self.assertEqual(post.title, "New Slide Name")

    def test_image_edit_view_saves_rendition_only_changes(self):
        post = Post.objects.create(
            title="Edited Poster",
            content_type=Post.CONTENT_IMAGE,
            cover=build_test_image_upload(name="edited.png"),
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("edit_slide_image", args=[post.pk]),
            {
                "rotation_degrees": "90",
                "crop_left_percent": "5",
                "crop_top_percent": "0",
                "crop_width_percent": "90",
                "crop_height_percent": "100",
                "overlay_text": "Campus",
                "overlay_position": "bottom_center",
                "overlay_text_color": "#FFFFFF",
                "overlay_size_percent": "6",
            },
        )
        self.assertEqual(response.status_code, 302)

        post.refresh_from_db()
        self.assertEqual(post.image_edit_settings["rotation_degrees"], 90)
        self.assertEqual(post.image_edit_settings["overlay_text"], "Campus")
        self.assertTrue(post.has_image_edits)
        self.assertTrue(post.media_variants["display"][0]["path"].endswith("screen_native.webp"))
        self.assertTrue((Path(self.media_root.name) / post.preview_image.name).exists())

    def test_image_edit_view_can_revert_saved_changes(self):
        post = Post.objects.create(
            title="Revert Poster",
            content_type=Post.CONTENT_IMAGE,
            cover=build_test_image_upload(name="revert.png"),
            image_edit_settings={
                "rotation_degrees": 180,
                "crop_left_percent": 10,
                "crop_top_percent": 10,
                "crop_width_percent": 80,
                "crop_height_percent": 80,
                "overlay_text": "Text",
                "overlay_position": "center",
                "overlay_text_color": "#FFFFFF",
                "overlay_size_percent": 6,
            },
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("edit_slide_image", args=[post.pk]),
            {"revert_image_edits": "1"},
        )
        self.assertEqual(response.status_code, 302)

        post.refresh_from_db()
        self.assertEqual(post.image_edit_settings, {})
        self.assertFalse(post.has_image_edits)

    def test_image_edit_view_clamps_crop_values_instead_of_erroring(self):
        post = Post.objects.create(
            title="Clamp Poster",
            content_type=Post.CONTENT_IMAGE,
            cover=build_test_image_upload(name="clamp.png"),
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("edit_slide_image", args=[post.pk]),
            {
                "rotation_degrees": "0",
                "crop_left_percent": "60",
                "crop_top_percent": "55",
                "crop_width_percent": "80",
                "crop_height_percent": "80",
                "overlay_text": "",
                "overlay_position": "bottom_center",
                "overlay_text_color": "#FFFFFF",
                "overlay_size_percent": "6",
            },
        )
        self.assertEqual(response.status_code, 302)

        post.refresh_from_db()
        self.assertEqual(post.image_edit_settings["crop_width_percent"], 40.0)
        self.assertEqual(post.image_edit_settings["crop_height_percent"], 45.0)

    def test_image_edit_view_accepts_comma_decimal_values(self):
        post = Post.objects.create(
            title="Comma Poster",
            content_type=Post.CONTENT_IMAGE,
            cover=build_test_image_upload(name="comma.png"),
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("edit_slide_image", args=[post.pk]),
            {
                "rotation_degrees": "0",
                "crop_left_percent": "0",
                "crop_top_percent": "0",
                "crop_width_percent": "99,5",
                "crop_height_percent": "91,0",
                "overlay_text": "",
                "overlay_position": "bottom_center",
                "overlay_text_color": "#FFFFFF",
                "overlay_size_percent": "6",
            },
        )
        self.assertEqual(response.status_code, 302)

        post.refresh_from_db()
        self.assertEqual(post.image_edit_settings["crop_width_percent"], 99.5)
        self.assertEqual(post.image_edit_settings["crop_height_percent"], 91.0)

    def test_image_edit_view_persists_free_rotation_and_font_choice(self):
        post = Post.objects.create(
            title="Free Rotate Poster",
            content_type=Post.CONTENT_IMAGE,
            cover=build_test_image_upload(name="free-rotate.png"),
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("edit_slide_image", args=[post.pk]),
            {
                "rotation_degrees": "-37.5",
                "crop_left_percent": "12",
                "crop_top_percent": "8",
                "crop_width_percent": "70",
                "crop_height_percent": "72",
                "overlay_text": "Campus",
                "overlay_position": "center_right",
                "overlay_font_family": "serif",
                "overlay_text_color": "#FFFFFF",
                "overlay_size_percent": "9",
            },
        )
        self.assertEqual(response.status_code, 302)

        post.refresh_from_db()
        self.assertEqual(post.image_edit_settings["rotation_degrees"], -37.5)
        self.assertEqual(post.image_edit_settings["overlay_font_family"], "serif")
        self.assertTrue(post.has_image_edits)

    def test_apply_image_edits_renders_visible_overlay_text_pixels(self):
        rendered = apply_image_edits(
            Image.new("RGB", (800, 450), "#225577"),
            {
                "overlay_text": "Campus",
                "overlay_position": "bottom_center",
                "overlay_font_family": "mono",
                "overlay_text_color": "#FFFFFF",
                "overlay_size_percent": 12,
            },
        )

        bright_pixels = sum(
            1
            for red, green, blue in rendered.getdata()
            if red >= 235 and green >= 235 and blue >= 235
        )
        self.assertGreater(bright_pixels, 100)


class SlideOrderingTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username="sorter",
            email="sorter@example.com",
            password="password123",
        )
        self.post_one = Post.objects.create(title="One", content_type="custom", description="one")
        self.post_two = Post.objects.create(title="Two", content_type="custom", description="two")
        self.post_three = Post.objects.create(title="Three", content_type="custom", description="three")

    def test_reorder_slides_persists_display_order(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("reorder_slides"),
            data=json.dumps({"ordered_ids": [self.post_three.pk, self.post_one.pk, self.post_two.pk]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        ordered_ids = list(Post.objects.order_by("display_order", "id").values_list("id", flat=True))
        self.assertEqual(ordered_ids, [self.post_three.pk, self.post_one.pk, self.post_two.pk])

    def test_manage_slides_view_uses_display_order(self):
        self.post_three.display_order = 1
        self.post_three.save(update_fields=["display_order"])
        self.post_one.display_order = 2
        self.post_one.save(update_fields=["display_order"])
        self.post_two.display_order = 3
        self.post_two.save(update_fields=["display_order"])

        self.client.force_login(self.user)
        response = self.client.get(reverse("manage_slides"))
        self.assertEqual(response.status_code, 200)
        object_list = list(response.context["object_list"])
        self.assertEqual([post.pk for post in object_list], [self.post_three.pk, self.post_one.pk, self.post_two.pk])

    def test_update_slide_visibility_hides_slide_from_slideshow(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("update_slide_visibility", args=[self.post_two.pk]),
            {"is_visible": "0"},
        )
        self.assertEqual(response.status_code, 302)
        self.post_two.refresh_from_db()
        self.assertFalse(self.post_two.is_visible)

        slideshow_response = self.client.get(reverse("slidedisplay"))
        self.assertEqual(slideshow_response.status_code, 200)
        visible_ids = [post.pk for post in slideshow_response.context["posts"]]
        self.assertEqual(visible_ids, [self.post_one.pk, self.post_three.pk])

    def test_manage_slides_shows_display_toggle_button(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("manage_slides"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hide from Display")


class GeneratedSlideSettingsTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username="manager",
            email="manager@example.com",
            password="password123",
        )
        self.config, _ = GeneratedSlideConfig.objects.get_or_create(
            scraper_name=GeneratedSlideConfig.DATELINE,
            defaults={
                "is_visible": True,
                "generated_slide_count": 3,
                "duration_seconds": 8,
                "transition_type": Post.TRANSITION_CROSSFADE,
            },
        )

    def test_update_generated_slide_config_persists_transition_type(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("update_generated_slide_config", args=[GeneratedSlideConfig.DATELINE]),
            {
                "is_visible": "on",
                "generated_slide_count": "4",
                "duration_seconds": "11",
                "transition_type": Post.TRANSITION_FADE_BLACK,
                "overflow_mode": GeneratedSlideConfig.OVERFLOW_CLIP,
                "scroll_speed": "80",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.config.refresh_from_db()
        self.assertEqual(self.config.generated_slide_count, 4)
        self.assertEqual(self.config.duration_seconds, 11)
        self.assertEqual(self.config.transition_type, Post.TRANSITION_FADE_BLACK)

    def test_dateline_template_emits_transition_type(self):
        html = render_to_string(
            "dateline_reader.html",
            {
                "dateline_config": type(
                    "Cfg",
                    (),
                    {
                        "is_visible": True,
                        "generated_slide_count": 3,
                        "duration_seconds": 8,
                        "transition_type": Post.TRANSITION_FADE_WHITE,
                    },
                )(),
                "weather_config": type("Cfg", (), {"is_visible": False})(),
                "calendar_slide_available": False,
            },
        )
        self.assertIn('const ANNOUNCEMENT_TRANSITION = "fade_white";', html)


class BreakingNewsTickerSettingsTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username="tickeradmin",
            email="tickeradmin@example.com",
            password="password123",
        )
        self.dateline_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.dateline_root.cleanup)
        self.dateline_path = Path(self.dateline_root.name) / "dateline_announcements.json"
        self.dateline_path.write_text(
            json.dumps(
                {
                    "fetched_at": timezone.now().isoformat(),
                    "announcements": [
                        {"title": "Campus Update", "body": "Body one"},
                        {"title": "Library Hours", "body": "Body two"},
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_update_breaking_news_ticker_config_persists_settings(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("update_breaking_news_ticker_config"),
            {
                "mode": BreakingNewsTickerConfig.MODE_ON,
                "include_dateline_titles": "on",
                "include_weather_alerts": "on",
                "include_custom_text": "on",
                "custom_text": "Welcome to campus",
                "scroll_speed": "145",
                "font_family": BreakingNewsTickerConfig.FONT_GEORGIA,
                "font_size": "28",
                "text_color": "#F8FAFC",
                "background_color": "#005A43",
            },
        )
        self.assertEqual(response.status_code, 302)
        config = BreakingNewsTickerConfig.load()
        self.assertEqual(config.mode, BreakingNewsTickerConfig.MODE_ON)
        self.assertTrue(config.include_dateline_titles)
        self.assertTrue(config.include_weather_alerts)
        self.assertTrue(config.include_custom_text)
        self.assertEqual(config.custom_text, "Welcome to campus")
        self.assertEqual(config.scroll_speed, 145)
        self.assertEqual(config.font_family, BreakingNewsTickerConfig.FONT_GEORGIA)
        self.assertEqual(config.font_size, 28)
        self.assertEqual(config.text_color, "#F8FAFC")
        self.assertEqual(config.background_color, "#005A43")

    def test_breaking_news_ticker_feed_includes_dateline_weather_and_custom_text(self):
        config = BreakingNewsTickerConfig.load()
        config.mode = BreakingNewsTickerConfig.MODE_ON
        config.include_dateline_titles = True
        config.include_weather_alerts = True
        config.include_custom_text = True
        config.custom_text = "Custom banner"
        config.save()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(
                    {
                        "features": [
                            {"properties": {"headline": "Severe Thunderstorm Warning"}},
                        ]
                    }
                ).encode("utf-8")

        with patch("posts.views.dateline_json_path", return_value=self.dateline_path):
            with patch("posts.views.urlopen", return_value=FakeResponse()):
                response = self.client.get(reverse("breaking_news_ticker_feed"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["enabled"])
        self.assertIn("Dateline: Campus Update", payload["items"])
        self.assertIn("Dateline: Library Hours", payload["items"])
        self.assertIn("Weather Alert: Severe Thunderstorm Warning", payload["items"])
        self.assertIn("Custom banner", payload["items"])

    def test_breaking_news_ticker_feed_reports_no_weather_alert(self):
        config = BreakingNewsTickerConfig.load()
        config.mode = BreakingNewsTickerConfig.MODE_ON
        config.include_weather_alerts = True
        config.save()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"features": []}).encode("utf-8")

        with patch("posts.views.urlopen", return_value=FakeResponse()):
            response = self.client.get(reverse("breaking_news_ticker_feed"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["items"], ["No weather alert"])


class HomeNavigationTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.superuser = self.user_model.objects.create_superuser(
            username="navadmin",
            email="navadmin@example.com",
            password="password123",
        )

    def test_authenticated_home_shows_nav_cards_without_password_reset(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add Slide")
        self.assertContains(response, "Settings")
        self.assertContains(response, "Log Out")
        self.assertNotContains(response, "Manage Users")
        self.assertNotContains(response, "Password Reset")


class DatelineFetchTests(TestCase):
    def setUp(self):
        self.dateline_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.dateline_root.cleanup)
        self.dateline_path = Path(self.dateline_root.name) / "dateline_announcements.json"

    def test_dateline_template_renders_fetched_at_footer(self):
        html = render_to_string(
            "dateline_reader.html",
            {
                "dateline_config": type(
                    "Cfg",
                    (),
                    {
                        "is_visible": True,
                        "generated_slide_count": 3,
                        "duration_seconds": 8,
                        "transition_type": Post.TRANSITION_CROSSFADE,
                    },
                )(),
                "weather_config": type("Cfg", (), {"is_visible": False})(),
                "calendar_slide_available": False,
            },
        )
        self.assertIn('class="fetched-at">Fetched on: --</div>', html)
        self.assertIn('function formatFetchedOn(value)', html)

    def test_fetch_json_view_returns_fresh_cached_payload_without_refresh(self):
        self.dateline_path.write_text(
            json.dumps(
                {
                    "fetched_at": timezone.now().isoformat(),
                    "announcements": [{"title": "Fresh item", "body": "Already cached"}],
                }
            ),
            encoding="utf-8",
        )

        with patch("posts.views.dateline_json_path", return_value=self.dateline_path):
            with patch("posts.views.scrape_dateline") as mock_scrape:
                response = self.client.get(reverse("getjson"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["announcements"][0]["title"], "Fresh item")
        self.assertFalse(payload["is_stale"])
        mock_scrape.assert_not_called()

    def test_fetch_json_view_uses_file_timestamp_for_legacy_array_payload(self):
        self.dateline_path.write_text(
            json.dumps([{"title": "Legacy item", "body": "Older export format"}]),
            encoding="utf-8",
        )

        with patch("posts.views.dateline_json_path", return_value=self.dateline_path):
            with patch("posts.views.scrape_dateline") as mock_scrape:
                response = self.client.get(reverse("getjson"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["announcements"][0]["title"], "Legacy item")
        self.assertIn("fetched_at", payload)
        self.assertFalse(payload["is_stale"])
        mock_scrape.assert_not_called()

    def test_fetch_json_view_refreshes_when_payload_is_older_than_a_day(self):
        self.dateline_path.write_text(
            json.dumps(
                {
                    "fetched_at": (timezone.now() - timedelta(days=2)).isoformat(),
                    "announcements": [{"title": "Old item", "body": "Stale"}],
                }
            ),
            encoding="utf-8",
        )

        with patch("posts.views.dateline_json_path", return_value=self.dateline_path):
            with patch(
                "posts.views.scrape_dateline",
                return_value=[Announcement(category="News", title="Fresh item", body="Updated", links=[])],
            ) as mock_scrape:
                response = self.client.get(reverse("getjson"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["announcements"][0]["title"], "Fresh item")
        self.assertFalse(payload["is_stale"])
        mock_scrape.assert_called_once()

        saved_payload = json.loads(self.dateline_path.read_text(encoding="utf-8"))
        self.assertEqual(saved_payload["announcements"][0]["title"], "Fresh item")
        self.assertIn("fetched_at", saved_payload)

    def test_fetch_json_view_falls_back_to_stale_file_if_refresh_fails(self):
        self.dateline_path.write_text(
            json.dumps(
                {
                    "fetched_at": (timezone.now() - timedelta(days=2)).isoformat(),
                    "announcements": [{"title": "Fallback item", "body": "Still here"}],
                }
            ),
            encoding="utf-8",
        )

        with patch("posts.views.dateline_json_path", return_value=self.dateline_path):
            with patch("posts.views.scrape_dateline", side_effect=RuntimeError("network down")):
                response = self.client.get(reverse("getjson"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["announcements"][0]["title"], "Fallback item")
        self.assertTrue(payload["is_stale"])


class SiteMigrationTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_root.cleanup)
        self.dateline_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.dateline_root.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.override.enable()
        self.addCleanup(self.override.disable)

        self.user_model = get_user_model()
        self.superuser = self.user_model.objects.create_superuser(
            username="migrator",
            email="migrator@example.com",
            password="password123",
        )

        self.dateline_path = Path(self.dateline_root.name) / "dateline_announcements.json"
        self.dateline_path.write_text(json.dumps([{"title": "Welcome", "body": "Fresh export"}]), encoding="utf-8")

    def build_export_fixture(self):
        Post.objects.create(
            title="Imported Poster",
            content_type=Post.CONTENT_IMAGE,
            cover=build_test_image_upload(name="imported.png"),
        )
        Post.objects.create(
            title="Rich Copy",
            content_type=Post.CONTENT_RICH_TEXT,
            description="<p>Hello</p>",
            duration_seconds=12,
            transition_type=Post.TRANSITION_FADE_GRAY,
        )

        weather = WeatherSlideConfig.load()
        weather.is_visible = True
        weather.overlay_source = WeatherSlideConfig.NASA_GIBS
        weather.map_layer = WeatherSlideConfig.CYCLOSM
        weather.duration_seconds = 45
        weather.save()

        calendar = CalendarSlideConfig.load()
        calendar.is_visible = True
        calendar.public_url = "https://calendar.google.com/calendar/embed?src=test"
        calendar.duration_seconds = 33
        calendar.save()

        empty_display = EmptyDisplayConfig.load()
        empty_display.mode = EmptyDisplayConfig.WEATHER
        empty_display.save()

        ticker = BreakingNewsTickerConfig.load()
        ticker.mode = BreakingNewsTickerConfig.MODE_ON
        ticker.include_dateline_titles = True
        ticker.include_weather_alerts = True
        ticker.include_custom_text = True
        ticker.custom_text = "Ticker text"
        ticker.text_color = "#FFFFFF"
        ticker.background_color = "#114466"
        ticker.save()

        screen = ScreenPowerSchedule.load()
        screen.screen_on_time = time(7, 0)
        screen.screen_off_time = time(22, 0)
        screen.save()

        appearance = SiteAppearanceSettings.load()
        appearance.theme_color = "#224466"
        appearance.save()

    def test_export_site_migration_zip_contains_manifest_and_media(self):
        self.build_export_fixture()
        self.client.force_login(self.superuser)

        with patch("posts.site_migration.dateline_json_path", return_value=self.dateline_path):
            response = self.client.get(reverse("export_site_migration"))

        self.assertEqual(response.status_code, 200)
        payload = b"".join(response.streaming_content)
        self.assertGreater(len(payload), 0)

        with zipfile.ZipFile(BytesIO(payload), "r") as archive:
            self.assertIn("manifest.json", archive.namelist())
            self.assertIn(DATELINE_ARCHIVE_PATH, archive.namelist())
            self.assertTrue(any(name.startswith("media/images/") for name in archive.namelist()))
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

        self.assertEqual(manifest["format"], "slidercms-site-export")
        self.assertEqual(manifest["counts"]["posts"], 2)

    def test_import_site_migration_from_uploaded_zip_restores_posts_and_settings(self):
        self.build_export_fixture()
        self.client.force_login(self.superuser)

        with patch("posts.site_migration.dateline_json_path", return_value=self.dateline_path):
            export_response = self.client.get(reverse("export_site_migration"))
            archive_payload = b"".join(export_response.streaming_content)

        Post.objects.all().delete()
        WeatherSlideConfig.objects.all().delete()
        CalendarSlideConfig.objects.all().delete()
        EmptyDisplayConfig.objects.all().delete()
        BreakingNewsTickerConfig.objects.all().delete()
        ScreenPowerSchedule.objects.all().delete()
        SiteAppearanceSettings.objects.all().delete()
        self.dateline_path.write_text("[]", encoding="utf-8")

        archive_upload = SimpleUploadedFile(
            "site-export.zip",
            archive_payload,
            content_type="application/zip",
        )

        with patch("posts.site_migration.dateline_json_path", return_value=self.dateline_path):
            response = self.client.post(
                reverse("import_site_migration"),
                {"archive_file": archive_upload},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Post.objects.count(), 2)
        self.assertEqual(Post.objects.order_by("display_order", "id").first().title, "Imported Poster")
        self.assertEqual(WeatherSlideConfig.load().overlay_source, WeatherSlideConfig.NASA_GIBS)
        self.assertEqual(CalendarSlideConfig.load().duration_seconds, 33)
        self.assertEqual(EmptyDisplayConfig.load().mode, EmptyDisplayConfig.WEATHER)
        self.assertEqual(BreakingNewsTickerConfig.load().custom_text, "Ticker text")
        self.assertEqual(ScreenPowerSchedule.load().screen_off_time, time(22, 0))
        self.assertEqual(SiteAppearanceSettings.load().theme_color, "#224466")
        self.assertIn("Fresh export", self.dateline_path.read_text(encoding="utf-8"))

    def test_import_site_migration_from_url_uses_download_helper(self):
        self.client.force_login(self.superuser)
        archive_bytes = BytesIO()
        with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format": "slidercms-site-export",
                        "version": 1,
                        "posts": [],
                        "generated_slide_configs": [],
                        "weather_slide_config": None,
                        "calendar_slide_config": None,
                        "empty_display_config": None,
                        "screen_power_schedule": None,
                        "site_appearance": None,
                        "project_files": {
                            "dateline_announcements": {
                                "present": False,
                                "archive_path": None,
                            }
                        },
                        "counts": {"posts": 0, "media_files": 0},
                    }
                ),
            )
        archive_bytes.seek(0)

        with patch(
            "posts.views.download_site_archive_from_url",
            return_value=BytesIO(archive_bytes.getvalue()),
        ) as mock_download:
            with patch("posts.site_migration.dateline_json_path", return_value=self.dateline_path):
                response = self.client.post(
                    reverse("import_site_migration"),
                    {"archive_url": "https://example.com/site-export.zip"},
                )

        self.assertEqual(response.status_code, 302)
        mock_download.assert_called_once_with("https://example.com/site-export.zip")
