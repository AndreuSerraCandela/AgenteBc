from __future__ import annotations

import argparse
import os
import secrets
import string
import sys
from pathlib import Path

import pyodbc


LOGIN_NAME = "agentebc_reader"


class ProvisioningError(RuntimeError):
    pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-env", type=Path, required=True)
    parser.add_argument("--output-env", type=Path, required=True)
    args = parser.parse_args()

    try:
        admin = _read_env(args.admin_env)
        server = _required(admin, "SQL_SERVER")
        database = _required(admin, "SQL_DATABASE")
        admin_user = _required(admin, "SQL_USER")
        admin_password = _required(admin, "SQL_PASSWORD")
        company = admin.get("BC_COMPANY", "")
        password = _generate_password()
        created_login = False
        created_user = False

        master = pyodbc.connect(
            _connection_string(
                server, "master", admin_user, admin_password
            ),
            autocommit=True,
            timeout=10,
        )
        try:
            if master.execute(
                "SELECT 1 FROM sys.sql_logins WHERE name = ?",
                LOGIN_NAME,
            ).fetchone():
                raise ProvisioningError(
                    f"El login {LOGIN_NAME} ya existe; no se ha modificado"
                )
            master.execute(
                f"CREATE LOGIN {_identifier(LOGIN_NAME)} "
                f"WITH PASSWORD = {_literal(password)}, "
                "CHECK_POLICY = ON, CHECK_EXPIRATION = OFF"
            )
            created_login = True
        finally:
            master.close()

        target = pyodbc.connect(
            _connection_string(
                server, database, admin_user, admin_password
            ),
            autocommit=True,
            timeout=10,
        )
        try:
            if target.execute(
                "SELECT 1 FROM sys.database_principals WHERE name = ?",
                LOGIN_NAME,
            ).fetchone():
                raise ProvisioningError(
                    f"El usuario {LOGIN_NAME} ya existe en {database}"
                )
            target.execute(
                f"CREATE USER {_identifier(LOGIN_NAME)} "
                f"FOR LOGIN {_identifier(LOGIN_NAME)}"
            )
            created_user = True
            target.execute(
                f"ALTER ROLE [db_datareader] ADD MEMBER {_identifier(LOGIN_NAME)}"
            )
        finally:
            target.close()

        _verify_reader(server, database, password)
        _write_output(args.output_env, server, database, password, company)
        print(
            f"Cuenta {LOGIN_NAME} creada y verificada en {database}; "
            "credenciales guardadas en el fichero local."
        )
        return 0
    except Exception as exc:
        if "created_user" in locals() and created_user:
            _drop_user_safely(
                server, database, admin_user, admin_password
            )
        if "created_login" in locals() and created_login:
            _drop_login_safely(server, admin_user, admin_password)
        print(f"Error de aprovisionamiento: {exc}", file=sys.stderr)
        return 1


def _verify_reader(server: str, database: str, password: str) -> None:
    connection = pyodbc.connect(
        _connection_string(server, database, LOGIN_NAME, password),
        autocommit=False,
        timeout=10,
    )
    try:
        role_status = connection.execute(
            "SELECT IS_MEMBER('db_datareader'), IS_MEMBER('db_datawriter'), "
            "IS_MEMBER('db_owner'), "
            "HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CREATE TABLE')"
        ).fetchone()
        if role_status is None or tuple(role_status) != (1, 0, 0, 0):
            raise ProvisioningError(
                f"Permisos efectivos inesperados para {LOGIN_NAME}: {role_status}"
            )
        writable_object = connection.execute(
            "SELECT TOP (1) s.name, t.name "
            "FROM sys.tables AS t "
            "JOIN sys.schemas AS s ON s.schema_id = t.schema_id "
            "WHERE HAS_PERMS_BY_NAME("
            "QUOTENAME(s.name) + '.' + QUOTENAME(t.name), 'OBJECT', 'UPDATE'"
            ") = 1"
        ).fetchone()
        if writable_object:
            raise ProvisioningError(
                "La cuenta heredó permiso UPDATE sobre al menos una tabla"
            )
        connection.execute("SELECT TOP (1) name FROM sys.tables").fetchone()
    finally:
        connection.rollback()
        connection.close()


def _drop_user_safely(
    server: str,
    database: str,
    admin_user: str,
    admin_password: str,
) -> None:
    try:
        connection = pyodbc.connect(
            _connection_string(server, database, admin_user, admin_password),
            autocommit=True,
            timeout=10,
        )
        try:
            connection.execute(
                f"DROP USER IF EXISTS {_identifier(LOGIN_NAME)}"
            )
        finally:
            connection.close()
    except Exception:
        pass


def _drop_login_safely(
    server: str,
    admin_user: str,
    admin_password: str,
) -> None:
    try:
        connection = pyodbc.connect(
            _connection_string(server, "master", admin_user, admin_password),
            autocommit=True,
            timeout=10,
        )
        try:
            connection.execute(
                f"DROP LOGIN IF EXISTS {_identifier(LOGIN_NAME)}"
            )
        finally:
            connection.close()
    except Exception:
        pass


def _read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        result[name.strip()] = value.strip().strip("\"'")
    return result


def _required(values: dict[str, str], name: str) -> str:
    value = values.get(name)
    if not value:
        raise ProvisioningError(f"Falta {name} en el fichero administrativo")
    return value


def _generate_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*_-+="
    required = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*_-+="),
    ]
    required.extend(secrets.choice(alphabet) for _ in range(36))
    secrets.SystemRandom().shuffle(required)
    return "".join(required)


def _connection_string(
    server: str,
    database: str,
    username: str,
    password: str,
) -> str:
    return (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={_odbc_value(server)};"
        f"DATABASE={_odbc_value(database)};"
        f"UID={_odbc_value(username)};"
        f"PWD={_odbc_value(password)};"
        "Encrypt=yes;TrustServerCertificate=yes"
    )


def _write_output(
    path: Path,
    server: str,
    database: str,
    password: str,
    company: str,
) -> None:
    content = (
        "# Cuenta de solo lectura creada para AgenteBC. No subir a Git.\n"
        f"SQL_SERVER={server}\n"
        f"SQL_DATABASE={database}\n"
        f"SQL_USER={LOGIN_NAME}\n"
        f"SQL_PASSWORD={password}\n"
        f"BC_COMPANY={company}\n"
    )
    path.write_text(content, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _identifier(value: str) -> str:
    return "[" + value.replace("]", "]]") + "]"


def _literal(value: str) -> str:
    return "N'" + value.replace("'", "''") + "'"


def _odbc_value(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


if __name__ == "__main__":
    raise SystemExit(main())
