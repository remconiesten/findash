#!/usr/bin/env python3
"""Copy FinBot tables n8n → findash inside MariaDB.

Row payloads never leave the server: CREATE LIKE + INSERT SELECT.
Stdout is counts and schema checks only. No Raw table.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import pymysql
from pymysql.err import OperationalError, ProgrammingError

from db_env import load_env

TABLES = ("FinBotTransactions", "FinBotTransactionsCC")
FORBIDDEN = "FinBotTransactionsRaw"
SIMILARITY_COL = "Similarity"


def qident(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def connect(env: dict[str, str]) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=env["MARIADB_HOST"],
        port=int(env["MARIADB_PORT"]),
        user=env["MARIADB_USER"],
        password=env["MARIADB_PASSWORD"],
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=8,
        read_timeout=120,
        cursorclass=pymysql.cursors.DictCursor,
    )


def table_exists(cur, schema: str, table: str) -> bool:
    cur.execute(
        """
        SELECT COUNT(*) AS n
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        """,
        (schema, table),
    )
    return int(cur.fetchone()["n"]) == 1


def column_exists(cur, schema: str, table: str, column: str) -> bool:
    cur.execute(
        """
        SELECT COUNT(*) AS n
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """,
        (schema, table, column),
    )
    return int(cur.fetchone()["n"]) == 1


def stats(cur, schema: str, table: str) -> dict[str, Any]:
    ident = f"{qident(schema)}.{qident(table)}"
    cur.execute(
        f"""
        SELECT COUNT(*) AS n,
               COUNT(DISTINCT TransactieID) AS nd,
               MIN(CHAR_LENGTH(TransactieID)) AS id_min,
               MAX(CHAR_LENGTH(TransactieID)) AS id_max
        FROM {ident}
        """
    )
    row = cur.fetchone()
    extra = {"similarity_nulls": None, "has_similarity": False}
    if column_exists(cur, schema, table, SIMILARITY_COL):
        extra["has_similarity"] = True
        cur.execute(
            f"""
            SELECT SUM(CASE WHEN {qident(SIMILARITY_COL)} IS NULL THEN 1 ELSE 0 END) AS n
            FROM {ident}
            """
        )
        extra["similarity_nulls"] = int(cur.fetchone()["n"] or 0)
    return {**row, **extra}


def print_stats(label: str, row: dict[str, Any]) -> None:
    sim = (
        f" similarity_nulls={row['similarity_nulls']}"
        if row["has_similarity"]
        else " similarity=absent"
    )
    print(
        f"  {label}: n={row['n']} distinct_id={row['nd']} "
        f"id_len={row['id_min']}-{row['id_max']}{sim}"
    )


def copy_table(cur, src: str, dest: str, table: str, *, dry_run: bool) -> None:
    if table == FORBIDDEN:
        raise RuntimeError("refusing forbidden table")
    if not table_exists(cur, src, table):
        raise RuntimeError(f"missing source {src}.{table}")
    src_stats = stats(cur, src, table)
    print_stats(f"{src}.{table}", src_stats)
    if src_stats["n"] != src_stats["nd"]:
        raise RuntimeError(f"{src}.{table}: TransactieID is not unique")
    if src_stats["id_min"] != 32 or src_stats["id_max"] != 32:
        raise RuntimeError(f"{src}.{table}: TransactieID length is not 32")

    dest_present = table_exists(cur, dest, table)
    if dest_present:
        dest_stats = stats(cur, dest, table)
        print_stats(f"{dest}.{table}", dest_stats)
        if (
            dest_stats["n"] == src_stats["n"]
            and dest_stats["nd"] == src_stats["nd"]
            and dest_stats["has_similarity"]
            and dest_stats["similarity_nulls"] == dest_stats["n"]
        ):
            print(f"  skip: {dest}.{table} already matches source")
            return
        raise RuntimeError(
            f"{dest}.{table} exists but does not match a completed copy. "
            "Inspect in phpMyAdmin; this script will not DROP it."
        )

    if dry_run:
        print(f"  dry-run: would CREATE LIKE + INSERT SELECT + ADD {SIMILARITY_COL}")
        return

    src_ident = f"{qident(src)}.{qident(table)}"
    dest_ident = f"{qident(dest)}.{qident(table)}"
    cur.execute(f"CREATE TABLE {dest_ident} LIKE {src_ident}")
    cur.execute(f"INSERT INTO {dest_ident} SELECT * FROM {src_ident}")
    inserted = cur.rowcount
    print(f"  inserted={inserted}")
    cur.execute(
        f"ALTER TABLE {dest_ident} "
        f"ADD COLUMN {qident(SIMILARITY_COL)} DECIMAL(6,4) NULL "
        f"AFTER {qident('Confidence')}"
    )
    cur.execute(f"SELECT COALESCE(MAX(id), 0) + 1 AS nxt FROM {dest_ident}")
    nxt = int(cur.fetchone()["nxt"])
    cur.execute(f"ALTER TABLE {dest_ident} AUTO_INCREMENT = {nxt}")
    after = stats(cur, dest, table)
    print_stats(f"{dest}.{table}", after)
    if after["n"] != src_stats["n"] or after["nd"] != src_stats["nd"]:
        raise RuntimeError("count mismatch after copy")
    if after["similarity_nulls"] != after["n"]:
        raise RuntimeError("Similarity must be NULL on copied rows")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    env = load_env()
    src = "n8n"
    dest = env.get("FINDASH_DATABASE") or "findash"
    if src == dest:
        print("FAIL: source n8n and FINDASH_DATABASE are the same")
        return 1
    print(
        f"copy {src} → {dest} as {env['MARIADB_USER']} "
        f"({'dry-run' if args.dry_run else 'write'}); passwords not printed"
    )
    try:
        conn = connect(env)
    except OperationalError as exc:
        print(f"FAIL: connect: {exc.args[0] if exc.args else exc}")
        return 1
    try:
        with conn.cursor() as cur:
            if table_exists(cur, src, FORBIDDEN):
                print(f"  note: {src}.{FORBIDDEN} exists; this script does not read it")
            if table_exists(cur, dest, FORBIDDEN):
                print(f"FAIL: {dest}.{FORBIDDEN} already exists; refusing to continue")
                return 1
            for table in TABLES:
                try:
                    copy_table(cur, src, dest, table, dry_run=args.dry_run)
                except (RuntimeError, ProgrammingError) as exc:
                    print(f"FAIL: {exc}")
                    return 1
            if table_exists(cur, dest, FORBIDDEN):
                print(f"FAIL: {dest}.{FORBIDDEN} appeared; unexpected")
                return 1
            print("OK")
            return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
