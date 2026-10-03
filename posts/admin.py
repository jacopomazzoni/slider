from django.contrib import admin
from .models import BreakingNewsTickerConfig, CalendarSlideConfig, GeneratedSlideConfig, Post, ScreenPowerSchedule, SiteAppearanceSettings, TransitDashboardConfig, TransitRoute, WeatherSlideConfig


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('display_order', 'title', 'content_type', 'is_visible', 'duration_seconds', 'transition_type', 'cover')
    list_filter = ('content_type', 'is_visible', 'transition_type')
    search_fields = ('title', 'description')
    ordering = ('display_order', 'id')


@admin.register(GeneratedSlideConfig)
class GeneratedSlideConfigAdmin(admin.ModelAdmin):
    list_display = ('scraper_name', 'is_visible', 'generated_slide_count', 'duration_seconds', 'transition_type')
    list_filter = ('scraper_name', 'is_visible', 'transition_type')


class SingletonConfigAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not self.model.objects.exists()


@admin.register(WeatherSlideConfig)
class WeatherSlideConfigAdmin(SingletonConfigAdmin):
    list_display = ('is_visible', 'overlay_source', 'map_layer', 'duration_seconds')


@admin.register(CalendarSlideConfig)
class CalendarSlideConfigAdmin(SingletonConfigAdmin):
    list_display = ('is_visible', 'public_url', 'duration_seconds')


@admin.register(TransitDashboardConfig)
class TransitDashboardConfigAdmin(SingletonConfigAdmin):
    list_display = ('is_visible', 'duration_seconds')


@admin.register(TransitRoute)
class TransitRouteAdmin(admin.ModelAdmin):
    list_display = ('sort_order', 'code', 'name', 'color', 'provider_route_ids', 'is_active')
    list_display_links = ('code',)
    list_editable = ('sort_order', 'color', 'is_active')
    search_fields = ('code', 'name')
    ordering = ('sort_order', 'code')


@admin.register(BreakingNewsTickerConfig)
class BreakingNewsTickerConfigAdmin(SingletonConfigAdmin):
    list_display = ('mode', 'include_dateline_titles', 'include_weather_alerts', 'include_custom_text', 'text_color', 'background_color')


@admin.register(ScreenPowerSchedule)
class ScreenPowerScheduleAdmin(SingletonConfigAdmin):
    list_display = ('screen_on_time', 'screen_off_time', 'last_screen_on_run', 'last_screen_off_run')


@admin.register(SiteAppearanceSettings)
class SiteAppearanceSettingsAdmin(SingletonConfigAdmin):
    list_display = ('theme_color', 'logo', 'favicon', 'asset_revision')
