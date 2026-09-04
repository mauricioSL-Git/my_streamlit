# Streamlit Utilitários

Aplicação Streamlit com:

1. Login por e-mail e senha usando SQLite.
2. Criação do primeiro acesso diretamente pela interface.
3. Gerenciamento de usuários (adicionar, trocar senha e excluir acessos).
4. QR Code instantâneo em PNG.
5. QR Code estático em PNG.
6. Download de vídeos do YouTube em MP4.
7. Download de vídeos do Vimeo em MP4.

> Use os módulos de download apenas para vídeos que você possui ou tem autorização para baixar.

## Estrutura

```text
streamlit_utilitarios/
├── streamlit_app.py
├── database.py
├── qr_utils.py
├── youtube_utils.py
├── vimeo_utils.py
├── seed_user.py
├── requirements.txt
├── packages.txt
├── README.md
├── data/
│   └── .gitkeep
└── .streamlit/
    ├── config.toml
    └── secrets.toml.example
```

## Banco de dados

A tabela principal é:

```sql
CREATE TABLE TB_EMPLOYEE (
    email TEXT PRIMARY KEY,
    password TEXT NOT NULL
);
```

A coluna `password` armazena um hash PBKDF2, e não a senha em texto aberto.

Também existe `TB_LOGIN_LOG(id, email, login_at, success)` para registrar as tentativas de login sem armazenar a senha.

## Rodar localmente

### 1. Criar o ambiente virtual

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

Linux/macOS:

```bash
source .venv/bin/activate
```

### 2. Instalar as dependências

```bash
pip install -r requirements.txt
```

Para os módulos de vídeo, tenha o FFmpeg instalado no computador. No Streamlit Community Cloud, `packages.txt` já solicita a instalação de `ffmpeg`.

### 3. Iniciar o app

```bash
streamlit run streamlit_app.py
```

Na primeira execução, se não houver usuários na `TB_EMPLOYEE`, o próprio app mostra a tela **Criar primeiro acesso**.

Depois de entrar, use **Gerenciar acessos** para cadastrar novos usuários, alterar senhas ou excluir acessos.

## YouTube

O módulo aceita links como:

```text
https://www.youtube.com/watch?v=JnP501l4l6Y
```

Você escolhe a qualidade máxima entre 360p, 480p, 720p e 1080p.

## Vimeo

O módulo aceita links como:

```text
https://vimeo.com/868438346?fl=pl&fe=cm
```

Basta colar o link e clicar em **Preparar MP4**. O app tenta obter a melhor versão MP4 disponível.

Vídeos privados, protegidos por senha, restritos a domínio ou que exigem login podem precisar de autenticação adicional.

## Certificados HTTPS

Os módulos YouTube e Vimeo estão configurados para lidar com o problema de certificado autoassinado que apareceu no ambiente local. Isso inclui `nocheckcertificate=True`, que desativa a validação do certificado HTTPS durante o download. Use essa configuração apenas em ambiente controlado/confiável.

## Limite de arquivo

Os downloads são limitados a aproximadamente 250 MB para reduzir uso excessivo de memória no Streamlit.

## Streamlit Community Cloud

O armazenamento SQLite local não tem persistência garantida no Community Cloud. Para manter usuários fixos após reinicializações, configure os Secrets do app, por exemplo:

```toml
[[users]]
email = "admin@exemplo.com"
password = "uma-senha-forte"
```

Ao iniciar, o app insere/atualiza esses usuários em `TB_EMPLOYEE`, salvando a senha em hash.

## Conta-mãe e permissão DEV

A `TB_EMPLOYEE` possui a coluna `dev`, com valor padrão `0`. O primeiro usuário
criado no sistema torna-se a **conta-mãe** e recebe `dev = 1` automaticamente.

- `dev = 0`: usuário comum. O módulo **Gerenciar acessos** nem aparece.
- `dev = 1`: pode abrir **Gerenciar acessos**, criar usuários, alterar senhas e
  excluir contas permitidas.
- Somente a conta-mãe pode conceder ou retirar `dev = 1` das outras contas.
- A conta-mãe é sempre `dev = 1`, nunca pode ser excluída e só pode ter sua
  própria senha alterada quando ela mesma estiver conectada.
- Outros usuários DEV não conseguem editar ou excluir a conta-mãe.

Em bancos criados por versões anteriores, a coluna `dev` é adicionada
automaticamente. O usuário mais antigo existente é definido como conta-mãe e
recebe `dev = 1`; os demais permanecem com `dev = 0` até serem liberados pela
conta-mãe.
