#!/usr/bin/env python3
"""Write a gitignored SQL file with the password from .env. Do not print it."""

from __future__ import annotations

import sys
from pathlib import Path

from db_env import ROOT, load_env

OUT = ROOT / "docs" / "sql" / "create-findash-user.local.sql"

# localhost/loopback + RFC1918 (10/8, 172.16/12, 192.168/16)
HOSTS = (
    "localhost",
    "127.0.0.1",
    "::1",
    "10.0.0.0/255.0.0.0",
    "172.16.0.0/255.240.0.0",
    "192.168.0.0/255.255.0.0",
)

TABLES = ("FinBotTransactions", "FinBotTransactionsCC")
DATABASE = "n8n"
USER = "findash"


def sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def render(password: str) -> str:
    pw = sql_string(password)
    lines = [
        "-- Generated from .env. Gitignored. Run as MariaDB admin, then delete.",
        "-- SELECT only on the two FinBot tables. No writes.",
        "",
    ]
    for host in HOSTS:
        account = f"{sql_string(USER)}@{sql_string(host)}"
        lines.append(f"CREATE USER IF NOT EXISTS {account} IDENTIFIED BY {pw};")
    lines.append("")
    for host in HOSTS:
        account = f"{sql_string(USER)}@{sql_string(host)}"
        lines.append(f"ALTER USER {account} IDENTIFIED BY {pw};")
    lines.append("")
    for host in HOSTS:
        account = f"{sql_string(USER)}@{sql_string(host)}"
        for table in TABLES:
            lines.append(
                f"GRANT SELECT ON `{DATABASE}`.`{table}` TO {account};"
            )
    lines.append("")
    lines.append("FLUSH PRIVILEGES;")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    env = load_env()
    if env["MARIADB_USER"] != USER:
        raise SystemExit(f"Expected MARIADB_USER={USER}")
    if env["MARIADB_DATABASE"] != DATABASE:
        raise SystemExit(f"Expected MARIADB_DATABASE={DATABASE}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(env["MARIADB_PASSWORD"]), encoding="utf-8")
    OUT.chmod(0o600)
    print(f"Wrote {OUT.relative_to(ROOT)} (password not printed).")
    print("Run that file as MariaDB admin, then: .venv/bin/python scripts/test_db_access.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
