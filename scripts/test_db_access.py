#!/usr/bin/env python3
"""Probe MariaDB as findash: connect, SELECT, confirm grants stay read-only."""

from __future__ import annotations

import re
import sys
from typing import Iterable

import pymysql
from pymysql.err import OperationalError, ProgrammingError

from db_env import load_env

ALLOWED_TABLES = {"FinBotTransactions", "FinBotTransactionsCC"}
FORBIDDEN_TABLES = ("FinBotTransactionsRaw",)
# Match privilege names, not the leading "GRANT" in SHOW GRANTS output.
WRITE_PRIVS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|SUPER|FILE|TRIGGER|"
    r"REFERENCES|INDEX|EVENT|EXECUTE|PROCESS|RELOAD|SHUTDOWN|LOCK TABLES|"
    r"REPLICATION|ALL PRIVILEGES|GRANT OPTION)\b",
    re.IGNORECASE,
)
IDENTIFIED_BY = re.compile(r"\s+IDENTIFIED BY\b.*", re.IGNORECASE)


def redact_grant(line: str) -> str:
    return IDENTIFIED_BY.sub(" IDENTIFIED BY <redacted>", line)


def connect(env: dict[str, str]) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=env["MARIADB_HOST"],
        port=int(env["MARIADB_PORT"]),
        user=env["MARIADB_USER"],
        password=env["MARIADB_PASSWORD"],
        database=env["MARIADB_DATABASE"],
        connect_timeout=8,
        read_timeout=15,
        charset="utf8mb4",
        autocommit=False,
    )


def fetch_one(cur, sql: str):
    cur.execute(sql)
    return cur.fetchone()


def fail(message: str) -> int:
    print(f"FAIL: {message}")
    return 1


def grants_are_readonly(grants: Iterable[str]) -> list[str]:
    problems = []
    saw_select = False
    for raw in grants:
        line = redact_grant(raw)
        if re.search(r"\bSELECT\b", line, re.IGNORECASE):
            saw_select = True
        if WRITE_PRIVS.search(line):
            problems.append(line)
        if "GRANT OPTION" in line.upper():
            problems.append(line)
    if not saw_select:
        problems.append("no SELECT privilege visible in SHOW GRANTS")
    return problems


def table_select_ok(cur, table: str) -> tuple[bool, str]:
    try:
        cur.execute(f"SELECT 1 FROM `{table}` LIMIT 1")
        cur.fetchall()
        return True, "SELECT ok"
    except (ProgrammingError, OperationalError) as exc:
        return False, exc.args[0] if exc.args else str(exc)


def main() -> int:
    env = load_env()
    host = env["MARIADB_HOST"]
    port = env["MARIADB_PORT"]
    user = env["MARIADB_USER"]
    print(f"Connecting to {host}:{port} as {user} (password not printed)...")
    try:
        conn = connect(env)
    except OperationalError as exc:
        detail = exc.args[1] if len(exc.args) > 1 else str(exc)
        hint = ""
        if "Access denied" in str(detail):
            hint = (
                " Run docs/sql/create-findash-user.local.sql as MariaDB admin, "
                "or put an existing findash password in .env."
            )
        return fail(f"connect failed: {detail}.{hint}")

    errors: list[str] = []
    try:
        with conn.cursor() as cur:
            user_row = fetch_one(cur, "SELECT USER(), CURRENT_USER(), DATABASE()")
            print(f"USER()={user_row[0]}  CURRENT_USER()={user_row[1]}  DATABASE()={user_row[2]}")

            cur.execute("SHOW GRANTS")
            grants = [row[0] for row in cur.fetchall()]
            print("Grants:")
            for line in grants:
                print(f"  {redact_grant(line)}")
            for problem in grants_are_readonly(grants):
                errors.append(f"privilege too broad: {problem}")

            for table in sorted(ALLOWED_TABLES):
                ok, detail = table_select_ok(cur, table)
                print(f"Table {table}: {detail}")
                if not ok:
                    errors.append(f"expected SELECT on {table}: {detail}")

            for table in FORBIDDEN_TABLES:
                ok, detail = table_select_ok(cur, table)
                if ok:
                    # HA MariaDB add-on can only GRANT on a whole database.
                    # Decision: accept n8n.*; dashboard and probes must not query Raw.
                    print(f"Table {table}: SELECT possible (accepted: add-on GRANT on n8n.*)")
                else:
                    print(f"Table {table}: denied")
    finally:
        conn.close()

    if errors:
        for item in errors:
            print(f"FAIL: {item}")
        return 1
    print("OK: connected, SELECT on both FinBot tables, grants look read-only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
