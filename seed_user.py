from __future__ import annotations

import getpass

from database import init_db, upsert_employee


def main() -> None:
    init_db()
    email = input("E-mail: ").strip()
    password = getpass.getpass("Senha: ")
    upsert_employee(email, password)
    print(f"Usuário {email} criado/atualizado com sucesso em TB_EMPLOYEE.")


if __name__ == "__main__":
    main()
