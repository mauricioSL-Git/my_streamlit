from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

import imageio_ffmpeg
import requests
from urllib3.exceptions import InsecureRequestWarning

MAX_MP3_BYTES = 100 * 1024 * 1024
MAX_VIDEO_BYTES = 180 * 1024 * 1024
MAX_PAGE_BYTES = 512 * 1024
CHUNK_SIZE = 256 * 1024

ProgressCallback = Callable[[dict], None]

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"
)
_DIRECT_SONG_RE = re.compile(
    r"/(?:song|hook)/([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})/?"
)
_PAGE_SONG_RE = re.compile(
    r"(?:suno\.com|/)(?:/)?song/([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})",
    re.IGNORECASE,
)

SUNO_PAGE_HOSTS = {
    "suno.com",
    "www.suno.com",
    "app.suno.ai",
    "www.app.suno.ai",
}
API_HOSTS = (
    "https://studio-api-prod.suno.com/api/clip/{clip_id}",
    "https://studio-api.prod.suno.com/api/clip/{clip_id}",
)


class SunoDownloadError(RuntimeError):
    """Erro amigável ao resolver ou baixar uma faixa do Suno."""


def _parsed(url: str):
    try:
        return urlsplit((url or "").strip())
    except (TypeError, ValueError, AttributeError) as exc:
        raise SunoDownloadError("URL inválida.") from exc


def _is_safe_https(url: str, allowed_roots: tuple[str, ...]) -> bool:
    """Evita SSRF: aceita apenas HTTPS em domínios do Suno/CDN oficial."""
    try:
        p = _parsed(url)
        host = (p.hostname or "").lower()
        if (
            p.scheme != "https"
            or not host
            or p.username
            or p.password
            or p.port not in (None, 443)
            or "\\" in url
            or any(ord(ch) < 32 for ch in url)
        ):
            return False
        return any(host == root or host.endswith("." + root) for root in allowed_roots)
    except (ValueError, SunoDownloadError):
        return False


def is_suno_url(value: str) -> bool:
    """Valida links de compartilhamento conhecidos do Suno."""
    try:
        p = _parsed(value)
    except SunoDownloadError:
        return False

    host = (p.hostname or "").lower()
    if p.scheme != "https" or host not in SUNO_PAGE_HOSTS:
        return False

    path = p.path.rstrip("/")
    return bool(
        re.fullmatch(r"/s/[A-Za-z0-9_-]{6,128}", path)
        or _DIRECT_SONG_RE.fullmatch(path)
    )


def _safe_filename(value: str) -> str:
    value = re.sub(r"[^\w\-. ()]+", "_", value or "", flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip(" ._-")
    return (value[:140] or "suno_musica") + ".mp3"


def _headers(*, media: bool = False) -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; InovaGenerator/1.0)",
        "Accept": "audio/mpeg,application/json,text/html,*/*;q=0.7",
    }
    if media:
        headers["Referer"] = "https://suno.com/"
    return headers


def _is_certificate_error(exc: requests.exceptions.SSLError) -> bool:
    text = str(exc).lower()
    return (
        "certificate_verify_failed" in text
        or "certificate verify failed" in text
        or "self-signed certificate" in text
        or "self signed certificate" in text
    )


def _get_with_ssl_fallback(
    session: requests.Session,
    url: str,
    *,
    allowed_roots: tuple[str, ...],
    headers: dict[str, str],
    timeout: int,
    allow_redirects: bool = False,
    stream: bool = False,
):
    """GET HTTPS com fallback restrito para ambientes com proxy/certificado local.

    A verificação TLS continua sendo a primeira tentativa. Somente se o erro for
    especificamente de validação de certificado, e somente para hosts permitidos,
    repetimos a chamada sem validar a cadeia. Isso atende servidores/Windows com
    proxy corporativo que injeta um certificado raiz próprio.
    """
    if not _is_safe_https(url, allowed_roots):
        raise SunoDownloadError("A conexão tentou acessar um domínio não permitido.")

    kwargs = {
        "headers": headers,
        "timeout": timeout,
        "allow_redirects": allow_redirects,
        "stream": stream,
    }
    try:
        return session.get(url, verify=True, **kwargs)
    except requests.exceptions.SSLError as exc:
        if not _is_certificate_error(exc):
            raise
        # O host já foi validado contra a allowlist acima. Não desabilitamos TLS
        # globalmente; o fallback vale apenas para esta requisição específica.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            return session.get(url, verify=False, **kwargs)


def _request_no_redirect(session: requests.Session, url: str, *, timeout: int = 25):
    return _get_with_ssl_fallback(
        session,
        url,
        allowed_roots=("suno.com", "suno.ai"),
        headers=_headers(),
        timeout=timeout,
        allow_redirects=False,
        stream=True,
    )


def _request_media(session: requests.Session, url: str, *, timeout: int = 40):
    """Segue redirects manualmente, validando cada host antes da conexão."""
    current = url
    for _ in range(8):
        response = _get_with_ssl_fallback(
            session,
            current,
            allowed_roots=("suno.com", "suno.ai"),
            headers=_headers(media=True),
            timeout=timeout,
            allow_redirects=False,
            stream=True,
        )
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response

        location = response.headers.get("Location")
        response.close()
        if not location:
            raise SunoDownloadError("A CDN do Suno retornou um redirecionamento inválido.")
        current = urljoin(current, location)
        if not _is_safe_https(current, ("suno.ai", "suno.com")):
            raise SunoDownloadError("O download foi redirecionado para um domínio não permitido.")

    raise SunoDownloadError("O download do Suno excedeu o limite de redirecionamentos.")


def _read_limited(response: requests.Response, limit: int) -> bytes:
    raw_len = response.headers.get("Content-Length")
    if raw_len and raw_len.isdecimal() and int(raw_len) > limit:
        raise SunoDownloadError("A resposta do Suno excede o limite permitido.")

    data = bytearray()
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        data.extend(chunk)
        if len(data) > limit:
            raise SunoDownloadError("A resposta do Suno excede o limite permitido.")
    return bytes(data)


def _clip_id_from_share(link: str, session: requests.Session) -> str:
    if not is_suno_url(link):
        raise SunoDownloadError(
            "Cole um link válido de música do Suno, por exemplo "
            "https://suno.com/song/... ou https://suno.com/s/..."
        )

    direct = _DIRECT_SONG_RE.fullmatch(_parsed(link).path.rstrip("/"))
    if direct:
        return direct.group(1).lower()

    current = link.strip()
    for _ in range(6):
        p = _parsed(current)
        host = (p.hostname or "").lower()
        if host not in SUNO_PAGE_HOSTS or p.scheme != "https":
            raise SunoDownloadError("O redirecionamento saiu dos domínios do Suno.")

        with _request_no_redirect(session, current) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                if not location:
                    raise SunoDownloadError("O Suno retornou um redirecionamento inválido.")
                current = urljoin(current, location)
                next_path = _parsed(current).path.rstrip("/")
                found = _DIRECT_SONG_RE.fullmatch(next_path)
                if found:
                    return found.group(1).lower()
                continue

            if response.status_code != 200:
                raise SunoDownloadError(
                    f"Não foi possível resolver o link no Suno (HTTP {response.status_code})."
                )

            page = _read_limited(response, MAX_PAGE_BYTES).decode("utf-8", errors="ignore")
            found = _PAGE_SONG_RE.search(page.replace("\\/", "/"))
            if found:
                return found.group(1).lower()
            break

    raise SunoDownloadError(
        "O Suno não informou o ID da música nesse link. Confira se o link é válido e acessível."
    )


def _get_clip(session: requests.Session, clip_id: str) -> dict:
    last_status: int | None = None
    last_error: Exception | None = None

    for template in API_HOSTS:
        url = template.format(clip_id=clip_id)
        try:
            response = _get_with_ssl_fallback(
                session,
                url,
                allowed_roots=("suno.com",),
                headers=_headers(),
                timeout=25,
                allow_redirects=False,
                stream=False,
            )
        except requests.RequestException as exc:
            last_error = exc
            continue

        last_status = response.status_code
        if response.status_code in {401, 403}:
            continue
        if response.status_code != 200:
            continue

        try:
            data = response.json()
        except ValueError as exc:
            last_error = exc
            continue

        if isinstance(data, dict) and data:
            return data

    if last_status in {401, 403}:
        raise SunoDownloadError(
            "O Suno não disponibilizou os metadados dessa música sem autenticação. "
            "O módulo não tenta contornar login, conteúdo privado ou bloqueios da plataforma."
        )
    if last_status is not None:
        raise SunoDownloadError(
            f"Não foi possível obter os metadados da música no Suno (HTTP {last_status})."
        )
    if last_error is not None:
        raise SunoDownloadError(f"Falha de conexão com o Suno: {last_error}") from last_error
    raise SunoDownloadError("Não foi possível obter os metadados da música no Suno.")


def _safe_media_url(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    url = value.strip()
    if _is_safe_https(url, ("suno.ai", "suno.com")):
        return url
    return None


def _looks_like_mp3(data: bytes) -> bool:
    if len(data) < 4:
        return False
    if data.startswith(b"ID3"):
        return True
    return data[0] == 0xFF and (data[1] & 0xE0) == 0xE0


def _download_media(
    session: requests.Session,
    url: str,
    *,
    limit: int,
    progress_callback: ProgressCallback | None,
    label: str,
) -> tuple[bytes, str]:
    if not _is_safe_https(url, ("suno.ai", "suno.com")):
        raise SunoDownloadError("A mídia retornada não pertence a um domínio permitido do Suno.")

    try:
        with _request_media(session, url, timeout=40) as response:
            if response.status_code != 200:
                raise SunoDownloadError(
                    f"O arquivo do Suno não está acessível (HTTP {response.status_code})."
                )

            final_url = response.url or url
            if not _is_safe_https(final_url, ("suno.ai", "suno.com")):
                raise SunoDownloadError("O download foi redirecionado para um domínio não permitido.")

            raw_total = response.headers.get("Content-Length")
            total = int(raw_total) if raw_total and raw_total.isdecimal() else None
            if total is not None and total > limit:
                raise SunoDownloadError("O arquivo excede o limite permitido deste aplicativo.")

            chunks: list[bytes] = []
            received = 0
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if not chunk:
                    continue
                chunks.append(chunk)
                received += len(chunk)
                if received > limit:
                    raise SunoDownloadError("O arquivo excede o limite permitido deste aplicativo.")
                if progress_callback:
                    progress_callback(
                        {
                            "status": "downloading",
                            "filename": label,
                            "downloaded_bytes": received,
                            "total_bytes": total,
                        }
                    )

            return b"".join(chunks), response.headers.get("Content-Type", "")
    except SunoDownloadError:
        raise
    except requests.RequestException as exc:
        raise SunoDownloadError(f"Falha ao baixar a mídia do Suno: {exc}") from exc


def _ffmpeg_path() -> str:
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and Path(bundled).exists():
            return str(bundled)
    except Exception as exc:
        raise SunoDownloadError(f"Não foi possível localizar o FFmpeg: {exc}") from exc
    raise SunoDownloadError("FFmpeg não encontrado para converter o vídeo do Suno em MP3.")


def _video_to_mp3(video_bytes: bytes, title: str, artist: str) -> bytes:
    with tempfile.TemporaryDirectory(prefix="suno_mp3_") as temp_dir:
        folder = Path(temp_dir)
        src = folder / "source.mp4"
        dst = folder / "result.mp3"
        src.write_bytes(video_bytes)

        command = [
            _ffmpeg_path(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "192k",
        ]
        if title:
            command += ["-metadata", f"title={title}"]
        if artist:
            command += ["-metadata", f"artist={artist}"]
        command.append(str(dst))

        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SunoDownloadError(f"Falha ao executar o FFmpeg: {exc}") from exc

        if completed.returncode != 0 or not dst.exists():
            detail = completed.stderr.decode("utf-8", errors="ignore").strip()
            raise SunoDownloadError(
                "O FFmpeg não conseguiu converter o vídeo do Suno em MP3. "
                + (detail[-500:] if detail else "")
            )

        result = dst.read_bytes()
        if len(result) > MAX_MP3_BYTES:
            raise SunoDownloadError("O MP3 gerado ultrapassa o limite de 100 MB.")
        if not _looks_like_mp3(result):
            raise SunoDownloadError("O arquivo convertido não parece ser um MP3 válido.")
        return result


def download_suno_mp3(
    suno_url: str,
    progress_callback: ProgressCallback | None = None,
    *,
    session: requests.Session | None = None,
) -> tuple[bytes, str, dict]:
    """Resolve um link compartilhado do Suno e retorna um MP3 em memória.

    Prioriza o MP3 já fornecido pela CDN do próprio Suno. Se a faixa expuser
    apenas vídeo público, usa FFmpeg localmente como fallback. Não tenta login,
    cookies, conteúdo privado, DRM ou contorno de respostas 401/403.
    """
    if not is_suno_url(suno_url):
        raise ValueError("Informe um link válido de música do Suno.")

    own_session = session is None
    client = session or requests.Session()
    try:
        if progress_callback:
            progress_callback({"status": "resolving", "percent": 5})

        clip_id = _clip_id_from_share(suno_url, client)
        if progress_callback:
            progress_callback({"status": "resolving", "percent": 12})

        clip = _get_clip(client, clip_id)
        title = str(clip.get("title") or "suno_musica").strip()
        artist = str(clip.get("display_name") or clip.get("handle") or "").strip()
        metadata_block = clip.get("metadata") if isinstance(clip.get("metadata"), dict) else {}
        duration = metadata_block.get("duration")

        audio_url = _safe_media_url(clip.get("audio_url"))
        video_url = _safe_media_url(clip.get("video_url"))
        origin = "MP3 da CDN do Suno"
        data: bytes | None = None
        audio_error: SunoDownloadError | None = None

        if audio_url:
            try:
                candidate, content_type = _download_media(
                    client,
                    audio_url,
                    limit=MAX_MP3_BYTES,
                    progress_callback=progress_callback,
                    label="audio.mp3",
                )
                if "html" in (content_type or "").lower() or not _looks_like_mp3(candidate):
                    raise SunoDownloadError(
                        "O Suno retornou uma resposta que não parece ser um arquivo MP3 válido."
                    )
                data = candidate
            except SunoDownloadError as exc:
                audio_error = exc

        if data is None:
            if not video_url:
                if audio_error is not None:
                    raise audio_error
                raise SunoDownloadError(
                    "Essa música não possui um MP3 ou MP4 público informado pelo Suno."
                )
            video_bytes, content_type = _download_media(
                client,
                video_url,
                limit=MAX_VIDEO_BYTES,
                progress_callback=progress_callback,
                label="video.mp4",
            )
            if "html" in (content_type or "").lower() or b"ftyp" not in video_bytes[:64]:
                raise SunoDownloadError("O Suno não retornou um MP4 válido para conversão.")
            if progress_callback:
                progress_callback({"status": "postprocessing", "percent": 88})
            data = _video_to_mp3(video_bytes, title, artist)
            origin = "MP4 da CDN do Suno convertido localmente para MP3"

        if len(data) > MAX_MP3_BYTES:
            raise SunoDownloadError("O MP3 final ultrapassa o limite de 100 MB.")

        if progress_callback:
            progress_callback({"status": "finished", "percent": 100, "filename": "audio.mp3"})

        base_name = f"{artist} - {title}" if artist else title
        filename = _safe_filename(base_name)
        info = {
            "title": title,
            "uploader": artist or None,
            "duration": duration,
            "webpage_url": f"https://suno.com/song/{clip_id}",
            "filesize": len(data),
            "id": clip_id,
            "origin": origin,
            "image_url": clip.get("image_large_url") or clip.get("image_url"),
        }
        return data, filename, info
    except requests.RequestException as exc:
        raise SunoDownloadError(f"Erro na conexão direta com o Suno: {exc}") from exc
    finally:
        if own_session:
            client.close()
