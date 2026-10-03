import json
import re

from django import forms
from django.contrib.auth import get_user_model
from urllib.parse import urlparse
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
    extract_youtube_video_id,
    normalize_google_slides_url,
)
from accounts.passwords import PASSWORD_MAX_LENGTH, password_widget_attrs, validate_basic_password
from .media_processing import OVERLAY_FONT_CHOICES, normalize_image_edit_config
from .rich_text import clean_rich_text

User = get_user_model()


class CommaFriendlyFloatField(forms.FloatField):
    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip().replace(',', '.')
        return super().to_python(value)


class MediaSlideForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ['title', 'cover', 'duration_seconds', 'transition_type']
        widgets = {
            'duration_seconds': forms.NumberInput(attrs={'min': 1, 'max': 3600, 'step': 1}),
            'transition_type': forms.Select(),
        }
    
    def clean_cover(self):
        cover = self.cleaned_data.get('cover')
        if not cover:
            raise forms.ValidationError("Please upload a media file.")
        return cover


class RichTextSlideForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = [
            'title',
            'description',
            'link',
            'text_color',
            'background_color',
            'duration_seconds',
            'transition_type',
        ]
        widgets = {
            'description': forms.Textarea(),
            'text_color': forms.TextInput(attrs={'type': 'color'}),
            'background_color': forms.TextInput(attrs={'type': 'color'}),
            'duration_seconds': forms.NumberInput(attrs={'min': 1, 'max': 3600, 'step': 1}),
            'transition_type': forms.Select(),
        }
    
    def clean_description(self):
        return clean_rich_text(self.cleaned_data.get('description'))


class HtmlSlideForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ['title', 'description', 'duration_seconds', 'transition_type']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 12, 'spellcheck': 'false'}),
            'duration_seconds': forms.NumberInput(attrs={'min': 1, 'max': 3600, 'step': 1}),
            'transition_type': forms.Select(),
        }
        labels = {
            'description': 'HTML',
        }

    def clean_description(self):
        description = self.cleaned_data.get('description') or ''
        if not description.strip():
            raise forms.ValidationError("Please add some HTML.")
        return description


class YouTubeSlideForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = [
            'title',
            'youtube_url',
            'youtube_start_seconds',
            'youtube_end_seconds',
            'youtube_quality',
            'youtube_show_captions',
            'duration_seconds',
            'transition_type',
        ]
        widgets = {
            'youtube_url': forms.URLInput(attrs={'placeholder': 'https://www.youtube.com/watch?v=...'}),
            'youtube_start_seconds': forms.NumberInput(attrs={'min': 0, 'max': 86400, 'step': 1, 'placeholder': '0'}),
            'youtube_end_seconds': forms.NumberInput(attrs={'min': 1, 'max': 86400, 'step': 1, 'placeholder': 'Optional'}),
            'youtube_quality': forms.Select(),
            'youtube_show_captions': forms.CheckboxInput(),
            'duration_seconds': forms.NumberInput(attrs={'min': 1, 'max': 3600, 'step': 1}),
            'transition_type': forms.Select(),
        }
        labels = {
            'youtube_url': 'YouTube URL',
            'youtube_start_seconds': 'Start Time (seconds)',
            'youtube_end_seconds': 'End Time (seconds)',
            'youtube_quality': 'Desired Resolution',
            'youtube_show_captions': 'Show Captions When Available',
        }

    def clean_youtube_url(self):
        youtube_url = (self.cleaned_data.get('youtube_url') or '').strip()
        if not youtube_url:
            raise forms.ValidationError("Please paste a YouTube link.")
        if not extract_youtube_video_id(youtube_url):
            raise forms.ValidationError("Use a valid YouTube video link.")
        return youtube_url

    def clean(self):
        cleaned_data = super().clean()
        start_seconds = cleaned_data.get('youtube_start_seconds') or 0
        end_seconds = cleaned_data.get('youtube_end_seconds')

        if end_seconds is not None and end_seconds <= start_seconds:
            self.add_error('youtube_end_seconds', "End time must be greater than the start time.")

        return cleaned_data


class GoogleSlidesSlideForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = [
            'title',
            'google_slides_url',
            'google_slides_start_slide',
            'google_slides_end_slide',
            'google_slides_advance_seconds',
            'transition_type',
        ]
        widgets = {
            'google_slides_url': forms.URLInput(attrs={'placeholder': 'https://docs.google.com/presentation/d/e/.../embed?...'}),
            'google_slides_start_slide': forms.NumberInput(attrs={'min': 1, 'max': 2000, 'step': 1, 'placeholder': '1'}),
            'google_slides_end_slide': forms.NumberInput(attrs={'min': 1, 'max': 2000, 'step': 1, 'placeholder': '1'}),
            'google_slides_advance_seconds': forms.NumberInput(attrs={'min': 1, 'max': 3600, 'step': 1, 'placeholder': '8'}),
            'transition_type': forms.Select(),
        }
        labels = {
            'google_slides_url': 'Google Slides URL',
            'google_slides_start_slide': 'Start Slide',
            'google_slides_end_slide': 'End Slide',
            'google_slides_advance_seconds': 'Seconds Per Page',
        }

    def clean_google_slides_url(self):
        google_slides_url = (self.cleaned_data.get('google_slides_url') or '').strip()
        if not google_slides_url:
            raise forms.ValidationError("Please paste a Google Slides link.")

        normalized_url = normalize_google_slides_url(google_slides_url)
        if not normalized_url:
            raise forms.ValidationError(
                "Use an HTTPS Google Slides presentation link from docs.google.com. Published embed links work best."
            )
        return normalized_url

    def clean(self):
        cleaned_data = super().clean()
        start_slide = cleaned_data.get('google_slides_start_slide') or 1
        end_slide = cleaned_data.get('google_slides_end_slide')

        if end_slide is None:
            cleaned_data['google_slides_end_slide'] = start_slide
            end_slide = start_slide

        if end_slide < start_slide:
            self.add_error('google_slides_end_slide', "End slide must be greater than or equal to the start slide.")

        return cleaned_data


class SlidePlaybackForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ['duration_seconds', 'transition_type']
        widgets = {
            'duration_seconds': forms.NumberInput(attrs={'min': 1, 'max': 3600, 'step': 1}),
            'transition_type': forms.Select(),
        }


class SlideTitleForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ['title']
        widgets = {
            'title': forms.TextInput(attrs={'maxlength': 200}),
        }


class GeneratedSlideConfigForm(forms.ModelForm):
    class Meta:
        model = GeneratedSlideConfig
        fields = ['is_visible', 'generated_slide_count', 'duration_seconds', 'transition_type', 'overflow_mode', 'scroll_speed']
        widgets = {
            'is_visible': forms.CheckboxInput(),
            'generated_slide_count': forms.NumberInput(attrs={'min': 1, 'max': 20, 'step': 1}),
            'duration_seconds': forms.NumberInput(attrs={'min': 1, 'max': 3600, 'step': 1}),
            'transition_type': forms.Select(),
            'overflow_mode': forms.Select(),
            'scroll_speed': forms.NumberInput(attrs={'min': 10, 'max': 1000, 'step': 10}),
        }


class WeatherSlideConfigForm(forms.ModelForm):
    class Meta:
        model = WeatherSlideConfig
        fields = ['is_visible', 'overlay_source', 'map_layer', 'duration_seconds']
        widgets = {
            'is_visible': forms.CheckboxInput(),
            'overlay_source': forms.Select(),
            'map_layer': forms.Select(),
            'duration_seconds': forms.NumberInput(attrs={'min': 1, 'max': 3600, 'step': 1}),
        }


class CalendarSlideConfigForm(forms.ModelForm):
    ALLOWED_HOSTS = {'calendar.google.com', 'www.google.com'}

    class Meta:
        model = CalendarSlideConfig
        fields = ['is_visible', 'public_url', 'duration_seconds']
        widgets = {
            'is_visible': forms.CheckboxInput(),
            'public_url': forms.URLInput(attrs={
                'placeholder': 'https://calendar.google.com/calendar/embed?...',
            }),
            'duration_seconds': forms.NumberInput(attrs={'min': 1, 'max': 3600, 'step': 1}),
        }

    def clean_public_url(self):
        public_url = (self.cleaned_data.get('public_url') or '').strip()
        if not public_url:
            return ''

        parsed = urlparse(public_url)
        host = parsed.netloc.lower()
        if parsed.scheme != 'https':
            raise forms.ValidationError("Use an HTTPS Google Calendar URL.")
        if host not in self.ALLOWED_HOSTS:
            raise forms.ValidationError("Use a public Google Calendar URL.")
        if not parsed.path.startswith('/calendar/'):
            raise forms.ValidationError("Use a Google Calendar URL, such as a public embed link.")
        return public_url

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('is_visible') and not cleaned_data.get('public_url'):
            self.add_error('public_url', "Add a public Google Calendar URL before showing this slide.")
        return cleaned_data


class BreakingNewsTickerConfigForm(forms.ModelForm):
    class Meta:
        model = BreakingNewsTickerConfig
        fields = [
            'mode',
            'include_dateline_titles',
            'include_weather_alerts',
            'include_custom_text',
            'custom_text',
            'scroll_speed',
            'font_family',
            'font_size',
            'text_color',
            'background_color',
        ]
        widgets = {
            'mode': forms.Select(),
            'include_dateline_titles': forms.CheckboxInput(),
            'include_weather_alerts': forms.CheckboxInput(),
            'include_custom_text': forms.CheckboxInput(),
            'custom_text': forms.TextInput(attrs={'maxlength': 500, 'placeholder': 'Type the persistent ticker text'}),
            'scroll_speed': forms.NumberInput(attrs={'min': 20, 'max': 400, 'step': 5}),
            'font_family': forms.Select(),
            'font_size': forms.NumberInput(attrs={'min': 12, 'max': 48, 'step': 1}),
            'text_color': forms.TextInput(attrs={'type': 'color', 'class': 'generated-color-input'}),
            'background_color': forms.TextInput(attrs={'type': 'color', 'class': 'generated-color-input'}),
        }
        labels = {
            'mode': 'Ticker',
            'include_dateline_titles': 'Use Dateline Titles',
            'include_weather_alerts': 'Use Weather Alerts',
            'include_custom_text': 'Use Custom Text',
            'custom_text': 'Custom Text',
            'scroll_speed': 'Scroll Speed',
            'font_family': 'Font',
            'font_size': 'Font Size',
            'text_color': 'Text Color',
            'background_color': 'Background Color',
        }

    def clean_custom_text(self):
        return (self.cleaned_data.get('custom_text') or '').strip()

    def clean(self):
        cleaned_data = super().clean()
        include_custom_text = cleaned_data.get('include_custom_text')
        custom_text = cleaned_data.get('custom_text') or ''
        if include_custom_text and not custom_text:
            self.add_error('custom_text', 'Add custom text before enabling that ticker source.')
        return cleaned_data


class TransitDashboardConfigForm(forms.ModelForm):
    MAP_PROVIDERS_REQUIRING_AUTH = {
        "CartoDB", "Esri", "HERE", "Jawg", "MapBox", "MapTiler", "MapTilesAPI",
        "NLS", "OpenWeatherMap", "Stadia", "Thunderforest", "TomTom", "AzureMaps",
    }

    class Meta:
        model = TransitDashboardConfig
        fields = [
            'is_visible', 'duration_seconds', 'selected_routes', 'map_layer', 'route_opacity_percent', 'animation_enabled', 'animation_easing',
            'initial_delay_seconds', 'animation_end_offset_seconds',
            'initial_zoom_offset', 'initial_x_offset_meters', 'initial_y_offset_meters',
            'zoom_offset', 'x_offset_meters', 'y_offset_meters',
            'show_incoming_buses', 'show_service_alerts', 'side_panel_order',
        ]
        widgets = {
            'is_visible': forms.CheckboxInput(),
            'duration_seconds': forms.NumberInput(attrs={'min': 1, 'max': 3600, 'step': 1}),
            'selected_routes': forms.CheckboxSelectMultiple(),
            'map_layer': forms.Select(choices=[('OpenStreetMap.Mapnik', 'OpenStreetMap Standard')]),
            'route_opacity_percent': forms.NumberInput(attrs={'type': 'range', 'min': 0, 'max': 100, 'step': 5}),
            'animation_enabled': forms.CheckboxInput(),
            'animation_easing': forms.Select(),
            'initial_delay_seconds': forms.NumberInput(attrs={'min': 0, 'max': 20, 'step': 1}),
            'animation_end_offset_seconds': forms.NumberInput(attrs={'min': 0, 'max': 20, 'step': 1}),
            'initial_zoom_offset': forms.NumberInput(attrs={'min': -5, 'max': 5, 'step': 1}),
            'initial_x_offset_meters': forms.NumberInput(attrs={'min': -5000, 'max': 5000, 'step': 100}),
            'initial_y_offset_meters': forms.NumberInput(attrs={'min': -5000, 'max': 5000, 'step': 100}),
            'zoom_offset': forms.NumberInput(attrs={'min': -5, 'max': 5, 'step': 1}),
            'x_offset_meters': forms.NumberInput(attrs={'min': -5000, 'max': 5000, 'step': 100}),
            'y_offset_meters': forms.NumberInput(attrs={'min': -5000, 'max': 5000, 'step': 100}),
            'show_incoming_buses': forms.CheckboxInput(),
            'show_service_alerts': forms.CheckboxInput(),
            'side_panel_order': forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['selected_routes'].queryset = TransitRoute.objects.filter(is_active=True)

    def clean_map_layer(self):
        provider = self.cleaned_data['map_layer'].strip()
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)*', provider):
            raise forms.ValidationError('Choose a supported map layer.')
        provider_name = provider.split('.', 1)[0]
        if provider_name in self.MAP_PROVIDERS_REQUIRING_AUTH or provider_name == 'OpenFireMap':
            raise forms.ValidationError('Choose a map layer that does not require authentication.')
        return provider

    def clean(self):
        cleaned_data = super().clean()
        duration = cleaned_data.get('duration_seconds')
        delay = cleaned_data.get('initial_delay_seconds')
        end_offset = cleaned_data.get('animation_end_offset_seconds')
        if (
            cleaned_data.get('animation_enabled')
            and duration is not None
            and delay is not None
            and end_offset is not None
            and delay + end_offset >= duration
        ):
            self.add_error(
                'animation_end_offset_seconds',
                'The initial delay and end offset must leave at least one second for the animation.',
            )
        return cleaned_data


class EmptyDisplayConfigForm(forms.ModelForm):
    class Meta:
        model = EmptyDisplayConfig
        fields = ['mode']
        widgets = {
            'mode': forms.Select(),
        }


class ScreenPowerScheduleForm(forms.ModelForm):
    def clean(self):
        data = super().clean()
        on, off = data.get('screen_on_time'), data.get('screen_off_time')
        if on and off and on.replace(second=0, microsecond=0) == off.replace(second=0, microsecond=0):
            self.add_error('screen_off_time', 'Screen on and off times must be different.')
        return data

    class Meta:
        model = ScreenPowerSchedule
        fields = ['is_enabled', 'screen_on_time', 'screen_off_time']
        widgets = {
            'screen_on_time': forms.TimeInput(attrs={'type': 'time', 'step': 60}, format='%H:%M'),
            'screen_off_time': forms.TimeInput(attrs={'type': 'time', 'step': 60}, format='%H:%M'),
        }


class SiteAppearanceForm(forms.ModelForm):
    favorite_theme_colors = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = SiteAppearanceSettings
        fields = ['public_base_url', 'theme_color', 'logo', 'favicon']
        widgets = {
            'theme_color': forms.TextInput(attrs={'type': 'color'}),
            'logo': forms.FileInput(attrs={'accept': '.png,.svg,image/png,image/svg+xml'}),
            'favicon': forms.FileInput(attrs={'accept': '.png,.svg,.ico,image/png,image/svg+xml,image/x-icon'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        favorite_colors = []
        if self.instance and self.instance.pk:
            favorite_colors = self.instance.favorite_theme_colors or []
        self.fields['favorite_theme_colors'].initial = json.dumps(favorite_colors)

    def clean_public_base_url(self):
        value = self.cleaned_data['public_base_url'].rstrip('/')
        parsed = urlparse(value)
        if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise forms.ValidationError('Enter an HTTP or HTTPS base URL without credentials, query parameters, or fragments.')
        return value

    def clean_favorite_theme_colors(self):
        raw_value = self.cleaned_data.get('favorite_theme_colors') or '[]'
        try:
            colors = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError('Favorite colors could not be read.') from exc

        if not isinstance(colors, list):
            raise forms.ValidationError('Favorite colors must be a list.')

        normalized = []
        seen = set()
        for value in colors:
            color = str(value or '').strip().upper()
            Post.color_validator(color)
            if color not in seen:
                normalized.append(color)
                seen.add(color)

        if len(normalized) > 8:
            raise forms.ValidationError('Save up to 8 favorite colors.')

        return normalized

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.favorite_theme_colors = self.cleaned_data.get('favorite_theme_colors', [])
        if commit:
            instance.save()
        return instance


class ImageEditForm(forms.Form):
    OVERLAY_POSITION_CHOICES = [
        ('top_left', 'Top Left'),
        ('top_center', 'Top Center'),
        ('top_right', 'Top Right'),
        ('center_left', 'Center Left'),
        ('center', 'Center'),
        ('center_right', 'Center Right'),
        ('bottom_left', 'Bottom Left'),
        ('bottom_center', 'Bottom Center'),
        ('bottom_right', 'Bottom Right'),
    ]

    rotation_degrees = CommaFriendlyFloatField(
        min_value=-180,
        max_value=180,
        initial=0,
        widget=forms.NumberInput(attrs={'min': -180, 'max': 180, 'step': 0.5}),
    )
    crop_left_percent = CommaFriendlyFloatField(min_value=0, max_value=95, initial=0, widget=forms.HiddenInput())
    crop_top_percent = CommaFriendlyFloatField(min_value=0, max_value=95, initial=0, widget=forms.HiddenInput())
    crop_width_percent = CommaFriendlyFloatField(min_value=5, max_value=100, initial=100, widget=forms.HiddenInput())
    crop_height_percent = CommaFriendlyFloatField(min_value=5, max_value=100, initial=100, widget=forms.HiddenInput())
    overlay_text = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.Textarea(attrs={'rows': 3}),
    )
    overlay_position = forms.ChoiceField(choices=OVERLAY_POSITION_CHOICES, initial='bottom_center')
    overlay_font_family = forms.ChoiceField(choices=OVERLAY_FONT_CHOICES, initial='sans_bold', required=False)
    overlay_text_color = forms.CharField(
        max_length=7,
        initial='#FFFFFF',
        validators=[Post.color_validator],
        widget=forms.TextInput(attrs={'type': 'color'}),
    )
    overlay_size_percent = forms.IntegerField(min_value=2, max_value=20, initial=6, widget=forms.NumberInput(attrs={'min': 2, 'max': 20, 'step': 1}))

    def __init__(self, *args, initial_settings=None, **kwargs):
        if initial_settings and 'initial' not in kwargs:
            kwargs['initial'] = normalize_image_edit_config(initial_settings)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        if self.errors:
            return cleaned_data

        max_width = max(5.0, 100.0 - cleaned_data['crop_left_percent'])
        max_height = max(5.0, 100.0 - cleaned_data['crop_top_percent'])
        cleaned_data['crop_width_percent'] = min(cleaned_data['crop_width_percent'], max_width)
        cleaned_data['crop_height_percent'] = min(cleaned_data['crop_height_percent'], max_height)
        cleaned_data['overlay_font_family'] = cleaned_data.get('overlay_font_family') or 'sans_bold'
        return cleaned_data

    def to_edit_settings(self):
        return normalize_image_edit_config(self.cleaned_data)


class SiteMigrationImportForm(forms.Form):
    archive_file = forms.FileField(required=False, label='Migration Zip File')
    archive_url = forms.URLField(
        required=False,
        label='Migration Zip URL',
        widget=forms.URLInput(attrs={'placeholder': 'https://example.com/slidercms-site-export.zip'}),
    )

    def clean(self):
        cleaned_data = super().clean()
        archive_file = cleaned_data.get('archive_file')
        archive_url = (cleaned_data.get('archive_url') or '').strip()

        if bool(archive_file) == bool(archive_url):
            raise forms.ValidationError('Choose either a zip file upload or a zip URL.')

        if archive_file and not archive_file.name.lower().endswith('.zip'):
            self.add_error('archive_file', 'Upload a .zip migration archive.')

        if archive_url:
            parsed = urlparse(archive_url)
            if parsed.scheme not in {'http', 'https'}:
                self.add_error('archive_url', 'Use an http or https URL for the migration archive.')

        return cleaned_data


class AdminSetUserPasswordForm(forms.Form):
    user = forms.ModelChoiceField(queryset=User.objects.none(), empty_label=None)
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

    def __init__(self, *args, user_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].queryset = user_queryset if user_queryset is not None else User.objects.order_by('username')
        self._selected_user = None

    def clean(self):
        cleaned_data = super().clean()
        selected_user = cleaned_data.get('user')
        if self.errors or not selected_user:
            return cleaned_data

        password1 = cleaned_data.get('new_password1')
        password2 = cleaned_data.get('new_password2')

        try:
            validate_basic_password(password1)
        except forms.ValidationError as exc:
            for error in exc.messages:
                self.add_error('new_password1', error)

        if password1 and password2 and password1 != password2:
            self.add_error('new_password2', "The two password fields didn't match.")

        self._selected_user = selected_user
        return cleaned_data

    def save(self):
        if self.errors or not self._selected_user:
            raise ValueError('The password form must be valid before saving.')
        self._selected_user.set_password(self.cleaned_data['new_password1'])
        self._selected_user.save(update_fields=['password'])
        return self._selected_user


class SlideOrderForm(forms.Form):
    ordered_ids = forms.JSONField()

    def clean_ordered_ids(self):
        ordered_ids = self.cleaned_data['ordered_ids']
        if not isinstance(ordered_ids, list):
            raise forms.ValidationError('Submit a list of slide IDs.')

        normalized_ids = []
        for value in ordered_ids:
            try:
                normalized_ids.append(int(value))
            except (TypeError, ValueError) as exc:
                raise forms.ValidationError('Slide order contains an invalid ID.') from exc

        if len(set(normalized_ids)) != len(normalized_ids):
            raise forms.ValidationError('Slide order contains duplicate IDs.')

        return normalized_ids


ImageSlideForm = MediaSlideForm
ImageUploadForm = MediaSlideForm
CustomContentForm = RichTextSlideForm
RawHtmlSlideForm = HtmlSlideForm
SlideDurationForm = SlidePlaybackForm
