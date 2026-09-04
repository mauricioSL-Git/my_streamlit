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
from qr_utils import is_valid_http_url, make_qr_png
from vimeo_utils import download_vimeo_mp4, is_vimeo_url
from youtube_utils import download_youtube_mp4, is_youtube_url

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

    st.session_state.setdefault("static_qr_bytes", None)
    st.session_state.setdefault("static_qr_url", None)
    st.session_state.setdefault("static_qr_filename", "qr_code_estatico")

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


def render_qr_instant() -> None:
    st.subheader("⚡ QR Code instantâneo")
    st.write("Cole uma URL. O QR Code é atualizado automaticamente conforme o campo muda.")

    url = st.text_input(
        "Link",
        key="instant_qr_url",
        placeholder="https://exemplo.com/pagina",
    ).strip()

    if not url:
        st.info("Digite um link para gerar o QR Code.")
        return

    if not is_valid_http_url(url):
        st.warning("Informe uma URL válida iniciada por http:// ou https://")
        return

    png_bytes = make_qr_png(url)
    st.image(png_bytes, caption="QR Code gerado", width=320)
    st.download_button(
        "Baixar PNG",
        data=png_bytes,
        file_name="qr_code_instantaneo.png",
        mime="image/png",
        width="stretch",
    )


def render_qr_static() -> None:
    st.subheader("🖼️ QR Code estático")
    st.write(
        "Informe o link e clique em Gerar. "
        "O resultado permanece disponível na sessão até você gerar outro."
    )

    with st.form("static_qr_form"):
        url = st.text_input(
            "Link",
            placeholder="https://exemplo.com/pagina",
        ).strip()
        filename = st.text_input("Nome do arquivo", value="qr_code_estatico")
        submitted = st.form_submit_button("Gerar QR Code", width="stretch")

    if submitted:
        if not is_valid_http_url(url):
            st.error("Informe uma URL válida iniciada por http:// ou https://")
        else:
            st.session_state.static_qr_bytes = make_qr_png(url)
            st.session_state.static_qr_url = url
            st.session_state.static_qr_filename = filename.strip() or "qr_code_estatico"

    if st.session_state.static_qr_bytes:
        st.image(
            st.session_state.static_qr_bytes,
            caption=st.session_state.static_qr_url,
            width=320,
        )
        safe_name = "".join(
            c
            for c in st.session_state.get("static_qr_filename", "qr_code_estatico")
            if c.isalnum() or c in {"-", "_"}
        ) or "qr_code_estatico"
        st.download_button(
            "Baixar PNG",
            data=st.session_state.static_qr_bytes,
            file_name=f"{safe_name}.png",
            mime="image/png",
            width="stretch",
        )


def render_youtube_downloader() -> None:
    st.subheader("🎬 Baixar vídeo do YouTube")
    st.caption("Use apenas em vídeos que você possui ou tem autorização para baixar.")

    with st.form("youtube_form"):
        url = st.text_input(
            "Link do vídeo",
            placeholder="https://www.youtube.com/watch?v=...",
        ).strip()
        quality = st.selectbox("Qualidade máxima", [360, 480, 720, 1080], index=2)
        submitted = st.form_submit_button("Preparar MP4", width="stretch")

    if submitted:
        st.session_state.yt_video_bytes = None
        st.session_state.yt_video_filename = None
        st.session_state.yt_video_meta = None

        if not is_youtube_url(url):
            st.error("Informe um link válido do YouTube.")
            return

        with st.spinner("Processando o vídeo..."):
            try:
                video_bytes, filename, metadata = download_youtube_mp4(url, quality)
            except Exception as exc:
                st.error(str(exc))
                return

        st.session_state.yt_video_bytes = video_bytes
        st.session_state.yt_video_filename = filename
        st.session_state.yt_video_meta = metadata
        st.success("Vídeo preparado com sucesso.")

    if st.session_state.yt_video_bytes:
        meta = st.session_state.yt_video_meta or {}
        if meta.get("title"):
            st.write(f"**Título:** {meta['title']}")
        if meta.get("uploader"):
            st.write(f"**Canal:** {meta['uploader']}")
        if meta.get("filesize"):
            st.write(f"**Tamanho:** {meta['filesize'] / (1024 * 1024):.1f} MB")

        st.download_button(
            "⬇️ Baixar MP4",
            data=st.session_state.yt_video_bytes,
            file_name=st.session_state.yt_video_filename or "video.mp4",
            mime="video/mp4",
            width="stretch",
        )

    st.info(
        "Observação: downloads do YouTube podem falhar em alguns vídeos por "
        "bloqueios do próprio YouTube, autenticação ou limitações de rede."
    )


def render_vimeo_downloader() -> None:
    st.subheader("🎥 Baixar vídeo do Vimeo")
    st.caption("Cole o link do Vimeo. O app prepara o vídeo em MP4.")

    with st.form("vimeo_form"):
        url = st.text_input(
            "Link do vídeo do Vimeo",
            placeholder="https://vimeo.com/868438346?fl=pl&fe=cm",
        ).strip()
        submitted = st.form_submit_button("Preparar MP4", width="stretch")

    if submitted:
        st.session_state.vimeo_video_bytes = None
        st.session_state.vimeo_video_filename = None
        st.session_state.vimeo_video_meta = None

        if not is_vimeo_url(url):
            st.error("Informe um link válido do Vimeo.")
            return

        with st.spinner("Processando o vídeo do Vimeo..."):
            try:
                video_bytes, filename, metadata = download_vimeo_mp4(url)
            except Exception as exc:
                st.error(str(exc))
                return

        st.session_state.vimeo_video_bytes = video_bytes
        st.session_state.vimeo_video_filename = filename
        st.session_state.vimeo_video_meta = metadata
        st.success("Vídeo preparado com sucesso.")

    if st.session_state.vimeo_video_bytes:
        meta = st.session_state.vimeo_video_meta or {}

        if meta.get("title"):
            st.write(f"**Título:** {meta['title']}")
        if meta.get("uploader"):
            st.write(f"**Autor:** {meta['uploader']}")
        if meta.get("duration"):
            duration = int(meta["duration"])
            minutes, seconds = divmod(duration, 60)
            st.write(f"**Duração:** {minutes}:{seconds:02d}")
        if meta.get("filesize"):
            st.write(f"**Tamanho:** {meta['filesize'] / (1024 * 1024):.1f} MB")

        st.download_button(
            "⬇️ Baixar MP4",
            data=st.session_state.vimeo_video_bytes,
            file_name=st.session_state.vimeo_video_filename or "video_vimeo.mp4",
            mime="video/mp4",
            width="stretch",
        )

    st.info(
        "Vídeos privados, protegidos por senha ou que exigem login no Vimeo "
        "podem precisar de autenticação adicional."
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
        "QR Code instantâneo",
        "QR Code estático",
        "Baixar vídeo do YouTube",
        "Baixar vídeo do Vimeo",
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

    if module == "QR Code instantâneo":
        render_qr_instant()
    elif module == "QR Code estático":
        render_qr_static()
    elif module == "Baixar vídeo do YouTube":
        render_youtube_downloader()
    elif module == "Baixar vídeo do Vimeo":
        render_vimeo_downloader()
    elif module == "Gerenciar acessos":
        render_access_manager()


if __name__ == "__main__":
    main()
