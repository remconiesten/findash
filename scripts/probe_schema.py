#!/usr/bin/env python3
"""Live schema + distincts. No Raw table, no IBAN/row dumps."""

from __future__ import annotations

import re
import sys
import time

import pymysql

from db_env import load_env

TABLES = ("FinBotTransactions", "FinBotTransactionsCC")
IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$", re.IGNORECASE)
NL_ACCT_RE = re.compile(r"^\d{6,14}$")  # numeric account-like
OTHER_ACCT_RE = re.compile(r"^[A-Z]\d{6,12}$", re.IGNORECASE)


def qident(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def timed(cur, sql: str, params=None):
    start = time.perf_counter()
    cur.execute(sql, params or ())
    rows = cur.fetchall()
    ms = (time.perf_counter() - start) * 1000
    return rows, ms


def looks_secret(value: str) -> bool:
    compact = re.sub(r"[\s.]", "", value)
    return bool(
        IBAN_RE.match(compact)
        or NL_ACCT_RE.match(compact)
        or OTHER_ACCT_RE.match(compact)
    )


def main() -> int:
    env = load_env()
    conn = pymysql.connect(
        host=env["MARIADB_HOST"],
        port=int(env["MARIADB_PORT"]),
        user=env["MARIADB_USER"],
        password=env["MARIADB_PASSWORD"],
        database=env["MARIADB_DATABASE"],
        connect_timeout=8,
        read_timeout=60,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            print(f"version={cur.fetchone()[0]}")

            cur.execute(
                """
                SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH, ENGINE
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME
                """
            )
            print("\n== tables (TABLE_ROWS is InnoDB estimate) ==")
            for name, nrows, data, idx, engine in cur.fetchall():
                print(f"  {name} engine={engine} est_rows={nrows} data={data} index={idx}")

            for table in TABLES:
                print(f"\n== {table} columns ==")
                cur.execute(
                    """
                    SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_DEFAULT
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                    ORDER BY ORDINAL_POSITION
                    """,
                    (table,),
                )
                cols = cur.fetchall()
                for col, typ, nullable, key, default in cols:
                    print(f"  {col} | {typ} | null={nullable} | key={key} | default={default}")

                print(f"\n== {table} indexes ==")
                cur.execute(
                    """
                    SELECT INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME
                    FROM information_schema.STATISTICS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                    ORDER BY INDEX_NAME, SEQ_IN_INDEX
                    """,
                    (table,),
                )
                idx_rows = cur.fetchall()
                if not idx_rows:
                    print("  (none)")
                for idx_name, nonuniq, seq, col in idx_rows:
                    kind = "unique" if nonuniq == 0 else "index"
                    print(f"  {idx_name} {kind} #{seq} {col}")

                count, ms = timed(cur, f"SELECT COUNT(*) FROM {qident(table)}")
                print(f"\n== {table} COUNT(*)={count[0][0]} ({ms:.0f} ms) ==")

            # Distinct vocab per table for columns that exist
            vocab_cols = (
                "Hoofdcategorie",
                "Subcategorie",
                "Af Bij",
                "Mutatiesoort",
                "Entiteit",
                "Rekening",
                "Code",
                "Tag",
            )
            for table in TABLES:
                cur.execute(
                    """
                    SELECT COLUMN_NAME FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                    """,
                    (table,),
                )
                have = {row[0] for row in cur.fetchall()}
                print(f"\n== {table} distincts ==")
                for col in vocab_cols:
                    if col not in have:
                        print(f"  {col}: (column absent)")
                        continue
                    rows, ms = timed(
                        cur,
                        f"SELECT {qident(col)} AS v, COUNT(*) AS n "
                        f"FROM {qident(table)} GROUP BY {qident(col)} ORDER BY n DESC",
                    )
                    print(f"  {col} ({len(rows)} values, {ms:.0f} ms)")
                    for value, n in rows:
                        shown = "<NULL>" if value is None else repr(value)
                        if isinstance(value, str) and looks_secret(value):
                            shown = f"<redacted len={len(value)}>"
                        print(f"    {n:6d}  {shown}")

                # Tegenrekening: counts only + non-secret labels
                if "Tegenrekening" in have:
                    rows, ms = timed(
                        cur,
                        f"SELECT {qident('Tegenrekening')} AS v, COUNT(*) AS n "
                        f"FROM {qident(table)} GROUP BY {qident('Tegenrekening')} ORDER BY n DESC",
                    )
                    secret = 0
                    labels = []
                    empty = 0
                    for value, n in rows:
                        if value is None or str(value).strip() == "":
                            empty += n
                        elif looks_secret(str(value)):
                            secret += n
                        else:
                            labels.append((n, value))
                    print(
                        f"  Tegenrekening ({len(rows)} distinct, {ms:.0f} ms): "
                        f"label_values={len(labels)} secret_like_rows={secret} empty_rows={empty}"
                    )
                    for n, value in labels[:40]:
                        print(f"    {n:6d}  {value!r}")

            # Category pairs
            for table in TABLES:
                cur.execute(
                    """
                    SELECT COLUMN_NAME FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                    """,
                    (table,),
                )
                have = {row[0] for row in cur.fetchall()}
                if "Hoofdcategorie" not in have or "Subcategorie" not in have:
                    continue
                extra = []
                if "Af Bij" in have:
                    extra.append(qident("Af Bij"))
                select_extra = (", " + ", ".join(extra)) if extra else ""
                group_extra = (", " + ", ".join(extra)) if extra else ""
                rows, ms = timed(
                    cur,
                    f"SELECT {qident('Hoofdcategorie')}, {qident('Subcategorie')}{select_extra}, "
                    f"COUNT(*) AS n FROM {qident(table)} "
                    f"GROUP BY {qident('Hoofdcategorie')}, {qident('Subcategorie')}{group_extra} "
                    f"ORDER BY {qident('Hoofdcategorie')}, {qident('Subcategorie')}",
                )
                print(f"\n== {table} hoofd×sub (± Af Bij) ({len(rows)} combos, {ms:.0f} ms) ==")
                for row in rows:
                    parts = [("<NULL>" if x is None else repr(x)) for x in row[:-1]]
                    print(f"    {row[-1]:6d}  " + " | ".join(parts))

            # Hypothesis checks: counts only
            print("\n== hypothesis counts (bank) ==")
            checks = [
                (
                    "interne hoofdcategorie",
                    "SELECT COUNT(*) FROM `FinBotTransactions` "
                    "WHERE `Hoofdcategorie` = 'Interne overboeking'",
                ),
                (
                    "sub creditcard",
                    "SELECT COUNT(*) FROM `FinBotTransactions` "
                    "WHERE `Subcategorie` = 'creditcard'",
                ),
                (
                    "sub sparen",
                    "SELECT COUNT(*) FROM `FinBotTransactions` "
                    "WHERE `Subcategorie` = 'sparen'",
                ),
                (
                    "sub van spaarrekening",
                    "SELECT COUNT(*) FROM `FinBotTransactions` "
                    "WHERE `Subcategorie` = 'van spaarrekening'",
                ),
                (
                    "hoofd Aflossing",
                    "SELECT COUNT(*) FROM `FinBotTransactions` "
                    "WHERE `Hoofdcategorie` = 'Aflossing'",
                ),
            ]
            for label, sql in checks:
                try:
                    rows, ms = timed(cur, sql)
                    print(f"  {label}: {rows[0][0]} ({ms:.0f} ms)")
                except Exception as exc:
                    print(f"  {label}: error {exc}")

            print("\n== hypothesis counts (CC) ==")
            cc_checks = [
                (
                    "hoofd Aflossing",
                    "SELECT COUNT(*) FROM `FinBotTransactionsCC` "
                    "WHERE `Hoofdcategorie` = 'Aflossing'",
                ),
                (
                    "Bij + Aflossing",
                    "SELECT COUNT(*) FROM `FinBotTransactionsCC` "
                    "WHERE `Af Bij` = 'Bij' AND `Hoofdcategorie` = 'Aflossing'",
                ),
            ]
            for label, sql in cc_checks:
                try:
                    rows, ms = timed(cur, sql)
                    print(f"  {label}: {rows[0][0]} ({ms:.0f} ms)")
                except Exception as exc:
                    print(f"  {label}: error {exc}")

            # Date range without dumping rows
            for table in TABLES:
                cur.execute(
                    """
                    SELECT COLUMN_NAME FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                    """,
                    (table,),
                )
                have = {row[0] for row in cur.fetchall()}
                date_col = "Datum" if "Datum" in have else None
                if date_col:
                    rows, ms = timed(
                        cur,
                        f"SELECT MIN({qident(date_col)}), MAX({qident(date_col)}) "
                        f"FROM {qident(table)}",
                    )
                    print(f"\n== {table} {date_col} min={rows[0][0]!r} max={rows[0][1]!r} ({ms:.0f} ms) ==")
                if "Jaar" in have and "Maand" in have:
                    rows, ms = timed(
                        cur,
                        f"SELECT {qident('Jaar')}, {qident('Maand')}, COUNT(*) "
                        f"FROM {qident(table)} GROUP BY {qident('Jaar')}, {qident('Maand')} "
                        f"ORDER BY {qident('Jaar')}, {qident('Maand')}",
                    )
                    print(f"== {table} jaar×maand ({len(rows)} buckets, {ms:.0f} ms) ==")
                    for jaar, maand, n in rows:
                        print(f"    {jaar}-{str(maand).zfill(2) if maand is not None else '??'}  {n}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
