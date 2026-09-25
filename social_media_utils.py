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

MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB para MP4
MAX_AUDIO_BYTES = 250 * 1024 * 1024  # 250 MB para MP3
ALLOWED_HEIGHTS = {360, 480, 720, 1080, 1440, 2160}

ProgressCallback = Callable[[dict], None]


def _is_certificate_error(exc: BaseException) -> bool:
    detail = str(exc).lower()
    return any(
        term in detail
        for term in (
            "certificate_verify_failed",
            "certificate verify failed",
            "self-signed certificate",
            "self signed certificate",
            "curl: (60)",
            "peer_failed_verification",
        )
    )


def _extract_with_ssl_fallback(url: str, options: dict) -> dict:
    """Executa o yt-dlp com SSL normal e só relaxa a validação em erro de certificado."""
    try:
        with YoutubeDL(options) as ydl:
            return ydl.extract_info(url.strip(), download=True)
    except DownloadError as exc:
        if not _is_certificate_error(exc):
            raise

        fallback_options = dict(options)
        fallback_options["nocheckcertificate"] = True

        with YoutubeDL(fallback_options) as ydl:
            return ydl.extract_info(url.strip(), download=True)

_PLATFORM_CONFIG = {
    "instagram": {
        "label": "Instagram",
        "hosts": {"instagram.com", "www.instagram.com"},
        "prefix": "streamlit_ig",
    },
    "facebook": {
        "label": "Facebook",
        "hosts": {
            "facebook.com",
            "www.facebook.com",
            "m.facebook.com",
            "web.facebook.com",
            "fb.watch",
            "www.fb.watch",
        },
        "prefix": "streamlit_fb",
    },
}


def _platform_config(platform: str) -> dict:
    try:
        return _PLATFORM_CONFIG[platform.lower()]
    except KeyError as exc:
        raise ValueError(f"Plataforma não suportada: {platform}") from exc


def is_social_url(value: str, platform: str) -> bool:
    config = _platform_config(platform)
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False

    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and host in config["hosts"]


def is_instagram_url(value: str) -> bool:
    return is_social_url(value, "instagram")


def is_facebook_url(value: str) -> bool:
    return is_social_url(value, "facebook")


def _safe_filename(value: str, fallback: str) -> str:
    value = re.sub(r"[^\w\-. ]+", "_", value, flags=re.UNICODE).strip(" ._")
    return value[:120] or fallback


def _find_output_file(folder: Path, extension: str) -> Path:
    extension = extension.lower()
    candidates = [
        path
        for path in folder.rglob("*")
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


def _get_ffmpeg_path() -> str:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    try:
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and Path(bundled).exists():
            return str(bundled)
    except Exception as exc:
        raise RuntimeError(f"Não foi possível localizar o FFmpeg: {exc}") from exc

    raise RuntimeError(
        "FFmpeg não foi encontrado. Instale imageio-ffmpeg ou disponibilize "
        "o executável ffmpeg no sistema."
    )


def _friendly_download_error(exc: DownloadError, platform: str) -> RuntimeError:
    label = _platform_config(platform)["label"]
    detail = re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", str(exc))
    lowered = detail.lower()

    if "ffmpeg" in lowered:
        prefix = "O FFmpeg não está disponível ou não conseguiu finalizar o arquivo."
    elif any(term in lowered for term in ("login", "cookie", "private", "not available", "403", "429")):
        prefix = (
            f"O {label} não permitiu o acesso anônimo a esse conteúdo. "
            "Ele pode ser privado, restrito, exigir login/cookies ou estar sujeito "
            "a uma limitação temporária da plataforma."
        )
    else:
        prefix = f"Não foi possível processar este conteúdo do {label}."

    return RuntimeError(f"{prefix} Detalhe técnico: {detail}")


def _metadata(info: dict, url: str, size: int, *, height: int | None = None) -> dict:
    return {
        "title": info.get("title") or info.get("description"),
        "uploader": info.get("uploader") or info.get("channel") or info.get("uploader_id"),
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url") or url,
        "filesize": size,
        "height": height,
    }


def _common_options(
    folder: Path,
    max_filesize: int,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    options = {
        "outtmpl": str(folder / "%(title).100s [%(id)s].%(ext)s"),
        "ffmpeg_location": _get_ffmpeg_path(),
        "noplaylist": True,
        "playlist_items": "1",
        "quiet": True,
        "no_warnings": True,
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


def download_social_mp4(
    url: str,
    platform: str,
    max_height: int = 720,
    progress_callback: ProgressCallback | None = None,
) -> tuple[bytes, str, dict]:
    config = _platform_config(platform)
    label = config["label"]
    if not is_social_url(url, platform):
        raise ValueError(f"Informe um link válido do {label}.")

    max_height = int(max_height)
    if max_height not in ALLOWED_HEIGHTS:
        max_height = 720

    with tempfile.TemporaryDirectory(prefix=f"{config['prefix']}_video_") as temp_dir:
        folder = Path(temp_dir)
        options = _common_options(folder, MAX_VIDEO_BYTES, progress_callback)
        options.update(
            {
                "format": (
                    f"bv*[height<={max_height}]+ba/"
                    f"b[height<={max_height}]/"
                    "bv*+ba/b"
                ),
                "format_sort": [
                    "vcodec:h264",
                    "quality",
                    "res",
                    "fps",
                    "acodec:aac",
                ],
                "merge_output_format": "mp4",
                "final_ext": "mp4",
                "postprocessors": [
                    {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}
                ],
            }
        )

        try:
            info = _extract_with_ssl_fallback(url, options)
        except DownloadError as exc:
            raise _friendly_download_error(exc, platform) from exc

        output_path = _find_output_file(folder, ".mp4")
        size = output_path.stat().st_size
        if size > MAX_VIDEO_BYTES:
            raise RuntimeError("O vídeo final ultrapassa o limite de 2 GB deste app.")

        title = _safe_filename(str(info.get("title") or output_path.stem), platform)
        filename = f"{title}.mp4"
        return output_path.read_bytes(), filename, _metadata(
            info, url, size, height=info.get("height")
        )


def download_social_mp3(
    url: str,
    platform: str,
    progress_callback: ProgressCallback | None = None,
) -> tuple[bytes, str, dict]:
    config = _platform_config(platform)
    label = config["label"]
    if not is_social_url(url, platform):
        raise ValueError(f"Informe um link válido do {label}.")

    with tempfile.TemporaryDirectory(prefix=f"{config['prefix']}_audio_") as temp_dir:
        folder = Path(temp_dir)
        options = _common_options(folder, MAX_AUDIO_BYTES, progress_callback)
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
            info = _extract_with_ssl_fallback(url, options)
        except DownloadError as exc:
            raise _friendly_download_error(exc, platform) from exc

        output_path = _find_output_file(folder, ".mp3")
        size = output_path.stat().st_size
        if size > MAX_AUDIO_BYTES:
            raise RuntimeError("O áudio final ultrapassa o limite de 250 MB deste app.")

        title = _safe_filename(str(info.get("title") or output_path.stem), platform)
        filename = f"{title}.mp3"
        return output_path.read_bytes(), filename, _metadata(info, url, size)


def download_instagram_mp4(url: str, max_height: int = 720, progress_callback: ProgressCallback | None = None):
    return download_social_mp4(url, "instagram", max_height, progress_callback)


def download_instagram_mp3(url: str, progress_callback: ProgressCallback | None = None):
    return download_social_mp3(url, "instagram", progress_callback)


def download_facebook_mp4(url: str, max_height: int = 720, progress_callback: ProgressCallback | None = None):
    return download_social_mp4(url, "facebook", max_height, progress_callback)


def download_facebook_mp3(url: str, progress_callback: ProgressCallback | None = None):
    return download_social_mp3(url, "facebook", progress_callback)
