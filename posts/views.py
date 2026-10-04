from django.shortcuts import get_object_or_404, render, redirect
from django.views.generic import ListView
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from .activity import activity_success
from .models import ActivityLog
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.db import transaction
from urllib.error import URLError
from urllib.request import Request, urlopen
from .models import (
    BreakingNewsTickerConfig,
    CalendarSlideConfig,
    EmptyDisplayConfig,
    GeneratedSlideConfig,
    Post,
    ScreenPowerSchedule,
    SlideLibraryConfig,
    default_library_sections,
    TransitDashboardConfig,
    TransitRoute,
    WeatherSlideConfig,
    content_type_for_file_name,
)
from .forms import (
    BreakingNewsTickerConfigForm,
    AdminSetUserPasswordForm,
    CalendarSlideConfigForm,
    TransitDashboardConfigForm,
    EmptyDisplayConfigForm,
    HtmlSlideForm,
    GeneratedSlideConfigForm,
    GoogleSlidesSlideForm,
    ImageEditForm,
    MediaSlideForm,
    RichTextSlideForm,
    SiteAppearanceForm,
    SiteMigrationImportForm,
    ScreenPowerScheduleForm,
    SlideOrderForm,
    SlidePlaybackForm,
    SlideTitleForm,
    WeatherSlideConfigForm,
    YouTubeSlideForm,
)
from .models import SiteAppearanceSettings
from .site_migration import (
    SiteMigrationError,
    dateline_json_path,
    download_site_archive_from_url,
    export_site_archive,
    import_site_archive,
)
from django.contrib.auth.decorators import user_passes_test
from accounts.permissions import is_site_admin
from django.contrib.auth.models import User
import json
import hashlib
from django.http import FileResponse, HttpResponse, JsonResponse
from django.conf import settings
from django.urls import reverse
from django.contrib import messages
from django.utils.dateparse import parse_datetime
from django.utils import timezone
import logging
import re
import requests
from bs4 import BeautifulSoup
from datetime import timedelta, timezone as dt_timezone

from scrape import normalize_dateline_payload, scrape_dateline, write_dateline_json


upload_logger = logging.getLogger("upload_errors")
DATELINE_MAX_AGE = timedelta(days=1)
WEATHER_ALERT_ENDPOINT = "https://api.weather.gov/alerts/active?zone=NYZ009"
WEATHER_ALERT_USER_AGENT = "sliderCMS BreakingNewsTicker"
TRANSIT_API_URL = "https://binghamtonupublic.etaspot.net/service.php"


def _uploaded_file_details(request):
    uploaded_file = request.FILES.get('cover')
    if not uploaded_file:
        return "no file"
    return {
        "name": uploaded_file.name,
        "content_type": uploaded_file.content_type,
        "size": uploaded_file.size,
    }


def _log_upload_form_errors(request, form, form_name):
    upload_logger.warning(
        "Upload validation failed form=%s user=%s errors=%s file=%s",
        form_name,
        getattr(request.user, "username", "anonymous"),
        form.errors.as_json(),
        _uploaded_file_details(request),
    )


def get_dateline_config():
    config, _ = GeneratedSlideConfig.objects.get_or_create(
        scraper_name=GeneratedSlideConfig.DATELINE
    )
    return config


def get_weather_config():
    return WeatherSlideConfig.load()


def get_calendar_config():
    return CalendarSlideConfig.load()


def get_transit_config():
    config, created = TransitDashboardConfig.objects.get_or_create(pk=TransitDashboardConfig.singleton_id)
    if created:
        config.selected_routes.set(TransitRoute.objects.filter(is_active=True))
    return config


def get_breaking_news_ticker_config():
    return BreakingNewsTickerConfig.load()


def get_empty_display_config():
    return EmptyDisplayConfig.load()


def get_screen_power_schedule():
    return ScreenPowerSchedule.load()


def get_site_appearance():
    return SiteAppearanceSettings.load()


def settings_page_context(
    *,
    screen_power_schedule_form=None,
    user_password_reset_form=None,
    site_appearance_form=None,
    request=None,
    site_migration_form=None,
):
    users = User.objects.all().order_by('username')
    screen_power_schedule = get_screen_power_schedule()
    site_appearance = get_site_appearance()
    return {
        'users': users,
        'screen_power_schedule': screen_power_schedule,
        'screen_power_timezone': settings.TIME_ZONE,
        'site_appearance': site_appearance,
        'activity_page': Paginator(ActivityLog.objects.all(), 25).get_page(request.GET.get('activity_page', 1) if request else 1),
        'screen_power_schedule_form': screen_power_schedule_form or ScreenPowerScheduleForm(instance=screen_power_schedule),
        'user_password_reset_form': user_password_reset_form or AdminSetUserPasswordForm(user_queryset=users),
        'site_appearance_form': site_appearance_form or SiteAppearanceForm(instance=site_appearance),
        'site_migration_form': site_migration_form or SiteMigrationImportForm(),
    }


def upload_page_context(
    *,
    media_form=None,
    rich_text_form=None,
    html_form=None,
    youtube_form=None,
    google_slides_form=None,
    active_tab='media',
):
    context = slide_source_context()
    context.update({
        'media_form': media_form or MediaSlideForm(prefix='media'),
        'rich_text_form': rich_text_form or RichTextSlideForm(prefix='rich'),
        'html_form': html_form or HtmlSlideForm(prefix='html'),
        'youtube_form': youtube_form or YouTubeSlideForm(prefix='youtube'),
        'google_slides_form': google_slides_form or GoogleSlidesSlideForm(prefix='gslides'),
        'active_tab': active_tab,
    })
    return context


def slide_source_context():
    dateline_config = get_dateline_config()
    weather_config = get_weather_config()
    calendar_config = get_calendar_config()
    transit_config = get_transit_config()
    breaking_news_ticker_config = get_breaking_news_ticker_config()
    empty_display_config = get_empty_display_config()
    section_order = SlideLibraryConfig.load().ordered_sections
    available = {
        'media': Post.objects.filter(is_visible=True).exists(),
        'dateline': dateline_config.is_visible,
        'weather': weather_config.is_visible,
        'calendar': calendar_config.is_visible and bool(calendar_config.public_url),
        'transit': transit_config.is_visible,
    }
    routes = {'media': 'slidedisplay', 'dateline': 'dateline', 'weather': 'weather_view',
              'calendar': 'calendar_view', 'transit': 'transit_view'}
    sequence = [{'key': key, 'url': reverse(routes[key]) + ('?section=media' if key == 'media' else '')}
                for key in section_order if available.get(key)]
    next_urls = {}
    for index, section in enumerate(sequence):
        next_urls[section['key']] = sequence[(index + 1) % len(sequence)]['url']
    return {
        'library_section_order': section_order,
        'display_sections': sequence,
        'section_next_urls': next_urls,
        'dateline_config': dateline_config,
        'weather_config': weather_config,
        'calendar_config': calendar_config,
        'transit_config': transit_config,
        'transit_routes': transit_config.selected_routes.filter(is_active=True),
        'transit_route_catalog': TransitRoute.objects.filter(is_active=True),
        'transit_selected_route_ids': set(transit_config.selected_routes.values_list('id', flat=True)),
        'transit_dashboard_available': transit_config.is_visible,
        'transit_dashboard_form': TransitDashboardConfigForm(instance=transit_config),
        'breaking_news_ticker_config': breaking_news_ticker_config,
        'empty_display_config': empty_display_config,
        'calendar_slide_available': calendar_config.is_visible and bool(calendar_config.public_url),
        'empty_display_choices': EmptyDisplayConfig.DISPLAY_CHOICES,
        'weather_overlay_sources': WeatherSlideConfig.OVERLAY_SOURCE_CHOICES,
        'weather_map_layers': WeatherSlideConfig.MAP_LAYER_CHOICES,
        'slide_transition_choices': Post.TRANSITION_CHOICES,
    }


def resolve_empty_display_mode(*, config=None, dateline_config=None, weather_config=None, calendar_config=None, transit_config=None):
    config = config or get_empty_display_config()
    dateline_config = dateline_config or get_dateline_config()
    weather_config = weather_config or get_weather_config()
    calendar_config = calendar_config or get_calendar_config()
    transit_config = transit_config or get_transit_config()

    availability = {
        EmptyDisplayConfig.DATELINE: bool(dateline_config.is_visible),
        EmptyDisplayConfig.WEATHER: bool(weather_config.is_visible),
        EmptyDisplayConfig.CALENDAR: bool(calendar_config.is_visible and calendar_config.public_url),
        EmptyDisplayConfig.TRANSIT: bool(transit_config.is_visible),
    }

    if config.mode == EmptyDisplayConfig.BLANK:
        return EmptyDisplayConfig.BLANK

    if config.mode == EmptyDisplayConfig.MESSAGE:
        return EmptyDisplayConfig.MESSAGE

    if config.mode in availability and availability[config.mode]:
        return config.mode

    for candidate in SlideLibraryConfig.load().ordered_sections:
        if availability.get(candidate):
            return candidate

    return EmptyDisplayConfig.MESSAGE


def apply_empty_display_fallback(posts, context):
    if posts:
        context['empty_display_mode'] = None
        context['empty_display_auto_redirect'] = False
        return None

    resolved_mode = resolve_empty_display_mode(
        config=context['empty_display_config'],
        dateline_config=context['dateline_config'],
        weather_config=context['weather_config'],
        calendar_config=context['calendar_config'],
        transit_config=context['transit_config'],
    )

    if resolved_mode == EmptyDisplayConfig.DATELINE:
        return redirect('dateline')
    if resolved_mode == EmptyDisplayConfig.WEATHER:
        return redirect('weather_view')
    if resolved_mode == EmptyDisplayConfig.CALENDAR:
        return redirect('calendar_view')
    if resolved_mode == EmptyDisplayConfig.TRANSIT:
        return redirect('transit_view')

    context['empty_display_mode'] = resolved_mode
    context['empty_display_auto_redirect'] = False
    return None


class HomePageView(ListView):
    model = Post
    template_name = "uploaded_images.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(slide_source_context())
        return context


def display(request):
    """Get the most recent uploaded image"""
    latest_post = Post.objects.filter(is_visible=True).order_by('display_order', 'id').first()
    if latest_post:
        try:
            latest_post.ensure_media_assets()
        except Exception:
            upload_logger.exception("Unable to build media assets for latest post_id=%s", latest_post.pk)
    posts = [latest_post] if latest_post else []
    context = {
        'posts': posts,
        'paused_mode': False,
    }
    context.update(slide_source_context())
    fallback_response = apply_empty_display_fallback(posts, context)
    if fallback_response is not None:
        return fallback_response
    return render(request, 'display.html', context)


@login_required
def all_images_view(request):
    """Display all stored slide posts."""
    posts = list(Post.objects.all().order_by('display_order', 'id'))
    for post in posts:
        try:
            post.ensure_media_assets()
        except Exception:
            upload_logger.exception("Unable to build media assets for post_id=%s", post.pk)
    context = {
        'object_list': posts,
    }
    context.update(slide_source_context())
    return render(request, "uploaded_images.html", context)


@login_required
@require_POST
def reorder_sections(request):
    try:
        payload = json.loads(request.body)
        order = payload.get('section_order') if isinstance(payload, dict) else None
        allowed = default_library_sections()
        if (not isinstance(order, list) or len(order) != len(allowed)
                or any(not isinstance(key, str) for key in order) or set(order) != set(allowed)):
            raise ValueError('Choose each library section exactly once.')
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid section order.'}, status=400)
    config = SlideLibraryConfig.load()
    config.section_order = order
    config.save(update_fields=['section_order'])
    activity_success(request, 'Slide Library and display section order updated.')
    return JsonResponse({'section_order': order})


@login_required
def edit_slide_image(request, pk):
    post = get_object_or_404(Post, id=pk)
    post.ensure_media_assets()

    if not post.is_editable_image:
        messages.error(request, 'Image editing is available for static image slides only.')
        return redirect('manage_slides')

    if request.method == 'POST' and 'revert_image_edits' in request.POST:
        post.image_edit_settings = {}
        post.save(update_fields=['image_edit_settings'])
        activity_success(request, 'Image renditions reverted to the original upload.')
        return redirect('edit_slide_image', pk=post.pk)

    if request.method == 'POST':
        form = ImageEditForm(request.POST)
        if form.is_valid():
            post.image_edit_settings = form.to_edit_settings()
            post.save(update_fields=['image_edit_settings'])
            activity_success(request, 'Image renditions updated. The original upload was left untouched.')
            return redirect('edit_slide_image', pk=post.pk)
        messages.error(request, 'Please correct the image editing settings below.')
    else:
        form = ImageEditForm(initial_settings=post.image_edit_settings)

    post.refresh_from_db()
    post.ensure_media_assets()
    return render(request, 'image_edit.html', {
        'post': post,
        'form': form,
    })


@login_required
def edit_rich_text_slide(request, pk):
    post = get_object_or_404(Post, id=pk, content_type=Post.CONTENT_RICH_TEXT)
    form = RichTextSlideForm(
        request.POST if request.method == 'POST' else None,
        instance=post,
        prefix='rich',
    )
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            activity_success(request, 'Rich text slide updated successfully.')
            return redirect('manage_slides')
        messages.error(request, 'Please correct the rich text settings below.')
    return render(request, 'post.html', {
        'post': post,
        'rich_text_form': form,
        'active_tab': 'rich',
        'editing_rich_text': True,
    })


@login_required
def edit_html_slide(request, pk):
    post = get_object_or_404(Post, id=pk, content_type=Post.CONTENT_HTML)

    if request.method == 'POST':
        form = HtmlSlideForm(request.POST, instance=post)
        if form.is_valid():
            form.save()
            activity_success(request, 'Custom HTML slide updated successfully.')
            return redirect('manage_slides')
        messages.error(request, 'Please correct the custom HTML settings below.')
    else:
        form = HtmlSlideForm(instance=post)

    return render(request, 'html_edit.html', {
        'post': post,
        'form': form,
    })


@login_required
def edit_google_slides_slide(request, pk):
    post = get_object_or_404(Post, id=pk, content_type=Post.CONTENT_GOOGLE_SLIDES)

    if request.method == 'POST':
        form = GoogleSlidesSlideForm(request.POST, instance=post)
        if form.is_valid():
            content = form.save(commit=False)
            content.content_type = Post.CONTENT_GOOGLE_SLIDES
            content.save()
            activity_success(request, 'Google Slides slide updated successfully.')
            return redirect('manage_slides')
        messages.error(request, 'Please correct the Google Slides settings below.')
    else:
        form = GoogleSlidesSlideForm(instance=post)

    return render(request, 'google_slides_edit.html', {
        'post': post,
        'form': form,
    })


@login_required
def upload_image(request):
    """Handle media, rich text, and custom HTML slide creation."""
    media_form = MediaSlideForm(prefix='media')
    rich_text_form = RichTextSlideForm(prefix='rich')
    html_form = HtmlSlideForm(prefix='html')
    youtube_form = YouTubeSlideForm(prefix='youtube')
    google_slides_form = GoogleSlidesSlideForm(prefix='gslides')
    active_tab = 'media'

    if request.method == 'POST':
        # Check which form was submitted
        if 'image_submit' in request.POST:
            active_tab = 'media'
            media_form = MediaSlideForm(request.POST, request.FILES, prefix='media')
            if media_form.is_valid():
                try:
                    content = media_form.save(commit=False)
                    content.content_type = content_type_for_file_name(content.cover.name)
                    content.save()
                    activity_success(request, f'Media slide added: {content.title} (ID {content.pk}).')
                    return redirect('manage_slides')
                except Exception:
                    upload_logger.exception(
                        "Media upload failed during save user=%s file=%s",
                        request.user.username,
                        _uploaded_file_details(request),
                    )
                    messages.error(request, 'The media file could not be saved. Check upload logs for details.')
            else:
                _log_upload_form_errors(request, media_form, "media")
                messages.error(request, 'Please correct the errors in the media form.')
        
        elif 'rich_submit' in request.POST:
            active_tab = 'rich'
            rich_text_form = RichTextSlideForm(request.POST, prefix='rich')
            if rich_text_form.is_valid():
                try:
                    content = rich_text_form.save(commit=False)
                    content.content_type = Post.CONTENT_RICH_TEXT
                    content.save()
                    activity_success(request, f'Rich text slide added: {content.title} (ID {content.pk}).')
                    return redirect('manage_slides')
                except Exception:
                    upload_logger.exception(
                        "Rich text upload failed during save user=%s",
                        request.user.username,
                    )
                    messages.error(request, 'The rich text slide could not be saved. Check upload logs for details.')
            else:
                _log_upload_form_errors(request, rich_text_form, "rich_text")
                messages.error(request, 'Please correct the errors in the rich text form.')

        elif 'html_submit' in request.POST:
            active_tab = 'html'
            html_form = HtmlSlideForm(request.POST, prefix='html')
            if html_form.is_valid():
                try:
                    content = html_form.save(commit=False)
                    content.content_type = Post.CONTENT_HTML
                    content.save()
                    activity_success(request, f'Custom HTML slide added: {content.title} (ID {content.pk}).')
                    return redirect('manage_slides')
                except Exception:
                    upload_logger.exception(
                        "Custom HTML upload failed during save user=%s",
                        request.user.username,
                    )
                    messages.error(request, 'The custom HTML slide could not be saved. Check upload logs for details.')
            else:
                _log_upload_form_errors(request, html_form, "custom_html")
                messages.error(request, 'Please correct the errors in the custom HTML form.')

        elif 'youtube_submit' in request.POST:
            active_tab = 'youtube'
            youtube_form = YouTubeSlideForm(request.POST, prefix='youtube')
            if youtube_form.is_valid():
                try:
                    content = youtube_form.save(commit=False)
                    content.content_type = Post.CONTENT_YOUTUBE
                    content.save()
                    activity_success(request, f'YouTube slide added: {content.title} (ID {content.pk}).')
                    return redirect('manage_slides')
                except Exception:
                    upload_logger.exception(
                        "YouTube slide upload failed during save user=%s",
                        request.user.username,
                    )
                    messages.error(request, 'The YouTube slide could not be saved. Check upload logs for details.')
            else:
                _log_upload_form_errors(request, youtube_form, "youtube")
                messages.error(request, 'Please correct the errors in the YouTube form.')

        elif 'google_slides_submit' in request.POST:
            active_tab = 'gslides'
            google_slides_form = GoogleSlidesSlideForm(request.POST, prefix='gslides')
            if google_slides_form.is_valid():
                try:
                    content = google_slides_form.save(commit=False)
                    content.content_type = Post.CONTENT_GOOGLE_SLIDES
                    content.save()
                    activity_success(request, f'Google Slides added: {content.title} (ID {content.pk}).')
                    return redirect('manage_slides')
                except Exception:
                    upload_logger.exception(
                        "Google Slides slide upload failed during save user=%s",
                        request.user.username,
                    )
                    messages.error(request, 'The Google Slides slide could not be saved. Check upload logs for details.')
            else:
                _log_upload_form_errors(request, google_slides_form, "google_slides")
                messages.error(request, 'Please correct the errors in the Google Slides form.')

    return render(
        request,
        'post.html',
        upload_page_context(
            media_form=media_form,
            rich_text_form=rich_text_form,
            html_form=html_form,
            youtube_form=youtube_form,
            google_slides_form=google_slides_form,
            active_tab=active_tab,
        ),
    )


@login_required
@require_POST
def delete_image(request, pk):
    """Delete a stored slide."""
    post = get_object_or_404(Post, id=pk)
    post.delete()
    activity_success(request, f'Deleted slide: {post.title} (ID {pk}).')
    return redirect('manage_slides')


@login_required
@require_POST
def update_slide_duration(request, pk):
    post = get_object_or_404(Post, id=pk)
    if post.content_type == Post.CONTENT_GOOGLE_SLIDES:
        messages.error(request, 'Google Slides timing is driven by its page range and seconds-per-page settings.')
        return redirect('manage_slides')
    form = SlidePlaybackForm(request.POST, instance=post)
    if form.is_valid():
        form.save()
        activity_success(request, f'"{post.title}" playback settings updated.')
    else:
        upload_logger.warning(
            "Duration update failed user=%s post_id=%s errors=%s",
            request.user.username,
            pk,
            form.errors.as_json(),
        )
        messages.error(request, 'Please enter a duration from 1 to 3600 seconds and choose a valid transition.')
    return redirect('manage_slides')


@login_required
@require_POST
def update_slide_title(request, pk):
    post = get_object_or_404(Post, id=pk)
    form = SlideTitleForm(request.POST, instance=post)
    if form.is_valid():
        form.save()
        activity_success(request, f'Slide title updated to "{post.title}".')
    else:
        upload_logger.warning(
            "Title update failed user=%s post_id=%s errors=%s",
            request.user.username,
            pk,
            form.errors.as_json(),
        )
        messages.error(request, 'Please enter a valid slide title.')
    return redirect('manage_slides')


@login_required
@require_POST
def update_slide_visibility(request, pk):
    post = get_object_or_404(Post, id=pk)
    post.is_visible = request.POST.get('is_visible') == '1'
    post.save(update_fields=['is_visible'])
    activity_success(
        request,
        f'"{post.title}" will {"" if post.is_visible else "not "}show in the display.',
    )
    return redirect('manage_slides')


@login_required
@require_POST
def update_generated_slide_config(request, scraper_name):
    if scraper_name != GeneratedSlideConfig.DATELINE:
        messages.error(request, 'Unknown generated slide source.')
        return redirect('manage_slides')

    config = get_dateline_config()
    form = GeneratedSlideConfigForm(request.POST, instance=config)
    if form.is_valid():
        form.save()
        activity_success(request, 'Dateline slide settings updated.')
    else:
        upload_logger.warning(
            "Generated slide config update failed user=%s scraper=%s errors=%s",
            request.user.username,
            scraper_name,
            form.errors.as_json(),
        )
        messages.error(
            request,
            'Please enter a slide count from 1 to 20, a duration from 1 to 3600 seconds, and valid transition and overflow options.',
        )
    return redirect('manage_slides')


@login_required
@require_POST
def update_weather_slide_config(request):
    config = get_weather_config()
    form = WeatherSlideConfigForm(request.POST, instance=config)
    if form.is_valid():
        form.save()
        activity_success(request, 'Weather dashboard settings updated.')
    else:
        upload_logger.warning(
            "Weather slide config update failed user=%s errors=%s",
            request.user.username,
            form.errors.as_json(),
        )
        messages.error(
            request,
            'Please choose a valid weather overlay, map layer, and duration from 1 to 3600 seconds.',
        )
    return redirect('manage_slides')


@login_required
@require_POST
def update_calendar_slide_config(request):
    config = get_calendar_config()
    form = CalendarSlideConfigForm(request.POST, instance=config)
    if form.is_valid():
        form.save()
        activity_success(request, 'Google Calendar slide settings updated.')
    else:
        upload_logger.warning(
            "Calendar slide config update failed user=%s errors=%s",
            request.user.username,
            form.errors.as_json(),
        )
        messages.error(
            request,
            'Please use a public Google Calendar URL and a duration from 1 to 3600 seconds.',
        )
    return redirect('manage_slides')


@login_required
@require_POST
def update_transit_dashboard_config(request):
    config = get_transit_config()
    form = TransitDashboardConfigForm(request.POST, instance=config)
    if form.is_valid():
        form.save()
        activity_success(request, 'Transit dashboard settings updated.')
    else:
        messages.error(request, 'Please check the transit routes, slide duration, and animation timing values.')
    return redirect('manage_slides')


@login_required
@require_POST
def update_empty_display_config(request):
    config = get_empty_display_config()
    form = EmptyDisplayConfigForm(request.POST, instance=config)
    if form.is_valid():
        form.save()
        activity_success(request, 'Empty display fallback updated.')
    else:
        upload_logger.warning(
            "Empty display fallback update failed user=%s errors=%s",
            request.user.username,
            form.errors.as_json(),
        )
        messages.error(request, 'Please choose a valid empty display fallback.')
    return redirect('manage_slides')


def _ticker_dateline_items():
    try:
        file_path = dateline_json_path()
        payload = None

        if file_path.exists():
            payload = _load_dateline_payload(file_path)

        if payload is None or _dateline_payload_is_stale(payload):
            try:
                payload = _refresh_dateline_payload(file_path)
            except Exception:
                upload_logger.exception("Unable to refresh Dateline announcements for ticker")

        payload = payload or {"announcements": []}
        announcements = payload.get("announcements") if isinstance(payload, dict) else payload
    except Exception:
        upload_logger.exception("Unable to load Dateline announcements for ticker")
        return []
    if not isinstance(announcements, list):
        return []

    limit = max(1, get_dateline_config().generated_slide_count or 1)
    items = []
    for announcement in announcements:
        title = str((announcement or {}).get("title") or "").strip()
        if title:
            items.append(f"Dateline: {title}")
        if len(items) >= limit:
            break
    return items


def _ticker_weather_alert_items():
    request_obj = Request(
        WEATHER_ALERT_ENDPOINT,
        headers={
            "Accept": "application/geo+json",
            "User-Agent": WEATHER_ALERT_USER_AGENT,
        },
    )
    try:
        with urlopen(request_obj, timeout=6) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError, ValueError):
        upload_logger.exception("Unable to load weather alerts for ticker")
        return ["Weather alert unavailable"]

    features = payload.get("features") or []
    if not features:
        return ["No weather alert"]

    items = []
    for feature in features[:3]:
        properties = (feature or {}).get("properties") or {}
        headline = str(properties.get("headline") or "").strip()
        event = str(properties.get("event") or "").strip()
        message = headline or event or "Weather alert"
        items.append(f"Weather Alert: {message}")
    return items


def build_breaking_news_ticker_items(config=None):
    config = config or get_breaking_news_ticker_config()
    if not config.is_enabled:
        return []

    items = []
    if config.include_dateline_titles:
        items.extend(_ticker_dateline_items())
    if config.include_weather_alerts:
        items.extend(_ticker_weather_alert_items())
    if config.include_custom_text and config.custom_text:
        items.append(config.custom_text.strip())

    return [item for item in items if str(item or "").strip()]


@login_required
@require_POST
def update_breaking_news_ticker_config(request):
    config = get_breaking_news_ticker_config()
    form = BreakingNewsTickerConfigForm(request.POST, instance=config)
    if form.is_valid():
        form.save()
        activity_success(request, 'Breaking news ticker settings updated.')
    else:
        upload_logger.warning(
            "Breaking news ticker config update failed user=%s errors=%s",
            request.user.username,
            form.errors.as_json(),
        )
        messages.error(
            request,
            'Please choose valid ticker settings and add custom text before enabling that source.',
        )
    return redirect('manage_slides')


@never_cache
def breaking_news_ticker_feed(request):
    config = get_breaking_news_ticker_config()
    return JsonResponse(
        {
            "enabled": config.is_enabled,
            "items": build_breaking_news_ticker_items(config),
        }
    )


def slidedisplay(request):
    """Render the slideshow for all configured slide types."""
    posts = list(Post.objects.filter(is_visible=True).order_by('display_order', 'id'))
    for post in posts:
        try:
            post.ensure_media_assets()
        except Exception:
            upload_logger.exception("Unable to build slideshow media assets for post_id=%s", post.pk)
    context = {
        'posts': posts,
        'paused_mode': False,
    }
    context.update(slide_source_context())
    sequence = context['display_sections']
    if posts and sequence and request.GET.get('section') != 'media' and sequence[0]['key'] != 'media':
        return redirect(sequence[0]['url'])
    fallback_response = apply_empty_display_fallback(posts, context)
    if fallback_response is not None:
        return fallback_response
    return render(request, 'display.html', context)


def paused_post_view(request, pk):
    post = get_object_or_404(Post, pk=pk)
    try:
        post.ensure_media_assets()
    except Exception:
        upload_logger.exception("Unable to build paused preview assets for post_id=%s", post.pk)
    context = {"posts": [post], "paused_mode": True, "empty_display_auto_redirect": False}
    context.update(slide_source_context())
    return render(request, "display.html", context)


def read_dateline(request, paused=False):
    """Viewing dateline reader after refresh from display"""
    context = slide_source_context()
    context["paused_mode"] = paused
    if paused:
        context["dateline_config"].is_visible = True
    return render(request, "dateline_reader.html", context)


def _parse_dateline_fetched_at(value):
    if not value:
        return None

    parsed = parse_datetime(str(value))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _dateline_payload_is_stale(payload):
    fetched_at = _parse_dateline_fetched_at(payload.get("fetched_at"))
    if fetched_at is None:
        return True
    return fetched_at <= timezone.now() - DATELINE_MAX_AGE


def _load_dateline_payload(file_path):
    with file_path.open('r', encoding='utf-8') as file_handle:
        payload = normalize_dateline_payload(json.load(file_handle))

    if not payload.get("fetched_at") and file_path.exists():
        file_mtime = timezone.datetime.fromtimestamp(file_path.stat().st_mtime, tz=dt_timezone.utc)
        payload["fetched_at"] = file_mtime.isoformat()

    return payload


def _refresh_dateline_payload(file_path):
    announcements = scrape_dateline()
    write_dateline_json(announcements, file_path, fetched_at=timezone.now())
    return _load_dateline_payload(file_path)


def fetch_json_view(request):
    """To actually fetch json file"""
    try:
        file_path = dateline_json_path()
        payload = None

        if file_path.exists():
            payload = _load_dateline_payload(file_path)

        if payload is None or _dateline_payload_is_stale(payload):
            try:
                payload = _refresh_dateline_payload(file_path)
            except Exception:
                upload_logger.exception("Unable to refresh Dateline announcements from source")
                if payload is None:
                    return JsonResponse({'error': 'Unable to refresh Dateline announcements.'}, status=503)

        payload = payload or {"fetched_at": None, "announcements": []}
        payload["is_stale"] = _dateline_payload_is_stale(payload)
        return JsonResponse(payload)

    except json.JSONDecodeError as e:
        return JsonResponse({'error': 'Invalid JSON', 'details': str(e)}, status=500)
    except Exception as e:
        return JsonResponse({'error': 'Server error', 'details': str(e)}, status=500)


# SETTINGS PAGE
@user_passes_test(is_site_admin, login_url='home')
def settings_view(request):
    return render(request, 'manage_users.html', settings_page_context(request=request))


@user_passes_test(is_site_admin, login_url='home')
def export_site_migration_view(request):
    archive = export_site_archive(exported_by=request.user.username)
    filename = f"slidercms-site-export-{timezone.now().strftime('%Y%m%d-%H%M%S')}.zip"
    return FileResponse(archive, as_attachment=True, filename=filename)


@user_passes_test(is_site_admin, login_url='home')
@require_POST
def import_site_migration_view(request):
    form = SiteMigrationImportForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, 'Choose a migration zip file or URL and fix any validation errors below.')
        return render(
            request,
            'manage_users.html',
            settings_page_context(site_migration_form=form),
            status=200,
        )

    archive_source = form.cleaned_data.get('archive_file')
    archive_url = (form.cleaned_data.get('archive_url') or '').strip()

    try:
        if archive_source:
            result = import_site_archive(archive_source)
        else:
            downloaded_archive = download_site_archive_from_url(archive_url)
            try:
                result = import_site_archive(downloaded_archive)
            finally:
                downloaded_archive.close()
    except SiteMigrationError as exc:
        upload_logger.warning(
            "Site migration import failed user=%s source=%s error=%s",
            request.user.username,
            archive_source.name if archive_source else archive_url,
            str(exc),
        )
        messages.error(request, str(exc))
        return render(
            request,
            'manage_users.html',
            settings_page_context(site_migration_form=form),
            status=200,
        )
    except Exception:
        upload_logger.exception(
            "Unexpected site migration import failure user=%s source=%s",
            request.user.username,
            archive_source.name if archive_source else archive_url,
        )
        messages.error(request, 'The migration archive could not be imported. Check the logs for details.')
        return render(
            request,
            'manage_users.html',
            settings_page_context(site_migration_form=form),
            status=200,
        )

    activity_success(
        request,
        f'Site archive imported successfully. Restored {result.post_count} slides and {result.media_file_count} media files.',
    )
    return redirect('settings')


@user_passes_test(is_site_admin, login_url='home')
@require_POST
def update_site_appearance(request):
    config = get_site_appearance()
    form = SiteAppearanceForm(request.POST, request.FILES, instance=config)
    if form.is_valid():
        form.save()
        activity_success(request, 'Site settings updated.')
    else:
        upload_logger.warning(
            "Site appearance update failed user=%s errors=%s",
            request.user.username,
            form.errors.as_json(),
        )
        messages.error(request, 'Please correct the site settings below.')
        return render(
            request,
            'manage_users.html',
            settings_page_context(site_appearance_form=form),
            status=200,
        )
    return redirect('settings')


@user_passes_test(is_site_admin, login_url='home')
@require_POST
def update_screen_power_schedule(request):
    config = get_screen_power_schedule()
    form = ScreenPowerScheduleForm(request.POST, instance=config)
    if form.is_valid():
        schedule = form.save(commit=False)
        schedule.last_applied_slot = ''
        schedule.last_attempt_at = None
        schedule.last_error = ''
        schedule.save(update_fields=['is_enabled', 'screen_on_time', 'screen_off_time',
                                     'last_applied_slot', 'last_attempt_at', 'last_error'])
        activity_success(request, 'Screen power schedule updated.')
    else:
        upload_logger.warning(
            "Screen power schedule update failed user=%s errors=%s",
            request.user.username,
            form.errors.as_json(),
        )
        messages.error(request, 'Please enter valid screen on and screen off times.')
        return render(
            request,
            'manage_users.html',
            settings_page_context(screen_power_schedule_form=form),
            status=200,
        )
    return redirect('settings')


@user_passes_test(is_site_admin, login_url='home')
@require_POST
def reset_user_password(request):
    users = User.objects.all().order_by('username')
    form = AdminSetUserPasswordForm(request.POST, user_queryset=users)
    if form.is_valid():
        updated_user = form.save()
        activity_success(request, f'Password updated for {updated_user.username}.')
    else:
        upload_logger.warning(
            "Admin password reset failed user=%s errors=%s",
            request.user.username,
            form.errors.as_json(),
        )
        messages.error(request, 'Password could not be updated. Review the validation details below.')
        return render(
            request,
            'manage_users.html',
            settings_page_context(user_password_reset_form=form),
            status=200,
        )
    return redirect('settings')


@login_required
@require_POST
def reorder_slides(request):
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'errors': {'ordered_ids': ['Invalid JSON payload.']}}, status=400)

    form = SlideOrderForm(payload)
    if not form.is_valid():
        upload_logger.warning(
            "Slide reorder failed user=%s errors=%s",
            request.user.username,
            form.errors.as_json(),
        )
        return JsonResponse({'ok': False, 'errors': json.loads(form.errors.as_json())}, status=400)

    ordered_ids = form.cleaned_data['ordered_ids']
    existing_ids = list(Post.objects.order_by('display_order', 'id').values_list('id', flat=True))
    if sorted(ordered_ids) != sorted(existing_ids):
        return JsonResponse({'ok': False, 'errors': {'ordered_ids': ['Submitted slide order did not match the current slides.']}}, status=400)

    with transaction.atomic():
        for index, post_id in enumerate(ordered_ids, start=1):
            Post.objects.filter(pk=post_id).update(display_order=index)

    activity_success(request, f'Reordered {len(ordered_ids)} slides.')
    return JsonResponse({'ok': True})


@user_passes_test(is_site_admin, login_url='home')
@require_POST
def toggle_superuser(request, pk):
    user = get_object_or_404(User, id=pk)
    is_admin = not user.is_superuser
    user.is_superuser = is_admin
    user.is_staff = is_admin
    user.save()
    activity_success(request, f'{user.username}: {"superuser" if is_admin else "standard user"}.')
    return redirect('settings')


def weather_view(request, paused=False):
    """Viewing weather"""
    weather_config = get_weather_config()
    if not weather_config.is_visible and not paused:
        calendar_config = get_calendar_config()
        if calendar_config.is_visible and calendar_config.public_url:
            return redirect('calendar_view')
        if get_transit_config().is_visible:
            return redirect('transit_view')
        return redirect('slidedisplay')
    context = slide_source_context()
    context["paused_mode"] = paused
    return render(request, "weather/weather.html", context)


@never_cache
def calendar_view(request, paused=False):
    """Display a public Google Calendar as a full-screen slide."""
    calendar_config = get_calendar_config()
    if (not calendar_config.is_visible or not calendar_config.public_url) and not paused:
        return redirect('slidedisplay')
    context = slide_source_context()
    context.update({
        'calendar_config': calendar_config,
        'paused_mode': paused,
    })
    return render(request, "calendar_display.html", context)


def _transit_api(service, *, ttl, **params):
    signature = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()[:20]
    cache_key = f"transit_api_v1:{service}:{signature}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached, True
    query = {"service": service, "token": "TESTING", **params}
    try:
        response = requests.get(TRANSIT_API_URL, params=query, timeout=(2, 5), headers={
            "User-Agent": "sliderCMS transit display/1.0",
        })
        response.raise_for_status()
        payload = response.json()
        cache.set(cache_key, payload, ttl)
        return payload, True
    except (requests.RequestException, ValueError):
        return None, False


def _transit_items(payload, key):
    if isinstance(payload, dict):
        value = payload.get(key, [])
        return value if isinstance(value, list) else []
    return payload if isinstance(payload, list) else []


def _transit_selected_routes(mobile=False):
    routes = list(TransitRoute.objects.filter(is_active=True) if mobile
                  else get_transit_config().selected_routes.filter(is_active=True))
    provider_ids = {int(value) for route in routes for value in (route.provider_route_ids or [])}
    return routes, provider_ids


def transit_map_data(request, mobile=False):
    routes, selected_ids = _transit_selected_routes(mobile=mobile)
    provider_routes, routes_ok = _transit_api("get_routes", ttl=21600)
    provider_stops, stops_ok = _transit_api("get_stops", ttl=21600)
    raw_routes = _transit_items(provider_routes, "get_routes")
    raw_stops = _transit_items(provider_stops, "get_stops")
    route_metadata = {int(item["id"]): item for item in raw_routes if isinstance(item, dict) and str(item.get("id", "")).isdigit()}
    stop_ids = set()
    output_routes = []
    for route in routes:
        for provider_id in route.provider_route_ids or []:
            item = route_metadata.get(int(provider_id))
            if not item:
                continue
            stop_ids.update(str(value) for value in item.get("stops", []))
            output_routes.append({
                "id": int(provider_id), "routeCode": route.code, "routeName": route.name,
                "name": item.get("name", route.name),
                "color": item.get("color") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(item.get("color", ""))) else route.color,
                "direction": (re.search(r"inbound|outbound", str(item.get("name", "")), re.I).group(0).title()
                    if re.search(r"inbound|outbound", str(item.get("name", "")), re.I)
                    else str(item.get("type", "")).title()),
                "encLine": item.get("encLine", ""),
                "stopIds": [str(value) for value in item.get("stops", [])],
            })
    stops = [{
        "id": str(item.get("id")), "name": item.get("name", "Stop"),
        "lat": item.get("lat"), "lng": item.get("lng"),
    } for item in raw_stops if isinstance(item, dict)
        and str(item.get("id", "")) in stop_ids
        and isinstance(item.get("lat"), (float, int))
        and isinstance(item.get("lng"), (float, int))]
    return JsonResponse({
        "routes": output_routes, "stops": stops,
        "selectedRouteIds": sorted(selected_ids),
        "sourcesAvailable": routes_ok and stops_ok,
    })


def transit_live_data(request, mobile=False):
    selected_routes, selected_ids = _transit_selected_routes(mobile=mobile)
    configured_routes = {
        int(provider_id): route
        for route in selected_routes
        for provider_id in (route.provider_route_ids or [])
        if str(provider_id).isdigit()
    }
    map_cache_key = "transit_map_ids_v2:" + ",".join(map(str, sorted(selected_ids)))
    map_payload = cache.get(map_cache_key)
    if not map_payload:
        routes_payload, _ = _transit_api("get_routes", ttl=21600)
        stops_payload, _ = _transit_api("get_stops", ttl=21600)
        route_items = _transit_items(routes_payload, "get_routes")
        stop_items = _transit_items(stops_payload, "get_stops")
        route_meta = {int(item["id"]): item for item in route_items if isinstance(item, dict) and str(item.get("id", "")).isdigit()}
        relevant_stops = {str(stop_id) for route_id in selected_ids for stop_id in route_meta.get(route_id, {}).get("stops", [])}
        stop_metadata = {
            str(item.get("id")): item for item in stop_items
            if isinstance(item, dict) and str(item.get("id", "")).isdigit()
        }
        map_payload = {"stop_ids": relevant_stops, "stops": stop_metadata, "routes": route_meta}
        cache.set(map_cache_key, map_payload, 21600)
    else:
        relevant_stops = map_payload["stop_ids"]
        stop_metadata = map_payload.get("stops", {})
        route_meta = map_payload.get("routes", {})

    vehicles_data, vehicles_ok = _transit_api("get_vehicles", ttl=12,
        includeETAData="1", inService="1", orderedETAArray="1")
    etas_data, etas_ok = _transit_api("get_stop_etas", ttl=18, statusData="1")
    alerts_data, alerts_ok = _transit_api("get_service_announcements", ttl=60)
    vehicles = [item for item in _transit_items(vehicles_data, "get_vehicles")
        if isinstance(item, dict) and str(item.get("routeID", "")).isdigit()
        and int(item["routeID"]) in selected_ids]
    stop_etas = []
    incoming_by_route = {}
    campus_lat, campus_lng = 42.0877, -75.9697
    for stop in _transit_items(etas_data, "get_stop_etas"):
        if not isinstance(stop, dict) or str(stop.get("id")) not in relevant_stops:
            continue
        arrivals = [arrival for arrival in stop.get("enRoute", []) if isinstance(arrival, dict)
            and str(arrival.get("routeID", "")).isdigit() and int(arrival["routeID"]) in selected_ids]
        if arrivals:
            stop_etas.append({"id": str(stop["id"]), "enRoute": arrivals})
        stop_info = stop_metadata.get(str(stop.get("id")), {})
        try:
            stop_lat, stop_lng = float(stop_info["lat"]), float(stop_info["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        # Keep the arrivals panel focused on stops around the university, not distant route terminals.
        lat_delta = (stop_lat - campus_lat) * 111.0
        lng_delta = (stop_lng - campus_lng) * 111.0 * 0.743
        if lat_delta * lat_delta + lng_delta * lng_delta > 2.0 * 2.0:
            continue
        for arrival in arrivals:
            route_id = int(arrival["routeID"])
            route_data = route_meta.get(route_id, {})
            route_name = str(route_data.get("name", ""))
            direction = str(route_data.get("direction", route_data.get("type", "")))
            if not re.search(r"\binbound\b", f"{route_name} {direction}", re.I):
                continue
            try:
                minutes = max(0, int(float(arrival.get("minutes", 0))))
            except (TypeError, ValueError):
                continue
            configured_route = configured_routes.get(route_id)
            if configured_route is None:
                continue
            candidate = {
                "routeCode": configured_route.code,
                "routeName": configured_route.name,
                "color": configured_route.color,
                "stopName": str(stop_info.get("name", "Campus stop")),
                "minutes": minutes,
            }
            previous = incoming_by_route.get(configured_route.code)
            if previous is None or minutes < previous["minutes"]:
                incoming_by_route[configured_route.code] = candidate

    now = timezone.now()
    alerts = []
    for group in _transit_items(alerts_data, "get_service_announcements"):
        if not isinstance(group, dict):
            continue
        for alert in group.get("announcements", []):
            if not isinstance(alert, dict) or not alert.get("text"):
                continue
            start = parse_datetime(alert.get("start", ""))
            end = parse_datetime(alert.get("end", ""))
            if start and timezone.is_naive(start):
                start = timezone.make_aware(start)
            if end and timezone.is_naive(end):
                end = timezone.make_aware(end)
            if (not start or start <= now) and (not end or end >= now):
                alerts.append({"type": group.get("type", "Service alert"), "text": str(alert["text"])[:1200]})
    return JsonResponse({
        "vehicles": vehicles, "stopEtas": stop_etas, "alerts": alerts,
        "incoming": sorted(incoming_by_route.values(), key=lambda item: (item["minutes"], item["routeCode"])),
        "liveAvailable": vehicles_ok or etas_ok, "vehiclesAvailable": vehicles_ok, "alertsAvailable": alerts_ok,
    })


def transit_mobile_url():
    return get_site_appearance().public_base_url.rstrip('/') + reverse('transit_mobile')


@login_required
@require_POST
def rich_text_qr(request):
    from django.core.exceptions import ValidationError
    from .rich_text import qr_markup

    try:
        markup = qr_markup(request.POST.get('text', ''), request.POST.get('size', '192'))
    except ValidationError as error:
        return JsonResponse({'error': ' '.join(error.messages)}, status=400)
    response = JsonResponse({'html': markup})
    response['Cache-Control'] = 'no-store'
    return response


def transit_mobile_qr(request):
    from .qr_codes import qr_variants

    revision, _, variants = qr_variants(transit_mobile_url())
    try:
        width = int(request.GET.get('size', next(iter(variants))))
    except (ValueError, TypeError):
        return HttpResponse('Invalid QR size.', status=400)
    if width not in variants:
        return HttpResponse('Unsupported QR size.', status=400)
    etag = '"%s-%s"' % (revision, width)
    if request.headers.get('If-None-Match') == etag:
        response = HttpResponse(status=304)
    else:
        response = HttpResponse(variants[width], content_type='image/png')
    response['ETag'] = etag
    response['Cache-Control'] = ('public, max-age=86400' if request.GET.get('v') == revision else 'no-cache')
    return response


def transit_view(request, paused=False, mobile=False):
    context = slide_source_context()
    if not context['transit_config'].is_visible and not paused:
        return redirect('slidedisplay')
    context['paused_mode'] = paused
    context['mobile_mode'] = mobile
    if not mobile:
        from .qr_codes import qr_variants

        url = transit_mobile_url()
        revision, modules, variants = qr_variants(url)
        endpoint = reverse('transit_mobile_qr')
        context['transit_mobile_url'] = url
        context['transit_qr_modules'] = modules
        context['transit_qr_sources'] = [
            {'width': width, 'url': f'{endpoint}?size={width}&v={revision}'}
            for width in variants
        ]
        context['transit_qr_default'] = next(source['url'] for source in context['transit_qr_sources'] if source['width'] >= 84)
    return render(request, 'transit_dashboard.html', context)

    
