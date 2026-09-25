from __future__ import annotations

import streamlit as st
from pathlib import Path
from html import escape
import base64
from database import (
    admin_delete_employee,
    admin_set_employee_dev,
    admin_upsert_employee,
    authenticate,
    count_employees,
    create_first_admin,
    employee_exists,
    init_db,
    is_dev,
    is_primary_admin,
    list_employees,
    register_login_attempt,
    seed_users,
)
from qr_utils import is_valid_http_url, make_qr_png, make_qr_with_logo_png
from youtube_utils import (
    cleanup_youtube_output,
    download_youtube_mp3,
    download_youtube_mp4,
    is_youtube_url,
)
from social_media_utils import (
    download_facebook_mp3,
    download_facebook_mp4,
    download_instagram_mp3,
    download_instagram_mp4,
    is_facebook_url,
    is_instagram_url,
)

BASE_DIR = Path(__file__).resolve().parent
LOGO_PATH = BASE_DIR / "img" / "logo.png"

st.set_page_config(
    page_title="Inova Generator",
    page_icon=str(LOGO_PATH) if LOGO_PATH.exists() else None,
    layout="centered",
)

def logo_heading(text: str) -> None:
    if LOGO_PATH.exists():
        logo_base64 = base64.b64encode(LOGO_PATH.read_bytes()).decode("utf-8")

        st.markdown(
            f"""
            <div style="
                display: flex;
                align-items: center;
                gap: 10px;
                margin: 0.1rem 0 0.6rem 0;
            ">
                <img
                    src="data:image/png;base64,{logo_base64}"
                    style="
                        width: 100px;
                        height: 100px;
                        object-fit: contain;
                    "
                >
                <span style="
                    font-size: 2rem;
                    font-weight: 700;
                    line-height: 1.2;
                ">
                    {escape(text)}
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        fa_heading("fa-solid fa-user-lock", text, level=1)

def inject_global_styles() -> None:
    """Carrega Font Awesome e o estilo visual base do Inova Generator."""
    st.markdown(
        """
        <link rel="stylesheet"
              href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.7.2/css/all.min.css">
        <style>
            .inova-heading {
                display: flex;
                align-items: center;
                gap: .55rem;
                margin: .1rem 0 .6rem 0;
                font-weight: 700;
                line-height: 1.2;
            }
            .inova-heading.h1 { font-size: 2rem; }
            .inova-heading.h2 { font-size: 1.55rem; }
            .inova-heading i { width: 1.55em; text-align: center; }
            .inova-brand {
                display: flex;
                align-items: center;
                min-height: 76px;
            }
            .inova-brand-title {
                font-size: 2rem;
                font-weight: 800;
                margin: 0;
                line-height: 1.1;
            }
            .inova-user-row {
                display: flex;
                align-items: center;
                gap: .45rem;
                margin-bottom: .25rem;
            }
            .inova-user-row i { width: 1.2rem; text-align: center; }

            /* Ícones Font Awesome na navegação principal. O key do widget
               vira a classe CSS st-key-selected_module no Streamlit. */
            .st-key-selected_module div[role="radiogroup"] > label p::before {
                display: inline-block;
                width: 1.35rem;
                margin-right: .30rem;
                text-align: center;
            }
            .st-key-selected_module div[role="radiogroup"] > label:nth-child(1) p::before,
            .st-key-selected_module div[role="radiogroup"] > label:nth-child(2) p::before {
                content: "\\f029";
                font-family: "Font Awesome 6 Free";
                font-weight: 900;
            }
            .st-key-selected_module div[role="radiogroup"] > label:nth-child(3) p::before {
                content: "\\f167";
                font-family: "Font Awesome 6 Brands";
                font-weight: 400;
            }
            .st-key-selected_module div[role="radiogroup"] > label:nth-child(4) p::before {
                content: "\\f16d";
                font-family: "Font Awesome 6 Brands";
                font-weight: 400;
            }
            .st-key-selected_module div[role="radiogroup"] > label:nth-child(5) p::before {
                content: "\\f09a";
                font-family: "Font Awesome 6 Brands";
                font-weight: 400;
            }
            .st-key-selected_module div[role="radiogroup"] > label:nth-child(6) p::before {
                content: "\\f0c0";
                font-family: "Font Awesome 6 Free";
                font-weight: 900;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def fa_heading(icon_class: str, text: str, level: int = 2) -> None:
    css_level = "h1" if level == 1 else "h2"
    st.markdown(
        f'<div class="inova-heading {css_level}"><i class="{escape(icon_class)}"></i><span>{escape(text)}</span></div>',
        unsafe_allow_html=True,
    )


def fa_user_line(icon_class: str, text: str) -> None:
    st.markdown(
        f'<div class="inova-user-row"><i class="{escape(icon_class)}"></i><strong>{escape(text)}</strong></div>',
        unsafe_allow_html=True,
    )


def _make_deferred_file_reader(path: str | Path):
    """Abre o arquivo somente quando o usuário clicar em baixar."""
    media_path = Path(path)

    def _open_file():
        if not media_path.exists():
            raise FileNotFoundError("O arquivo temporário expirou. Prepare o download novamente.")
        return media_path.open("rb")

    return _open_file


def _cleanup_session_media(value) -> None:
    """Limpa apenas arquivos temporários criados pelo downloader do YouTube."""
    if isinstance(value, (str, Path)):
        cleanup_youtube_output(value)


def initialize_app() -> None:
    init_db()

    # No Streamlit Community Cloud o SQLite local pode ser recriado após reboot.
    # Os Secrets permitem repovoar TB_EMPLOYEE sem deixar senhas no repositório.
    try:
        configured_users = st.secrets.get("users", [])
        if configured_users:
            seed_users(configured_users)
    except FileNotFoundError:
        pass

    st.session_state.setdefault("authenticated", False)
    st.session_state.setdefault("auth_email", None)

    st.session_state.setdefault("normal_qr_bytes", None)
    st.session_state.setdefault("normal_qr_url", None)
    st.session_state.setdefault("logo_qr_bytes", None)
    st.session_state.setdefault("logo_qr_url", None)

    st.session_state.setdefault("yt_video_bytes", None)
    st.session_state.setdefault("yt_video_filename", None)
    st.session_state.setdefault("yt_video_meta", None)

    st.session_state.setdefault("instagram_video_bytes", None)
    st.session_state.setdefault("instagram_video_filename", None)
    st.session_state.setdefault("instagram_video_meta", None)

    st.session_state.setdefault("facebook_video_bytes", None)
    st.session_state.setdefault("facebook_video_filename", None)
    st.session_state.setdefault("facebook_video_meta", None)

    st.session_state.setdefault("processing_locked", False)
    st.session_state.setdefault("processing_owner", None)
    st.session_state.setdefault("processing_jobs", {})


def begin_processing(owner: str, payload: dict | None = None) -> None:
    """Agenda uma tarefa e bloqueia a navegação antes do processamento pesado."""
    st.session_state.processing_locked = True
    st.session_state.processing_owner = owner
    if payload is not None:
        jobs = dict(st.session_state.get("processing_jobs", {}))
        jobs[owner] = payload
        st.session_state.processing_jobs = jobs


def get_processing_job(owner: str) -> dict | None:
    return st.session_state.get("processing_jobs", {}).get(owner)


def end_processing(owner: str | None = None) -> None:
    current_owner = st.session_state.get("processing_owner")
    if owner is not None and current_owner not in {None, owner}:
        return
    jobs = dict(st.session_state.get("processing_jobs", {}))
    if owner is not None:
        jobs.pop(owner, None)
    elif current_owner is not None:
        jobs.pop(current_owner, None)
    st.session_state.processing_jobs = jobs
    st.session_state.processing_locked = False
    st.session_state.processing_owner = None


def release_all_controls() -> None:
    """Garante que toda a interface volte a ficar disponível após um download."""
    st.session_state.processing_locked = False
    st.session_state.processing_owner = None
    st.session_state.processing_jobs = {}


def cancel_processing(owner: str | None = None) -> None:
    """Cancela a tarefa atual e remove a fila pendente correspondente."""
    current_owner = st.session_state.get("processing_owner")
    target = owner or current_owner
    if owner is None or current_owner == owner:
        jobs = dict(st.session_state.get("processing_jobs", {}))
        if target is not None:
            jobs.pop(target, None)
        st.session_state.processing_jobs = jobs
        st.session_state.processing_locked = False
        st.session_state.processing_owner = None


def is_processing() -> bool:
    return bool(st.session_state.get("processing_locked", False))


def logout() -> None:
    st.session_state.authenticated = False
    st.session_state.auth_email = None

    _cleanup_session_media(st.session_state.get("yt_video_bytes"))
    st.session_state.yt_video_bytes = None
    st.session_state.yt_video_filename = None
    st.session_state.yt_video_meta = None

    st.session_state.instagram_video_bytes = None
    st.session_state.instagram_video_filename = None
    st.session_state.instagram_video_meta = None
    st.session_state.facebook_video_bytes = None
    st.session_state.facebook_video_filename = None
    st.session_state.facebook_video_meta = None
    st.session_state.processing_locked = False
    st.session_state.processing_owner = None
    st.session_state.processing_jobs = {}

    st.rerun()


def first_access_screen() -> None:
    fa_heading("fa-solid fa-user-plus", "Criar primeiro acesso", level=1)
    st.caption(
        "Ainda não há usuários cadastrados. "
        "Defina agora o primeiro e-mail e a senha do sistema."
    )

    with st.form("first_access_form", clear_on_submit=False):
        email = st.text_input("E-mail", placeholder="seuemail@exemplo.com").strip()
        password = st.text_input("Senha", type="password")
        confirm_password = st.text_input("Confirmar senha", type="password")
        submitted = st.form_submit_button("Criar acesso", icon=":material/person_add:", width="stretch")

    if not submitted:
        return

    if not email or "@" not in email:
        st.error("Informe um e-mail válido.")
        return

    if len(password) < 6:
        st.error("A senha deve ter pelo menos 6 caracteres.")
        return

    if password != confirm_password:
        st.error("As senhas não coincidem.")
        return

    try:
        create_first_admin(email, password)
    except (ValueError, PermissionError) as exc:
        st.error(str(exc))
        return

    st.success("Primeiro acesso criado com sucesso. Agora você já pode entrar.")
    st.rerun()


def login_screen() -> None:
    logo_heading("Acesso ao sistema")
    st.caption("Informe seu e-mail e senha para continuar.")

    with st.form("login_form", clear_on_submit=False):
        email = st.text_input("E-mail", placeholder="nome@empresa.com")
        password = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar", icon=":material/login:", width="stretch")

    if submitted:
        ok = authenticate(email, password)
        register_login_attempt(email, ok)

        if ok:
            st.session_state.authenticated = True
            st.session_state.auth_email = email.strip().lower()
            st.rerun()
        else:
            st.error("E-mail ou senha inválidos.")


def render_header() -> None:
    logo_col, title_col, action_col = st.columns([1, 4, 1])
    with logo_col:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), width=82)
        else:
            st.markdown(
                '<div class="inova-brand"><i class="fa-solid fa-wand-magic-sparkles fa-2x"></i></div>',
                unsafe_allow_html=True,
            )
    with title_col:
        st.markdown(
            '<div class="inova-brand"><div class="inova-brand-title">Inova Generator</div></div>',
            unsafe_allow_html=True,
        )
        if is_primary_admin(st.session_state.auth_email):
            st.caption(
                f"Conectado como {st.session_state.auth_email} · Conta-mãe · DEV"
            )
        elif is_dev(st.session_state.auth_email):
            st.caption(f"Conectado como {st.session_state.auth_email} · DEV")
        else:
            st.caption(f"Conectado como {st.session_state.auth_email}")
    with action_col:
        st.write("")
        st.button(
            "Sair",
            icon=":material/logout:",
            on_click=logout,
            width="stretch",
            disabled=is_processing(),
        )


def render_qr_normal() -> None:
    owner = "qr_normal"
    fa_heading("fa-solid fa-qrcode", "QR Code normal")
    st.write("Informe o link e clique em Gerar QR Code.")
    busy = is_processing()
    active = busy and st.session_state.get("processing_owner") == owner

    with st.form("normal_qr_form"):
        url = st.text_input(
            "Link",
            placeholder="https://exemplo.com/pagina",
            key="normal_qr_input_url",
            disabled=busy,
        ).strip()
        action_col, cancel_col = st.columns([3, 1])
        with action_col:
            submitted = st.form_submit_button(
                "Gerar QR Code",
                icon=":material/qr_code_2:",
                width="stretch",
                disabled=busy,
            )
        with cancel_col:
            st.form_submit_button(
                "Cancelar",
                icon=":material/cancel:",
                width="stretch",
                disabled=not active,
                on_click=cancel_processing,
                args=(owner,),
            )

    if submitted:
        begin_processing(owner, {"url": url})
        st.rerun()

    job = get_processing_job(owner)
    if active and job:
        try:
            job_url = str(job.get("url") or "").strip()
            if not is_valid_http_url(job_url):
                st.error("Informe uma URL válida iniciada por http:// ou https://")
            else:
                st.session_state.normal_qr_bytes = make_qr_png(job_url)
                st.session_state.normal_qr_url = job_url
        finally:
            end_processing(owner)
            st.rerun()

    if st.session_state.normal_qr_bytes:
        st.image(
            st.session_state.normal_qr_bytes,
            caption=st.session_state.normal_qr_url,
            width=320,
        )
        st.download_button(
            "Baixar PNG",
            icon=":material/download:",
            on_click=release_all_controls,
            data=st.session_state.normal_qr_bytes,
            file_name="qr_code.png",
            mime="image/png",
            width="stretch",
        )


def render_qr_with_logo() -> None:
    owner = "qr_logo"
    fa_heading("fa-solid fa-qrcode", "QR Code com logotipo")
    st.write(
        "Informe o link e envie seu logotipo. A imagem será redimensionada "
        "e colocada no centro do QR Code, mantendo o fundo original."
    )
    busy = is_processing()
    active = busy and st.session_state.get("processing_owner") == owner

    with st.form("logo_qr_form"):
        url = st.text_input(
            "Link",
            placeholder="https://exemplo.com/pagina",
            key="logo_qr_input_url",
            disabled=busy,
        ).strip()
        logo_file = st.file_uploader(
            "Logotipo",
            type=["png", "jpg", "jpeg", "svg"],
            help="Formatos aceitos: PNG, JPG, JPEG ou SVG. Máximo de 5 MB.",
            key="logo_qr_file",
            disabled=busy,
        )
        action_col, cancel_col = st.columns([3, 1])
        with action_col:
            submitted = st.form_submit_button(
                "Gerar QR Code com logotipo",
                icon=":material/qr_code_2:",
                width="stretch",
                disabled=busy,
            )
        with cancel_col:
            st.form_submit_button(
                "Cancelar",
                icon=":material/cancel:",
                width="stretch",
                disabled=not active,
                on_click=cancel_processing,
                args=(owner,),
            )

    if submitted:
        payload = {"url": url, "logo_bytes": None, "logo_name": None}
        if logo_file is not None:
            payload["logo_bytes"] = logo_file.getvalue()
            payload["logo_name"] = logo_file.name
        begin_processing(owner, payload)
        st.rerun()

    job = get_processing_job(owner)
    if active and job:
        try:
            job_url = str(job.get("url") or "").strip()
            logo_bytes = job.get("logo_bytes")
            logo_name = job.get("logo_name")
            if not is_valid_http_url(job_url):
                st.error("Informe uma URL válida iniciada por http:// ou https://")
            elif not logo_bytes or not logo_name:
                st.error("Envie um logotipo PNG, JPG, JPEG ou SVG.")
            else:
                try:
                    with st.spinner("Gerando o QR Code com logotipo..."):
                        st.session_state.logo_qr_bytes = make_qr_with_logo_png(
                            job_url, logo_bytes, logo_name
                        )
                    st.session_state.logo_qr_url = job_url
                except (ValueError, RuntimeError) as exc:
                    st.session_state.logo_qr_bytes = None
                    st.session_state.logo_qr_url = None
                    st.error(str(exc))
        finally:
            end_processing(owner)
            st.rerun()

    if st.session_state.logo_qr_bytes:
        st.image(
            st.session_state.logo_qr_bytes,
            caption=st.session_state.logo_qr_url,
            width=360,
        )
        st.download_button(
            "Baixar PNG",
            icon=":material/download:",
            on_click=release_all_controls,
            data=st.session_state.logo_qr_bytes,
            file_name="qr_code_com_logo.png",
            mime="image/png",
            width="stretch",
        )


def _render_media_downloader(
    *,
    platform_key: str,
    platform_label: str,
    icon: str,
    placeholder: str,
    url_validator,
    download_mp4,
    download_mp3,
) -> None:
    fa_heading(icon, f"Baixar do {platform_label}")
    st.caption("Use apenas em vídeos que você possui ou tem autorização para baixar.")

    busy = is_processing()
    active = busy and st.session_state.get("processing_owner") == platform_key
    state_prefix = platform_key

    media_type = st.radio(
        "Formato",
        ["Vídeo MP4", "Áudio MP3"],
        horizontal=True,
        key=f"{platform_key}_media_type",
        disabled=busy,
    )

    with st.form(f"{platform_key}_form"):
        url = st.text_input(
            "Link do vídeo",
            placeholder=placeholder,
            key=f"{platform_key}_url",
            disabled=busy,
        ).strip()

        if media_type == "Vídeo MP4":
            quality = st.selectbox(
                "Qualidade máxima do vídeo",
                [360, 480, 720, 1080],
                index=2,
                format_func=lambda value: f"{value}p",
                key=f"{platform_key}_quality",
                disabled=busy,
            )
            submit_label = "Preparar vídeo MP4"
        else:
            quality = None
            st.caption("Para MP3 será utilizado o melhor áudio disponível.")
            submit_label = "Preparar áudio MP3"

        action_col, cancel_col = st.columns([3, 1])
        with action_col:
            submitted = st.form_submit_button(
                submit_label,
                icon=":material/video_file:" if media_type == "Vídeo MP4" else ":material/audio_file:",
                width="stretch",
                disabled=busy,
            )
        with cancel_col:
            st.form_submit_button(
                "Cancelar",
                icon=":material/cancel:",
                width="stretch",
                disabled=not active,
                on_click=cancel_processing,
                args=(platform_key,),
            )

    if submitted:
        begin_processing(
            platform_key,
            {
                "url": url,
                "media_type": media_type,
                "quality": int(quality or 720),
            },
        )
        st.rerun()

    job = get_processing_job(platform_key)
    if active and job:
        bytes_key = f"{state_prefix}_video_bytes"
        filename_key = f"{state_prefix}_video_filename"
        meta_key = f"{state_prefix}_video_meta"
        if platform_key == "yt":
            _cleanup_session_media(st.session_state.get(bytes_key))
        st.session_state[bytes_key] = None
        st.session_state[filename_key] = None
        st.session_state[meta_key] = None

        job_url = str(job.get("url") or "").strip()
        job_media_type = str(job.get("media_type") or "Vídeo MP4")
        job_quality = int(job.get("quality") or 720)

        if not url_validator(job_url):
            st.error(f"Informe um link válido do {platform_label}.")
            end_processing(platform_key)
            st.rerun()

        progress_bar = st.progress(3, text=f"Validando link do {platform_label}...")
        status_text = st.empty()
        status_text.caption("Preparando informações do vídeo...")
        progress_state = {
            "active_files": {},
            "finished_files": set(),
            "last_value": 3,
        }

        def update_progress(value: int, text: str) -> None:
            value = max(progress_state["last_value"], min(int(value), 100))
            progress_state["last_value"] = value
            progress_bar.progress(value, text=text)

        def progress_callback(data: dict) -> None:
            if (
                not st.session_state.get("processing_locked", False)
                or st.session_state.get("processing_owner") != platform_key
            ):
                raise RuntimeError("__PROCESSING_CANCELLED__")

            status = data.get("status")
            if status == "downloading":
                filename = str(data.get("filename") or "arquivo")
                if filename not in progress_state["active_files"]:
                    progress_state["active_files"][filename] = len(
                        progress_state["active_files"]
                    )
                file_index = progress_state["active_files"][filename]
                downloaded = data.get("downloaded_bytes") or 0
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0

                if total > 0:
                    part_percent = min(downloaded / total, 1.0)
                    percent_text = f"{part_percent * 100:.1f}%"
                else:
                    # Mesmo sem Content-Length, a barra sai do estado inicial
                    # e o usuário vê que o fluxo realmente começou.
                    part_percent = 0.0
                    percent_text = "em andamento"

                if job_media_type == "Áudio MP3":
                    value = max(8, int(part_percent * 80))
                else:
                    base = min(file_index * 40, 80)
                    value = max(8, min(int(base + (part_percent * 40)), 85))

                update_progress(value, f"Baixando do {platform_label}: {percent_text}")
                if downloaded > 0:
                    downloaded_mb = downloaded / (1024 * 1024)
                    if total > 0:
                        total_mb = total / (1024 * 1024)
                        status_text.caption(
                            f"Arquivo atual: {downloaded_mb:.1f} MB de {total_mb:.1f} MB"
                        )
                    else:
                        status_text.caption(
                            f"Arquivo atual: {downloaded_mb:.1f} MB baixados"
                        )

            elif status == "finished":
                filename = str(data.get("filename") or "arquivo")
                progress_state["finished_files"].add(filename)
                value = 80 if job_media_type == "Áudio MP3" else min(
                    40 * len(progress_state["finished_files"]), 85
                )
                update_progress(max(value, 80), "Download concluído. Preparando arquivo...")
                status_text.caption("Parte baixada com sucesso.")

            elif status == "postprocessing":
                update_progress(90, "Processando com FFmpeg...")
                status_text.caption(
                    "Convertendo o áudio para MP3..."
                    if job_media_type == "Áudio MP3"
                    else "Juntando/processando vídeo e áudio..."
                )

        try:
            update_progress(5, f"Obtendo informações do {platform_label}...")
            if job_media_type == "Áudio MP3":
                media_bytes, filename, metadata = download_mp3(
                    job_url, progress_callback=progress_callback
                )
            else:
                media_bytes, filename, metadata = download_mp4(
                    job_url, job_quality, progress_callback=progress_callback
                )
        except Exception as exc:
            progress_bar.empty()
            status_text.empty()
            if "__PROCESSING_CANCELLED__" in str(exc):
                st.info("Processamento cancelado.")
            else:
                st.error(str(exc))
            end_processing(platform_key)
            return

        update_progress(100, "Arquivo pronto para baixar!")
        status_text.success("Processamento concluído.")
        st.session_state[bytes_key] = media_bytes
        st.session_state[filename_key] = filename
        st.session_state[meta_key] = metadata
        end_processing(platform_key)

    media_data = st.session_state.get(f"{state_prefix}_video_bytes")
    if media_data:
        meta = st.session_state.get(f"{state_prefix}_video_meta") or {}
        filename = st.session_state.get(f"{state_prefix}_video_filename") or f"{platform_key}.bin"
        is_mp3 = filename.lower().endswith(".mp3")

        st.divider()
        st.success("Arquivo preparado com sucesso!")
        if meta.get("title"):
            st.write(f"**Título:** {meta['title']}")
        if meta.get("uploader"):
            st.write(f"**Canal/Perfil:** {meta['uploader']}")
        if meta.get("duration"):
            duration = int(meta["duration"])
            minutes, seconds = divmod(duration, 60)
            hours, minutes = divmod(minutes, 60)
            duration_text = (
                f"{hours}:{minutes:02d}:{seconds:02d}"
                if hours
                else f"{minutes}:{seconds:02d}"
            )
            st.write(f"**Duração:** {duration_text}")
        if not is_mp3 and meta.get("height"):
            st.write(f"**Resolução:** {meta['height']}p")
        if meta.get("filesize"):
            size_mb = meta["filesize"] / (1024 * 1024)
            st.write(f"**Tamanho:** {size_mb:.1f} MB")

        if isinstance(media_data, (str, Path)):
            media_path = Path(media_data)
            if not media_path.exists():
                st.warning("O arquivo temporário expirou. Prepare o download novamente.")
                _cleanup_session_media(media_data)
                st.session_state[f"{state_prefix}_video_bytes"] = None
                return
            download_data = _make_deferred_file_reader(media_path)
            download_click = "ignore"
        else:
            # Instagram/Facebook ainda retornam bytes pelo yt-dlp.
            download_data = media_data
            download_click = release_all_controls

        st.download_button(
            "Baixar MP3" if is_mp3 else "Baixar MP4",
            icon=":material/download:",
            on_click=download_click,
            data=download_data,
            file_name=filename,
            mime="audio/mpeg" if is_mp3 else "video/mp4",
            width="stretch",
        )

    st.info(
        f"O {platform_label} pode exigir login/cookies para conteúdos privados, "
        "restritos ou sujeitos a verificações da própria plataforma. "
        "Vídeos MP4 podem ter até 2 GB."
    )


def render_youtube_downloader() -> None:
    _render_media_downloader(
        platform_key="yt",
        platform_label="YouTube",
        icon="fa-brands fa-youtube",
        placeholder="https://www.youtube.com/watch?v=...",
        url_validator=is_youtube_url,
        download_mp4=download_youtube_mp4,
        download_mp3=download_youtube_mp3,
    )


def render_instagram_downloader() -> None:
    _render_media_downloader(
        platform_key="instagram",
        platform_label="Instagram",
        icon="fa-brands fa-instagram",
        placeholder="https://www.instagram.com/reel/...",
        url_validator=is_instagram_url,
        download_mp4=download_instagram_mp4,
        download_mp3=download_instagram_mp3,
    )


def render_facebook_downloader() -> None:
    _render_media_downloader(
        platform_key="facebook",
        platform_label="Facebook",
        icon="fa-brands fa-facebook",
        placeholder="https://www.facebook.com/.../videos/...",
        url_validator=is_facebook_url,
        download_mp4=download_facebook_mp4,
        download_mp3=download_facebook_mp3,
    )

def render_access_manager() -> None:
    actor_email = st.session_state.auth_email

    # A interface e o banco verificam a permissão. Mesmo que alguém tente
    # chamar esta função manualmente, uma conta dev = 0 não consegue operar.
    if not is_dev(actor_email):
        st.error("Esta conta não possui permissão para gerenciar acessos.")
        return

    actor_is_mother = is_primary_admin(actor_email)

    fa_heading("fa-solid fa-users-gear", "Gerenciar acessos")

    if actor_is_mother:
        st.success(
            "Você está na conta-mãe. Ela é DEV permanente, não pode ser "
            "excluída e somente ela mesma pode alterar a própria senha."
        )
        st.caption(
            "Somente a conta-mãe pode conceder ou retirar a permissão DEV "
            "das demais contas."
        )
    else:
        st.info(
            "Sua conta possui DEV = 1. Você pode criar usuários, alterar "
            "senhas e excluir outras contas, mas não pode alterar nem "
            "excluir a conta-mãe."
        )

    st.write(
        "Para criar um usuário ou trocar sua senha, informe o e-mail e a nova senha. "
        "Usuários novos são criados com DEV = 0 por padrão."
    )

    # ========================================================
    # CRIAR USUÁRIO / ALTERAR SENHA
    # ========================================================
    with st.form("employee_form", clear_on_submit=True):
        email = st.text_input(
            "E-mail do usuário",
            placeholder="usuario@exemplo.com",
        ).strip()
        password = st.text_input("Nova senha", type="password")
        confirm_password = st.text_input("Confirmar senha", type="password")
        submitted = st.form_submit_button("Salvar usuário", icon=":material/save:", width="stretch")

    if submitted:
        if not email or "@" not in email:
            st.error("Informe um e-mail válido.")
        elif len(password) < 6:
            st.error("A senha deve ter pelo menos 6 caracteres.")
        elif password != confirm_password:
            st.error("As senhas não coincidem.")
        else:
            try:
                admin_upsert_employee(actor_email, email, password)
                st.success(f"Acesso de {email.lower()} salvo com sucesso.")
                st.rerun()
            except (ValueError, PermissionError) as exc:
                st.error(str(exc))

    # ========================================================
    # LISTA E PERMISSÕES
    # ========================================================
    employees = list_employees()
    st.divider()
    st.write(f"**Usuários cadastrados: {len(employees)}**")

    if not employees:
        st.info("Nenhum usuário cadastrado.")
        return

    for employee in employees:
        employee_email = employee["email"]
        employee_dev = int(employee.get("dev", 0)) == 1
        employee_is_mother = bool(employee.get("is_mother"))
        employee_is_current = employee_email == actor_email

        with st.container(border=True):
            col_info, col_role = st.columns([3, 2])

            with col_info:
                if employee_is_mother:
                    fa_user_line("fa-solid fa-crown", employee_email)
                    st.caption("Conta-mãe · DEV = 1 permanente")
                elif employee_dev:
                    fa_user_line("fa-solid fa-screwdriver-wrench", employee_email)
                    st.caption("DEV = 1 · pode gerenciar acessos")
                else:
                    fa_user_line("fa-solid fa-user", employee_email)
                    st.caption("DEV = 0 · usuário comum")

                if employee_is_current:
                    st.caption("Sessão atual")

            with col_role:
                # Só a conta-mãe escolhe quem recebe DEV.
                if employee_is_mother:
                    st.checkbox(
                        "Permissão DEV",
                        value=True,
                        disabled=True,
                        key=f"mother_dev_{employee_email}",
                    )
                elif actor_is_mother:
                    desired_dev = st.checkbox(
                        "Permissão DEV",
                        value=employee_dev,
                        key=f"dev_toggle_{employee_email}",
                    )
                    if desired_dev != employee_dev:
                        if st.button(
                            "Salvar permissão",
                            icon=":material/admin_panel_settings:",
                            key=f"save_dev_{employee_email}",
                            width="stretch",
                        ):
                            try:
                                admin_set_employee_dev(
                                    actor_email,
                                    employee_email,
                                    desired_dev,
                                )
                                st.success(
                                    f"Permissão DEV de {employee_email} atualizada."
                                )
                                st.rerun()
                            except (ValueError, PermissionError) as exc:
                                st.error(str(exc))
                else:
                    st.checkbox(
                        "Permissão DEV",
                        value=employee_dev,
                        disabled=True,
                        key=f"readonly_dev_{employee_email}",
                    )

            st.divider()

            action_col1, action_col2 = st.columns([3, 1])
            with action_col1:
                if employee_is_mother and not actor_is_mother:
                    st.caption(
                        "Esta conta só pode ter a senha alterada pela própria conta-mãe."
                    )
                elif employee_is_mother and actor_is_mother:
                    st.caption(
                        "Para alterar sua senha, use o formulário acima com este mesmo e-mail."
                    )
                else:
                    st.caption(
                        "Para alterar a senha, use o formulário acima com este e-mail."
                    )

            with action_col2:
                delete_disabled = employee_is_mother or employee_is_current
                delete_help = None
                if employee_is_mother:
                    delete_help = "A conta-mãe nunca pode ser excluída."
                elif employee_is_current:
                    delete_help = "Você não pode excluir a conta da sessão atual."

                if st.button(
                    "Excluir",
                    icon=":material/delete:",
                    key=f"delete_employee_{employee_email}",
                    disabled=delete_disabled,
                    help=delete_help,
                    width="stretch",
                ):
                    try:
                        if admin_delete_employee(actor_email, employee_email):
                            st.success(f"Usuário {employee_email} excluído.")
                            st.rerun()
                    except PermissionError as exc:
                        st.error(str(exc))

    st.caption(
        "Regras: DEV = 0 não vê o módulo Gerenciar acessos. DEV = 1 pode "
        "criar, editar e excluir contas permitidas. A conta-mãe é o primeiro "
        "acesso, permanece DEV = 1, só pode ser editada por ela mesma e nunca "
        "pode ser removida."
    )


def main() -> None:
    initialize_app()
    inject_global_styles()

    if not st.session_state.authenticated:
        if count_employees() == 0:
            first_access_screen()
        else:
            login_screen()
        return

    # Se a conta tiver sido removida por outro DEV enquanto esta sessão estava
    # aberta, encerra o acesso no próximo rerun.
    if not employee_exists(st.session_state.auth_email):
        st.session_state.authenticated = False
        st.session_state.auth_email = None
        st.warning("Esta conta não existe mais. Faça login novamente.")
        st.rerun()

    render_header()

    modules = [
        "QR Code normal",
        "QR Code com logotipo",
        "Baixar do YouTube",
        "Baixar do Instagram",
        "Baixar do Facebook",
    ]

    # O módulo simplesmente não existe na navegação de quem tem dev = 0.
    if is_dev(st.session_state.auth_email):
        modules.append("Gerenciar acessos")

    module = st.radio(
        "Módulo",
        modules,
        horizontal=True,
        label_visibility="collapsed",
        key="selected_module",
        disabled=is_processing(),
    )

    if is_processing():
        st.warning(
            "Processamento em andamento. Os módulos e ações ficam bloqueados "
            "até concluir ou você cancelar pelo botão ao lado de Processar/Gerar."
        )

    st.divider()

    if module == "QR Code normal":
        render_qr_normal()
    elif module == "QR Code com logotipo":
        render_qr_with_logo()
    elif module == "Baixar do YouTube":
        render_youtube_downloader()
    elif module == "Baixar do Instagram":
        render_instagram_downloader()
    elif module == "Baixar do Facebook":
        render_facebook_downloader()
    elif module == "Gerenciar acessos":
        render_access_manager()


if __name__ == "__main__":
    main()