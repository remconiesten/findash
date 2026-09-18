#!/usr/bin/env python3
"""Move a (hoofd, sub) pair on findash copies. No n8n, no Raw, counts only.

Default is dry-run. Pass --apply to write MariaDB + Qdrant payload (hoofd only).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "findash"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.config import load_settings
from app.db import connect, tx_ident, tx_schema
from app.ingest import point_id
from app.qdrant_io import patch_own_payload, qdrant_enabled, redact_qdrant_error
from app.studio import is_structural_target

SOURCES = (("bank", "FinBotTransactions"), ("cc", "FinBotTransactionsCC"))


def validate_move(from_hoofd: str, to_hoofd: str, sub: str) -> None:
    from_hoofd = (from_hoofd or "").strip()
    to_hoofd = (to_hoofd or "").strip()
    sub = (sub or "").strip()
    if not from_hoofd or not to_hoofd or not sub:
        raise ValueError("from_hoofd, to_hoofd and sub are required")
    if from_hoofd == to_hoofd:
        raise ValueError("from_hoofd and to_hoofd are the same")
    if is_structural_target(from_hoofd, sub) or is_structural_target(to_hoofd, sub):
        raise ValueError("refusing structural pair")


def _count_sql(table: str) -> str:
    return f"""
        SELECT Hoofdcategorie AS hoofd, Subcategorie AS sub, COUNT(*) AS n
        FROM {table}
        WHERE Subcategorie = %s AND Hoofdcategorie IN (%s, %s)
        GROUP BY Hoofdcategorie, Subcategorie
        ORDER BY Hoofdcategorie
        """


def _id_sql(table: str) -> str:
    return f"""
        SELECT TransactieID AS transactie_id
        FROM {table}
        WHERE Hoofdcategorie = %s AND Subcategorie = %s
        """


def _update_sql(table: str) -> str:
    return f"""
        UPDATE {table}
        SET Hoofdcategorie = %s
        WHERE Hoofdcategorie = %s AND Subcategorie = %s
        """


def snapshot(cur, sub: str, from_hoofd: str, to_hoofd: str) -> dict[str, Any]:
    out: dict[str, Any] = {"by_src": {}}
    for src, name in SOURCES:
        table = tx_ident(name)
        cur.execute(_count_sql(table), (sub, from_hoofd, to_hoofd))
        counts = {(row["hoofd"], row["sub"]): int(row["n"]) for row in cur.fetchall()}
        cur.execute(_id_sql(table), (from_hoofd, sub))
        ids = [row["transactie_id"] for row in cur.fetchall()]
        out["by_src"][src] = {
            "from_n": counts.get((from_hoofd, sub), 0),
            "to_n": counts.get((to_hoofd, sub), 0),
            "ids": ids,
        }
    cur.execute(
        """
        SELECT COUNT(*) AS n FROM category_suggestion
        WHERE hoofd = %s AND sub = %s
        """,
        (from_hoofd, sub),
    )
    row = cur.fetchone() or {}
    out["suggestion_from_n"] = int(row.get("n") or 0)
    return out


def print_snapshot(label: str, snap: dict[str, Any], *, from_hoofd: str, to_hoofd: str, sub: str) -> None:
    print(f"{label} pair {from_hoofd}/{sub} → {to_hoofd}/{sub}")
    for src, data in snap["by_src"].items():
        print(
            f"  {src}: from_n={data['from_n']} to_n={data['to_n']} "
            f"move_ids={len(data['ids'])}"
        )
    print(f"  suggestions from_n={snap['suggestion_from_n']}")


def apply_sql(cur, *, from_hoofd: str, to_hoofd: str, sub: str) -> dict[str, int]:
    written = {"bank": 0, "cc": 0, "suggestion": 0}
    for src, name in SOURCES:
        table = tx_ident(name)
        cur.execute(_update_sql(table), (to_hoofd, from_hoofd, sub))
        written[src] = int(cur.rowcount or 0)
    cur.execute(
        """
        UPDATE category_suggestion
        SET hoofd = %s
        WHERE hoofd = %s AND sub = %s
        """,
        (to_hoofd, from_hoofd, sub),
    )
    written["suggestion"] = int(cur.rowcount or 0)
    return written


def patch_qdrant(settings: dict[str, str], to_hoofd: str, by_src: dict[str, Any]) -> tuple[int, int]:
    if not qdrant_enabled(settings):
        print("  qdrant: skipped (not enabled)")
        return 0, 0
    ok = 0
    failed = 0
    for src, data in by_src.items():
        for txid in data["ids"]:
            try:
                patch_own_payload(settings, point_id(src, txid), {"hoofd": to_hoofd})
                ok += 1
            except Exception as exc:
                failed += 1
                print(f"  qdrant patch fail src={src}: {redact_qdrant_error(exc)}")
    print(f"  qdrant patched={ok} failed={failed}")
    return ok, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-hoofd", required=True)
    parser.add_argument("--to-hoofd", required=True)
    parser.add_argument("--sub", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write findash rows, suggestions, and Qdrant payload. Default: dry-run.",
    )
    args = parser.parse_args()
    from_hoofd = args.from_hoofd.strip()
    to_hoofd = args.to_hoofd.strip()
    sub = args.sub.strip()
    try:
        validate_move(from_hoofd, to_hoofd, sub)
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 1
    schema = tx_schema()
    if schema == "n8n":
        print("FAIL: refusing to write n8n; set MARIADB_DATABASE=findash")
        return 1
    mode = "apply" if args.apply else "dry-run"
    print(f"relabel {schema} ({mode}); passwords not printed")
    conn = connect()
    try:
        with conn.cursor() as cur:
            before = snapshot(cur, sub, from_hoofd, to_hoofd)
            print_snapshot("before", before, from_hoofd=from_hoofd, to_hoofd=to_hoofd, sub=sub)
            if not args.apply:
                print("OK dry-run (no writes)")
                return 0
            written = apply_sql(cur, from_hoofd=from_hoofd, to_hoofd=to_hoofd, sub=sub)
            print(
                f"  sql bank={written['bank']} cc={written['cc']} "
                f"suggestion={written['suggestion']}"
            )
            after = snapshot(cur, sub, from_hoofd, to_hoofd)
            print_snapshot("after", after, from_hoofd=from_hoofd, to_hoofd=to_hoofd, sub=sub)
            if after["by_src"]["bank"]["from_n"] or after["by_src"]["cc"]["from_n"]:
                print("FAIL: from-pair still has rows")
                return 1
    finally:
        conn.close()
    settings = load_settings()
    patch_qdrant(settings, to_hoofd, before["by_src"])
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
