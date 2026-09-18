#!/usr/bin/env python3
"""Distinct FinBot terms for the translation seed. No Raw, no IBAN dump."""

from __future__ import annotations

import sys

import pymysql

from db_env import load_env

NAMESPACES = {
    "hoofd": "Hoofdcategorie",
    "sub": "Subcategorie",
    "af_bij": "Af Bij",
    "mutatiesoort": "Mutatiesoort",
    "rekening": "Rekening",
}


def main() -> int:
    env = load_env()
    conn = pymysql.connect(
        host=env["MARIADB_HOST"],
        port=int(env["MARIADB_PORT"]),
        user=env["MARIADB_USER"],
        password=env["MARIADB_PASSWORD"],
        database=env["MARIADB_DATABASE"],
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            for ns, col in NAMESPACES.items():
                ident = "`" + col.replace("`", "``") + "`"
                cur.execute(
                    f"SELECT DISTINCT {ident} FROM FinBotTransactions "
                    f"UNION SELECT DISTINCT {ident} FROM FinBotTransactionsCC"
                    if col != "Mutatiesoort"
                    else f"SELECT DISTINCT {ident} FROM FinBotTransactions"
                )
                values = sorted({r[0] for r in cur.fetchall() if r[0]})
                print(f"## {ns} ({len(values)})")
                for v in values:
                    print(v)
                print()
            cur.execute("SELECT DISTINCT `Type` FROM FinBotTransactionsCC")
            types = sorted({r[0] for r in cur.fetchall() if r[0]})
            print(f"## cc_type ({len(types)})")
            for v in types:
                print(v)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
