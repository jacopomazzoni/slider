import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_time

from .models import (
    BreakingNewsTickerConfig,
    CalendarSlideConfig,
    EmptyDisplayConfig,
    GeneratedSlideConfig,
    Post,
    ScreenPowerSchedule,
    SlideLibraryConfig,
    TransitDashboardConfig,
    TransitRoute,
    SiteAppearanceSettings,
    WeatherSlideConfig,
)


ARCHIVE_FORMAT = "slidercms-site-export"
ARCHIVE_VERSION = 1
MANIFEST_NAME = "manifest.json"
MEDIA_PREFIX = "media/"
DATELINE_ARCHIVE_PATH = "project_files/dateline_announcements.json"
DOWNLOAD_CHUNK_SIZE = 64 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_ARCHIVE_SIZE_BYTES = 4 * 1024 * 1024 * 1024


class SiteMigrationError(Exception):
    pass


@dataclass
class SiteImportResult:
    post_count: int
    media_file_count: int


def dateline_json_path():
    return Path(settings.DATELINE_PATH)


def export_site_archive(*, exported_by="system"):
    archive_file = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024, mode="w+b")
    manifest = build_site_manifest(exported_by=exported_by)

    with zipfile.ZipFile(archive_file, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True))
        for file_path in iter_media_files():
            archive.write(file_path, f"{MEDIA_PREFIX}{file_path.relative_to(settings.MEDIA_ROOT).as_posix()}")

        dateline_path = dateline_json_path()
        if dateline_path.exists():
            archive.write(dateline_path, DATELINE_ARCHIVE_PATH)

    archive_file.seek(0)
    return archive_file


def build_site_manifest(*, exported_by="system"):
    dateline_path = dateline_json_path()
    media_files = list(iter_media_files())
    transit_config = TransitDashboardConfig.objects.first()
    transit_config_data = serialize_instance_or_none(transit_config)
    if transit_config_data:
        transit_config_data["selected_route_codes"] = list(
            transit_config.selected_routes.order_by("sort_order", "code").values_list("code", flat=True)
        )
    return {
        "format": ARCHIVE_FORMAT,
        "version": ARCHIVE_VERSION,
        "exported_at": timezone.now().isoformat(),
        "exported_by": exported_by,
        "posts": [serialize_instance(post) for post in Post.objects.order_by("display_order", "id")],
        "generated_slide_configs": [
            serialize_instance(config)
            for config in GeneratedSlideConfig.objects.order_by("scraper_name")
        ],
        "weather_slide_config": serialize_instance_or_none(WeatherSlideConfig.objects.first()),
        "calendar_slide_config": serialize_instance_or_none(CalendarSlideConfig.objects.first()),
        "transit_dashboard_config": transit_config_data,
        "transit_routes": [serialize_instance(route) for route in TransitRoute.objects.order_by("sort_order", "code")],
        "empty_display_config": serialize_instance_or_none(EmptyDisplayConfig.objects.first()),
        "breaking_news_ticker_config": serialize_instance_or_none(BreakingNewsTickerConfig.objects.first()),
        "screen_power_schedule": serialize_instance_or_none(ScreenPowerSchedule.objects.first()),
        "slide_library_config": serialize_instance_or_none(SlideLibraryConfig.objects.first()),
        "site_appearance": serialize_instance_or_none(SiteAppearanceSettings.objects.first()),
        "project_files": {
            "dateline_announcements": {
                "present": dateline_path.exists(),
                "archive_path": DATELINE_ARCHIVE_PATH if dateline_path.exists() else None,
            },
        },
        "counts": {
            "posts": Post.objects.count(),
            "media_files": len(media_files),
        },
    }


def iter_media_files():
    media_root = Path(settings.MEDIA_ROOT)
    if not media_root.exists():
        return []
    return [path for path in sorted(media_root.rglob("*")) if path.is_file()]


def serialize_instance_or_none(instance):
    return serialize_instance(instance) if instance else None


def serialize_instance(instance):
    payload = {"pk": instance.pk, "fields": {}}
    for field in instance._meta.concrete_fields:
        if field.primary_key:
            continue
        payload["fields"][field.name] = serialize_field_value(field, field.value_from_object(instance))
    return payload


def serialize_field_value(field, value):
    if hasattr(value, "name"):
        value = value.name

    if value is None:
        return None

    if isinstance(field, (models.DateTimeField, models.DateField, models.TimeField)):
        return value.isoformat()

    return value


def download_site_archive_from_url(archive_url):
    download_target = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024, mode="w+b")
    total_bytes = 0
    request = urllib.request.Request(
        archive_url,
        headers={"User-Agent": "sliderCMS Site Migration"},
    )

    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_ARCHIVE_SIZE_BYTES:
                    raise SiteMigrationError("The migration archive is larger than 4 GB.")
                download_target.write(chunk)
    except SiteMigrationError:
        raise
    except (urllib.error.URLError, OSError) as exc:
        raise SiteMigrationError("The migration archive could not be downloaded from that URL.") from exc

    download_target.seek(0)
    return download_target


def import_site_archive(archive_file):
    try:
        archive_file.seek(0)
    except (AttributeError, OSError):
        pass

    try:
        with zipfile.ZipFile(archive_file, "r", allowZip64=True) as archive:
            manifest = load_manifest(archive)
            validate_archive(archive, manifest)
            workspace_parent = Path(settings.MEDIA_ROOT).parent
            workspace_parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".slidercms-import-", dir=workspace_parent) as workspace_dir:
                workspace = Path(workspace_dir)
                extracted_media_root = workspace / "media"
                media_file_count = extract_media_files(archive, extracted_media_root)
                extracted_dateline_path = extract_dateline_file(archive, manifest, workspace)
                apply_site_import(
                    manifest,
                    extracted_media_root=extracted_media_root,
                    extracted_dateline_path=extracted_dateline_path,
                )
    except zipfile.BadZipFile as exc:
        raise SiteMigrationError("The selected file is not a valid sliderCMS migration zip archive.") from exc

    return SiteImportResult(
        post_count=len(manifest.get("posts", [])),
        media_file_count=media_file_count,
    )


def load_manifest(archive):
    try:
        manifest_bytes = archive.read(MANIFEST_NAME)
    except KeyError as exc:
        raise SiteMigrationError("The migration archive is missing manifest.json.") from exc

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SiteMigrationError("The migration archive manifest could not be read.") from exc

    if manifest.get("format") != ARCHIVE_FORMAT:
        raise SiteMigrationError("This zip file is not a sliderCMS site migration archive.")
    if manifest.get("version") != ARCHIVE_VERSION:
        raise SiteMigrationError(
            f"Unsupported archive version {manifest.get('version')}. This site expects version {ARCHIVE_VERSION}."
        )

    return manifest


def validate_archive(archive, manifest):
    zip_names = set(archive.namelist())
    missing_media_paths = sorted(
        relative_path
        for relative_path in expected_media_paths(manifest)
        if f"{MEDIA_PREFIX}{relative_path}" not in zip_names
    )
    if missing_media_paths:
        preview = ", ".join(missing_media_paths[:3])
        suffix = "..." if len(missing_media_paths) > 3 else ""
        raise SiteMigrationError(
            f"The archive is missing required media files: {preview}{suffix}"
        )

    dateline_meta = manifest.get("project_files", {}).get("dateline_announcements", {})
    archive_path = dateline_meta.get("archive_path")
    if dateline_meta.get("present") and archive_path not in zip_names:
        raise SiteMigrationError("The archive is missing the exported dateline announcements file.")


def expected_media_paths(manifest):
    paths = set()

    for record in manifest.get("posts", []):
        fields = record.get("fields", {})
        add_media_path(paths, fields.get("cover"))
        add_media_path(paths, fields.get("preview_image"))
        media_variants = fields.get("media_variants") or {}
        for variant in media_variants.get("display", []):
            add_media_path(paths, variant.get("path"))

    site_appearance = manifest.get("site_appearance") or {}
    appearance_fields = site_appearance.get("fields", {})
    add_media_path(paths, appearance_fields.get("logo"))
    add_media_path(paths, appearance_fields.get("favicon"))
    return paths


def add_media_path(path_set, relative_path):
    if relative_path:
        path_set.add(relative_path.lstrip("/"))


def extract_media_files(archive, extracted_media_root):
    extracted_media_root.mkdir(parents=True, exist_ok=True)
    media_file_count = 0

    for archive_name in archive.namelist():
        if not archive_name.startswith(MEDIA_PREFIX) or archive_name.endswith("/"):
            continue

        relative_target = safe_relative_zip_path(archive_name, MEDIA_PREFIX)
        target_path = extracted_media_root / relative_target
        target_path.parent.mkdir(parents=True, exist_ok=True)

        with archive.open(archive_name, "r") as source, target_path.open("wb") as destination:
            shutil.copyfileobj(source, destination)

        media_file_count += 1

    return media_file_count


def extract_dateline_file(archive, manifest, workspace):
    dateline_meta = manifest.get("project_files", {}).get("dateline_announcements", {})
    if not dateline_meta.get("present"):
        return None

    archive_name = dateline_meta.get("archive_path") or DATELINE_ARCHIVE_PATH
    target_path = workspace / "project_files" / "dateline_announcements.json"
    target_path.parent.mkdir(parents=True, exist_ok=True)

    with archive.open(archive_name, "r") as source, target_path.open("wb") as destination:
        shutil.copyfileobj(source, destination)

    return target_path


def safe_relative_zip_path(archive_name, prefix):
    raw_relative = archive_name[len(prefix):]
    relative_path = Path(raw_relative)

    if not raw_relative or relative_path.is_absolute() or ".." in relative_path.parts:
        raise SiteMigrationError(f"Unsafe archive entry detected: {archive_name}")

    return relative_path


def apply_site_import(manifest, *, extracted_media_root, extracted_dateline_path):
    media_root = Path(settings.MEDIA_ROOT)
    dateline_path = dateline_json_path()

    with tempfile.TemporaryDirectory(prefix=".slidercms-rollback-", dir=media_root.parent) as backup_dir:
        backup_root = Path(backup_dir)
        media_backup = backup_root / "media"
        dateline_backup = backup_root / "dateline_announcements.json"

        if dateline_path.exists():
            dateline_backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dateline_path, dateline_backup)

        original_media_moved = False
        try:
            with transaction.atomic():
                # Both directory renames stay on one filesystem, keeping the DB
                # lock short without copying the old media tree to temporary storage.
                if media_root.exists():
                    os.replace(media_root, media_backup)
                    original_media_moved = True
                os.replace(extracted_media_root, media_root)
                replace_dateline_file(extracted_dateline_path, dateline_path)
                replace_database_records(manifest)
        except Exception:
            if media_root.exists():
                shutil.rmtree(media_root, ignore_errors=True)
            if original_media_moved and media_backup.exists():
                os.replace(media_backup, media_root)
            restore_dateline_file(dateline_path, dateline_backup)
            raise


def replace_database_records(manifest):
    Post.objects.all().delete()
    GeneratedSlideConfig.objects.all().delete()
    WeatherSlideConfig.objects.all().delete()
    CalendarSlideConfig.objects.all().delete()
    TransitDashboardConfig.objects.all().delete()
    if "transit_routes" in manifest:
        TransitRoute.objects.all().delete()
        restore_records(TransitRoute, manifest.get("transit_routes", []))
    EmptyDisplayConfig.objects.all().delete()
    BreakingNewsTickerConfig.objects.all().delete()
    ScreenPowerSchedule.objects.all().delete()
    SiteAppearanceSettings.objects.all().delete()

    restore_records(Post, manifest.get("posts", []))
    restore_records(GeneratedSlideConfig, manifest.get("generated_slide_configs", []))
    restore_singleton(WeatherSlideConfig, manifest.get("weather_slide_config"))
    restore_singleton(CalendarSlideConfig, manifest.get("calendar_slide_config"))
    transit_config = manifest.get("transit_dashboard_config")
    if transit_config:
        TransitDashboardConfig.objects.bulk_create([build_instance(TransitDashboardConfig, transit_config)])
        TransitDashboardConfig.objects.get(pk=TransitDashboardConfig.singleton_id).selected_routes.set(
            TransitRoute.objects.filter(code__in=transit_config.get("selected_route_codes", []))
        )
    else:
        transit_config = TransitDashboardConfig.objects.create(pk=TransitDashboardConfig.singleton_id)
        transit_config.selected_routes.set(TransitRoute.objects.filter(is_active=True))
    restore_singleton(EmptyDisplayConfig, manifest.get("empty_display_config"))
    restore_singleton(BreakingNewsTickerConfig, manifest.get("breaking_news_ticker_config"))
    restore_singleton(ScreenPowerSchedule, manifest.get("screen_power_schedule"))
    SlideLibraryConfig.objects.all().delete()
    restore_singleton(SlideLibraryConfig, manifest.get("slide_library_config"))
    ScreenPowerSchedule.objects.update(last_scheduler_check=None, last_attempt_at=None,
        last_applied_slot='', last_error='', last_screen_on_run=None, last_screen_off_run=None)
    restore_singleton(SiteAppearanceSettings, manifest.get("site_appearance"))


def restore_records(model, records):
    if not records:
        return
    instances = [build_instance(model, record) for record in records]
    model.objects.bulk_create(instances)


def restore_singleton(model, record):
    if not record:
        return
    model.objects.bulk_create([build_instance(model, record)])


def build_instance(model, record):
    values = {}
    for field in model._meta.concrete_fields:
        if field.primary_key:
            values[field.attname] = record.get("pk")
            continue
        serialized_fields = record.get("fields", {})
        if field.name in serialized_fields:
            values[field.name] = deserialize_field_value(field, serialized_fields[field.name])
        else:
            values[field.name] = field.get_default()
    return model(**values)


def deserialize_field_value(field, value):
    if value is None:
        return None

    if isinstance(field, models.DateTimeField):
        parsed = parse_datetime(value)
        return parsed if parsed is not None else value

    if isinstance(field, models.TimeField):
        parsed = parse_time(value)
        return parsed if parsed is not None else value

    if isinstance(field, models.DateField):
        parsed = parse_date(value)
        return parsed if parsed is not None else value

    return value


def replace_dateline_file(source_path, destination_path):
    destination_path = Path(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    if source_path and Path(source_path).exists():
        shutil.copy2(source_path, destination_path)
    elif destination_path.exists():
        destination_path.unlink()


def restore_dateline_file(destination_path, backup_path):
    destination_path = Path(destination_path)
    backup_path = Path(backup_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    if backup_path.exists():
        shutil.copy2(backup_path, destination_path)
    elif destination_path.exists():
        destination_path.unlink()
