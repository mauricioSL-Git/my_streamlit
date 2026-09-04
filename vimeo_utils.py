from __future__ import annotations

import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

MAX_DOWNLOAD_BYTES = 250 * 1024 * 1024  # 250 MB


def is_vimeo_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False

    host = (parsed.hostname or "").lower()
    return host == "vimeo.com" or host.endswith(".vimeo.com")


def _safe_filename(value: str) -> str:
    value = re.sub(r"[^\w\-. ]+", "_", value, flags=re.UNICODE).strip(" ._")
    return value[:120] or "video_vimeo"


def _clean_error_message(message: str) -> str:
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", message)


def _find_output_file(folder: Path) -> Path:
    candidates = [
        p
        for p in folder.iterdir()
        if p.is_file()
        and p.suffix.lower() == ".mp4"
        and not p.name.endswith(".part")
    ]

    if not candidates:
        raise RuntimeError(
            "O download terminou, mas o arquivo MP4 não foi localizado."
        )

    return max(candidates, key=lambda p: p.stat().st_mtime)


def download_vimeo_mp4(url: str) -> tuple[bytes, str, dict]:
    """Baixa um vídeo do Vimeo e devolve bytes, nome do arquivo e metadados."""

    if not is_vimeo_url(url):
        raise ValueError("Informe um link válido do Vimeo.")

    with tempfile.TemporaryDirectory(prefix="streamlit_vimeo_") as temp_dir:
        folder = Path(temp_dir)
        output_template = str(folder / "%(title).100s [%(id)s].%(ext)s")

        # Prioriza MP4. Quando vídeo e áudio vierem separados, o FFmpeg faz a união.
        format_selector = (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo[ext=mp4]+bestaudio/"
            "best[ext=mp4]"
        )

        ydl_opts = {
            "format": format_selector,
            "outtmpl": output_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
            "max_filesize": MAX_DOWNLOAD_BYTES,
            "overwrites": True,
            "continuedl": True,
            "restrictfilenames": False,
            # Mantém o mesmo tratamento de certificado usado no módulo do YouTube.
            # Útil em redes/antivírus que injetam certificados próprios.
            "compat_opts": {"no-certifi"},
            "nocheckcertificate": True,
        }

        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url.strip(), download=True)
        except DownloadError as exc:
            detail = _clean_error_message(str(exc))
            raise RuntimeError(
                "Não foi possível baixar este vídeo do Vimeo. "
                "O vídeo pode ser privado, protegido por senha ou exigir autenticação. "
                f"Detalhe técnico: {detail}"
            ) from exc

        output_path = _find_output_file(folder)
        size = output_path.stat().st_size

        if size > MAX_DOWNLOAD_BYTES:
            raise RuntimeError("O arquivo ultrapassa o limite de 250 MB deste app.")

        title = _safe_filename(str(info.get("title") or output_path.stem))
        filename = f"{title}.mp4"

        metadata = {
            "title": info.get("title"),
            "uploader": info.get("uploader") or info.get("channel"),
            "duration": info.get("duration"),
            "webpage_url": info.get("webpage_url") or url,
            "filesize": size,
        }

        return output_path.read_bytes(), filename, metadata
