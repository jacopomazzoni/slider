"""Reusable, locally generated QR rasters with integer-sized modules."""

from functools import lru_cache
from hashlib import sha256
from io import BytesIO
from math import ceil

import qrcode


# Compact and desktop QR slots from 720p through 8K / high-DPI screens.
QR_TARGET_PIXELS = (48, 84, 128, 168, 252, 336, 504, 672)


@lru_cache(maxsize=32)
def qr_variants(text):
    """Return (revision, module count, {pixel width: PNG bytes}) for a string.

    Includes a four-module quiet zone; sizes round UP to whole modules without
    interpolation. A bounded memory cache avoids filesystem writes on the Pi.
    """
    qr = qrcode.QRCode(border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    modules = qr.modules_count + 2 * qr.border
    variants = {}
    for target in QR_TARGET_PIXELS:
        qr.box_size = ceil(target / modules)
        width = modules * qr.box_size
        if width in variants:
            continue
        output = BytesIO()
        qr.make_image(fill_color='black', back_color='white').save(output, format='PNG')
        variants[width] = output.getvalue()
    return sha256(text.encode('utf-8')).hexdigest(), modules, variants
