from __future__ import annotations

import base64
import binascii


def encode_text_base64(text: str) -> str:
    """Codifica texto UTF-8 em Base64 padrão."""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def decode_base64_text(value: str) -> tuple[bytes, str | None]:
    """
    Decodifica Base64 padrão.

    Espaços e quebras de linha são ignorados. Padding ausente é completado
    automaticamente quando possível. Retorna os bytes e, se forem UTF-8,
    também o texto decodificado.
    """
    compact = "".join(value.split())
    if not compact:
        raise ValueError("Informe um conteúdo Base64 para decodificar.")

    # Base64 válido tem comprimento múltiplo de 4. Completar '=' torna a
    # ferramenta amigável a valores copiados sem o padding final.
    compact += "=" * (-len(compact) % 4)

    try:
        decoded = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("O conteúdo informado não é um Base64 válido.") from exc

    try:
        decoded_text = decoded.decode("utf-8")
    except UnicodeDecodeError:
        decoded_text = None

    return decoded, decoded_text
