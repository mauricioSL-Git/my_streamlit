from __future__ import annotations

from io import BytesIO
from urllib.parse import urlparse

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def is_valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def make_qr_png(url: str, box_size: int = 10, border: int = 4) -> bytes:
    if not is_valid_http_url(url):
        raise ValueError("Informe uma URL válida iniciada por http:// ou https://")

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(url.strip())
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
