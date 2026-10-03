from django.db import models
from django.db.models import Max
from django.conf import settings
from django.utils import timezone
from django.core.validators import FileExtensionValidator
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
import magic
from pdf2image import convert_from_path
import os
import json
import shutil
from django.core.files.base import ContentFile
from io import BytesIO
from pathlib import Path
from datetime import time
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from PIL import Image
from .media_processing import IMAGE_RENDITION_TARGETS, RENDITION_LAYOUT_VERSION, build_image_assets, build_video_thumbnail, image_edit_config_is_default

# To check if the uploaded file is valid:
IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'gif', 'webp']
VIDEO_EXTENSIONS = ['mp4', 'm4v', 'mov', 'webm', 'ogv']
DOCUMENT_EXTENSIONS = ['pdf']
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS + VIDEO_EXTENSIONS + DOCUMENT_EXTENSIONS

IMAGE_MIME_TYPES = {'image/png', 'image/jpg', 'image/jpeg', 'image/gif', 'image/webp'}
VIDEO_MIME_TYPES = {
    'application/mp4',
    'video/mp4',
    'video/x-m4v',
    'video/quicktime',
    'video/webm',
    'video/ogg',
}
DOCUMENT_MIME_TYPES = {'application/pdf'}
ALLOWED_MIME_TYPES = IMAGE_MIME_TYPES | VIDEO_MIME_TYPES | DOCUMENT_MIME_TYPES
GENERIC_BINARY_MIME_TYPES = {'application/octet-stream', 'binary/octet-stream'}

ext_validator = FileExtensionValidator(ALLOWED_EXTENSIONS)


def content_type_for_file_name(filename):
    extension = Path(filename).suffix.lower().lstrip('.')
    if extension in VIDEO_EXTENSIONS:
        return 'video'
    return 'image'


def validate_file_mimetype(file):
    file_mime_type = magic.from_buffer(file.read(4096), mime=True)
    file.seek(0)
    extension = Path(file.name).suffix.lower().lstrip('.')
    if extension in VIDEO_EXTENSIONS and file_mime_type in GENERIC_BINARY_MIME_TYPES:
        return
    if file_mime_type not in ALLOWED_MIME_TYPES:
        raise ValidationError(
            "Unsupported file type. Upload PNG, JPG, JPEG, GIF, WEBP, PDF, MP4, M4V, MOV, WEBM, or OGV."
        )


def _int_or_zero(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class Post(models.Model):
    CONTENT_IMAGE = 'image'
    CONTENT_VIDEO = 'video'
    CONTENT_RICH_TEXT = 'custom'
    CONTENT_HTML = 'html'
    CONTENT_YOUTUBE = 'youtube'
    CONTENT_GOOGLE_SLIDES = 'gslides'

    TRANSITION_FADE_GRAY = 'fade_gray'
    TRANSITION_FADE_BLACK = 'fade_black'
    TRANSITION_FADE_WHITE = 'fade_white'
    TRANSITION_CROSSFADE = 'crossfade'

    color_validator = RegexValidator(
        regex=r'^#[0-9A-Fa-f]{6}$',
        message='Use a valid 6-digit hex color, for example #005A43.',
    )

    CONTENT_TYPE_CHOICES = [
        (CONTENT_IMAGE, 'Image/PDF Slide'),
        (CONTENT_VIDEO, 'Video Slide'),
        (CONTENT_RICH_TEXT, 'Rich Text'),
        (CONTENT_HTML, 'Custom HTML'),
        (CONTENT_YOUTUBE, 'YouTube Slide'),
        (CONTENT_GOOGLE_SLIDES, 'Google Slides'),
    ]

    TRANSITION_CHOICES = [
        (TRANSITION_FADE_GRAY, 'Fade to Gray'),
        (TRANSITION_FADE_BLACK, 'Fade to Black'),
        (TRANSITION_FADE_WHITE, 'Fade to White'),
        (TRANSITION_CROSSFADE, 'Crossfade'),
    ]
    
    content_type = models.CharField(max_length=10, choices=CONTENT_TYPE_CHOICES, default='image')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    link = models.URLField(blank=True, null=True)
    youtube_url = models.URLField(blank=True, null=True, max_length=1000)
    youtube_start_seconds = models.PositiveIntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(0), MaxValueValidator(86400)],
    )
    youtube_end_seconds = models.PositiveIntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1), MaxValueValidator(86400)],
    )
    YOUTUBE_QUALITY_AUTO = 'auto'
    YOUTUBE_QUALITY_360 = 'medium'
    YOUTUBE_QUALITY_480 = 'large'
    YOUTUBE_QUALITY_720 = 'hd720'
    YOUTUBE_QUALITY_1080 = 'hd1080'
    YOUTUBE_QUALITY_4K = 'highres'
    YOUTUBE_QUALITY_CHOICES = [
        (YOUTUBE_QUALITY_AUTO, 'Auto'),
        (YOUTUBE_QUALITY_360, '360p'),
        (YOUTUBE_QUALITY_480, '480p'),
        (YOUTUBE_QUALITY_720, '720p'),
        (YOUTUBE_QUALITY_1080, '1080p'),
        (YOUTUBE_QUALITY_4K, 'Best available / 4K'),
    ]
    youtube_quality = models.CharField(
        max_length=20,
        choices=YOUTUBE_QUALITY_CHOICES,
        default=YOUTUBE_QUALITY_AUTO,
    )
    youtube_show_captions = models.BooleanField(default=False)
    google_slides_url = models.URLField(blank=True, null=True, max_length=2000)
    google_slides_start_slide = models.PositiveIntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1), MaxValueValidator(2000)],
    )
    google_slides_end_slide = models.PositiveIntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1), MaxValueValidator(2000)],
    )
    google_slides_advance_seconds = models.PositiveIntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1), MaxValueValidator(3600)],
    )
    text_color = models.CharField(
        max_length=7,
        default='#F8FAFC',
        validators=[color_validator],
    )
    background_color = models.CharField(
        max_length=7,
        default='#0F172A',
        validators=[color_validator],
    )
    duration_seconds = models.PositiveIntegerField(
        default=8,
        validators=[MinValueValidator(1), MaxValueValidator(3600)],
    )
    transition_type = models.CharField(
        max_length=20,
        choices=TRANSITION_CHOICES,
        default=TRANSITION_CROSSFADE,
    )
    is_visible = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0, db_index=True)
    media_revision = models.PositiveIntegerField(default=0)
    cover = models.FileField(
        upload_to='images/', 
        validators=[ext_validator, validate_file_mimetype],
        blank=True, 
        null=True
    )
    preview_image = models.FileField(upload_to='renditions/', blank=True, null=True)
    media_variants = models.JSONField(default=dict, blank=True)
    image_edit_settings = models.JSONField(default=dict, blank=True)

    def save(self, *args, **kwargs):
        was_adding = self._state.adding
        previous_cover_name = None
        previous_image_edit_settings = {}
        if self.pk:
            try:
                previous = Post.objects.only('cover', 'image_edit_settings').get(pk=self.pk)
                previous_cover_name = previous.cover.name
                previous_image_edit_settings = previous.image_edit_settings or {}
            except Post.DoesNotExist:
                previous_cover_name = None
                previous_image_edit_settings = {}

        if self.content_type == self.CONTENT_GOOGLE_SLIDES:
            self.duration_seconds = self.google_slides_total_duration_seconds

        if was_adding and not self.display_order:
            max_order = Post.objects.aggregate(max_order=Max('display_order'))['max_order'] or 0
            self.display_order = max_order + 1
        super().save(*args, **kwargs)

        converted_from_pdf = self._convert_pdf_cover_to_image()
        cover_changed = bool(self.cover) and previous_cover_name != self.cover.name
        image_edits_changed = (self.image_edit_settings or {}) != (previous_image_edit_settings or {})

        if self.cover and (was_adding or cover_changed or converted_from_pdf or image_edits_changed or not self.preview_image):
            self._rebuild_media_assets()
        elif not self.cover and (self.preview_image or self.media_variants):
            self._clear_generated_media_assets()
    
    def __str__(self):
        return f"{self.get_content_type_display()} - {self.title}"
    
    # Overriding built-in model delete
    # Means that the deleted file also gets deleted from database
    def delete(self, *args, **kwargs):
        self._clear_generated_media_assets()
        if self.cover:
            self.cover.delete(save=False)
        super().delete(*args, **kwargs)

    def _convert_pdf_cover_to_image(self):
        if not self.cover or not self.cover.name.lower().endswith('.pdf'):
            return False

        pdf_path = Path(self.cover.path)
        pages = convert_from_path(pdf_path, dpi=200, first_page=1, last_page=1)
        first_page = pages[0]
        buffer = BytesIO()
        first_page.save(buffer, format="PNG")
        buffer.seek(0)
        new_filename = f"{Path(self.cover.name).stem}.png"
        self.cover.save(new_filename, ContentFile(buffer.read()), save=False)
        self.content_type = self.CONTENT_IMAGE
        super().save(update_fields=['cover', 'content_type'])

        new_cover_path = Path(self.cover.path)
        if pdf_path.exists() and pdf_path != new_cover_path:
            pdf_path.unlink()
        return True

    def rendition_directory(self):
        return Path(settings.MEDIA_ROOT) / "renditions" / f"post-{self.pk}"

    def _clear_generated_media_assets(self, *, persist=False):
        rendition_dir = self.rendition_directory()
        if rendition_dir.exists():
            shutil.rmtree(rendition_dir, ignore_errors=True)

        self.preview_image = None
        self.media_variants = {}
        if persist and self.pk:
            super().save(update_fields=['preview_image', 'media_variants'])

    def _rebuild_media_assets(self):
        self._clear_generated_media_assets()
        output_dir = self.rendition_directory()

        if self.content_type == self.CONTENT_IMAGE:
            manifest = build_image_assets(
                Path(self.cover.path),
                output_dir,
                edit_config=self.image_edit_settings,
            )
        elif self.content_type == self.CONTENT_VIDEO:
            manifest = build_video_thumbnail(Path(self.cover.path), output_dir)
        else:
            return

        relative_output_dir = Path("renditions") / f"post-{self.pk}"
        thumbnail_name = manifest.get("thumbnail")
        self.preview_image.name = str(relative_output_dir / thumbnail_name) if thumbnail_name else ""

        display_variants = []
        for variant in manifest.get("display", []):
            variant_record = {
                "label": variant["label"],
                "width": variant["width"],
                "height": variant["height"],
                "path": self.cover.name if variant["path"] is None else str(relative_output_dir / variant["path"]),
            }
            display_variants.append(variant_record)

        editor_preview = manifest.get("editor_preview") or {}
        editor_preview_record = {}
        if editor_preview.get("path"):
            editor_preview_record = {
                "path": str(relative_output_dir / editor_preview["path"]),
                "width": editor_preview.get("width", 0),
                "height": editor_preview.get("height", 0),
            }

        self.media_variants = {
            "kind": manifest.get("kind", "image"),
            "animated": manifest.get("animated", False),
            "layout_version": manifest.get("layout_version", ""),
            "display": display_variants,
            "editor_preview": editor_preview_record,
        }
        self.media_revision += 1
        super().save(update_fields=['preview_image', 'media_variants', 'media_revision'])

    def ensure_media_assets(self):
        if not self.cover:
            return

        if (
            self.content_type == self.CONTENT_IMAGE
            and not (self.media_variants or {}).get("display")
            and self._adopt_existing_media_assets()
        ):
            return

        preview_name = self.preview_image.name if self.preview_image else ""
        uses_legacy_thumbnail = "thumbnail_200w" in preview_name
        generated_assets_missing = self._generated_media_assets_missing()
        if self.content_type == self.CONTENT_IMAGE and (
            not self.preview_image
            or not self.media_variants.get("display")
            or not self.media_variants.get("editor_preview")
            or self.media_variants.get("layout_version") != RENDITION_LAYOUT_VERSION
            or uses_legacy_thumbnail
            or generated_assets_missing
        ):
            self._rebuild_media_assets()
        elif self.content_type == self.CONTENT_VIDEO and (
            not self.preview_image
            or uses_legacy_thumbnail
            or generated_assets_missing
        ):
            self._rebuild_media_assets()

    def _adopt_existing_media_assets(self):
        rendition_dir = self.rendition_directory()
        thumbnail = rendition_dir / "thumbnail_250w.webp"
        editor_preview = rendition_dir / "editor_preview_600w.webp"
        if not thumbnail.is_file() or not editor_preview.is_file():
            return False

        try:
            with Image.open(self.cover.path) as source_image:
                original_width, original_height = source_image.size
                animated = bool(getattr(source_image, "is_animated", False))
        except (OSError, ValueError):
            return False

        display = []
        if animated:
            display.append({
                "label": "original",
                "width": original_width,
                "height": original_height,
                "path": self.cover.name,
            })
        else:
            native = rendition_dir / "screen_native.webp"
            if native.is_file():
                with Image.open(native) as native_image:
                    native_width, native_height = native_image.size
                display.append({
                    "label": "original",
                    "width": native_width,
                    "height": native_height,
                    "path": str(native.relative_to(settings.MEDIA_ROOT)),
                })
            else:
                display.append({
                    "label": "original",
                    "width": original_width,
                    "height": original_height,
                    "path": self.cover.name,
                })

            for label, target_width, target_height in IMAGE_RENDITION_TARGETS:
                variant_path = rendition_dir / f"screen_{target_width}x{target_height}.webp"
                if not variant_path.is_file():
                    continue
                with Image.open(variant_path) as variant_image:
                    width, height = variant_image.size
                display.append({
                    "label": label,
                    "width": width,
                    "height": height,
                    "path": str(variant_path.relative_to(settings.MEDIA_ROOT)),
                })

        with Image.open(editor_preview) as preview:
            preview_width, preview_height = preview.size

        self.preview_image.name = str(thumbnail.relative_to(settings.MEDIA_ROOT))
        self.media_variants = {
            "kind": "image",
            "animated": animated,
            "layout_version": RENDITION_LAYOUT_VERSION,
            "display": display,
            "editor_preview": {
                "path": str(editor_preview.relative_to(settings.MEDIA_ROOT)),
                "width": preview_width,
                "height": preview_height,
            },
        }
        self.media_revision = max(self.media_revision, 1)
        super().save(update_fields=["preview_image", "media_variants", "media_revision"])
        return True

    def _generated_media_assets_missing(self):
        generated_prefix = f"renditions/post-{self.pk}/"
        paths = []
        if self.preview_image:
            paths.append(self.preview_image.name)

        editor_preview = self.media_variants.get("editor_preview") or {}
        if editor_preview.get("path"):
            paths.append(editor_preview["path"])

        for variant in self.media_variants.get("display", []):
            path = variant.get("path")
            if path:
                paths.append(path)

        for path in paths:
            if str(path).startswith(generated_prefix) and not default_storage.exists(path):
                return True
        return False

    def media_url(self, relative_path):
        if not relative_path:
            return ""
        base_url = default_storage.url(relative_path)
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}v={self.media_revision}"

    @property
    def preview_url(self):
        if self.preview_image:
            return self.media_url(self.preview_image.name)
        if self.content_type == self.CONTENT_YOUTUBE:
            return self.youtube_thumbnail_url
        if self.content_type == self.CONTENT_GOOGLE_SLIDES:
            return ""
        if self.content_type == self.CONTENT_HTML:
            return ""
        if self.content_type == self.CONTENT_IMAGE and self.cover:
            return self.media_url(self.cover.name)
        return ""

    @property
    def cover_media_url(self):
        if self.cover:
            return self.media_url(self.cover.name)
        return ""

    @property
    def image_editor_preview_url(self):
        editor_preview = self.media_variants.get("editor_preview") or {}
        if editor_preview.get("path"):
            return self.media_url(editor_preview["path"])

        candidates = [variant for variant in self.display_renditions if variant.get("url")]
        if candidates:
            candidates.sort(key=lambda variant: abs(_int_or_zero(variant.get("width")) - 600))
            return candidates[0]["url"]

        return self.cover_media_url

    def display_rendition_url_near_width(self, target_width):
        candidates = [
            variant
            for variant in self.display_renditions
            if variant.get("url") and _int_or_zero(variant.get("width")) > 0
        ]
        if candidates:
            candidates.sort(key=lambda variant: abs(_int_or_zero(variant.get("width")) - target_width))
            return candidates[0]["url"]
        return self.primary_display_url

    @property
    def slide_library_preview_url(self):
        if self.content_type == self.CONTENT_IMAGE and not self.media_variants.get("animated", False):
            return self.display_rendition_url_near_width(600)

        return self.preview_url or self.cover_media_url

    @property
    def primary_display_url(self):
        display_renditions = self.display_renditions
        if display_renditions:
            return display_renditions[0]["url"]
        return self.cover_media_url

    @property
    def initial_display_url(self):
        if self.content_type == self.CONTENT_IMAGE and self.media_variants.get("animated", False):
            return self.cover_media_url
        if self.content_type == self.CONTENT_IMAGE:
            return self.display_rendition_url_near_width(1920)
        return self.preview_url or self.primary_display_url

    @property
    def display_srcset(self):
        if self.content_type != self.CONTENT_IMAGE or self.media_variants.get("animated", False):
            return ""

        srcset_entries = []
        seen_widths = set()
        for variant in self.display_renditions:
            width = _int_or_zero(variant.get("width"))
            url = variant.get("url")
            if not url or width <= 0 or width in seen_widths:
                continue
            srcset_entries.append(f"{url} {width}w")
            seen_widths.add(width)
        return ", ".join(srcset_entries)

    @property
    def is_editable_image(self):
        return (
            self.content_type == self.CONTENT_IMAGE
            and bool(self.cover)
            and not self.media_variants.get("animated", False)
        )

    @property
    def has_image_edits(self):
        return self.content_type == self.CONTENT_IMAGE and not image_edit_config_is_default(self.image_edit_settings)

    @property
    def display_renditions(self):
        display_entries = []
        for variant in self.media_variants.get("display", []):
            display_entries.append(
                {
                    "label": variant.get("label", "original"),
                    "width": variant.get("width", 0),
                    "height": variant.get("height", 0),
                    "url": self.media_url(variant.get("path")),
                }
            )
        if not display_entries and self.cover:
            display_entries.append(
                {
                    "label": "original",
                    "width": 0,
                    "height": 0,
                    "url": self.media_url(self.cover.name),
                }
            )
        return display_entries

    @property
    def display_renditions_json(self):
        return json.dumps(self.display_renditions)

    @property
    def youtube_video_id(self):
        return extract_youtube_video_id(self.youtube_url)

    @property
    def youtube_thumbnail_url(self):
        if not self.youtube_video_id:
            return ""
        return f"https://i.ytimg.com/vi/{self.youtube_video_id}/hqdefault.jpg"

    @property
    def youtube_embed_url(self):
        if not self.youtube_video_id:
            return ""

        query = {
            "autoplay": 1,
            "mute": 1,
            "controls": 0,
            "rel": 0,
            "playsinline": 1,
            "modestbranding": 1,
        }
        if self.youtube_start_seconds:
            query["start"] = int(self.youtube_start_seconds)
        if self.youtube_end_seconds:
            query["end"] = int(self.youtube_end_seconds)
        if self.youtube_quality and self.youtube_quality != self.YOUTUBE_QUALITY_AUTO:
            query["vq"] = self.youtube_quality
        if self.youtube_show_captions:
            query["cc_load_policy"] = 1
        else:
            query["cc_load_policy"] = 0

        return f"https://www.youtube-nocookie.com/embed/{self.youtube_video_id}?{urlencode(query)}"

    @property
    def google_slides_start_slide_number(self):
        return max(1, int(self.google_slides_start_slide or 1))

    @property
    def google_slides_end_slide_number(self):
        end_slide = int(self.google_slides_end_slide or self.google_slides_start_slide_number)
        return max(self.google_slides_start_slide_number, end_slide)

    @property
    def google_slides_advance_interval_seconds(self):
        return max(1, int(self.google_slides_advance_seconds or 8))

    @property
    def google_slides_slide_count(self):
        return (self.google_slides_end_slide_number - self.google_slides_start_slide_number) + 1

    @property
    def google_slides_total_duration_seconds(self):
        return self.google_slides_slide_count * self.google_slides_advance_interval_seconds

    @property
    def google_slides_range_label(self):
        start_slide = self.google_slides_start_slide_number
        end_slide = self.google_slides_end_slide_number
        if start_slide == end_slide:
            return f"Slide {start_slide}"
        return f"Slides {start_slide}-{end_slide}"

    @property
    def google_slides_embed_url(self):
        base_url = normalize_google_slides_url(self.google_slides_url)
        if not base_url:
            return ""

        parsed = urlparse(base_url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        query["start"] = ["true"]
        query["loop"] = ["false"]
        query["delayms"] = [str(self.google_slides_advance_interval_seconds * 1000)]
        query["rm"] = ["minimal"]
        slide_id = f"id.p{self.google_slides_start_slide_number}"
        query["slide"] = [slide_id]
        slide_fragment = f"slide={slide_id}"
        return urlunparse(
            parsed._replace(
                query=urlencode(query, doseq=True),
                fragment=slide_fragment,
            )
        )

    @property
    def html_source_element_id(self):
        return f"html-slide-source-{self.pk}"

    @property
    def html_slide_document(self):
        raw_html = self.description or ""
        lowered = raw_html.lower()
        if "<html" in lowered:
            return raw_html
        return (
            "<!doctype html>\n"
            '<html lang="en">\n'
            "<head>\n"
            '<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            "<style>html,body{width:100%;height:100%;margin:0;overflow:hidden;}</style>\n"
            "</head>\n"
            f"<body>{raw_html}</body>\n"
            "</html>"
        )

    class Meta:
        ordering = ['display_order', 'id']


def extract_youtube_video_id(raw_url):
    if not raw_url:
        return ""

    parsed = urlparse((raw_url or "").strip())
    host = (parsed.netloc or "").lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    candidate = ""
    if host in {"youtu.be", "www.youtu.be"}:
        candidate = path_parts[0] if path_parts else ""
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"}:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        elif path_parts and path_parts[0] in {"embed", "shorts", "live"}:
            candidate = path_parts[1] if len(path_parts) > 1 else ""

    if candidate and len(candidate) == 11 and all(char.isalnum() or char in "-_" for char in candidate):
        return candidate
    return ""


def normalize_google_slides_url(raw_url):
    if not raw_url:
        return ""

    parsed = urlparse((raw_url or "").strip())
    if parsed.scheme != "https":
        return ""

    host = (parsed.netloc or "").lower()
    if host != "docs.google.com":
        return ""

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 3 or path_parts[0] != "presentation" or path_parts[1] != "d":
        return ""

    if path_parts[2] == "e":
        if len(path_parts) < 4:
            return ""
        base_path = f"/presentation/d/e/{path_parts[3]}/embed"
    else:
        base_path = f"/presentation/d/{path_parts[2]}/embed"

    source_query = parse_qs(parsed.query, keep_blank_values=True)
    normalized_query = []
    for key in sorted(source_query.keys()):
        if key in {"delayms", "loop", "rm", "slide", "start"}:
            continue
        for value in source_query.get(key, []):
            normalized_query.append((key, value))
    normalized_query.append(("rm", "minimal"))
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            base_path,
            "",
            urlencode(normalized_query, doseq=True),
            "",
        )
    )


class GeneratedSlideConfig(models.Model):
    DATELINE = 'dateline'
    OVERFLOW_SCROLL = 'scroll'
    OVERFLOW_SCALE = 'scale'
    OVERFLOW_CLIP = 'clip'

    SCRAPER_CHOICES = [
        (DATELINE, 'Dateline Announcements'),
    ]
    OVERFLOW_MODE_CHOICES = [
        (OVERFLOW_SCROLL, 'Scroll top to bottom'),
        (OVERFLOW_SCALE, 'Scale down to fit'),
        (OVERFLOW_CLIP, 'Clip overflow'),
    ]

    scraper_name = models.CharField(
        max_length=30,
        choices=SCRAPER_CHOICES,
        default=DATELINE,
        unique=True,
    )
    is_visible = models.BooleanField(default=True)
    generated_slide_count = models.PositiveIntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(20)],
    )
    duration_seconds = models.PositiveIntegerField(
        default=8,
        validators=[MinValueValidator(1), MaxValueValidator(3600)],
    )
    transition_type = models.CharField(
        max_length=20,
        choices=Post.TRANSITION_CHOICES,
        default=Post.TRANSITION_CROSSFADE,
    )
    overflow_mode = models.CharField(
        max_length=10,
        choices=OVERFLOW_MODE_CHOICES,
        default=OVERFLOW_CLIP,
    )
    scroll_speed = models.PositiveIntegerField(
        default=80,
        validators=[MinValueValidator(10), MaxValueValidator(1000)],
    )

    def __str__(self):
        return self.get_scraper_name_display()


class SingletonConfigModel(models.Model):
    singleton_id = 1

    class Meta:
        abstract = True

    @classmethod
    def load(cls):
        config, _ = cls.objects.get_or_create(pk=cls.singleton_id)
        return config

    def save(self, *args, **kwargs):
        self.pk = self.singleton_id
        super().save(*args, **kwargs)


class WeatherSlideConfig(SingletonConfigModel):
    RAINVIEWER = 'rainviewer'
    NASA_GIBS = 'nasa_gibs'

    OSM_HOT = 'osm_hot'
    OSM_STANDARD = 'osm_standard'
    OPENTOPOMAP = 'opentopomap'
    CYCLOSM = 'cyclosm'

    OVERLAY_SOURCE_CHOICES = [
        (RAINVIEWER, 'RainViewer radar (precipitation only)'),
        (NASA_GIBS, 'NASA GIBS GOES-East satellite'),
    ]

    MAP_LAYER_CHOICES = [
        (OSM_HOT, 'OpenStreetMap Humanitarian'),
        (OSM_STANDARD, 'OpenStreetMap Standard'),
        (OPENTOPOMAP, 'OpenTopoMap'),
        (CYCLOSM, 'CyclOSM'),
    ]

    is_visible = models.BooleanField(default=True)
    overlay_source = models.CharField(
        max_length=30,
        choices=OVERLAY_SOURCE_CHOICES,
        default=RAINVIEWER,
    )
    map_layer = models.CharField(
        max_length=30,
        choices=MAP_LAYER_CHOICES,
        default=OSM_HOT,
    )
    duration_seconds = models.PositiveIntegerField(
        default=24,
        validators=[MinValueValidator(1), MaxValueValidator(3600)],
    )

    def __str__(self):
        return "Weather Dashboard"


class CalendarSlideConfig(SingletonConfigModel):
    is_visible = models.BooleanField(default=False)
    public_url = models.URLField(blank=True, max_length=2000)
    duration_seconds = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(3600)],
    )

    def __str__(self):
        return "Google Calendar"


class TransitRoute(models.Model):
    code = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=120)
    color = models.CharField(
        max_length=7,
        default="#005a43",
        validators=[RegexValidator(r"^#[0-9a-fA-F]{6}$", "Enter a six-digit hex color.")],
    )
    schedule_url = models.URLField(max_length=500, blank=True)
    provider_route_ids = models.JSONField(default=list, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("sort_order", "code")

    def __str__(self):
        return f"{self.code} - {self.name}"


class TransitDashboardConfig(SingletonConfigModel):
    EASING_GENTLE = "gentle"
    EASING_SMOOTH = "smooth"
    EASING_BRISK = "brisk"
    EASING_CHOICES = [
        (EASING_GENTLE, "Gentle"),
        (EASING_SMOOTH, "Smooth"),
        (EASING_BRISK, "Direct"),
    ]

    PANEL_INCOMING_FIRST = "incoming_first"
    PANEL_ALERTS_FIRST = "alerts_first"
    PANEL_ORDER_CHOICES = [
        (PANEL_INCOMING_FIRST, "Next incoming buses, then service alerts"),
        (PANEL_ALERTS_FIRST, "Service alerts, then next incoming buses"),
    ]

    is_visible = models.BooleanField(default=False)
    animation_enabled = models.BooleanField(default=True)
    animation_easing = models.CharField(max_length=12, choices=EASING_CHOICES, default=EASING_SMOOTH)
    duration_seconds = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(3600)],
    )
    initial_delay_seconds = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(20)],
    )
    animation_end_offset_seconds = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(0), MaxValueValidator(20)],
    )
    map_layer = models.CharField(max_length=128, default="OpenStreetMap.Mapnik")
    route_opacity_percent = models.PositiveSmallIntegerField(
        default=100,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    initial_zoom_offset = models.SmallIntegerField(default=0, validators=[MinValueValidator(-5), MaxValueValidator(5)])
    initial_x_offset_meters = models.SmallIntegerField(default=0, validators=[MinValueValidator(-5000), MaxValueValidator(5000)])
    initial_y_offset_meters = models.SmallIntegerField(default=0, validators=[MinValueValidator(-5000), MaxValueValidator(5000)])
    zoom_offset = models.SmallIntegerField(default=0, validators=[MinValueValidator(-5), MaxValueValidator(5)])
    x_offset_meters = models.SmallIntegerField(default=0, validators=[MinValueValidator(-5000), MaxValueValidator(5000)])
    y_offset_meters = models.SmallIntegerField(default=0, validators=[MinValueValidator(-5000), MaxValueValidator(5000)])
    show_incoming_buses = models.BooleanField(default=True)
    show_service_alerts = models.BooleanField(default=True)
    side_panel_order = models.CharField(
        max_length=20, choices=PANEL_ORDER_CHOICES, default=PANEL_INCOMING_FIRST,
    )
    selected_routes = models.ManyToManyField(TransitRoute, blank=True, related_name="dashboard_configs")

    def __str__(self):
        return "Transit Dashboard"


class EmptyDisplayConfig(SingletonConfigModel):
    AUTO = 'auto'
    MESSAGE = 'message'
    BLANK = 'blank'
    DATELINE = 'dateline'
    WEATHER = 'weather'
    CALENDAR = 'calendar'
    TRANSIT = 'transit'

    DISPLAY_CHOICES = [
        (AUTO, 'Automatic'),
        (MESSAGE, 'No Content Message'),
        (BLANK, 'Blank Screen'),
        (DATELINE, 'Dateline Announcements'),
        (WEATHER, 'Weather Dashboard'),
        (CALENDAR, 'Google Calendar'),
        (TRANSIT, 'Campus Transit Dashboard'),
    ]

    mode = models.CharField(
        max_length=20,
        choices=DISPLAY_CHOICES,
        default=AUTO,
    )

    def __str__(self):
        return "Empty Display Fallback"


class BreakingNewsTickerConfig(SingletonConfigModel):
    MODE_OFF = 'off'
    MODE_ON = 'on'
    MODE_CHOICES = [
        (MODE_OFF, 'Off'),
        (MODE_ON, 'On'),
    ]
    FONT_SYSTEM = 'system'
    FONT_ARIAL = 'arial'
    FONT_VERDANA = 'verdana'
    FONT_TREBUCHET = 'trebuchet'
    FONT_GEORGIA = 'georgia'
    FONT_TIMES = 'times'
    FONT_COURIER = 'courier'
    FONT_CHOICES = [
        (FONT_SYSTEM, 'System Sans'),
        (FONT_ARIAL, 'Arial'),
        (FONT_VERDANA, 'Verdana'),
        (FONT_TREBUCHET, 'Trebuchet MS'),
        (FONT_GEORGIA, 'Georgia'),
        (FONT_TIMES, 'Times New Roman'),
        (FONT_COURIER, 'Courier New'),
    ]

    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=MODE_OFF)
    include_dateline_titles = models.BooleanField(default=False)
    include_weather_alerts = models.BooleanField(default=False)
    include_custom_text = models.BooleanField(default=False)
    custom_text = models.CharField(max_length=500, blank=True)
    scroll_speed = models.PositiveIntegerField(
        default=110,
        validators=[MinValueValidator(20), MaxValueValidator(400)],
    )
    font_family = models.CharField(
        max_length=20,
        choices=FONT_CHOICES,
        default=FONT_SYSTEM,
    )
    font_size = models.PositiveIntegerField(
        default=20,
        validators=[MinValueValidator(12), MaxValueValidator(48)],
    )
    text_color = models.CharField(
        max_length=7,
        default='#FFFFFF',
        validators=[Post.color_validator],
    )
    background_color = models.CharField(
        max_length=7,
        default='#B42318',
        validators=[Post.color_validator],
    )

    @property
    def is_enabled(self):
        return self.mode == self.MODE_ON

    @property
    def font_stack(self):
        return {
            self.FONT_ARIAL: 'Arial, Helvetica, sans-serif',
            self.FONT_VERDANA: 'Verdana, Geneva, sans-serif',
            self.FONT_TREBUCHET: 'Trebuchet MS, Arial, sans-serif',
            self.FONT_GEORGIA: 'Georgia, Times, serif',
            self.FONT_TIMES: 'Times New Roman, Times, serif',
            self.FONT_COURIER: 'Courier New, Courier, monospace',
        }.get(self.font_family, 'system-ui, -apple-system, BlinkMacSystemFont, sans-serif')

    def __str__(self):
        return "Breaking News Ticker"


class ScreenPowerSchedule(SingletonConfigModel):
    is_enabled = models.BooleanField(default=True)
    screen_on_time = models.TimeField(default=time(8, 0))
    screen_off_time = models.TimeField(default=time(17, 0))
    last_screen_on_run = models.DateTimeField(blank=True, null=True, editable=False)
    last_screen_off_run = models.DateTimeField(blank=True, null=True, editable=False)
    last_scheduler_check = models.DateTimeField(blank=True, null=True, editable=False)
    last_attempt_at = models.DateTimeField(blank=True, null=True, editable=False)
    last_applied_slot = models.CharField(max_length=40, blank=True, editable=False)
    last_error = models.TextField(blank=True, editable=False)

    @property
    def scheduler_healthy(self):
        return bool(self.last_scheduler_check and (timezone.now() - self.last_scheduler_check).total_seconds() < 300)

    def __str__(self):
        return "Screen Power Schedule"


class ActivityLog(models.Model):
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    username = models.CharField(max_length=150)
    action = models.CharField(max_length=160)
    target = models.CharField(max_length=300, blank=True)
    outcome = models.CharField(max_length=20, choices=[('success', 'Success'), ('failed', 'Failed'), ('submitted', 'Submitted')])

    class Meta:
        ordering = ['-occurred_at', '-pk']


class SiteAppearanceSettings(SingletonConfigModel):
    public_base_url = models.URLField(max_length=2048, default='http://pi-serv.rex-powan.ts.net')
    logo = models.FileField(
        upload_to='branding/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(['png', 'svg'])],
    )
    favicon = models.FileField(
        upload_to='branding/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(['png', 'svg', 'ico'])],
    )
    theme_color = models.CharField(
        max_length=7,
        default='#005A43',
        validators=[Post.color_validator],
    )
    favorite_theme_colors = models.JSONField(default=list, blank=True)
    asset_revision = models.PositiveIntegerField(default=0, editable=False)

    def save(self, *args, **kwargs):
        previous_logo_name = None
        previous_favicon_name = None
        if self.pk:
            try:
                previous = SiteAppearanceSettings.objects.only('logo', 'favicon').get(pk=self.pk)
                previous_logo_name = previous.logo.name if previous.logo else None
                previous_favicon_name = previous.favicon.name if previous.favicon else None
            except SiteAppearanceSettings.DoesNotExist:
                previous_logo_name = None
                previous_favicon_name = None

        if (
            previous_logo_name != (self.logo.name if self.logo else None)
            or previous_favicon_name != (self.favicon.name if self.favicon else None)
        ):
            self.asset_revision += 1

        super().save(*args, **kwargs)

        for previous_name, current_file in (
            (previous_logo_name, self.logo),
            (previous_favicon_name, self.favicon),
        ):
            current_name = current_file.name if current_file else None
            if previous_name and previous_name != current_name:
                default_storage.delete(previous_name)

    def asset_url(self, asset):
        if not asset:
            return ""
        base_url = default_storage.url(asset.name)
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}v={self.asset_revision}"

    @property
    def logo_url(self):
        return self.asset_url(self.logo)

    @property
    def favicon_url(self):
        return self.asset_url(self.favicon)

    def __str__(self):
        return "Site Appearance"
