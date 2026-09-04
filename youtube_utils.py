from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

MAX_DOWNLOAD_BYTES = 250 * 1024 * 1024  # 250 MB
ALLOWED_HEIGHTS = {360, 480, 720, 1080, 1440, 2160}


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


def _javascript_runtimes() -> dict:
    """Localiza um runtime JS compatível com o yt-dlp, priorizando Deno."""
    try:
        import deno  # type: ignore

        deno_path = deno.find_deno_bin()
        if deno_path:
            return {"deno": {"path": str(deno_path)}}
    except Exception:
        pass

    # Node 22+ também é suportado pelo yt-dlp atual. O próprio yt-dlp
    # valida a versão; se for antiga, ele simplesmente não a utilizará.
    node = shutil.which("node") or shutil.which("nodejs")
    if node:
        return {"node": {"path": node}}

    # Deno é habilitado por padrão no yt-dlp. Mantemos a entrada para que
    # instalações em que o binário já esteja no PATH ainda possam funcionar.
    return {"deno": {}}


def _ydl_options(folder: Path, max_height: int) -> dict:
    # Não restringimos o codec/extensão na seleção inicial: o YouTube pode
    # disponibilizar combinações diferentes por vídeo. O FFmpeg faz o merge e,
    # quando necessário, o remux para MP4 ao final.
    format_selector = (
        f"bv*[height<={max_height}]+ba/"
        f"b[height<={max_height}]/"
        "bv*+ba/b"
    )

    return {
        "format": format_selector,
        # Equivalente à preferência atual do preset `-t mp4` do yt-dlp.
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
        "js_runtimes": _javascript_runtimes(),
    }


def _friendly_download_error(exc: DownloadError) -> RuntimeError:
    detail = re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", str(exc))
    lowered = detail.lower()

    if "sign in" in lowered or "cookies" in lowered or "bot" in lowered:
        prefix = (
            "O YouTube recusou a requisição anônima. Esse vídeo pode exigir "
            "login/cookies ou uma validação anti-bot do próprio YouTube."
        )
    elif "ffmpeg" in lowered:
        prefix = "O FFmpeg não está disponível ou não conseguiu finalizar o MP4."
    elif "javascript" in lowered or "challenge" in lowered or "ejs" in lowered:
        prefix = (
            "O runtime JavaScript/EJS necessário para o YouTube não conseguiu "
            "resolver o desafio do player."
        )
    else:
        prefix = "Não foi possível baixar este vídeo do YouTube."

    return RuntimeError(f"{prefix} Detalhe técnico: {detail}")


def download_youtube_mp4(
    url: str, max_height: int = 720
) -> tuple[bytes, str, dict]:
    """Baixa um vídeo público/autorizado do YouTube e retorna um MP4 em memória."""
    if not is_youtube_url(url):
        raise ValueError("Informe um link válido do YouTube.")

    max_height = int(max_height)
    if max_height not in ALLOWED_HEIGHTS:
        max_height = 720

    with tempfile.TemporaryDirectory(prefix="streamlit_yt_") as temp_dir:
        folder = Path(temp_dir)

        try:
            with YoutubeDL(_ydl_options(folder, max_height)) as ydl:
                info = ydl.extract_info(url.strip(), download=True)
        except DownloadError as exc:
            raise _friendly_download_error(exc) from exc

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
