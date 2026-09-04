#from __future__ import annotations
#
#import re
#import shutil
#import tempfile
#from pathlib import Path
#from typing import Callable
#from urllib.parse import urlparse
#
#import imageio_ffmpeg
#from yt_dlp import YoutubeDL
#from yt_dlp.utils import DownloadError
#
#MAX_DOWNLOAD_BYTES = 750 * 1024 * 1024  # 750 MB
#ALLOWED_HEIGHTS = {360, 480, 720, 1080, 1440, 2160}
#
#
#def is_vimeo_url(value: str) -> bool:
#    """
#    Mantido com este nome para não quebrar o restante do projeto.
#
#    Aceita tanto:
#    - links diretos do Vimeo;
#    - links player.vimeo.com;
#    - páginas externas que contenham um player Vimeo incorporado.
#    """
#    try:
#        parsed = urlparse(value.strip())
#    except ValueError:
#        return False
#
#    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
#
#
#def _safe_filename(value: str) -> str:
#    value = re.sub(r"[^\w\-. ]+", "_", value, flags=re.UNICODE).strip(" ._")
#    return value[:120] or "video_vimeo"
#
#
#def _clean_error_message(message: str) -> str:
#    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
#    return ansi_escape.sub("", message)
#
#
#def _get_ffmpeg_path() -> str:
#    """Localiza o FFmpeg sem depender do winget/PATH do Windows."""
#    try:
#        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
#        if ffmpeg_path and Path(ffmpeg_path).exists():
#            return ffmpeg_path
#    except Exception:
#        pass
#
#    ffmpeg_path = shutil.which("ffmpeg")
#    if ffmpeg_path:
#        return ffmpeg_path
#
#    raise RuntimeError(
#        "FFmpeg não foi encontrado. Instale as dependências do requirements.txt "
#        "e reinicie o aplicativo."
#    )
#
#
#def _find_output_file(folder: Path) -> Path:
#    candidates = [
#        p
#        for p in folder.rglob("*")
#        if p.is_file()
#        and p.suffix.lower() == ".mp4"
#        and not p.name.endswith((".part", ".ytdl"))
#    ]
#
#    if not candidates:
#        raise RuntimeError(
#            "O processamento terminou, mas o arquivo MP4 final não foi localizado. "
#            "Verifique se o FFmpeg está disponível no ambiente."
#        )
#
#    return max(candidates, key=lambda p: p.stat().st_mtime)
#
#
#def _primary_info(info: dict) -> dict:
#    """Obtém os metadados do primeiro vídeo quando a página vira playlist."""
#    if not isinstance(info, dict):
#        return {}
#
#    entries = info.get("entries")
#    if entries:
#        try:
#            for entry in entries:
#                if isinstance(entry, dict):
#                    nested = _primary_info(entry)
#                    if nested:
#                        return nested
#        except TypeError:
#            pass
#
#    return info
#
#
#def _host_is_vimeo(host: str) -> bool:
#    host = host.lower().split(":", 1)[0]
#    return host == "vimeo.com" or host.endswith(".vimeo.com")
#
#
#def _extract_vimeo_id_and_hash(value: str) -> tuple[str | None, str | None]:
#    """
#    Extrai ID e hash não listado de links Vimeo conhecidos.
#
#    Exemplos:
#      https://vimeo.com/868438346
#      https://vimeo.com/123456789/abcdef1234
#      https://player.vimeo.com/video/123456789?h=abcdef1234
#    """
#    try:
#        parsed = urlparse(value)
#    except ValueError:
#        return None, None
#
#    host = (parsed.hostname or "").lower()
#    if not _host_is_vimeo(host):
#        return None, None
#
#    parts = [part for part in parsed.path.split("/") if part]
#    video_id = None
#    unlisted_hash = None
#
#    if host == "player.vimeo.com" or host.endswith(".player.vimeo.com"):
#        if "video" in parts:
#            index = parts.index("video")
#            if index + 1 < len(parts) and parts[index + 1].isdigit():
#                video_id = parts[index + 1]
#        query_hash = parse_qs(parsed.query).get("h", [None])[0]
#        if query_hash:
#            unlisted_hash = query_hash
#    else:
#        # Pega o último segmento puramente numérico como ID.
#        for index, part in enumerate(parts):
#            if part.isdigit() and 6 <= len(part) <= 12:
#                video_id = part
#                if index + 1 < len(parts):
#                    next_part = parts[index + 1]
#                    if re.fullmatch(r"[0-9a-fA-F]{6,64}", next_part):
#                        unlisted_hash = next_part
#
#    return video_id, unlisted_hash
#
#
#def _build_player_url(source_url: str) -> str | None:
#    video_id, unlisted_hash = _extract_vimeo_id_and_hash(source_url)
#    if not video_id:
#        return None
#
#    player_url = f"https://player.vimeo.com/video/{video_id}"
#    if unlisted_hash:
#        player_url += "?" + urlencode({"h": unlisted_hash})
#
#    return player_url
#
#
#def _is_direct_vimeo_page(value: str) -> bool:
#    try:
#        host = (urlparse(value).hostname or "").lower()
#    except ValueError:
#        return False
#
#    return _host_is_vimeo(host)
#
#
#def _is_player_url(value: str) -> bool:
#    try:
#        host = (urlparse(value).hostname or "").lower()
#    except ValueError:
#        return False
#
#    return host == "player.vimeo.com" or host.endswith(".player.vimeo.com")
#
#
#def _ensure_anonymous_vimeo_client() -> None:
#    """Confirma que a instalação do yt-dlp possui o cliente anônimo atual do Vimeo."""
#    try:
#        from yt_dlp.extractor.vimeo import VimeoIE
#    except Exception as exc:
#        raise RuntimeError(
#            f"Não foi possível carregar o extrator Vimeo do yt-dlp: {exc}"
#        ) from exc
#
#    clients = set(getattr(VimeoIE, "_CLIENT_CONFIGS", {}).keys())
#    default_client = getattr(VimeoIE, "_DEFAULT_CLIENT", None)
#
#    if "macos_basic" not in clients:
#        raise RuntimeError(
#            "Sua instalação do yt-dlp ainda não possui o cliente anônimo atual do Vimeo "
#            "(macos_basic). Instale a branch master indicada no requirements.txt e reinicie "
#            "o Streamlit. Clientes encontrados: "
#            f"{', '.join(sorted(clients)) or 'nenhum'}; padrão: {default_client or 'desconhecido'}."
#        )
#
#
#
#def _ydl_options(
#    folder: Path,
#    max_height: int,
#    progress_callback: Callable[[dict], None] | None = None,
#    referer: str | None = None,
#) -> dict:
#    format_selector = (
#        f"bv*[height<={max_height}]+ba/"
#        f"b[height<={max_height}]/"
#        "bv*+ba/b"
#    )
#
#    options = {
#        "format": format_selector,
#        "format_sort": [
#            "vcodec:h264",
#            "lang",
#            "quality",
#            "res",
#            "fps",
#            "hdr:12",
#            "acodec:aac",
#        ],
#        "outtmpl": str(folder / "%(title).100s [%(id)s].%(ext)s"),
#        "noplaylist": True,
#        "playlist_items": "1",
#        "quiet": True,
#        "no_warnings": True,
#        "merge_output_format": "mp4",
#        "final_ext": "mp4",
#        "postprocessors": [
#            {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"},
#        ],
#        "ffmpeg_location": _get_ffmpeg_path(),
#
#        # Usa os certificados confiáveis do sistema, como no módulo do YouTube.
#        "compat_opts": {"no-certifi"},
#
#        # O master atual do yt-dlp possui um cliente Vimeo anônimo dedicado.
#        # Forçamos esse cliente para vídeos públicos, evitando o cliente web
#        # que exige conta autenticada.
#        "extractor_args": {
#            "vimeo": {
#                "client": ["macos_basic"],
#                "original_format_policy": ["never"],
#            }
#        },
#
#        # IMPORTANTE:
#        # Não transformamos o link informado em player.vimeo.com.
#        # O próprio extrator Vimeo recebe a URL original e usa o cliente
#        # anônimo macos_basic para vídeos públicos quando disponível.
#
#        "max_filesize": MAX_DOWNLOAD_BYTES,
#        "overwrites": True,
#        "continuedl": True,
#        "retries": 10,
#        "fragment_retries": 10,
#        "extractor_retries": 5,
#        "file_access_retries": 3,
#        "concurrent_fragment_downloads": 4,
#        "socket_timeout": 30,
#    }
#
#    if referer:
#        options["http_headers"] = {
#            "Referer": referer,
#        }
#
#    if progress_callback is not None:
#        options["progress_hooks"] = [progress_callback]
#
#        def postprocessor_hook(data: dict) -> None:
#            progress_callback(
#                {
#                    "status": "postprocessing",
#                    "postprocessor_status": data.get("status"),
#                    "postprocessor": data.get("postprocessor"),
#                }
#            )
#
#        options["postprocessor_hooks"] = [postprocessor_hook]
#
#    return options
#
#
#def _friendly_vimeo_error(exc: Exception, source_url: str) -> RuntimeError:
#    detail = _clean_error_message(str(exc))
#    lowered = detail.lower()
#
#    if "unsupported api client" in lowered:
#        prefix = (
#            "Esta instalação do yt-dlp ainda não possui o cliente macos_basic. "
#            "Instale a branch master indicada no requirements.txt e reinicie o app."
#        )
#    elif "web client only works when logged-in" in lowered:
#        prefix = (
#            "O yt-dlp ainda está usando o cliente web do Vimeo. Isso normalmente indica "
#            "que a versão estável/antiga continua carregada em vez da branch master."
#        )
#    elif "the vimeo extractor only works when logged-in" in lowered:
#        prefix = (
#            "Mesmo com o cliente anônimo atual, o Vimeo recusou esta extração sem login. "
#            "Nesse caso o aplicativo não tenta contornar a exigência de autenticação."
#        )
#    elif (
#        "unsupported url" in lowered
#        or "no video formats" in lowered
#        or "no video could be found" in lowered
#        or "unable to extract" in lowered
#    ):
#        prefix = (
#            "Não encontrei um vídeo Vimeo acessível nessa página. "
#            "Confirme que a página realmente contém um player Vimeo reproduzível."
#        )
#    elif "embed-only" in lowered or "embedding url" in lowered:
#        prefix = (
#            "O Vimeo informou que este vídeo só pode ser aberto a partir da página "
#            "onde foi incorporado. Cole exatamente o link da página do filme."
#        )
#    elif "because of its privacy settings" in lowered:
#        prefix = (
#            "O Vimeo recusou esse contexto de incorporação por causa das configurações "
#            "de privacidade do vídeo. Use a página exata onde o vídeo é reproduzido."
#        )
#    elif (
#        "private" in lowered
#        or "password" in lowered
#        or "forbidden" in lowered
#        or "http error 403" in lowered
#    ):
#        prefix = (
#            "A página ou o vídeo exige uma autorização que o aplicativo não possui, "
#            "ou o Vimeo bloqueou a requisição."
#        )
#    elif "drm" in lowered:
#        prefix = "O vídeo parece usar DRM. Este módulo não remove nem contorna DRM."
#    elif (
#        "certificate_verify_failed" in lowered
#        or "certificate verify failed" in lowered
#        or "self-signed certificate" in lowered
#        or "self signed certificate" in lowered
#    ):
#        prefix = "Falha na validação do certificado HTTPS ao acessar a página ou o Vimeo."
#    elif "ffmpeg" in lowered:
#        prefix = "O FFmpeg não conseguiu finalizar o arquivo."
#    else:
#        prefix = "Não foi possível preparar o vídeo Vimeo dessa página."
#
#    host = urlparse(source_url).hostname or "página informada"
#    return RuntimeError(f"{prefix} Origem: {host}. Detalhe técnico: {detail}")
#
#
#def _download_with_yt_dlp(
#    target_url: str,
#    folder: Path,
#    max_height: int,
#    progress_callback: Callable[[dict], None] | None,
#    referer: str | None = None,
#) -> dict:
#    folder.mkdir(parents=True, exist_ok=True)
#
#    with YoutubeDL(
#        _ydl_options(
#            folder,
#            max_height,
#            progress_callback=progress_callback,
#            referer=referer,
#        )
#    ) as ydl:
#        return ydl.extract_info(target_url, download=True)
#
#
#def _build_attempts(source_url: str) -> list[tuple[str, str | None, str]]:
#    """Usa exatamente a URL informada pelo usuário.
#
#    Não converte vimeo.com/ID para player.vimeo.com, porque alguns vídeos
#    públicos são marcados como embed-only no player direto. Páginas externas
#    continuam sendo entregues ao GenericIE do yt-dlp normalmente.
#    """
#    return [(source_url, None, "URL informada")]
#
#
#def download_vimeo_mp4(
#    url: str,
#    max_height: int = 1080,
#    progress_callback: Callable[[dict], None] | None = None,
#) -> tuple[bytes, str, dict]:
#    """
#    Baixa um vídeo Vimeo público/autorizado.
#
#    `url` pode ser:
#    - uma página normal do Vimeo;
#    - um player.vimeo.com;
#    - uma página externa que contenha um Vimeo incorporado.
#
#    Estratégia atual:
#    - usa exatamente a URL informada pelo usuário;
#    - para Vimeo público, usa o cliente anônimo macos_basic do yt-dlp master;
#    - página externa continua sendo entregue ao GenericIE do yt-dlp;
#    - não tenta contornar senha, login, DRM ou outras restrições de acesso.
#    """
#    if not is_vimeo_url(url):
#        raise ValueError(
#            "Informe uma URL válida iniciada por http:// ou https://. Pode ser o "
#            "link da página do filme ou um link direto do Vimeo."
#        )
#
#    max_height = int(max_height)
#    if max_height not in ALLOWED_HEIGHTS:
#        max_height = 1080
#
#    _ensure_anonymous_vimeo_client()
#
#    source_url = url.strip()
#    attempts = _build_attempts(source_url)
#
#    with tempfile.TemporaryDirectory(prefix="streamlit_vimeo_") as temp_dir:
#        root_folder = Path(temp_dir)
#        info: dict | None = None
#        output_folder: Path | None = None
#        last_exc: Exception | None = None
#
#        for index, (target_url, referer, _description) in enumerate(attempts, start=1):
#            attempt_folder = root_folder / f"attempt_{index}"
#
#            try:
#                info = _download_with_yt_dlp(
#                    target_url,
#                    attempt_folder,
#                    max_height,
#                    progress_callback,
#                    referer=referer,
#                )
#                output_folder = attempt_folder
#                break
#            except Exception as exc:
#                last_exc = exc
#                continue
#
#        if info is None or output_folder is None:
#            if last_exc is None:
#                raise RuntimeError("Não foi possível iniciar a extração do Vimeo.")
#            raise _friendly_vimeo_error(last_exc, source_url) from last_exc
#
#        output_path = _find_output_file(output_folder)
#        size = output_path.stat().st_size
#
#        if size > MAX_DOWNLOAD_BYTES:
#            raise RuntimeError(
#                "O vídeo final ultrapassa o limite de 750 MB deste app."
#            )
#
#        video_info = _primary_info(info)
#        title = _safe_filename(
#            str(video_info.get("title") or info.get("title") or output_path.stem)
#        )
#        filename = f"{title}.mp4"
#
#        metadata = {
#            "title": video_info.get("title") or info.get("title"),
#            "uploader": (
#                video_info.get("uploader")
#                or video_info.get("channel")
#                or info.get("uploader")
#                or info.get("channel")
#            ),
#            "duration": video_info.get("duration") or info.get("duration"),
#            "webpage_url": video_info.get("webpage_url") or source_url,
#            "source_page": source_url,
#            "filesize": size,
#            "height": video_info.get("height") or info.get("height"),
#        }
#
#        return output_path.read_bytes(), filename, metadata
#