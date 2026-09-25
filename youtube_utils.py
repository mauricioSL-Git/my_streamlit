from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Any
from urllib.parse import urlparse

import imageio_ffmpeg
from pytubefix import YouTube

# Limites do aplicativo
MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB para MP4
MAX_AUDIO_BYTES = 250 * 1024 * 1024  # 250 MB para MP3
ALLOWED_HEIGHTS = {360, 480, 720, 1080, 1440, 2160}

# Os arquivos finais precisam sobreviver ao fim da função para que o Streamlit
# possa entregá-los usando st.download_button(data=callable). O diretório é
# limpo automaticamente quando novas tarefas começam.
DOWNLOAD_ROOT = Path(tempfile.gettempdir()) / "inova_generator_youtube"
STALE_OUTPUT_SECONDS = 60 * 60  # 1 hora

ProgressCallback = Callable[[dict], None]

# Estratégia de cliente para ambientes de datacenter (como Streamlit Community).
# WEB é tentado primeiro porque o pytubefix 11.x consegue gerar PO Token
# automaticamente para clientes WEB usando Node.js. Os demais são fallback.
DEFAULT_YOUTUBE_CLIENTS = ("VISION_OS", "WEB", "ANDROID_VR", "IOS")


def _youtube_clients() -> tuple[str, ...]:
    raw = os.getenv("YOUTUBE_CLIENTS", "").strip()
    if not raw:
        return DEFAULT_YOUTUBE_CLIENTS

    clients = tuple(part.strip().upper() for part in raw.split(",") if part.strip())
    return clients or DEFAULT_YOUTUBE_CLIENTS


def _youtube_proxies() -> dict[str, str] | None:
    """Lê um proxy opcional do Streamlit Secrets / variável de ambiente.

    No Streamlit Community Cloud, adicione em Settings > Secrets, por exemplo:
        YOUTUBE_PROXY = "socks5://usuario:senha@host:porta"

    Root-level secrets do Streamlit ficam disponíveis como variáveis de ambiente.
    """
    proxy = os.getenv("YOUTUBE_PROXY", "").strip()
    if not proxy:
        return None

    allowed = ("http://", "https://", "socks4://", "socks4a://", "socks5://", "socks5h://")
    if not proxy.lower().startswith(allowed):
        raise RuntimeError(
            "YOUTUBE_PROXY possui formato inválido. Use http://, https:// ou socks5://."
        )

    return {"http": proxy, "https": proxy}


def is_youtube_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False

    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and host in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "music.youtube.com",
    }


def _safe_filename(value: str) -> str:
    value = re.sub(r"[^\w\-. ]+", "_", value, flags=re.UNICODE).strip(" ._")
    return value[:120] or "youtube"


def _get_ffmpeg_path() -> str:
    """Localiza o FFmpeg no Streamlit Cloud ou no ambiente local."""
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
        "FFmpeg não foi encontrado. Mantenha 'ffmpeg' no packages.txt ou "
        "instale imageio-ffmpeg no ambiente local."
    )


def _cleanup_stale_outputs(max_age_seconds: int = STALE_OUTPUT_SECONDS) -> None:
    """Remove downloads temporários antigos para não lotar o disco do servidor."""
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - max_age_seconds

    for item in DOWNLOAD_ROOT.iterdir():
        try:
            if item.stat().st_mtime >= cutoff:
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
        except OSError:
            # Limpeza é best-effort; não deve impedir um novo download.
            pass


def cleanup_youtube_output(value: str | Path | None) -> None:
    """Remove o diretório temporário referente a um arquivo final do YouTube."""
    if not value:
        return

    try:
        path = Path(value).resolve()
        root = DOWNLOAD_ROOT.resolve()
        if root == path or root not in path.parents:
            return

        parent = path.parent
        if parent.exists():
            shutil.rmtree(parent, ignore_errors=True)
    except (OSError, RuntimeError, ValueError):
        pass


def _new_output_folder(prefix: str) -> Path:
    _cleanup_stale_outputs()
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(DOWNLOAD_ROOT)))


def _stream_filesize(stream: Any) -> int:
    for attr in ("filesize", "filesize_approx"):
        try:
            value = getattr(stream, attr, None)
            if value:
                return int(value)
        except Exception:
            pass
    return 0


def _stream_height(stream: Any) -> int:
    try:
        height = getattr(stream, "height", None)
        if height:
            return int(height)
    except Exception:
        pass

    resolution = str(getattr(stream, "resolution", "") or "")
    match = re.search(r"(\d+)", resolution)
    return int(match.group(1)) if match else 0


def _select_video_stream(yt: YouTube, max_height: int):
    """Seleciona MP4 até a altura pedida, preferindo vídeo adaptativo."""
    adaptive = yt.streams.filter(
        only_video=True,
        adaptive=True,
        subtype="mp4",
    ).all()
    eligible = [stream for stream in adaptive if 0 < _stream_height(stream) <= max_height]

    if eligible:
        return max(
            eligible,
            key=lambda stream: (
                _stream_height(stream),
                int(getattr(stream, "fps", 0) or 0),
                int(getattr(stream, "bitrate", 0) or 0),
            ),
        ), False

    # Fallback para streams progressivos MP4 (vídeo + áudio juntos), comuns até 720p.
    progressive = yt.streams.filter(progressive=True, subtype="mp4").all()
    eligible = [stream for stream in progressive if 0 < _stream_height(stream) <= max_height]
    if eligible:
        return max(
            eligible,
            key=lambda stream: (
                _stream_height(stream),
                int(getattr(stream, "fps", 0) or 0),
                int(getattr(stream, "bitrate", 0) or 0),
            ),
        ), True

    raise RuntimeError(
        f"Não encontrei um stream MP4 de até {max_height}p para este vídeo. "
        "Tente outra qualidade ou outro vídeo."
    )


def _select_audio_stream(yt: YouTube):
    """Prefere M4A/AAC para compatibilidade e usa outro áudio como fallback."""
    preferred = yt.streams.filter(only_audio=True, subtype="mp4").order_by("abr").last()
    if preferred is not None:
        return preferred

    fallback = yt.streams.filter(only_audio=True).order_by("abr").last()
    if fallback is None:
        raise RuntimeError("Não encontrei uma faixa de áudio disponível para este vídeo.")
    return fallback


def _make_progress_callbacks(progress_callback: ProgressCallback | None):
    if progress_callback is None:
        return None, None

    def on_progress(stream, _chunk: bytes, bytes_remaining: int) -> None:
        total = _stream_filesize(stream)
        downloaded = max(total - int(bytes_remaining or 0), 0) if total else 0
        progress_callback(
            {
                "status": "downloading",
                "filename": str(getattr(stream, "default_filename", "youtube")),
                "downloaded_bytes": downloaded,
                "total_bytes": total,
                "total_bytes_estimate": total,
            }
        )

    def on_complete(stream, file_path: str | None) -> None:
        progress_callback(
            {
                "status": "finished",
                "filename": str(
                    file_path
                    or getattr(stream, "default_filename", "youtube")
                ),
            }
        )

    return on_progress, on_complete


def _build_youtube_for_client(
    url: str,
    progress_callback: ProgressCallback | None,
    client: str,
) -> YouTube:
    """Cria um objeto YouTube para um cliente específico.

    O fallback entre clientes é feito no download real, pois erros SABR/PoToken
    podem aparecer somente depois que ``stream.download()`` começa.
    """
    on_progress, on_complete = _make_progress_callbacks(progress_callback)
    proxies = _youtube_proxies()

    yt = YouTube(
        url.strip(),
        client=client,
        proxies=proxies,
        on_progress_callback=on_progress,
        on_complete_callback=on_complete,
    )
    yt.check_availability()
    streams = yt.streams.all()
    if not streams:
        raise RuntimeError(f"O cliente {client} não retornou streams utilizáveis.")
    return yt


def _clean_attempt_files(folder: Path) -> None:
    """Limpa arquivos parciais antes de tentar outro cliente."""
    if not folder.exists():
        return
    for item in folder.iterdir():
        try:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
        except OSError:
            pass


def _clean_error_text(exc: BaseException, limit: int = 420) -> str:
    detail = re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", str(exc))
    detail = detail.replace("\n", " ").strip()
    return detail[-limit:] or exc.__class__.__name__


def _raise_all_clients_failed(failures: list[str]) -> None:
    detail = " | ".join(failures[-4:]) or "nenhum cliente respondeu"
    lowered = detail.lower()
    proxies = _youtube_proxies()

    if any(
        term in lowered
        for term in (
            "sabr",
            "po token",
            "potoken",
            "bot",
            "403",
            "429",
            "stream protection",
        )
    ):
        proxy_note = (
            " O proxy configurado também foi tentado."
            if proxies
            else " No Streamlit Community, um proxy residencial/ISP em YOUTUBE_PROXY pode ser necessário."
        )
        raise RuntimeError(
            "O YouTube recusou ou interrompeu o streaming protegido (SABR/PO Token) "
            "em todos os clientes tentados."
            + proxy_note
            + f" Detalhe técnico: {detail}"
        )

    raise RuntimeError(
        "Não foi possível baixar este vídeo com os clientes do YouTube disponíveis. "
        f"Detalhe técnico: {detail}"
    )


def _run_ffmpeg(args: list[str], progress_callback: ProgressCallback | None) -> None:
    if progress_callback is not None:
        progress_callback(
            {
                "status": "postprocessing",
                "postprocessor_status": "started",
                "postprocessor": "FFmpeg",
            }
        )

    command = [_get_ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", *args]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=30 * 60,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("O FFmpeg excedeu o tempo máximo de processamento.") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "erro desconhecido").strip()
        detail = detail[-1500:]
        raise RuntimeError(f"O FFmpeg não conseguiu finalizar o arquivo. Detalhe: {detail}")


def _friendly_error(exc: BaseException) -> RuntimeError:
    detail = re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", str(exc))
    lowered = detail.lower()

    if "__processing_cancelled__" in lowered:
        return RuntimeError("__PROCESSING_CANCELLED__")
    if any(term in lowered for term in ("age restricted", "sign in", "login", "private")):
        prefix = (
            "O YouTube exige autenticação para este vídeo. "
            "O Streamlit Community não pode concluir a autenticação interativa desse conteúdo."
        )
    elif any(term in lowered for term in ("403", "429", "bot", "po token", "potoken")):
        prefix = (
            "O YouTube recusou a requisição do servidor. Isso pode ocorrer por "
            "limitação do IP do Streamlit Community ou verificação anti-bot."
        )
    elif "ffmpeg" in lowered:
        prefix = "O FFmpeg não está disponível ou não conseguiu processar o arquivo."
    else:
        prefix = "Não foi possível processar este conteúdo do YouTube com pytubefix."

    return RuntimeError(f"{prefix} Detalhe técnico: {detail}")


def _metadata(yt: YouTube, url: str, size: int, *, height: int | None = None) -> dict:
    try:
        duration = int(getattr(yt, "length", 0) or 0) or None
    except Exception:
        duration = None

    return {
        "title": getattr(yt, "title", None),
        "uploader": getattr(yt, "author", None),
        "duration": duration,
        "webpage_url": getattr(yt, "watch_url", None) or url,
        "filesize": size,
        "height": height,
    }


def download_youtube_mp4(
    url: str,
    max_height: int = 720,
    progress_callback: ProgressCallback | None = None,
) -> tuple[Path, str, dict]:
    """Baixa MP4 tentando novamente com outro cliente se SABR/PoToken falhar."""
    if not is_youtube_url(url):
        raise ValueError("Informe um link válido do YouTube.")

    max_height = int(max_height)
    if max_height not in ALLOWED_HEIGHTS:
        max_height = 720

    folder = _new_output_folder("video_")
    failures: list[str] = []

    try:
        for client in _youtube_clients():
            _clean_attempt_files(folder)
            try:
                yt = _build_youtube_for_client(url, progress_callback, client)
                video_stream, is_progressive = _select_video_stream(yt, max_height)
                video_size = _stream_filesize(video_stream)

                if video_size > MAX_VIDEO_BYTES:
                    raise RuntimeError("O vídeo selecionado ultrapassa o limite de 2 GB deste app.")

                title = _safe_filename(str(getattr(yt, "title", None) or "youtube"))
                final_path = folder / f"{title}.mp4"

                if is_progressive:
                    source_path = video_stream.download(
                        output_path=str(folder),
                        filename="source_progressive.mp4",
                        skip_existing=False,
                        timeout=30,
                        max_retries=5,
                    )
                    if not source_path:
                        raise RuntimeError("O download do vídeo foi interrompido antes de terminar.")

                    if progress_callback is not None:
                        progress_callback({
                            "status": "postprocessing",
                            "postprocessor_status": "started",
                            "postprocessor": "Finalização MP4",
                        })
                    shutil.move(str(source_path), final_path)
                else:
                    audio_stream = _select_audio_stream(yt)
                    audio_size = _stream_filesize(audio_stream)
                    if video_size and audio_size and (video_size + audio_size) > MAX_VIDEO_BYTES:
                        raise RuntimeError("O vídeo e o áudio selecionados ultrapassam o limite de 2 GB.")

                    video_ext = str(getattr(video_stream, "subtype", "mp4") or "mp4")
                    audio_ext = str(getattr(audio_stream, "subtype", "m4a") or "m4a")
                    if audio_ext == "mp4":
                        audio_ext = "m4a"

                    video_path = video_stream.download(
                        output_path=str(folder),
                        filename=f"video_source.{video_ext}",
                        skip_existing=False,
                        timeout=30,
                        max_retries=5,
                    )
                    if not video_path:
                        raise RuntimeError("O download da faixa de vídeo foi interrompido.")

                    audio_path = audio_stream.download(
                        output_path=str(folder),
                        filename=f"audio_source.{audio_ext}",
                        skip_existing=False,
                        timeout=30,
                        max_retries=5,
                    )
                    if not audio_path:
                        raise RuntimeError("O download da faixa de áudio foi interrompido.")

                    _run_ffmpeg(
                        [
                            "-i", str(video_path),
                            "-i", str(audio_path),
                            "-map", "0:v:0",
                            "-map", "1:a:0",
                            "-c:v", "copy",
                            "-c:a", "aac",
                            "-b:a", "192k",
                            "-movflags", "+faststart",
                            str(final_path),
                        ],
                        progress_callback,
                    )

                if not final_path.exists() or final_path.stat().st_size == 0:
                    raise RuntimeError("O arquivo MP4 final não foi criado corretamente.")

                size = final_path.stat().st_size
                if size > MAX_VIDEO_BYTES:
                    raise RuntimeError("O vídeo final ultrapassa o limite de 2 GB deste app.")

                for source in folder.iterdir():
                    if source != final_path and source.is_file():
                        source.unlink(missing_ok=True)

                metadata = _metadata(yt, url, size, height=_stream_height(video_stream))
                metadata["youtube_client"] = client
                return final_path, final_path.name, metadata

            except Exception as exc:
                text = _clean_error_text(exc)
                if "__PROCESSING_CANCELLED__" in text:
                    raise RuntimeError("__PROCESSING_CANCELLED__") from exc
                # Limites locais não mudam ao trocar de cliente.
                if any(term in text.lower() for term in ("limite de 2 gb", "ultrapassa o limite")):
                    raise
                failures.append(f"{client}: {text}")
                _clean_attempt_files(folder)
                continue

        _raise_all_clients_failed(failures)
        raise RuntimeError("Falha inesperada no fallback do YouTube.")

    except Exception as exc:
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        if isinstance(exc, (ValueError, RuntimeError)):
            raise
        raise _friendly_error(exc) from exc


def download_youtube_mp3(
    url: str,
    progress_callback: ProgressCallback | None = None,
) -> tuple[Path, str, dict]:
    """Baixa áudio e converte para MP3, com fallback real entre clientes."""
    if not is_youtube_url(url):
        raise ValueError("Informe um link válido do YouTube.")

    folder = _new_output_folder("audio_")
    failures: list[str] = []

    try:
        for client in _youtube_clients():
            _clean_attempt_files(folder)
            try:
                yt = _build_youtube_for_client(url, progress_callback, client)
                audio_stream = _select_audio_stream(yt)
                source_size = _stream_filesize(audio_stream)

                if source_size > MAX_AUDIO_BYTES * 2:
                    raise RuntimeError("A faixa de áudio é grande demais para este app.")

                audio_ext = str(getattr(audio_stream, "subtype", "m4a") or "m4a")
                if audio_ext == "mp4":
                    audio_ext = "m4a"

                source_path = audio_stream.download(
                    output_path=str(folder),
                    filename=f"audio_source.{audio_ext}",
                    skip_existing=False,
                    timeout=30,
                    max_retries=5,
                )
                if not source_path:
                    raise RuntimeError("O download do áudio foi interrompido antes de terminar.")

                title = _safe_filename(str(getattr(yt, "title", None) or "youtube"))
                final_path = folder / f"{title}.mp3"

                _run_ffmpeg(
                    [
                        "-i", str(source_path),
                        "-vn",
                        "-codec:a", "libmp3lame",
                        "-b:a", "192k",
                        "-map_metadata", "0",
                        str(final_path),
                    ],
                    progress_callback,
                )

                if not final_path.exists() or final_path.stat().st_size == 0:
                    raise RuntimeError("O arquivo MP3 final não foi criado corretamente.")

                size = final_path.stat().st_size
                if size > MAX_AUDIO_BYTES:
                    raise RuntimeError("O áudio final ultrapassa o limite de 250 MB deste app.")

                Path(source_path).unlink(missing_ok=True)
                metadata = _metadata(yt, url, size, height=None)
                metadata["youtube_client"] = client
                return final_path, final_path.name, metadata

            except Exception as exc:
                text = _clean_error_text(exc)
                if "__PROCESSING_CANCELLED__" in text:
                    raise RuntimeError("__PROCESSING_CANCELLED__") from exc
                if any(term in text.lower() for term in ("grande demais", "limite de 250 mb")):
                    raise
                failures.append(f"{client}: {text}")
                _clean_attempt_files(folder)
                continue

        _raise_all_clients_failed(failures)
        raise RuntimeError("Falha inesperada no fallback do YouTube.")

    except Exception as exc:
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        if isinstance(exc, (ValueError, RuntimeError)):
            raise
        raise _friendly_error(exc) from exc

