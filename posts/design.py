"""Bounded, portable Fabric documents and lightweight playback assets."""
import base64
import binascii
import json
import math
import re
from io import BytesIO

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

MAX_DOCUMENT_BYTES = 12 * 1024 * 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_OBJECTS = 80
SYSTEM_FONTS = ('Arial', 'Georgia', 'Verdana', 'Trebuchet MS', 'Courier New', 'Impact')
GOOGLE_SERIF_FONTS = (
    'Alegreya', 'Alegreya SC', 'Bitter', 'Bodoni Moda', 'Cormorant',
    'Cormorant Garamond', 'Cormorant Infant', 'Crimson Pro',
    'EB Garamond', 'Faustina', 'Fraunces', 'Gelasio',
    'Gentium Book Plus', 'IBM Plex Serif', 'Libre Baskerville',
    'Literata', 'Lora', 'Merriweather', 'Newsreader', 'Noto Serif',
    'Noto Serif Display', 'Petrona', 'Playfair Display', 'PT Serif',
    'Roboto Serif', 'Source Serif 4', 'Spectral', 'Tinos',
    'Vollkorn', 'Zilla Slab',
)
GOOGLE_SANS_FONTS = (
    'Archivo', 'Arimo', 'Barlow', 'Barlow Condensed',
    'Barlow Semi Condensed', 'Cabin', 'Chivo', 'DM Sans', 'Epilogue',
    'Exo 2', 'Figtree', 'Fira Sans', 'Hanken Grotesk',
    'IBM Plex Sans', 'Inter', 'Josefin Sans', 'Jost', 'Karla',
    'Lato', 'Libre Franklin', 'Montserrat', 'Montserrat Alternates',
    'Mulish', 'Noto Sans', 'Noto Sans Display', 'Nunito',
    'Open Sans', 'Overpass', 'Poppins', 'PT Sans', 'Public Sans',
    'Quattrocento Sans', 'Raleway', 'Roboto', 'Roboto Condensed',
    'Rubik', 'Source Sans 3', 'Titillium Web', 'Ubuntu',
    'Urbanist', 'Work Sans',
)
GOOGLE_MONO_FONTS = (
    'IBM Plex Mono', 'Roboto Mono', 'Source Code Pro', 'Space Mono',
)
GOOGLE_FONTS = GOOGLE_SERIF_FONTS + GOOGLE_SANS_FONTS + GOOGLE_MONO_FONTS
FONTS = SYSTEM_FONTS + GOOGLE_FONTS
SIZES = ((1920, 1080), (1080, 1920), (1440, 1080), (1080, 1080))


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        raise ValidationError('Choose a valid six-digit color.')
    return value


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValidationError('A layer has invalid dimensions or position.')
    return value


def raster(data, *, expected_size=None):
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in ('PNG', 'JPEG', 'WEBP') or image.width * image.height > 16_000_000:
                raise ValidationError('Use PNG, JPEG, or WebP images up to 16 megapixels.')
            if expected_size and image.size != expected_size:
                raise ValidationError('The rendered slide dimensions do not match its canvas.')
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise ValidationError('The image cannot be decoded.') from error


def validate_document(document):
    if not isinstance(document, dict) or document.get('schema') != 1:
        raise ValidationError('Unsupported slide design format.')
    width, height = document.get('width'), document.get('height')
    if (width, height) not in SIZES:
        raise ValidationError('Choose a supported canvas size.')
    objects = document.get('objects')
    if not isinstance(objects, list) or len(objects) > MAX_OBJECTS:
        raise ValidationError('A design can contain up to 80 layers.')
    result = {'schema': 1, 'width': width, 'height': height,
              'background': color(document.get('background', '#FFFFFF')), 'objects': []}
    for obj in objects:
        if not isinstance(obj, dict) or obj.get('type') not in ('Textbox', 'Rect', 'Circle', 'Image'):
            raise ValidationError('Unsupported layer type.')
        layer = {'type': obj['type'], 'originX': 'left', 'originY': 'top'}
        for key, default, low, high in (
            ('left', 0, -8000, 8000), ('top', 0, -8000, 8000),
            ('width', 100, 1, 8000), ('height', 100, 1, 8000),
            ('scaleX', 1, .01, 20), ('scaleY', 1, .01, 20),
            ('angle', 0, -360, 360), ('opacity', 1, 0, 1),
        ):
            layer[key] = number(obj.get(key, default), low, high)
        for key in ('flipX', 'flipY', 'locked'):
            if key in obj and not isinstance(obj[key], bool):
                raise ValidationError('Invalid layer switch.')
            layer[key] = obj.get(key, False)
        layer['visible'] = obj.get('visible', True) is not False
        layer['stroke'] = color(obj.get('stroke') or '#222222')
        layer['strokeWidth'] = number(obj.get('strokeWidth', 0), 0, 100)
        layer['paintFirst'] = 'stroke'
        shadow = obj.get('shadowSettings')
        if shadow is not None:
            if not isinstance(shadow, dict):
                raise ValidationError('Invalid layer shadow.')
            layer['shadowSettings'] = {
                'color': color(shadow.get('color', '#000000')),
                'opacity': number(shadow.get('opacity', .35), 0, 1),
                'blur': number(shadow.get('blur', 12), 0, 100),
                'offsetX': number(shadow.get('offsetX', 6), -200, 200),
                'offsetY': number(shadow.get('offsetY', 6), -200, 200),
            }
        if obj['type'] in ('Rect', 'Image'):
            layer['cornerRadius'] = number(obj.get('cornerRadius', 0), 0, 1000)
        if obj['type'] != 'Image':
            layer['fill'] = color(obj.get('fill', '#222222'))
        if obj['type'] == 'Textbox':
            text = obj.get('text', '')
            if not isinstance(text, str) or len(text) > 5000:
                raise ValidationError('Text layers are limited to 5,000 characters.')
            layer.update(text=text, fontFamily=obj.get('fontFamily', 'Arial'),
                         fontSize=number(obj.get('fontSize', 64), 8, 400),
                         fontWeight=obj.get('fontWeight', 'normal'),
                         fontStyle=obj.get('fontStyle', 'normal'),
                         underline=obj.get('underline', False),
                         textAlign=obj.get('textAlign', 'left'))
            if not isinstance(layer['underline'], bool):
                raise ValidationError('Invalid underline setting.')
            if layer['fontFamily'] not in FONTS or layer['fontWeight'] not in ('normal', 'bold') or layer['fontStyle'] not in ('normal', 'italic') or layer['textAlign'] not in ('left', 'center', 'right'):
                raise ValidationError('Choose a supported font and text style.')
        elif obj['type'] == 'Circle':
            layer['radius'] = number(obj.get('radius', 50), 1, 4000)
        elif obj['type'] == 'Image':
            src = obj.get('src', '')
            if not isinstance(src, str) or len(src) > MAX_IMAGE_BYTES * 4 // 3 + 100:
                raise ValidationError('An embedded image is too large.')
            match = re.fullmatch(r'data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)', src)
            if not match:
                raise ValidationError('Images must be embedded PNG, JPEG, or WebP files, not URLs.')
            try:
                data = base64.b64decode(match[2], validate=True)
            except (ValueError, binascii.Error) as error:
                raise ValidationError('Invalid embedded image.') from error
            raster(data)
            layer['src'] = src
        result['objects'].append(layer)
    return result


def read_document(upload):
    if upload.size > MAX_DOCUMENT_BYTES:
        raise ValidationError('The design is too large. Use fewer or smaller images (12 MB maximum).')
    try:
        document = json.loads(upload.read(MAX_DOCUMENT_BYTES + 1))
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise ValidationError('The design file is not valid JSON.') from error
    return validate_document(document)


def build_design_assets(source_path, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as image:
        width, height = image.size
        image.thumbnail((250, 2500), Image.Resampling.LANCZOS)
        image.save(output_dir / 'thumbnail_250w.webp', 'WEBP', quality=85)
    return {'kind': 'design', 'thumbnail': 'thumbnail_250w.webp',
            'display': [{'label': 'rendered', 'width': width, 'height': height, 'path': None}]}
