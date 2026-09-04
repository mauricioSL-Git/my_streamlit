from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import imageio_ffmpeg
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

# Limites do aplicativo
MAX_VIDEO_BYTES = 750 * 1024 * 1024  # 750 MB para MP4
MAX_AUDIO_BYTES = 250 * 1024 * 1024  # 250 MB para MP3
ALLOWED_HEIGHTS = {360, 480, 720, 1080, 1440, 2160}

ProgressCallback = Callable[[dict], None]


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
    return value[:120] or "youtube"


def _find_output_file(folder: Path, extension: str) -> Path:
    extension = extension.lower()
    candidates = [
        path
        for path in folder.iterdir()
        if path.is_file()
        and path.suffix.lower() == extension
        and not path.name.endswith((".part", ".ytdl"))
    ]

    if not candidates:
        raise RuntimeError(
            f"O processamento terminou, mas o arquivo {extension} final não foi "
            "localizado. Verifique se o FFmpeg está disponível no ambiente."
        )

    return max(candidates, key=lambda path: path.stat().st_mtime)


def _javascript_runtimes() -> dict:
    """Localiza um runtime JavaScript compatível com o yt-dlp, priorizando Deno."""
    try:
        import deno  # type: ignore

        deno_path = deno.find_deno_bin()
        if deno_path:
            return {"deno": {"path": str(deno_path)}}
    except Exception:
        pass

    node = shutil.which("node") or shutil.which("nodejs")
    if node:
        return {"node": {"path": node}}

    return {"deno": {}}


def _get_ffmpeg_path() -> str:
    """
    Usa o FFmpeg do sistema quando existir (por exemplo no Streamlit Cloud)
    e, no Windows/local, usa o binário fornecido pelo imageio-ffmpeg.
    """
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    try:
        bundled_ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled_ffmpeg and Path(bundled_ffmpeg).exists():
            return str(bundled_ffmpeg)
    except Exception as exc:
        raise RuntimeError(
            f"Não foi possível localizar o FFmpeg pelo imageio-ffmpeg: {exc}"
        ) from exc

    raise RuntimeError(
        "FFmpeg não foi encontrado. Instale a dependência imageio-ffmpeg "
        "ou disponibilize o executável ffmpeg no sistema."
    )


def _common_options(
    folder: Path,
    max_filesize: int,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    ffmpeg_path = _get_ffmpeg_path()

    options = {
        "outtmpl": str(folder / "%(title).100s [%(id)s].%(ext)s"),
        "ffmpeg_location": ffmpeg_path,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        # Usa o repositório de certificados confiáveis do sistema. Isso evita
        # falhas em ambientes que possuem certificado corporativo/local.
        "compat_opts": {"no-certifi"},
        "max_filesize": max_filesize,
        "overwrites": True,
        "continuedl": True,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 5,
        "file_access_retries": 3,
        "concurrent_fragment_downloads": 4,
        "socket_timeout": 30,
        "js_runtimes": _javascript_runtimes(),
        "extractor_args": {
            "youtube": {
                "player_client": [
                    "default",
                    "web_embedded",
                ],
            }
        },
    }

    if progress_callback is not None:
        options["progress_hooks"] = [progress_callback]

        def postprocessor_hook(data: dict) -> None:
            progress_callback(
                {
                    "status": "postprocessing",
                    "postprocessor_status": data.get("status"),
                    "postprocessor": data.get("postprocessor"),
                }
            )

        options["postprocessor_hooks"] = [postprocessor_hook]

    return options


def _friendly_download_error(exc: DownloadError) -> RuntimeError:
    detail = re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", str(exc))
    lowered = detail.lower()

    if (
        "certificate_verify_failed" in lowered
        or "certificate verify failed" in lowered
        or "self-signed certificate" in lowered
        or "self signed certificate" in lowered
    ):
        prefix = (
            "Falha na validação do certificado HTTPS. O ambiente apresentou "
            "um certificado local/intermediário que não foi reconhecido."
        )
    elif (
        "po token" in lowered
        or "potoken" in lowered
        or "sign in" in lowered
        or "cookies" in lowered
        or "confirm you're not a bot" in lowered
        or "confirm you’re not a bot" in lowered
        or "bot" in lowered
        or "http error 403" in lowered
    ):
        prefix = (
            "O YouTube recusou a requisição anônima. Esse vídeo/IP pode exigir "
            "login, cookies ou validação anti-bot/PO Token do próprio YouTube."
        )
    elif "ffmpeg" in lowered:
        prefix = "O FFmpeg não está disponível ou não conseguiu finalizar o arquivo."
    elif "javascript" in lowered or "challenge" in lowered or "ejs" in lowered:
        prefix = (
            "O runtime JavaScript/EJS necessário para o YouTube não conseguiu "
            "resolver o desafio do player."
        )
    else:
        prefix = "Não foi possível processar este conteúdo do YouTube."

    return RuntimeError(f"{prefix} Detalhe técnico: {detail}")


def _metadata(info: dict, url: str, size: int, *, height: int | None = None) -> dict:
    return {
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url") or url,
        "filesize": size,
        "height": height,
    }


def download_youtube_mp4(
    url: str,
    max_height: int = 720,
    progress_callback: ProgressCallback | None = None,
) -> tuple[bytes, str, dict]:
    """Baixa um vídeo público/autorizado do YouTube e retorna o MP4 em memória."""
    if not is_youtube_url(url):
        raise ValueError("Informe um link válido do YouTube.")

    max_height = int(max_height)
    if max_height not in ALLOWED_HEIGHTS:
        max_height = 720

    with tempfile.TemporaryDirectory(prefix="streamlit_yt_video_") as temp_dir:
        folder = Path(temp_dir)

        options = _common_options(
            folder,
            MAX_VIDEO_BYTES,
            progress_callback,
        )
        options.update(
            {
                "format": (
                    f"bv*[height<={max_height}]+ba/"
                    f"b[height<={max_height}]/"
                    "bv*+ba/b"
                ),
                "format_sort": [
                    "vcodec:h264",
                    "lang",
                    "quality",
                    "res",
                    "fps",
                    "hdr:12",
                    "acodec:aac",
                ],
                "merge_output_format": "mp4",
                "final_ext": "mp4",
                "postprocessors": [
                    {
                        "key": "FFmpegVideoRemuxer",
                        "preferedformat": "mp4",
                    }
                ],
            }
        )

        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url.strip(), download=True)
        except DownloadError as exc:
            raise _friendly_download_error(exc) from exc

        output_path = _find_output_file(folder, ".mp4")
        size = output_path.stat().st_size

        if size > MAX_VIDEO_BYTES:
            raise RuntimeError(
                "O vídeo final ultrapassa o limite de 750 MB deste app."
            )

        title = _safe_filename(str(info.get("title") or output_path.stem))
        filename = f"{title}.mp4"
        metadata = _metadata(
            info,
            url,
            size,
            height=info.get("height"),
        )

        return output_path.read_bytes(), filename, metadata


def download_youtube_mp3(
    url: str,
    progress_callback: ProgressCallback | None = None,
) -> tuple[bytes, str, dict]:
    """Baixa a melhor faixa de áudio disponível e converte o resultado para MP3."""
    if not is_youtube_url(url):
        raise ValueError("Informe um link válido do YouTube.")

    with tempfile.TemporaryDirectory(prefix="streamlit_yt_audio_") as temp_dir:
        folder = Path(temp_dir)

        options = _common_options(
            folder,
            MAX_AUDIO_BYTES,
            progress_callback,
        )
        options.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }
        )

        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url.strip(), download=True)
        except DownloadError as exc:
            raise _friendly_download_error(exc) from exc

        output_path = _find_output_file(folder, ".mp3")
        size = output_path.stat().st_size

        if size > MAX_AUDIO_BYTES:
            raise RuntimeError(
                "O áudio final ultrapassa o limite de 250 MB deste app."
            )

        title = _safe_filename(str(info.get("title") or output_path.stem))
        filename = f"{title}.mp3"
        metadata = _metadata(info, url, size, height=None)

        return output_path.read_bytes(), filename, metadata
