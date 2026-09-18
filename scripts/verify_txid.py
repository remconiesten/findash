#!/usr/bin/env python3
"""Check TransactieID MD5 vs n8n recipe. SQL counts only — no row dumps, no IBANs.

Bank hash is verified on n8n.FinBotTransactionsRaw. CC on findash.FinBotTransactionsCC.
Does not read config/anonymize.local.json.
"""

from __future__ import annotations

import sys

import pymysql

from db_env import load_env

RAW = "`n8n`.`FinBotTransactionsRaw`"
BANK = "`findash`.`FinBotTransactions`"
CC = "`findash`.`FinBotTransactionsCC`"


def connect(env: dict[str, str]) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=env["MARIADB_HOST"],
        port=int(env["MARIADB_PORT"]),
        user=env["MARIADB_USER"],
        password=env["MARIADB_PASSWORD"],
        charset="utf8mb4",
        connect_timeout=8,
        read_timeout=120,
        cursorclass=pymysql.cursors.DictCursor,
    )


def one(cur, sql: str):
    cur.execute(sql)
    return cur.fetchone()


def ratio(label: str, matched: int, total: int) -> None:
    pct = (100.0 * matched / total) if total else 0.0
    print(f"  {label}: {matched}/{total} ({pct:.1f}%)")


def main() -> int:
    env = load_env()
    print(
        f"verify txid as {env['MARIADB_USER']} db={env['MARIADB_DATABASE']}; "
        "SQL aggregates only"
    )
    conn = connect(env)
    try:
        with conn.cursor() as cur:
            raw_n = one(cur, f"SELECT COUNT(*) AS n FROM {RAW}")["n"]
            bank_n = one(cur, f"SELECT COUNT(*) AS n FROM {BANK}")["n"]
            join_n = one(
                cur,
                f"""
                SELECT COUNT(*) AS n FROM {RAW} r
                INNER JOIN {BANK} t
                  ON TRIM(t.TransactieID) = TRIM(r.TransactieID)
                """,
            )["n"]
            print("== overlap Raw vs findash bank ==")
            print(f"  raw={raw_n} findash_bank={bank_n} id_join={join_n}")

            print("== bank MD5(Datum+Naam+Mededelingen+Saldo) vs Raw.TransactieID ==")
            bank_ok = int(
                one(
                    cur,
                    f"""
                    SELECT SUM(
                      LOWER(MD5(CONCAT(
                        IFNULL(`Datum`, ''),
                        IFNULL(`Naam / Omschrijving`, ''),
                        IFNULL(`Mededelingen`, ''),
                        IFNULL(`Saldo na mutatie`, '')
                      ))) = LOWER(TRIM(`TransactieID`))
                    ) AS m FROM {RAW}
                    """,
                )["m"]
                or 0
            )
            bank_no_med = int(
                one(
                    cur,
                    f"""
                    SELECT SUM(
                      LOWER(MD5(CONCAT(
                        IFNULL(`Datum`, ''),
                        IFNULL(`Naam / Omschrijving`, ''),
                        IFNULL(`Saldo na mutatie`, '')
                      ))) = LOWER(TRIM(`TransactieID`))
                    ) AS m FROM {RAW}
                    """,
                )["m"]
                or 0
            )
            ratio("recipe", bank_ok, raw_n)
            ratio("without Mededelingen (control)", bank_no_med, raw_n)

            print("== cc MD5(Datum+Omschrijving+Type+Mutatie) vs CC.TransactieID ==")
            cc_n = one(cur, f"SELECT COUNT(*) AS n FROM {CC}")["n"]
            cc_ok = int(
                one(
                    cur,
                    f"""
                    SELECT SUM(
                      LOWER(MD5(CONCAT(
                        IFNULL(`Datum`, ''),
                        IFNULL(`Omschrijving`, ''),
                        IFNULL(`Type`, ''),
                        IFNULL(`Mutatie`, '')
                      ))) = LOWER(TRIM(`TransactieID`))
                    ) AS m FROM {CC}
                    """,
                )["m"]
                or 0
            )
            cc_bedrag = int(
                one(
                    cur,
                    f"""
                    SELECT SUM(
                      LOWER(MD5(CONCAT(
                        IFNULL(`Datum`, ''),
                        IFNULL(`Omschrijving`, ''),
                        IFNULL(`Type`, ''),
                        IFNULL(CAST(`Bedrag` AS CHAR CHARACTER SET utf8mb4), '')
                      ))) = LOWER(TRIM(`TransactieID`))
                    ) AS m FROM {CC}
                    """,
                )["m"]
                or 0
            )
            ratio("recipe", cc_ok, cc_n)
            ratio("Type+Bedrag instead of Mutatie (control)", cc_bedrag, cc_n)

        failed = bank_ok != raw_n or cc_ok != cc_n or join_n != bank_n
        if failed:
            print("FAIL: recipe does not match stored TransactieID 100%")
            return 1
        print("OK: bank and CC recipes match stored TransactieID")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
