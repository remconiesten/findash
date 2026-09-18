#!/usr/bin/env python3
"""Audit Bij-rows that look like merchant refunds vs real income.

No Raw, no Tegenrekening, no Mededelingen, no IBAN dumps.
"""

from __future__ import annotations

import re
import sys
from decimal import Decimal

import pymysql

from db_env import load_env

IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
STRUCTURAL_HOOFD = frozenset({"Interne overboeking"})
STRUCTURAL_SUB = frozenset({"sparen", "van spaarrekening", "creditcard"})
REAL_INCOME_SUB = frozenset(
    {
        "salaris",
        "belastingteruggaaf",
        "kinderbijslag",
        "toeslagen",
        "bijdrage opa",
        "bijdrage kado",
        "uit bouwdepot",
        "van spaarrekening",
        "crypto verkoop",
        "laadvergoeding",
    }
)


def money(value) -> str:
    amount = Decimal(str(value or 0))
    return f"{amount.quantize(Decimal('0.01'))}"


def redact(value: str | None, limit: int = 60) -> str:
    if not value:
        return ""
    text = IBAN_RE.sub("…", str(value))
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def connect(env: dict[str, str]) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=env["MARIADB_HOST"],
        port=int(env["MARIADB_PORT"]),
        user=env["MARIADB_USER"],
        password=env["MARIADB_PASSWORD"],
        database=env["MARIADB_DATABASE"],
        connect_timeout=8,
        read_timeout=60,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def run(cur, sql: str, params=None):
    cur.execute(sql, params or ())
    return cur.fetchall()


def section(title: str) -> None:
    print(f"\n== {title} ==")


def main() -> int:
    env = load_env()
    conn = connect(env)
    try:
        with conn.cursor() as cur:
            section("bank Bij by flow bucket")
            rows = run(
                cur,
                """
                SELECT
                  CASE
                    WHEN Hoofdcategorie = 'Interne overboeking' THEN 'internal'
                    WHEN Subcategorie IN ('sparen', 'van spaarrekening') THEN 'saving'
                    WHEN Hoofdcategorie = 'Inkomsten' THEN 'income'
                    ELSE 'refund_or_other'
                  END AS bucket,
                  COUNT(*) AS n,
                  SUM(`Bedrag (EUR)`) AS eur
                FROM FinBotTransactions
                WHERE `Af Bij` = 'Bij'
                GROUP BY bucket
                ORDER BY n DESC
                """,
            )
            for row in rows:
                print(f"  {row['bucket']:18} n={row['n']:4}  €{money(row['eur'])}")

            section("Inkomsten Bij by sub")
            rows = run(
                cur,
                """
                SELECT Subcategorie, COUNT(*) AS n, SUM(`Bedrag (EUR)`) AS eur
                FROM FinBotTransactions
                WHERE `Af Bij` = 'Bij' AND Hoofdcategorie = 'Inkomsten'
                GROUP BY Subcategorie
                ORDER BY n DESC
                """,
            )
            for row in rows:
                flag = "" if row["Subcategorie"] in REAL_INCOME_SUB else "  <- not in real-income list"
                print(
                    f"  {row['Subcategorie'] or '(leeg)':22} n={row['n']:4}  "
                    f"€{money(row['eur'])}{flag}"
                )

            section("Inkomsten/overig Bij by Entiteit")
            rows = run(
                cur,
                """
                SELECT
                  Entiteit,
                  COUNT(*) AS n,
                  SUM(`Bedrag (EUR)`) AS eur,
                  MIN(`Bedrag (EUR)`) AS mn,
                  MAX(`Bedrag (EUR)`) AS mx
                FROM FinBotTransactions
                WHERE `Af Bij` = 'Bij'
                  AND Hoofdcategorie = 'Inkomsten'
                  AND Subcategorie = 'overig'
                GROUP BY Entiteit
                ORDER BY n DESC, eur DESC
                """,
            )
            for row in rows:
                print(
                    f"  {redact(row['Entiteit'] or '(leeg)', 40):40} "
                    f"n={row['n']:3}  €{money(row['eur']):>10}  "
                    f"min {money(row['mn'])}  max {money(row['mx'])}"
                )

            section("Entiteit on Inkomsten that also has expense Af")
            rows = run(
                cur,
                """
                SELECT
                  i.Entiteit,
                  i.Subcategorie AS income_sub,
                  i.n_in, i.eur_in,
                  e.n_af, e.eur_af,
                  e.hoofd_af, e.sub_af
                FROM (
                  SELECT
                    Entiteit, Subcategorie,
                    COUNT(*) AS n_in,
                    SUM(`Bedrag (EUR)`) AS eur_in
                  FROM FinBotTransactions
                  WHERE `Af Bij` = 'Bij' AND Hoofdcategorie = 'Inkomsten'
                  GROUP BY Entiteit, Subcategorie
                ) i
                JOIN (
                  SELECT
                    Entiteit,
                    COUNT(*) AS n_af,
                    SUM(`Bedrag (EUR)`) AS eur_af,
                    MIN(Hoofdcategorie) AS hoofd_af,
                    MIN(Subcategorie) AS sub_af
                  FROM FinBotTransactions
                  WHERE `Af Bij` = 'Af'
                    AND Hoofdcategorie NOT IN ('Inkomsten', 'Interne overboeking')
                    AND Subcategorie NOT IN ('sparen', 'creditcard')
                  GROUP BY Entiteit
                ) e ON e.Entiteit = i.Entiteit
                WHERE i.Entiteit IS NOT NULL AND i.Entiteit <> ''
                ORDER BY i.n_in DESC, e.n_af DESC
                """,
            )
            if not rows:
                print("  (geen overlap)")
            for row in rows:
                print(
                    f"  {redact(row['Entiteit'], 28):28}  "
                    f"ink {row['income_sub']:18} n={row['n_in']:3} €{money(row['eur_in']):>10}  |  "
                    f"Af {row['hoofd_af']}/{row['sub_af']} n={row['n_af']:3} €{money(row['eur_af'])}"
                )

            section("van spaarrekening Bij by Entiteit (should be saving, not shop)")
            rows = run(
                cur,
                """
                SELECT
                  Entiteit, COUNT(*) AS n, SUM(`Bedrag (EUR)`) AS eur,
                  MIN(`Bedrag (EUR)`) AS mn, MAX(`Bedrag (EUR)`) AS mx
                FROM FinBotTransactions
                WHERE `Af Bij` = 'Bij' AND Subcategorie = 'van spaarrekening'
                GROUP BY Entiteit
                ORDER BY n DESC
                """,
            )
            for row in rows:
                print(
                    f"  {redact(row['Entiteit'] or '(leeg)', 40):40} "
                    f"n={row['n']:3}  €{money(row['eur']):>10}  "
                    f"min {money(row['mn'])} max {money(row['mx'])}"
                )

            section("already-refund: Bij, not Inkomsten, not intern, not saving")
            rows = run(
                cur,
                """
                SELECT
                  Hoofdcategorie, Subcategorie, Entiteit,
                  COUNT(*) AS n, SUM(`Bedrag (EUR)`) AS eur
                FROM FinBotTransactions
                WHERE `Af Bij` = 'Bij'
                  AND Hoofdcategorie <> 'Inkomsten'
                  AND Hoofdcategorie <> 'Interne overboeking'
                  AND Subcategorie NOT IN ('sparen', 'van spaarrekening')
                GROUP BY Hoofdcategorie, Subcategorie, Entiteit
                ORDER BY n DESC, eur DESC
                """,
            )
            print(f"  groups={len(rows)}")
            for row in rows[:40]:
                print(
                    f"  {row['Hoofdcategorie']}/{row['Subcategorie']:18}  "
                    f"{redact(row['Entiteit'] or '', 28):28}  "
                    f"n={row['n']:3}  €{money(row['eur'])}"
                )
            if len(rows) > 40:
                print(f"  … {len(rows) - 40} more groups")

            totals = run(
                cur,
                """
                SELECT COUNT(*) AS n, SUM(`Bedrag (EUR)`) AS eur
                FROM FinBotTransactions
                WHERE `Af Bij` = 'Bij'
                  AND Hoofdcategorie <> 'Inkomsten'
                  AND Hoofdcategorie <> 'Interne overboeking'
                  AND Subcategorie NOT IN ('sparen', 'van spaarrekening')
                """,
            )[0]
            print(f"  TOTAL already-refund n={totals['n']}  €{money(totals['eur'])}")

            section("laadvergoeding Bij vs laadpaal Af")
            rows = run(
                cur,
                """
                SELECT
                  Hoofdcategorie, Subcategorie, `Af Bij` AS richting,
                  Entiteit, COUNT(*) AS n, SUM(`Bedrag (EUR)`) AS eur
                FROM FinBotTransactions
                WHERE Subcategorie IN ('laadvergoeding', 'laadpaal')
                GROUP BY Hoofdcategorie, Subcategorie, `Af Bij`, Entiteit
                ORDER BY Subcategorie, richting, n DESC
                """,
            )
            for row in rows:
                print(
                    f"  {row['richting']:3} {row['Hoofdcategorie']}/{row['Subcategorie']:16}  "
                    f"{redact(row['Entiteit'] or '', 28):28}  "
                    f"n={row['n']:3}  €{money(row['eur'])}"
                )

            section("CC Bij by Type / hoofd / sub")
            rows = run(
                cur,
                """
                SELECT
                  `Type` AS typ, `Af Bij` AS richting,
                  Hoofdcategorie, Subcategorie,
                  COUNT(*) AS n, SUM(Bedrag) AS eur
                FROM FinBotTransactionsCC
                WHERE `Af Bij` = 'Bij'
                GROUP BY `Type`, `Af Bij`, Hoofdcategorie, Subcategorie
                ORDER BY n DESC
                """,
            )
            for row in rows:
                print(
                    f"  {row['typ'] or '(leeg)':12} {row['richting']:3}  "
                    f"{row['Hoofdcategorie']}/{row['Subcategorie']:18}  "
                    f"n={row['n']:3}  €{money(row['eur'])}"
                )

            section("schema: TransactieID")
            rows = run(
                cur,
                """
                SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, COLUMN_KEY
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME IN ('FinBotTransactions', 'FinBotTransactionsCC')
                  AND COLUMN_NAME = 'TransactieID'
                """,
            )
            for row in rows:
                print(
                    f"  {row['TABLE_NAME']}.{row['COLUMN_NAME']} "
                    f"{row['COLUMN_TYPE']} key={row['COLUMN_KEY']}"
                )
            idx = run(
                cur,
                """
                SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, COLUMN_NAME, SEQ_IN_INDEX
                FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME IN ('FinBotTransactions', 'FinBotTransactionsCC')
                  AND COLUMN_NAME = 'TransactieID'
                ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
                """,
            )
            for row in idx:
                uniq = "UNIQUE" if row["NON_UNIQUE"] == 0 else "non-unique"
                print(
                    f"  index {row['TABLE_NAME']}.{row['INDEX_NAME']} "
                    f"{uniq} col={row['COLUMN_NAME']}"
                )
            lens = run(
                cur,
                """
                SELECT 'bank' AS src,
                       MIN(CHAR_LENGTH(TransactieID)) AS mn,
                       MAX(CHAR_LENGTH(TransactieID)) AS mx,
                       COUNT(*) AS n,
                       COUNT(DISTINCT TransactieID) AS nd
                FROM FinBotTransactions
                UNION ALL
                SELECT 'cc',
                       MIN(CHAR_LENGTH(TransactieID)),
                       MAX(CHAR_LENGTH(TransactieID)),
                       COUNT(*),
                       COUNT(DISTINCT TransactieID)
                FROM FinBotTransactionsCC
                """,
            )
            for row in lens:
                print(
                    f"  {row['src']:4} n={row['n']} distinct={row['nd']} "
                    f"id_len {row['mn']}-{row['mx']}"
                )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
