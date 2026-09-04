# Atualização do my_streamlit

Este pacote atualiza os módulos solicitados sem alterar banco de dados ou permissões.

## Mudanças

- YouTube: integração atual do `yt-dlp` com EJS + Deno, seleção flexível de formatos, merge/remux com FFmpeg para MP4, retries e suporte a 360p–2160p.
- Vimeo: seleção flexível de formatos, remux para MP4, `curl_cffi` para compatibilidade de rede/TLS e qualidade até 2160p.
- QR Code: mantém um QR estático tradicional e substitui o QR instantâneo por um QR com logotipo central.
- Logos aceitos: PNG, JPG, JPEG e SVG; SVG é convertido para bitmap com CairoSVG antes da composição.
- O QR com logo usa correção de erro H e mantém o logo pequeno para preservar leitura.

## Como aplicar

Na raiz do seu repositório, copie os arquivos deste pacote substituindo:

- `youtube_utils.py`
- `vimeo_utils.py`
- `qr_utils.py`
- `requirements.txt`
- `packages.txt`

Depois copie também `apply_streamlit_upgrade.py` e execute:

```bash
python apply_streamlit_upgrade.py
```

O script cria `streamlit_app.py.bak` e atualiza a interface automaticamente.

Em seguida:

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

No Streamlit Community Cloud, faça commit/push dos arquivos atualizados para disparar o redeploy.

> Use os módulos de download somente em vídeos que você possui ou tem autorização para baixar. Conteúdo privado, DRM, login obrigatório ou restrições do provedor não são contornados por esta atualização.
