from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import qrcode
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_M

MAX_LOGO_BYTES = 5 * 1024 * 1024
MAX_LOGO_PIXELS = 20_000_000
ALLOWED_LOGO_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg"}


def is_valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def _make_qr(url: str, *, error_correction: int, box_size: int, border: int):
    if not is_valid_http_url(url):
        raise ValueError("Informe uma URL válida iniciada por http:// ou https://")

    qr = qrcode.QRCode(
        version=None,
        error_correction=error_correction,
        box_size=box_size,
        border=border,
    )
    qr.add_data(url.strip())
    qr.make(fit=True)
    return qr


def make_qr_png(url: str, box_size: int = 10, border: int = 4) -> bytes:
    """Gera um QR Code tradicional em PNG."""
    qr = _make_qr(
        url,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )

    image = qr.make_image(
        fill_color="black",
        back_color="white",
    ).convert("RGB")

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _load_logo(logo_bytes: bytes, logo_filename: str) -> Image.Image:
    if not logo_bytes:
        raise ValueError("Envie uma imagem para usar como logotipo.")

    if len(logo_bytes) > MAX_LOGO_BYTES:
        raise ValueError("O logotipo deve ter no máximo 5 MB.")

    suffix = Path(logo_filename or "").suffix.lower()

    if suffix not in ALLOWED_LOGO_SUFFIXES:
        raise ValueError("O logotipo deve ser PNG, JPG, JPEG ou SVG.")

    try:
        if suffix == ".svg":
            try:
                import cairosvg
            except ImportError as exc:
                raise RuntimeError(
                    "O suporte a SVG requer a dependência CairoSVG."
                ) from exc

            raster_bytes = cairosvg.svg2png(
                bytestring=logo_bytes,
                output_width=1200,
            )
            image = Image.open(BytesIO(raster_bytes))
        else:
            image = Image.open(BytesIO(logo_bytes))

        image.load()

    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("Não foi possível ler a imagem enviada.") from exc

    if image.width <= 0 or image.height <= 0:
        raise ValueError("A imagem enviada possui dimensões inválidas.")

    if image.width * image.height > MAX_LOGO_PIXELS:
        raise ValueError("A imagem enviada é grande demais. Use uma imagem menor.")

    return ImageOps.exif_transpose(image).convert("RGBA")


def make_qr_with_logo_png(
    url: str,
    logo_bytes: bytes,
    logo_filename: str,
    box_size: int = 12,
    border: int = 4,
) -> bytes:
    """Gera um QR Code e posiciona a imagem enviada no centro, sem remover o fundo."""
    qr = _make_qr(
        url,
        error_correction=ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )

    qr_image = qr.make_image(
        fill_color="black",
        back_color="white",
    ).convert("RGBA")

    logo = _load_logo(logo_bytes, logo_filename)

    # Mantém o logotipo em tamanho seguro para preservar a leitura do QR Code.
    max_logo_side = max(28, int(qr_image.width * 0.18))
    logo.thumbnail(
        (max_logo_side, max_logo_side),
        Image.Resampling.LANCZOS,
    )

    # Área branca de proteção atrás da imagem. O fundo original do arquivo
    # permanece intacto; esta base apenas evita que os módulos do QR Code
    # interfiram visualmente na região ocupada pelo logotipo.
    padding = max(6, int(qr_image.width * 0.012))
    radius = max(6, int(qr_image.width * 0.02))
    panel_size = (
        logo.width + padding * 2,
        logo.height + padding * 2,
    )

    panel = Image.new("RGBA", panel_size, (255, 255, 255, 0))
    mask = Image.new("L", panel_size, 0)

    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle(
        (0, 0, panel_size[0] - 1, panel_size[1] - 1),
        radius=radius,
        fill=255,
    )

    white = Image.new("RGBA", panel_size, (255, 255, 255, 255))
    panel.paste(white, (0, 0), mask)

    # Usa o canal alfa da própria imagem. PNG/SVG transparente continua
    # transparente; JPG/JPEG mantém exatamente o seu fundo original.
    panel.alpha_composite(logo, (padding, padding))

    left = (qr_image.width - panel.width) // 2
    top = (qr_image.height - panel.height) // 2
    qr_image.alpha_composite(panel, (left, top))

    buffer = BytesIO()
    qr_image.convert("RGB").save(
        buffer,
        format="PNG",
        optimize=True,
    )
    return buffer.getvalue()
