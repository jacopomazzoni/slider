"""Sanitized rich text with portable QR descriptors, not user-supplied images."""
import base64
import json

import bleach
from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError

from .qr_codes import qr_variants

ALLOWED_TAGS = ['p', 'br', 'strong', 'b', 'em', 'i', 'u', 'ul', 'ol', 'li', 'span']
QR_SIZES = (128, 192, 256)


def validate_qr(text, size):
    if not isinstance(text, str) or not text.strip() or len(text) > 512:
        raise ValidationError('Enter between 1 and 512 characters for the QR code.')
    try:
        size = int(size)
    except (ValueError, TypeError):
        raise ValidationError('Choose a valid QR code size.')
    if size not in QR_SIZES:
        raise ValidationError('Choose a valid QR code size.')
    return text.strip(), size


def clean_rich_text(html):
    html = bleach.clean(html or '', tags=ALLOWED_TAGS,
                        attributes={'span': ['data-qr-text', 'data-qr-size']}, strip=True)
    soup = BeautifulSoup(html, 'html.parser')
    codes = soup.select('span[data-qr-text]')
    if len(codes) > 8:
        raise ValidationError('Add up to 8 QR codes per slide.')
    for code in codes:
        text, size = validate_qr(code['data-qr-text'], code.get('data-qr-size', 192))
        code.attrs = {'data-qr-text': text, 'data-qr-size': str(size)}
        code.clear()
        code.append('QR code')
    if not soup.get_text(strip=True):
        raise ValidationError('Please add a description or QR code.')
    return str(soup)


def render_rich_text(html):
    try:
        cleaned = clean_rich_text(html)
    except ValidationError:
        return bleach.clean(html or '', tags=ALLOWED_TAGS, attributes={}, strip=True)
    soup = BeautifulSoup(cleaned, 'html.parser')
    for code in soup.select('span[data-qr-text]'):
        _, modules, variants = qr_variants(code['data-qr-text'])
        size = int(code['data-qr-size'])
        sources = [{'width': width, 'url': 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')}
                   for width, png in variants.items()]
        code['class'] = 'rich-qr'
        code['contenteditable'] = 'false'
        code['style'] = (f'display:inline-flex;align-items:center;justify-content:center;'
                         f'width:{size}px;height:{size}px;max-width:100%;background:#fff;vertical-align:middle;')
        code.clear()
        image = soup.new_tag('img', attrs={
            'src': next(source['url'] for source in sources if source['width'] >= size),
            'alt': 'QR code', 'width': size, 'height': size,
            'data-qr-modules': modules, 'data-qr-sources': json.dumps(sources),
            'style': 'display:block;max-width:100%;max-height:100%;image-rendering:pixelated;',
        })
        code.append(image)
    return str(soup)


def qr_markup(text, size):
    text, size = validate_qr(text, size)
    soup = BeautifulSoup('', 'html.parser')
    soup.append(soup.new_tag('span', attrs={'data-qr-text': text, 'data-qr-size': str(size)}))
    return render_rich_text(str(soup))
