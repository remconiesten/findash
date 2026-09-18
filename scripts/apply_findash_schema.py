#!/usr/bin/env python3
"""Create findash.ui_string / term and seed NL+EN+RU. Uses .env MARIADB_*."""

from __future__ import annotations

import sys
from pathlib import Path

import pymysql

from db_env import load_env

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "findash" / "sql" / "migrations"
FILES = (
    "001_create_findash.sql",
    "002_seed_ui_string_nl.sql",
    "003_seed_en_ru.sql",
    "004_studio.sql",
    "005_suggestion.sql",
    "006_suggestion_layer.sql",
)


def _statements(sql: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    for raw in sql.splitlines():
        line = raw.strip()
        if not line or line.startswith("--"):
            continue
        buf.append(raw)
        if line.endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            buf = []
            if stmt:
                out.append(stmt)
    if buf:
        stmt = "\n".join(buf).strip().rstrip(";").strip()
        if stmt:
            out.append(stmt)
    return out


def main() -> int:
    env = load_env()
    schema = env.get("FINDASH_DATABASE") or "findash"
    conn = pymysql.connect(
        host=env["MARIADB_HOST"],
        port=int(env["MARIADB_PORT"]),
        user=env["MARIADB_USER"],
        password=env["MARIADB_PASSWORD"],
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=8,
        read_timeout=60,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{schema}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            print(f"database {schema}: ok")
            for name in FILES:
                path = MIGRATIONS / name
                sql = path.read_text(encoding="utf-8")
                n = 0
                for stmt in _statements(sql):
                    cur.execute(stmt)
                    n += 1
                print(f"{name}: {n} statements")
            cur.execute(f"SELECT COUNT(*) FROM `{schema}`.`ui_string`")
            ui = cur.fetchone()[0]
            cur.execute(f"SELECT COUNT(*) FROM `{schema}`.`term`")
            terms = cur.fetchone()[0]
            print(f"ui_string={ui} term={terms}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
