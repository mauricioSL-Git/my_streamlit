from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

DB_PATH = Path(os.getenv("APP_DB_PATH", "data/app.db"))
PBKDF2_ITERATIONS = 310_000
PRIMARY_ADMIN_KEY = "PRIMARY_ADMIN_EMAIL"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _ensure_employee_dev_column(conn: sqlite3.Connection) -> None:
    """Migra bancos antigos adicionando a coluna dev quando necessário."""
    columns = {
        str(row["name"]).lower()
        for row in conn.execute("PRAGMA table_info(TB_EMPLOYEE)").fetchall()
    }

    if "dev" not in columns:
        conn.execute(
            "ALTER TABLE TB_EMPLOYEE ADD COLUMN dev INTEGER NOT NULL DEFAULT 0"
        )


def _ensure_primary_admin(conn: sqlite3.Connection) -> str | None:
    """
    Garante a existência da conta-mãe.

    - O primeiro usuário criado é gravado em TB_APP_CONFIG.
    - Em bancos antigos, o usuário de menor rowid vira a conta-mãe.
    - A conta-mãe sempre é mantida com dev = 1.
    """
    row = conn.execute(
        "SELECT config_value FROM TB_APP_CONFIG WHERE config_key = ?",
        (PRIMARY_ADMIN_KEY,),
    ).fetchone()

    admin_email: str | None = None

    if row:
        candidate = _normalize_email(str(row["config_value"]))
        exists = conn.execute(
            "SELECT 1 FROM TB_EMPLOYEE WHERE email = ?",
            (candidate,),
        ).fetchone()
        if exists:
            admin_email = candidate

    if admin_email is None:
        first_user = conn.execute(
            "SELECT email FROM TB_EMPLOYEE ORDER BY rowid ASC LIMIT 1"
        ).fetchone()

        if not first_user:
            return None

        admin_email = _normalize_email(first_user["email"])
        conn.execute(
            """
            INSERT INTO TB_APP_CONFIG (config_key, config_value)
            VALUES (?, ?)
            ON CONFLICT(config_key)
            DO UPDATE SET config_value = excluded.config_value
            """,
            (PRIMARY_ADMIN_KEY, admin_email),
        )

    # A conta-mãe é sempre DEV e isso nunca pode ser revogado.
    conn.execute(
        "UPDATE TB_EMPLOYEE SET dev = 1 WHERE email = ?",
        (admin_email,),
    )
    return admin_email


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS TB_EMPLOYEE (
                email TEXT PRIMARY KEY,
                password TEXT NOT NULL,
                dev INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        _ensure_employee_dev_column(conn)

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS TB_LOGIN_LOG (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                login_at TEXT NOT NULL,
                success INTEGER NOT NULL CHECK (success IN (0, 1))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS TB_APP_CONFIG (
                config_key TEXT PRIMARY KEY,
                config_value TEXT NOT NULL
            )
            """
        )
        _ensure_primary_admin(conn)
        conn.commit()


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("A senha não pode ser vazia.")

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_value: str) -> bool:
    try:
        algorithm, iterations_str, salt_hex, digest_hex = stored_value.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def _parse_dev(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return 1 if value == 1 else 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "sim", "on"}:
            return 1
        if normalized in {"0", "false", "no", "nao", "não", "off"}:
            return 0
    return 1 if default == 1 else 0


def _upsert_employee_with_connection(
    conn: sqlite3.Connection,
    email: str,
    plain_password: str,
    *,
    dev_on_create: int = 0,
) -> bool:
    """
    Cria ou atualiza a senha de um usuário.
    Retorna True quando um usuário novo foi criado.

    O campo dev só é aplicado na criação. Alteração de permissão passa por
    admin_set_employee_dev(), que contém as regras de autorização.
    """
    email = _normalize_email(email)

    if not email:
        raise ValueError("O e-mail não pode ser vazio.")
    if not plain_password:
        raise ValueError("A senha não pode ser vazia.")

    row = conn.execute(
        "SELECT password FROM TB_EMPLOYEE WHERE email = ?",
        (email,),
    ).fetchone()

    if row:
        if not verify_password(plain_password, row["password"]):
            conn.execute(
                "UPDATE TB_EMPLOYEE SET password = ? WHERE email = ?",
                (hash_password(plain_password), email),
            )
        return False

    conn.execute(
        "INSERT INTO TB_EMPLOYEE (email, password, dev) VALUES (?, ?, ?)",
        (email, hash_password(plain_password), _parse_dev(dev_on_create)),
    )
    return True


def create_first_admin(email: str, plain_password: str) -> None:
    """Cria a conta-mãe: primeiro usuário do sistema, sempre com dev = 1."""
    email = _normalize_email(email)

    if not email:
        raise ValueError("O e-mail não pode ser vazio.")
    if not plain_password:
        raise ValueError("A senha não pode ser vazia.")

    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_employee_dev_column(conn)

        total = conn.execute(
            "SELECT COUNT(*) AS total FROM TB_EMPLOYEE"
        ).fetchone()["total"]

        if int(total) > 0:
            raise PermissionError(
                "O primeiro acesso já foi criado. Entre com uma conta autorizada."
            )

        _upsert_employee_with_connection(
            conn,
            email,
            plain_password,
            dev_on_create=1,
        )
        conn.execute(
            """
            INSERT INTO TB_APP_CONFIG (config_key, config_value)
            VALUES (?, ?)
            ON CONFLICT(config_key)
            DO UPDATE SET config_value = excluded.config_value
            """,
            (PRIMARY_ADMIN_KEY, email),
        )
        conn.execute(
            "UPDATE TB_EMPLOYEE SET dev = 1 WHERE email = ?",
            (email,),
        )
        conn.commit()


def get_primary_admin_email() -> str | None:
    with _connect() as conn:
        admin_email = _ensure_primary_admin(conn)
        conn.commit()
    return admin_email


def is_primary_admin(email: str | None) -> bool:
    if not email:
        return False

    email = _normalize_email(email)
    admin_email = get_primary_admin_email()
    return bool(admin_email and email == admin_email)


def is_dev(email: str | None) -> bool:
    """Retorna True somente para contas com dev = 1."""
    if not email:
        return False

    email = _normalize_email(email)
    with _connect() as conn:
        admin_email = _ensure_primary_admin(conn)
        row = conn.execute(
            "SELECT dev FROM TB_EMPLOYEE WHERE email = ?",
            (email,),
        ).fetchone()
        conn.commit()

    if admin_email and email == admin_email:
        return True
    return bool(row and int(row["dev"]) == 1)


def employee_exists(email: str | None) -> bool:
    if not email:
        return False
    email = _normalize_email(email)
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM TB_EMPLOYEE WHERE email = ?",
            (email,),
        ).fetchone()
    return row is not None


def upsert_employee(email: str, plain_password: str) -> None:
    """
    Função de manutenção/seed. Novos usuários entram com dev = 0;
    se for o primeiro usuário de um banco antigo, ele é promovido a conta-mãe.
    """
    with _connect() as conn:
        _upsert_employee_with_connection(
            conn,
            email,
            plain_password,
            dev_on_create=0,
        )
        _ensure_primary_admin(conn)
        conn.commit()


def _require_dev(conn: sqlite3.Connection, actor_email: str) -> str:
    actor_email = _normalize_email(actor_email)
    admin_email = _ensure_primary_admin(conn)

    row = conn.execute(
        "SELECT dev FROM TB_EMPLOYEE WHERE email = ?",
        (actor_email,),
    ).fetchone()

    if not row or int(row["dev"]) != 1:
        raise PermissionError("Esta conta não possui permissão DEV para gerenciar acessos.")

    # Defesa extra para garantir que a conta-mãe permaneça DEV.
    if admin_email and actor_email == admin_email:
        conn.execute(
            "UPDATE TB_EMPLOYEE SET dev = 1 WHERE email = ?",
            (admin_email,),
        )

    return admin_email or ""


def admin_upsert_employee(
    actor_email: str,
    target_email: str,
    plain_password: str,
) -> None:
    """
    Contas dev = 1 podem criar usuários e alterar senhas.

    Regra especial da conta-mãe:
    - somente ela própria pode alterar sua senha;
    - outros DEV não podem modificá-la.
    """
    actor_email = _normalize_email(actor_email)
    target_email = _normalize_email(target_email)

    with _connect() as conn:
        admin_email = _require_dev(conn, actor_email)

        if target_email == admin_email and actor_email != admin_email:
            raise PermissionError(
                "A conta-mãe só pode ser editada por ela mesma."
            )

        _upsert_employee_with_connection(
            conn,
            target_email,
            plain_password,
            dev_on_create=0,
        )

        # Mesmo se a conta-mãe alterar a própria senha, dev permanece 1.
        if target_email == admin_email:
            conn.execute(
                "UPDATE TB_EMPLOYEE SET dev = 1 WHERE email = ?",
                (admin_email,),
            )

        conn.commit()


def admin_set_employee_dev(
    actor_email: str,
    target_email: str,
    dev: int | bool,
) -> None:
    """
    Concede/remove permissão DEV.

    Apenas a conta-mãe pode escolher quais outras contas terão dev = 1.
    A conta-mãe permanece dev = 1 para sempre.
    """
    actor_email = _normalize_email(actor_email)
    target_email = _normalize_email(target_email)
    new_dev = _parse_dev(dev)

    with _connect() as conn:
        admin_email = _require_dev(conn, actor_email)

        if actor_email != admin_email:
            raise PermissionError(
                "Somente a conta-mãe pode conceder ou remover a permissão DEV."
            )

        if target_email == admin_email:
            raise PermissionError(
                "A conta-mãe é DEV permanente e essa permissão não pode ser alterada."
            )

        exists = conn.execute(
            "SELECT 1 FROM TB_EMPLOYEE WHERE email = ?",
            (target_email,),
        ).fetchone()
        if not exists:
            raise ValueError("Usuário não encontrado.")

        conn.execute(
            "UPDATE TB_EMPLOYEE SET dev = ? WHERE email = ?",
            (new_dev, target_email),
        )
        conn.commit()


def admin_delete_employee(actor_email: str, target_email: str) -> bool:
    """
    Contas dev = 1 podem excluir outras contas.

    A conta-mãe nunca pode ser excluída por ninguém.
    Para evitar encerrar a própria sessão de forma inconsistente, uma conta
    DEV também não pode excluir a si mesma.
    """
    actor_email = _normalize_email(actor_email)
    target_email = _normalize_email(target_email)

    if not target_email:
        return False

    with _connect() as conn:
        admin_email = _require_dev(conn, actor_email)

        if target_email == admin_email:
            raise PermissionError(
                "A conta-mãe é permanente e não pode ser excluída por ninguém."
            )

        if target_email == actor_email:
            raise PermissionError(
                "Você não pode excluir a própria conta enquanto está conectado."
            )

        cursor = conn.execute(
            "DELETE FROM TB_EMPLOYEE WHERE email = ?",
            (target_email,),
        )
        conn.commit()
        return cursor.rowcount > 0


def seed_users(users: Iterable[Mapping[str, str]]) -> None:
    """
    Recria usuários configurados via Streamlit Secrets.

    Formato opcional:
        [[users]]
        email = "usuario@exemplo.com"
        password = "senha"
        dev = 0

    Se o banco estiver vazio, o primeiro usuário torna-se a conta-mãe e dev = 1.
    Nos demais, dev vindo dos Secrets só é aplicado na criação.
    """
    normalized_users: list[tuple[str, str, int]] = []

    for user in users:
        email = _normalize_email(str(user.get("email", "")))
        password = str(user.get("password", ""))
        dev = _parse_dev(user.get("dev", 0))
        if email and password:
            normalized_users.append((email, password, dev))

    if not normalized_users:
        return

    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_employee_dev_column(conn)
        current_admin = _ensure_primary_admin(conn)

        for email, password, dev in normalized_users:
            _upsert_employee_with_connection(
                conn,
                email,
                password,
                dev_on_create=dev,
            )

        if current_admin is None:
            mother_email = normalized_users[0][0]
            conn.execute(
                """
                INSERT INTO TB_APP_CONFIG (config_key, config_value)
                VALUES (?, ?)
                ON CONFLICT(config_key)
                DO UPDATE SET config_value = excluded.config_value
                """,
                (PRIMARY_ADMIN_KEY, mother_email),
            )
            conn.execute(
                "UPDATE TB_EMPLOYEE SET dev = 1 WHERE email = ?",
                (mother_email,),
            )

        _ensure_primary_admin(conn)
        conn.commit()


def count_employees() -> int:
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM TB_EMPLOYEE").fetchone()
    return int(row["total"] if row else 0)


def list_employees() -> list[dict]:
    with _connect() as conn:
        admin_email = _ensure_primary_admin(conn)
        rows = conn.execute(
            "SELECT email, dev FROM TB_EMPLOYEE ORDER BY rowid ASC"
        ).fetchall()
        conn.commit()

    result: list[dict] = []
    for row in rows:
        email = str(row["email"])
        result.append(
            {
                "email": email,
                "dev": int(row["dev"]),
                "is_mother": bool(admin_email and email == admin_email),
            }
        )
    return result


def authenticate(email: str, plain_password: str) -> bool:
    email = _normalize_email(email)
    if not email or not plain_password:
        return False

    with _connect() as conn:
        row = conn.execute(
            "SELECT password FROM TB_EMPLOYEE WHERE email = ?",
            (email,),
        ).fetchone()

    if not row:
        return False
    return verify_password(plain_password, row["password"])


def register_login_attempt(email: str, success: bool) -> None:
    email = _normalize_email(email) or "<vazio>"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            "INSERT INTO TB_LOGIN_LOG (email, login_at, success) VALUES (?, ?, ?)",
            (email, now, int(success)),
        )
        conn.commit()


def list_login_attempts(limit: int = 100) -> list[dict]:
    limit = max(1, min(int(limit), 1000))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, email, login_at, success
            FROM TB_LOGIN_LOG
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
