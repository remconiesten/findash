"""MariaDB access. Table names never come from request input."""

from __future__ import annotations

import time
from typing import Any, Iterable

import pymysql
from pymysql.err import OperationalError, ProgrammingError

from app.config import FINDASH_DB_ALLOWED, load_settings

FINBOT_TABLES = frozenset({"FinBotTransactions", "FinBotTransactionsCC"})
FINDASH_TABLES = frozenset({"ui_string", "term"})
FORBIDDEN = frozenset({"FinBotTransactionsRaw"})


class TimedCursor:
    def __init__(self, cur: Any, timings: list[tuple[str, float]]):
        self._cur = cur
        self._timings = timings

    def execute(self, name: str, sql: str, params: Iterable[Any] | None = None):
        start = time.perf_counter()
        self._cur.execute(sql, tuple(params or ()))
        ms = (time.perf_counter() - start) * 1000
        self._timings.append((name, ms))
        return self._cur

    def fetchall(self):
        return self._cur.fetchall()

    def fetchone(self):
        return self._cur.fetchone()


def connect():
    settings = load_settings()
    return pymysql.connect(
        host=settings["MARIADB_HOST"],
        port=int(settings["MARIADB_PORT"]),
        user=settings["MARIADB_USER"],
        password=settings["MARIADB_PASSWORD"],
        database=settings["MARIADB_DATABASE"],
        connect_timeout=8,
        read_timeout=30,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def findash_schema() -> str:
    name = load_settings()["FINDASH_DATABASE"]
    if name not in FINDASH_DB_ALLOWED:
        raise ValueError("invalid findash schema")
    return name


def assert_table(schema: str, table: str) -> None:
    if table in FORBIDDEN:
        raise ValueError("forbidden table")
    if schema in FINDASH_DB_ALLOWED and table in FINBOT_TABLES:
        return
    if schema in FINDASH_DB_ALLOWED and table in FINDASH_TABLES:
        return
    raise ValueError("table not on allowlist")


def tx_schema() -> str:
    name = load_settings()["MARIADB_DATABASE"]
    if name not in FINDASH_DB_ALLOWED:
        raise ValueError("invalid transaction schema")
    return name


def tx_ident(table: str) -> str:
    schema = tx_schema()
    assert_table(schema, table)
    return f"{qident(schema)}.{qident(table)}"


def qident(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def ping() -> str:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return "ok"
    finally:
        conn.close()


def select1() -> bool:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    finally:
        conn.close()


def ui_string_exists() -> bool:
    schema = findash_schema()
    assert_table(schema, "ui_string")
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT 1 FROM {qident(schema)}.{qident('ui_string')} LIMIT 1"
            )
            cur.fetchone()
        return True
    except (ProgrammingError, OperationalError):
        return False
    finally:
        conn.close()
