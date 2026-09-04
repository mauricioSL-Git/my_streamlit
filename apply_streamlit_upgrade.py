"""Aplica as mudanças de interface no streamlit_app.py atual do projeto.

Uso, na raiz do repositório:
    python apply_streamlit_upgrade.py

O script cria streamlit_app.py.bak antes de alterar o arquivo.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

APP = Path("streamlit_app.py")

if not APP.exists():
    raise SystemExit("streamlit_app.py não foi encontrado na pasta atual.")

text = APP.read_text(encoding="utf-8")
original = text

text = text.replace(
    "from qr_utils import is_valid_http_url, make_qr_png",
    "from qr_utils import is_valid_http_url, make_qr_png, make_qr_with_logo_png",
)

state_anchor = 'st.session_state.setdefault("static_qr_filename", "qr_code_estatico")'
if state_anchor in text and 'logo_qr_bytes' not in text:
    text = text.replace(
        state_anchor,
        state_anchor
        + '\n    st.session_state.setdefault("logo_qr_bytes", None)'
        + '\n    st.session_state.setdefault("logo_qr_url", None)'
        + '\n    st.session_state.setdefault("logo_qr_filename", "qr_code_com_logo")',
    )

new_logo_function = r'''def render_qr_with_logo() -> None:
    st.subheader("🎨 QR Code com logotipo")
    st.write(
        "Informe o link e envie um logotipo PNG, JPG, JPEG ou SVG. "
        "O logotipo será colocado no centro do QR Code."
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
            help="Formatos aceitos: PNG, JPG, JPEG e SVG. Máximo recomendado: 5 MB.",
        )
        filename = st.text_input("Nome do arquivo", value="qr_code_com_logo")
        submitted = st.form_submit_button("Gerar QR Code com logotipo", width="stretch")

    if submitted:
        if not is_valid_http_url(url):
            st.error("Informe uma URL válida iniciada por http:// ou https://")
        elif logo_file is None:
            st.error("Envie um logotipo PNG, JPG, JPEG ou SVG.")
        else:
            try:
                st.session_state.logo_qr_bytes = make_qr_with_logo_png(
                    url,
                    logo_file.getvalue(),
                    logo_file.name,
                )
            except Exception as exc:
                st.error(str(exc))
            else:
                st.session_state.logo_qr_url = url
                st.session_state.logo_qr_filename = filename.strip() or "qr_code_com_logo"

    if st.session_state.get("logo_qr_bytes"):
        st.image(
            st.session_state.logo_qr_bytes,
            caption=st.session_state.get("logo_qr_url"),
            width=360,
        )
        safe_name = "".join(
            c
            for c in st.session_state.get("logo_qr_filename", "qr_code_com_logo")
            if c.isalnum() or c in {"-", "_"}
        ) or "qr_code_com_logo"
        st.download_button(
            "Baixar PNG",
            data=st.session_state.logo_qr_bytes,
            file_name=f"{safe_name}.png",
            mime="image/png",
            width="stretch",
        )

'''

pattern = re.compile(
    r"def render_qr_instant\(\) -> None:\n.*?(?=def render_qr_static\(\) -> None:)",
    re.DOTALL,
)
text, count = pattern.subn(new_logo_function, text, count=1)
if count != 1:
    raise SystemExit(
        "Não consegui localizar render_qr_instant(). O arquivo pode ter mudado; nada foi salvo."
    )

# Adiciona escolha de qualidade ao Vimeo e passa o valor à função.
vimeo_form_anchor = '''        url = st.text_input(
            "Link do vídeo do Vimeo",
            placeholder="https://vimeo.com/868438346?fl=pl&fe=cm",
        ).strip()
        submitted = st.form_submit_button("Preparar MP4", width="stretch")'''
if vimeo_form_anchor in text:
    text = text.replace(
        vimeo_form_anchor,
        '''        url = st.text_input(
            "Link do vídeo do Vimeo",
            placeholder="https://vimeo.com/868438346?fl=pl&fe=cm",
        ).strip()
        quality = st.selectbox(
            "Qualidade máxima",
            [360, 480, 720, 1080, 1440, 2160],
            index=3,
            key="vimeo_quality",
        )
        submitted = st.form_submit_button("Preparar MP4", width="stretch")''',
    )

text = text.replace(
    "download_vimeo_mp4(url)",
    "download_vimeo_mp4(url, quality)",
)

# Amplia as qualidades do YouTube.
text = text.replace(
    'st.selectbox("Qualidade máxima", [360, 480, 720, 1080], index=2)',
    'st.selectbox("Qualidade máxima", [360, 480, 720, 1080, 1440, 2160], index=2)',
)

text = text.replace(
    '"QR Code instantâneo",\n        "QR Code estático",',
    '"QR Code estático",\n        "QR Code com logotipo",',
)

text = text.replace(
    '''    if module == "QR Code instantâneo":
        render_qr_instant()
    elif module == "QR Code estático":
        render_qr_static()
    elif module == "Baixar vídeo do YouTube":''',
    '''    if module == "QR Code estático":
        render_qr_static()
    elif module == "QR Code com logotipo":
        render_qr_with_logo()
    elif module == "Baixar vídeo do YouTube":''',
)

if text == original:
    raise SystemExit("Nenhuma alteração foi aplicada.")

backup = APP.with_suffix(APP.suffix + ".bak")
shutil.copy2(APP, backup)
APP.write_text(text, encoding="utf-8")
print(f"OK: {APP} atualizado.")
print(f"Backup: {backup}")
