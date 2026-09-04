from __future__ import annotations

import streamlit as st

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
from youtube_utils import download_youtube_mp3, download_youtube_mp4, is_youtube_url

st.set_page_config(
    page_title="Utilitários",
    page_icon="🧰",
    layout="centered",
)


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

    st.session_state.setdefault("vimeo_video_bytes", None)
    st.session_state.setdefault("vimeo_video_filename", None)
    st.session_state.setdefault("vimeo_video_meta", None)


def logout() -> None:
    st.session_state.authenticated = False
    st.session_state.auth_email = None

    st.session_state.yt_video_bytes = None
    st.session_state.yt_video_filename = None
    st.session_state.yt_video_meta = None

    st.session_state.vimeo_video_bytes = None
    st.session_state.vimeo_video_filename = None
    st.session_state.vimeo_video_meta = None

    st.rerun()


def first_access_screen() -> None:
    st.title("👤 Criar primeiro acesso")
    st.caption(
        "Ainda não há usuários cadastrados. "
        "Defina agora o primeiro e-mail e a senha do sistema."
    )

    with st.form("first_access_form", clear_on_submit=False):
        email = st.text_input("E-mail", placeholder="seuemail@exemplo.com").strip()
        password = st.text_input("Senha", type="password")
        confirm_password = st.text_input("Confirmar senha", type="password")
        submitted = st.form_submit_button("Criar acesso", width="stretch")

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
    st.title("🔐 Acesso ao sistema")
    st.caption("Informe seu e-mail e senha para continuar.")

    with st.form("login_form", clear_on_submit=False):
        email = st.text_input("E-mail", placeholder="nome@empresa.com")
        password = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar", width="stretch")

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
    col1, col2 = st.columns([4, 1])
    with col1:
        st.title("🧰 Utilitários")
        if is_primary_admin(st.session_state.auth_email):
            st.caption(
                f"Conectado como {st.session_state.auth_email} · Conta-mãe · DEV"
            )
        elif is_dev(st.session_state.auth_email):
            st.caption(
                f"Conectado como {st.session_state.auth_email} · DEV"
            )
        else:
            st.caption(f"Conectado como {st.session_state.auth_email}")
    with col2:
        st.write("")
        st.button("Sair", on_click=logout, width="stretch")


def render_qr_normal() -> None:
    st.subheader("🔳 QR Code normal")
    st.write("Informe o link e clique em Gerar QR Code.")

    with st.form("normal_qr_form"):
        url = st.text_input(
            "Link",
            placeholder="https://exemplo.com/pagina",
        ).strip()
        submitted = st.form_submit_button("Gerar QR Code", width="stretch")

    if submitted:
        if not is_valid_http_url(url):
            st.error("Informe uma URL válida iniciada por http:// ou https://")
        else:
            st.session_state.normal_qr_bytes = make_qr_png(url)
            st.session_state.normal_qr_url = url

    if st.session_state.normal_qr_bytes:
        st.image(
            st.session_state.normal_qr_bytes,
            caption=st.session_state.normal_qr_url,
            width=320,
        )
        st.download_button(
            "Baixar PNG",
            data=st.session_state.normal_qr_bytes,
            file_name="qr_code.png",
            mime="image/png",
            width="stretch",
        )


def render_qr_with_logo() -> None:
    st.subheader("🎨 QR Code com logotipo")
    st.write(
        "Informe o link e envie seu logotipo. A imagem será redimensionada "
        "e colocada no centro do QR Code, mantendo o fundo original."
    )

    with st.form("logo_qr_form"):
        url = st.text_input(
            "Link",
            placeholder="https://exemplo.com/pagina",
            key="logo_qr_input_url",
        ).strip()
        logo_file = st.file_uploader(
            "Logotipo",
            type=["png", "jpg", "jpeg", "svg"],
            help="Formatos aceitos: PNG, JPG, JPEG ou SVG. Máximo de 5 MB.",
        )
        submitted = st.form_submit_button(
            "Gerar QR Code com logotipo",
            width="stretch",
        )

    if submitted:
        if not is_valid_http_url(url):
            st.error("Informe uma URL válida iniciada por http:// ou https://")
        elif logo_file is None:
            st.error("Envie um logotipo PNG, JPG, JPEG ou SVG.")
        else:
            try:
                with st.spinner(
                    "Gerando o QR Code com logotipo..."
                ):
                    st.session_state.logo_qr_bytes = make_qr_with_logo_png(
                        url,
                        logo_file.getvalue(),
                        logo_file.name,
                    )
                st.session_state.logo_qr_url = url
            except (ValueError, RuntimeError) as exc:
                st.session_state.logo_qr_bytes = None
                st.session_state.logo_qr_url = None
                st.error(str(exc))

    if st.session_state.logo_qr_bytes:
        st.image(
            st.session_state.logo_qr_bytes,
            caption=st.session_state.logo_qr_url,
            width=360,
        )
        st.download_button(
            "Baixar PNG",
            data=st.session_state.logo_qr_bytes,
            file_name="qr_code_com_logo.png",
            mime="image/png",
            width="stretch",
        )



def render_youtube_downloader() -> None:
    st.subheader("🎬 Baixar do YouTube")
    st.caption("Use apenas em vídeos que você possui ou tem autorização para baixar.")

    # O formato fica fora do formulário para que a interface seja atualizada
    # imediatamente. Ao selecionar MP3, a qualidade do vídeo desaparece.
    media_type = st.radio(
        "Formato",
        ["Vídeo MP4", "Áudio MP3"],
        horizontal=True,
        key="youtube_media_type",
    )

    with st.form("youtube_form"):
        url = st.text_input(
            "Link do vídeo",
            placeholder="https://www.youtube.com/watch?v=...",
            key="youtube_url",
        ).strip()

        if media_type == "Vídeo MP4":
            quality = st.selectbox(
                "Qualidade máxima do vídeo",
                [360, 480, 720, 1080],
                index=2,
                format_func=lambda value: f"{value}p",
            )
            submit_label = "Preparar vídeo MP4"
        else:
            quality = None
            st.caption("🎵 Para MP3 será utilizado o melhor áudio disponível.")
            submit_label = "Preparar áudio MP3"

        submitted = st.form_submit_button(submit_label, width="stretch")

    if submitted:
        st.session_state.yt_video_bytes = None
        st.session_state.yt_video_filename = None
        st.session_state.yt_video_meta = None

        if not is_youtube_url(url):
            st.error("Informe um link válido do YouTube.")
            return

        progress_bar = st.progress(0, text="Preparando download...")
        status_text = st.empty()

        progress_state = {
            "active_files": {},
            "finished_files": set(),
            "last_value": 0,
        }

        def update_progress(value: int, text: str) -> None:
            value = max(progress_state["last_value"], min(int(value), 100))
            progress_state["last_value"] = value
            progress_bar.progress(value, text=text)

        def progress_callback(data: dict) -> None:
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
                    part_percent = 0.0
                    percent_text = "..."

                # MP3 normalmente possui um único download; MP4 em 1080p
                # normalmente possui vídeo e áudio separados.
                if media_type == "Áudio MP3":
                    value = int(part_percent * 80)
                else:
                    base = min(file_index * 40, 80)
                    value = int(base + (part_percent * 40))
                    value = min(value, 85)

                update_progress(
                    max(value, 1),
                    f"Baixando do YouTube: {percent_text}",
                )

                if downloaded > 0:
                    downloaded_mb = downloaded / (1024 * 1024)
                    if total > 0:
                        total_mb = total / (1024 * 1024)
                        status_text.caption(
                            f"⬇️ Arquivo atual: {downloaded_mb:.1f} MB "
                            f"de {total_mb:.1f} MB"
                        )
                    else:
                        status_text.caption(
                            f"⬇️ Arquivo atual: {downloaded_mb:.1f} MB baixados"
                        )

            elif status == "finished":
                filename = str(data.get("filename") or "arquivo")
                progress_state["finished_files"].add(filename)

                if media_type == "Áudio MP3":
                    value = 80
                else:
                    value = min(40 * len(progress_state["finished_files"]), 85)

                update_progress(value, "Download concluído. Preparando arquivo...")
                status_text.caption("✅ Parte baixada com sucesso.")

            elif status == "postprocessing":
                update_progress(90, "Processando com FFmpeg...")

                if media_type == "Áudio MP3":
                    status_text.caption("🎵 Convertendo o áudio para MP3...")
                else:
                    status_text.caption("🎬 Juntando/processando vídeo e áudio...")

        try:
            if media_type == "Áudio MP3":
                media_bytes, filename, metadata = download_youtube_mp3(
                    url,
                    progress_callback=progress_callback,
                )
            else:
                media_bytes, filename, metadata = download_youtube_mp4(
                    url,
                    int(quality or 720),
                    progress_callback=progress_callback,
                )
        except Exception as exc:
            progress_bar.empty()
            status_text.empty()
            st.error(str(exc))
            return

        update_progress(100, "Arquivo pronto para baixar!")
        status_text.success("✅ Processamento concluído.")

        st.session_state.yt_video_bytes = media_bytes
        st.session_state.yt_video_filename = filename
        st.session_state.yt_video_meta = metadata

    if st.session_state.yt_video_bytes:
        meta = st.session_state.yt_video_meta or {}
        filename = st.session_state.yt_video_filename or "youtube.bin"
        is_mp3 = filename.lower().endswith(".mp3")

        st.divider()
        st.success("Arquivo preparado com sucesso!")

        if meta.get("title"):
            st.write(f"**Título:** {meta['title']}")

        if meta.get("uploader"):
            st.write(f"**Canal:** {meta['uploader']}")

        if meta.get("duration"):
            duration = int(meta["duration"])
            minutes, seconds = divmod(duration, 60)
            hours, minutes = divmod(minutes, 60)

            if hours:
                duration_text = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                duration_text = f"{minutes}:{seconds:02d}"

            st.write(f"**Duração:** {duration_text}")

        if not is_mp3 and meta.get("height"):
            st.write(f"**Resolução:** {meta['height']}p")

        if meta.get("filesize"):
            size_mb = meta["filesize"] / (1024 * 1024)
            st.write(f"**Tamanho:** {size_mb:.1f} MB")

        st.download_button(
            "⬇️ Baixar MP3" if is_mp3 else "⬇️ Baixar MP4",
            data=st.session_state.yt_video_bytes,
            file_name=filename,
            mime="audio/mpeg" if is_mp3 else "video/mp4",
            width="stretch",
        )

    st.info(
        "O YouTube altera frequentemente os mecanismos de acesso aos vídeos. "
        "Alguns conteúdos podem exigir autenticação ou validações adicionais."
    )

def render_vimeo_maintenance() -> None:
    st.subheader("🎥 Vimeo — Em Manutenção")
    st.warning(
        "🚧 O módulo de download do Vimeo está temporariamente desativado e em manutenção."
    )
    st.info(
        "Estamos aguardando uma solução estável para o acesso aos vídeos do Vimeo. "
        "As demais ferramentas do sistema continuam funcionando normalmente."
    )


def render_access_manager() -> None:
    actor_email = st.session_state.auth_email

    # A interface e o banco verificam a permissão. Mesmo que alguém tente
    # chamar esta função manualmente, uma conta dev = 0 não consegue operar.
    if not is_dev(actor_email):
        st.error("Esta conta não possui permissão para gerenciar acessos.")
        return

    actor_is_mother = is_primary_admin(actor_email)

    st.subheader("👥 Gerenciar acessos")

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
        submitted = st.form_submit_button("Salvar usuário", width="stretch")

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
                    st.markdown(f"👑 **{employee_email}**")
                    st.caption("Conta-mãe · DEV = 1 permanente")
                elif employee_dev:
                    st.markdown(f"🛠️ **{employee_email}**")
                    st.caption("DEV = 1 · pode gerenciar acessos")
                else:
                    st.markdown(f"👤 **{employee_email}**")
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
                        "🔒 Esta conta só pode ter a senha alterada pela própria conta-mãe."
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
        "Baixar vídeo do YouTube",
        "Vimeo (Em Manutenção)",
    ]

    # O módulo simplesmente não existe na navegação de quem tem dev = 0.
    if is_dev(st.session_state.auth_email):
        modules.append("Gerenciar acessos")

    module = st.radio(
        "Módulo",
        modules,
        horizontal=True,
        label_visibility="collapsed",
    )

    st.divider()

    if module == "QR Code normal":
        render_qr_normal()
    elif module == "QR Code com logotipo":
        render_qr_with_logo()
    elif module == "Baixar vídeo do YouTube":
        render_youtube_downloader()
    elif module == "Vimeo (Em Manutenção)":
        render_vimeo_maintenance()
    elif module == "Gerenciar acessos":
        render_access_manager()


if __name__ == "__main__":
    main()