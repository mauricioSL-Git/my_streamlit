from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import deno
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

MAX_DOWNLOAD_BYTES = 250 * 1024 * 1024  # 250 MB


def is_youtube_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False

    host = (parsed.hostname or "").lower()
    return host in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "music.youtube.com",
    }


def _safe_filename(value: str) -> str:
    value = re.sub(r"[^\w\-. ]+", "_", value, flags=re.UNICODE).strip(" ._")
    return value[:120] or "video"


def _find_output_file(folder: Path) -> Path:
    candidates = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == ".mp4" and not p.name.endswith(".part")
    ]
    if not candidates:
        raise RuntimeError("O download terminou, mas o arquivo MP4 não foi localizado.")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def download_youtube_mp4(url: str, max_height: int = 720) -> tuple[bytes, str, dict]:
    if not is_youtube_url(url):
        raise ValueError("Informe um link válido do YouTube.")

    max_height = int(max_height)
    if max_height not in {360, 480, 720, 1080}:
        max_height = 720

    with tempfile.TemporaryDirectory(prefix="streamlit_yt_") as temp_dir:
        folder = Path(temp_dir)
        output_template = str(folder / "%(title).100s [%(id)s].%(ext)s")

        # Preferimos MP4 + M4A para produzir um MP4 sem recodificar quando possível.
        format_selector = (
            f"bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"best[height<={max_height}][ext=mp4]/best[ext=mp4]/best"
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
            # Usa certificados do sistema quando possível e desabilita a checagem
            # para ambientes com certificado autoassinado/proxy HTTPS.
            "compat_opts": {"no-certifi"},
            "nocheckcertificate": True,
            # O pacote yt-dlp[default] inclui o componente EJS.
        }

        # O projeto instala Deno pelo PyPI e passa o caminho explicitamente
        # para maximizar a compatibilidade atual do yt-dlp com YouTube.
        try:
            deno_path = deno.find_deno_bin()
        except Exception:
            deno_path = None

        if deno_path:
            ydl_opts["js_runtimes"] = {"deno": {"path": str(deno_path)}}
        else:
            # Fallback local: use Node apenas se estiver disponível. O yt-dlp
            # decidirá se a versão instalada é suportada.
            node = shutil.which("node") or shutil.which("nodejs")
            if node:
                ydl_opts["js_runtimes"] = {"node": {"path": node}}

        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url.strip(), download=True)
        except DownloadError as exc:
            raise RuntimeError(
                "Não foi possível baixar este vídeo. O YouTube pode exigir "
                "validação adicional, cookies ou um runtime JavaScript compatível. "
                f"Detalhe técnico: {exc}"
            ) from exc

        output_path = _find_output_file(folder)
        size = output_path.stat().st_size
        if size > MAX_DOWNLOAD_BYTES:
            raise RuntimeError("O arquivo ultrapassa o limite de 250 MB deste app.")

        title = _safe_filename(str(info.get("title") or output_path.stem))
        filename = f"{title}.mp4"
        metadata = {
            "title": info.get("title"),
            "uploader": info.get("uploader"),
            "duration": info.get("duration"),
            "webpage_url": info.get("webpage_url") or url,
            "filesize": size,
        }
        return output_path.read_bytes(), filename, metadata
