from __future__ import annotations

import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

MAX_DOWNLOAD_BYTES = 250 * 1024 * 1024  # 250 MB
ALLOWED_HEIGHTS = {360, 480, 720, 1080, 1440, 2160}


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
        and not p.name.endswith((".part", ".ytdl"))
    ]
    if not candidates:
        raise RuntimeError(
            "O download terminou, mas o arquivo MP4 final não foi localizado. "
            "Verifique se o FFmpeg está instalado no ambiente."
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _ydl_options(folder: Path, max_height: int) -> dict:
    format_selector = (
        f"bv*[height<={max_height}]+ba/"
        f"b[height<={max_height}]/"
        "bv*+ba/b"
    )

    return {
        "format": format_selector,
        "format_sort": [
            "vcodec:h264",
            "lang",
            "quality",
            "res",
            "fps",
            "hdr:12",
            "acodec:aac",
        ],
        "outtmpl": str(folder / "%(title).100s [%(id)s].%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "final_ext": "mp4",
        "postprocessors": [
            {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"},
        ],
        "max_filesize": MAX_DOWNLOAD_BYTES,
        "overwrites": True,
        "continuedl": True,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 5,
        "file_access_retries": 3,
        "concurrent_fragment_downloads": 4,
        "socket_timeout": 30,
    }


def download_vimeo_mp4(
    url: str, max_height: int = 1080
) -> tuple[bytes, str, dict]:
    """Baixa um vídeo público/autorizado do Vimeo e retorna MP4 em memória."""
    if not is_vimeo_url(url):
        raise ValueError("Informe um link válido do Vimeo.")

    max_height = int(max_height)
    if max_height not in ALLOWED_HEIGHTS:
        max_height = 1080

    with tempfile.TemporaryDirectory(prefix="streamlit_vimeo_") as temp_dir:
        folder = Path(temp_dir)

        try:
            with YoutubeDL(_ydl_options(folder, max_height)) as ydl:
                info = ydl.extract_info(url.strip(), download=True)
        except DownloadError as exc:
            detail = _clean_error_message(str(exc))
            lowered = detail.lower()
            if "embed-only" in lowered or "referer" in lowered:
                prefix = (
                    "Este vídeo do Vimeo só pode ser reproduzido em uma página "
                    "específica e exige o endereço da página de incorporação."
                )
            elif "log" in lowered or "private" in lowered or "password" in lowered:
                prefix = (
                    "Este vídeo do Vimeo exige autenticação, é privado ou está "
                    "protegido por senha."
                )
            else:
                prefix = "Não foi possível baixar este vídeo do Vimeo."
            raise RuntimeError(f"{prefix} Detalhe técnico: {detail}") from exc

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
            "height": info.get("height"),
        }
        return output_path.read_bytes(), filename, metadata
