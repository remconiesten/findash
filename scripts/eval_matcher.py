#!/usr/bin/env python3
"""Leave-one-out matcher report. Counts only: no omschrijving, no IBAN.

Usage:
  PYTHONPATH=. .venv/bin/python scripts/eval_matcher.py
  PYTHONPATH=. .venv/bin/python scripts/eval_matcher.py --skip-qdrant
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "findash"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.config import load_settings
from app.db import connect
from app.embed import get_embedder
from app.hybrid import first_non_null, memory_suggestions, tally
from app.ingest import fetch_index_rows, point_id
from app.qdrant_io import _client, qdrant_enabled, redact_qdrant_error, search_own
from app.studio import suggestion_from_neighbors

BATCH = 32


def _pct(num: int, den: int) -> str:
    if not den:
        return "n/a"
    return f"{100.0 * num / den:5.1f}%"


def _print_tally(name: str, t: dict[str, Any]) -> None:
    print(
        f"{name:<36} shown={t['shown']:5d}  silent={t['silent']:5d}  "
        f"hoofd {_pct(t['hoofd_ok'], t['shown'])}  pair {_pct(t['pair_ok'], t['shown'])}"
    )


def _confusion(
    gold: list[tuple[str, str]],
    suggested: list[dict[str, Any] | None],
    *,
    limit: int = 8,
) -> None:
    pairs: Counter[tuple[str, str]] = Counter()
    for (gh, _gs), sug in zip(gold, suggested):
        if not sug:
            continue
        sh = sug.get("hoofd") or ""
        if sh != gh:
            pairs[(gh, sh)] += 1
    if not pairs:
        print("  (geen andere-hoofd onder getoonde voorstellen)")
        return
    print("  andere hoofd (getoond, n≥2):")
    for (a, b), n in pairs.most_common(limit):
        if n < 2:
            break
        print(f"    {a} -> {b}: {n}")


def _knn_from_row(cs: dict[str, Any] | None, *, unanimous_only: bool) -> dict[str, Any] | None:
    if not cs:
        return None
    if unanimous_only and not int(cs.get("unanimous") or 0):
        return None
    if not cs.get("hoofd") or not cs.get("sub"):
        return None
    return {
        "hoofd": cs["hoofd"],
        "sub": cs["sub"],
        "layer": "knn",
        "unanimous": bool(int(cs.get("unanimous") or 0)),
    }


def _load_suggestions() -> dict[tuple[str, str], dict[str, Any]]:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT src, transactie_id, hoofd, sub, unanimous, disagrees, score
                FROM category_suggestion
                """
            )
            out = {}
            for row in cur.fetchall():
                out[(row["src"], row["transactie_id"])] = row
            return out
    finally:
        conn.close()


def _flatten(index_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flat = []
    for row in index_rows:
        payload = row["payload"]
        flat.append(
            {
                "src": row["src"],
                "transactie_id": row["transactie_id"],
                "index_text": row["index_text"],
                "richting": payload.get("richting") or "",
                "entiteit": payload.get("entiteit") or "",
                "hoofd": payload.get("hoofd") or "",
                "sub": payload.get("sub") or "",
                "flow_kind": payload.get("flow_kind") or "",
            }
        )
    return flat


def _knn_live(
    index_rows: list[dict[str, Any]],
    settings: dict[str, str],
    *,
    same_richting: bool,
) -> list[dict[str, Any] | None]:
    embedder = get_embedder(settings)
    client = _client(settings, timeout=20)
    out: list[dict[str, Any] | None] = []
    try:
        for start in range(0, len(index_rows), BATCH):
            chunk = index_rows[start : start + BATCH]
            vectors = embedder.embed_queries([row["index_text"] for row in chunk])
            for row, vector in zip(chunk, vectors):
                richting = row["payload"].get("richting") or ""
                try:
                    neighbors = search_own(
                        settings,
                        vector,
                        limit=5,
                        exclude_point_id=point_id(row["src"], row["transactie_id"]),
                        richting=richting if same_richting else None,
                        client=client,
                    )
                except Exception as exc:
                    print(f"FAIL: {redact_qdrant_error(exc)}")
                    raise
                sug = suggestion_from_neighbors(neighbors)
                if not sug:
                    out.append(None)
                    continue
                hit = {
                    "hoofd": sug["hoofd"],
                    "sub": sug["sub"],
                    "layer": "knn",
                    "unanimous": bool(sug.get("unanimous")),
                    "mixed": bool(sug.get("mixed")),
                }
                out.append(hit)
            done = start + len(chunk)
            if done % 512 < BATCH or done == len(index_rows):
                print(f"  knn {done}/{len(index_rows)}", flush=True)
    finally:
        client.close()
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-qdrant", action="store_true")
    args = parser.parse_args()
    print("leave-one-out matcher (counts only, geen PII)")
    index_rows, stats = fetch_index_rows()
    print(
        f"indexed={stats['indexed']} skipped_structural={stats['skipped_structural']}"
    )
    flat = _flatten(index_rows)
    gold = [(r["hoofd"], r["sub"]) for r in flat]
    stored = _load_suggestions()
    print(f"category_suggestion={len(stored)}")

    knn_all = [
        _knn_from_row(stored.get((r["src"], r["transactie_id"])), unanimous_only=False)
        for r in flat
    ]
    knn_unan = [
        _knn_from_row(stored.get((r["src"], r["transactie_id"])), unanimous_only=True)
        for r in flat
    ]
    memory = memory_suggestions(flat)
    mem_then_unan = [
        first_non_null(mem, knn) for mem, knn in zip(memory, knn_unan)
    ]

    print()
    print("variant")
    a = tally(gold, knn_all)
    _print_tally("A  k-NN altijd (huidig)", a)
    _confusion(gold, knn_all)
    b = tally(gold, knn_unan)
    _print_tally("B  k-NN alleen unaniem", b)
    _confusion(gold, knn_unan)
    m = tally(gold, memory)
    _print_tally("M  geheugen tekst/entiteit LOO", m)
    _confusion(gold, memory)
    d = tally(gold, mem_then_unan)
    _print_tally("D  geheugen, anders B", d)
    _confusion(gold, mem_then_unan)

    mem_hits = sum(1 for x in memory if x)
    text_hits = sum(1 for x in memory if x and x.get("source") == "text")
    ent_hits = sum(1 for x in memory if x and x.get("source") == "entity")
    print(f"geheugen hits: {mem_hits} (tekst={text_hits} entiteit={ent_hits})")

    settings = load_settings()
    if args.skip_qdrant or not qdrant_enabled(settings):
        print()
        print("Qdrant overgeslagen (--skip-qdrant of niet geconfigureerd).")
        print("Validatie: kijk of M/D de GUI-lijst kort genoeg maken; C/E volgen met Qdrant.")
        return 0

    print()
    print("C  k-NN zelfde richting (live)…")
    knn_dir = _knn_live(index_rows, settings, same_richting=True)
    knn_dir_unan = [
        hit if hit and hit.get("unanimous") else None for hit in knn_dir
    ]
    c_all = tally(gold, knn_dir)
    _print_tally("C  k-NN zelfde richting", c_all)
    _confusion(gold, knn_dir)
    c = tally(gold, knn_dir_unan)
    _print_tally("C' k-NN richting + unaniem", c)
    _confusion(gold, knn_dir_unan)
    e_hits = [
        first_non_null(mem, knn) for mem, knn in zip(memory, knn_dir_unan)
    ]
    e = tally(gold, e_hits)
    _print_tally("E  geheugen, anders C'", e)
    _confusion(gold, e_hits)

    print()
    print(
        "Validatie: geen GUI tot jij een variant kiest. "
        "Verwacht: E of D als productregel (kort + hoge hoofd_acc op getoonde voorstellen)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
