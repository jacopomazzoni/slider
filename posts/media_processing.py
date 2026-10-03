from functools import lru_cache
from pathlib import Path
import logging
import subprocess

from PIL import Image, ImageDraw, ImageFont, ImageOps


THUMBNAIL_WIDTH = 250
EDITOR_PREVIEW_WIDTH = 600
RENDITION_LAYOUT_VERSION = "aspect_fit_v4"
MAX_NATIVE_WEBP_PIXELS = 50_000_000
IMAGE_RENDITION_TARGETS = [
    ("720p", 1280, 720),
    ("1080p", 1920, 1080),
    ("2k_dci", 2048, 1080),
    ("1440p", 2560, 1440),
    ("1600p", 2560, 1600),
    ("uwqhd", 3440, 1440),
    ("4k_uhd", 3840, 2160),
    ("4k_dci", 4096, 2160),
    ("5k", 5120, 2880),
    ("6k", 6016, 3384),
    ("8k_uhd", 7680, 4320),
    ("8k_dci", 8192, 4320),
]
logger = logging.getLogger("upload_errors")
DEFAULT_IMAGE_EDIT_CONFIG = {
    "rotation_degrees": 0,
    "crop_left_percent": 0.0,
    "crop_top_percent": 0.0,
    "crop_width_percent": 100.0,
    "crop_height_percent": 100.0,
    "overlay_text": "",
    "overlay_position": "bottom_center",
    "overlay_text_color": "#FFFFFF",
    "overlay_size_percent": 6,
    "overlay_font_family": "sans_bold",
}
OVERLAY_POSITIONS = {
    "top_left",
    "top_center",
    "top_right",
    "center_left",
    "center",
    "center_right",
    "bottom_left",
    "bottom_center",
    "bottom_right",
}
OVERLAY_FONT_FAMILIES = {
    "sans_bold": {
        "label": "Sans Bold",
        "paths": (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Verdana Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
        ),
        "fontconfig": "DejaVu Sans:style=Bold",
        "css_family": '"DejaVu Sans", Verdana, Arial, sans-serif',
        "css_weight": "700",
    },
    "sans": {
        "label": "Sans",
        "paths": (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Verdana.ttf",
            "/Library/Fonts/Arial.ttf",
        ),
        "fontconfig": "DejaVu Sans",
        "css_family": '"DejaVu Sans", Verdana, Arial, sans-serif',
        "css_weight": "500",
    },
    "serif": {
        "label": "Serif",
        "paths": (
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSerif.ttf",
            "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
            "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
            "/Library/Fonts/Times New Roman.ttf",
        ),
        "fontconfig": "DejaVu Serif:style=Bold",
        "css_family": '"DejaVu Serif", Georgia, "Times New Roman", serif',
        "css_weight": "700",
    },
    "mono": {
        "label": "Monospace",
        "paths": (
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
            "/System/Library/Fonts/Supplemental/Menlo Bold.ttf",
            "/System/Library/Fonts/Supplemental/Menlo.ttc",
            "/Library/Fonts/Courier New Bold.ttf",
            "/Library/Fonts/Courier New.ttf",
        ),
        "fontconfig": "DejaVu Sans Mono:style=Bold",
        "css_family": '"DejaVu Sans Mono", Menlo, Consolas, "Courier New", monospace',
        "css_weight": "700",
    },
}
OVERLAY_FONT_CHOICES = [(key, value["label"]) for key, value in OVERLAY_FONT_FAMILIES.items()]


def _has_alpha(image):
    if image.mode in {"RGBA", "LA"}:
        return True
    return image.mode == "P" and "transparency" in image.info


def normalize_image_edit_config(edit_config):
    if not isinstance(edit_config, dict):
        edit_config = {}

    normalized = dict(DEFAULT_IMAGE_EDIT_CONFIG)

    try:
        rotation = float(edit_config.get("rotation_degrees", normalized["rotation_degrees"]))
    except (TypeError, ValueError):
        rotation = normalized["rotation_degrees"]
    normalized["rotation_degrees"] = round(min(max(rotation, -180.0), 180.0), 2)

    for key in ("crop_left_percent", "crop_top_percent", "crop_width_percent", "crop_height_percent"):
        try:
            normalized[key] = float(edit_config.get(key, normalized[key]))
        except (TypeError, ValueError):
            normalized[key] = DEFAULT_IMAGE_EDIT_CONFIG[key]

    normalized["crop_left_percent"] = min(max(normalized["crop_left_percent"], 0.0), 95.0)
    normalized["crop_top_percent"] = min(max(normalized["crop_top_percent"], 0.0), 95.0)
    normalized["crop_width_percent"] = min(max(normalized["crop_width_percent"], 5.0), 100.0)
    normalized["crop_height_percent"] = min(max(normalized["crop_height_percent"], 5.0), 100.0)

    if normalized["crop_left_percent"] + normalized["crop_width_percent"] > 100.0:
        normalized["crop_width_percent"] = max(5.0, 100.0 - normalized["crop_left_percent"])
    if normalized["crop_top_percent"] + normalized["crop_height_percent"] > 100.0:
        normalized["crop_height_percent"] = max(5.0, 100.0 - normalized["crop_top_percent"])

    overlay_text = str(edit_config.get("overlay_text", normalized["overlay_text"]) or "").strip()
    normalized["overlay_text"] = overlay_text[:200]

    overlay_position = str(edit_config.get("overlay_position", normalized["overlay_position"]) or "").strip()
    normalized["overlay_position"] = overlay_position if overlay_position in OVERLAY_POSITIONS else "bottom_center"

    overlay_color = str(edit_config.get("overlay_text_color", normalized["overlay_text_color"]) or "").strip()
    if len(overlay_color) == 7 and overlay_color.startswith("#"):
        normalized["overlay_text_color"] = overlay_color.upper()

    overlay_font_family = str(edit_config.get("overlay_font_family", normalized["overlay_font_family"]) or "").strip()
    if overlay_font_family in OVERLAY_FONT_FAMILIES:
        normalized["overlay_font_family"] = overlay_font_family

    try:
        overlay_size = int(edit_config.get("overlay_size_percent", normalized["overlay_size_percent"]))
    except (TypeError, ValueError):
        overlay_size = normalized["overlay_size_percent"]
    normalized["overlay_size_percent"] = min(max(overlay_size, 2), 20)

    return normalized


def image_edit_config_is_default(edit_config):
    normalized = normalize_image_edit_config(edit_config)
    return normalized == DEFAULT_IMAGE_EDIT_CONFIG


def _open_first_frame(source_path):
    with Image.open(source_path) as opened:
        opened = ImageOps.exif_transpose(opened)
        animated = bool(getattr(opened, "is_animated", False))
        first_frame = opened.convert("RGBA" if _has_alpha(opened) else "RGB").copy()
        return first_frame, animated


def _save_image(image, destination):
    save_kwargs = {"format": "WEBP", "quality": 86, "method": 6}
    if image.mode == "RGBA":
        save_kwargs["lossless"] = True
    image.save(destination, **save_kwargs)


@lru_cache(maxsize=None)
def _resolve_overlay_font_path(font_family):
    family_config = OVERLAY_FONT_FAMILIES.get(font_family, OVERLAY_FONT_FAMILIES[DEFAULT_IMAGE_EDIT_CONFIG["overlay_font_family"]])

    for font_path in family_config["paths"]:
        if Path(font_path).is_file():
            return font_path

    try:
        result = subprocess.run(
            ["fc-match", "-f", "%{file}\n", family_config["fontconfig"]],
            check=True,
            capture_output=True,
            text=True,
        )
        matched_path = result.stdout.strip()
        if matched_path and Path(matched_path).is_file():
            return matched_path
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    return None


def _load_overlay_font(font_size, font_family):
    font_path = _resolve_overlay_font_path(font_family)
    if font_path:
        try:
            return ImageFont.truetype(font_path, font_size)
        except OSError:
            logger.warning("Could not load overlay font at path=%s", font_path)

    try:
        return ImageFont.load_default(size=font_size)
    except TypeError:
        return ImageFont.load_default()


def _apply_overlay_text(image, edit_config):
    overlay_text = edit_config.get("overlay_text") or ""
    if not overlay_text:
        return image

    composed = image.convert("RGBA")
    overlay = Image.new("RGBA", composed.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(18, int(min(composed.size) * (edit_config["overlay_size_percent"] / 100.0)))
    font = _load_overlay_font(font_size, edit_config["overlay_font_family"])
    spacing = max(4, font_size // 5)
    text_color = edit_config["overlay_text_color"]
    padding = max(12, font_size // 3)
    box_padding = max(12, font_size // 2)

    bbox = draw.multiline_textbbox((0, 0), overlay_text, font=font, spacing=spacing, align="left")
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    vertical_position, _, horizontal_position = edit_config["overlay_position"].partition("_")
    if horizontal_position == "":
        horizontal_position = "center"

    if horizontal_position == "left":
        text_x = padding
        align = "left"
    elif horizontal_position == "right":
        text_x = composed.width - text_width - padding
        align = "right"
    else:
        text_x = (composed.width - text_width) / 2
        align = "center"

    if vertical_position == "top":
        text_y = padding
    elif vertical_position == "center":
        text_y = (composed.height - text_height) / 2
    else:
        text_y = composed.height - text_height - padding

    draw_x = text_x - bbox[0]
    draw_y = text_y - bbox[1]
    rectangle = (
        int(text_x - box_padding),
        int(text_y - box_padding // 2),
        int(text_x + text_width + box_padding),
        int(text_y + text_height + box_padding),
    )
    draw.rounded_rectangle(rectangle, radius=max(8, font_size // 4), fill=(0, 0, 0, 144))
    draw.multiline_text(
        (draw_x, draw_y),
        overlay_text,
        font=font,
        fill=text_color,
        spacing=spacing,
        align=align,
    )
    result = Image.alpha_composite(composed, overlay)
    return result if image.mode == "RGBA" else result.convert("RGB")


def apply_image_edits(source_image, edit_config):
    normalized = normalize_image_edit_config(edit_config)
    image = source_image.copy()

    if normalized["rotation_degrees"]:
        image = image.rotate(-normalized["rotation_degrees"], expand=True, resample=Image.Resampling.BICUBIC)

    width, height = image.size
    left = int(round(width * (normalized["crop_left_percent"] / 100.0)))
    top = int(round(height * (normalized["crop_top_percent"] / 100.0)))
    crop_width = int(round(width * (normalized["crop_width_percent"] / 100.0)))
    crop_height = int(round(height * (normalized["crop_height_percent"] / 100.0)))
    right = min(width, max(left + 1, left + crop_width))
    bottom = min(height, max(top + 1, top + crop_height))
    left = min(left, right - 1)
    top = min(top, bottom - 1)

    if (left, top, right, bottom) != (0, 0, width, height):
        image = image.crop((left, top, right, bottom))

    return _apply_overlay_text(image, normalized)


def _build_thumbnail(source_image, destination):
    thumbnail = source_image.copy()
    thumbnail.thumbnail((THUMBNAIL_WIDTH, THUMBNAIL_WIDTH * 8), Image.Resampling.LANCZOS)
    _save_image(thumbnail, destination)


def _build_width_variant(source_image, target_width, destination):
    preview = source_image.copy()
    preview.thumbnail((target_width, target_width * 8), Image.Resampling.LANCZOS)
    _save_image(preview, destination)
    return preview.size


def _build_fit_variant(source_image, target_width, target_height, destination):
    contained = ImageOps.contain(source_image, (target_width, target_height), Image.Resampling.LANCZOS)
    _save_image(contained, destination)
    return contained.size


def _run_media_command(command):
    try:
        subprocess.run(command, check=True, capture_output=True)
        return True
    except FileNotFoundError:
        logger.warning("Media tool missing for command=%s", command[0])
    except subprocess.CalledProcessError as error:
        stderr = error.stderr.decode("utf-8", errors="ignore").strip()
        logger.warning("Media command failed command=%s stderr=%s", " ".join(command), stderr)
    return False


def build_image_assets(source_path, output_dir, edit_config=None):
    output_dir.mkdir(parents=True, exist_ok=True)
    source_image, animated = _open_first_frame(source_path)
    unedited_source_image = source_image.copy()
    if not animated:
        source_image = apply_image_edits(source_image, edit_config)

    original_width, original_height = source_image.size

    thumbnail_path = output_dir / "thumbnail_250w.webp"
    _build_thumbnail(source_image, thumbnail_path)
    editor_preview_path = output_dir / "editor_preview_600w.webp"
    editor_preview_width, editor_preview_height = _build_width_variant(
        unedited_source_image,
        EDITOR_PREVIEW_WIDTH,
        editor_preview_path,
    )

    display_variants = []

    if not animated:
        native_path = None
        if original_width * original_height <= MAX_NATIVE_WEBP_PIXELS:
            native_destination = output_dir / "screen_native.webp"
            _save_image(source_image, native_destination)
            native_path = native_destination.name
        display_variants.append(
            {
                "label": "original",
                "path": native_path,
                "width": original_width,
                "height": original_height,
            }
        )
        for label, target_width, target_height in IMAGE_RENDITION_TARGETS:
            scale = min(target_width / original_width, target_height / original_height)
            if scale > 1:
                continue
            destination = output_dir / f"screen_{target_width}x{target_height}.webp"
            variant_width, variant_height = _build_fit_variant(source_image, target_width, target_height, destination)
            display_variants.append(
                {
                    "label": label,
                    "path": destination.name,
                    "width": variant_width,
                    "height": variant_height,
                }
            )
    else:
        display_variants.append(
            {
                "label": "original",
                "path": None,
                "width": original_width,
                "height": original_height,
            }
        )

    return {
        "thumbnail": thumbnail_path.name,
        "layout_version": RENDITION_LAYOUT_VERSION,
        "editor_preview": {
            "path": editor_preview_path.name,
            "width": editor_preview_width,
            "height": editor_preview_height,
        },
        "display": display_variants,
        "animated": animated,
        "kind": "image",
    }


def _build_video_thumbnail(source_path, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    thumbnail_path = output_dir / "thumbnail_250w.jpg"
    base_command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        "00:00:00.500",
        "-i",
        str(source_path),
        "-frames:v",
        "1",
        "-vf",
        f"scale={THUMBNAIL_WIDTH}:-1:flags=lanczos",
        str(thumbnail_path),
    ]
    fallback_command = base_command.copy()
    fallback_command[5] = "00:00:00.000"

    if not _run_media_command(base_command):
        _run_media_command(fallback_command)

    return thumbnail_path.name if thumbnail_path.exists() else ""


def build_video_thumbnail(source_path, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    thumbnail_name = _build_video_thumbnail(source_path, output_dir)

    return {
        "thumbnail": thumbnail_name,
        "display": [],
        "animated": False,
        "kind": "video",
    }
