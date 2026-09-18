#!/usr/bin/env python3
"""Fill category_suggestion from text memory only (no k-NN proposals)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "findash"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.db import connect
from app.hybrid import memory_suggestions, propose
from app.ingest import fetch_index_rows
from app.studio import ensure_suggestion_layer

BATCH = 256


def _flatten(index_rows: list[dict]) -> list[dict]:
    out = []
    for row in index_rows:
        payload = row["payload"]
        out.append(
            {
                "src": row["src"],
                "transactie_id": row["transactie_id"],
                "index_text": row["index_text"],
                "richting": payload.get("richting") or "",
                "hoofd": payload.get("hoofd") or "",
                "sub": payload.get("sub") or "",
            }
        )
    return out


def main() -> int:
    rows, stats = fetch_index_rows()
    print(
        f"refresh suggestions indexed={stats['indexed']} "
        f"(skip structural={stats['skipped_structural']})"
    )
    flat = _flatten(rows)
    memory = memory_suggestions(flat)
    conn = connect()
    disagrees = 0
    written = 0
    text_n = 0
    none_n = 0
    try:
        with conn.cursor() as cur:
            ensure_suggestion_layer(cur)
            for start in range(0, len(rows), BATCH):
                chunk = rows[start : start + BATCH]
                mem_chunk = memory[start : start + len(chunk)]
                for row, mem in zip(chunk, mem_chunk):
                    if not row.get("transactie_id"):
                        continue
                    sug = propose(mem)
                    payload = row["payload"]
                    if sug:
                        score = sug.get("share")
                        if score is None:
                            score = sug.get("score") or 0
                        mismatch = (sug["hoofd"], sug["sub"]) != (
                            payload["hoofd"],
                            payload["sub"],
                        )
                        hoofd, sub = sug["hoofd"], sug["sub"]
                        unan = 1 if sug.get("unanimous") else 0
                        n_nb = int(sug.get("n") or 0)
                        text_n += 1
                    else:
                        score = 0
                        mismatch = False
                        hoofd, sub = payload["hoofd"] or "", payload["sub"] or ""
                        unan = 0
                        n_nb = 0
                        none_n += 1
                    if mismatch:
                        disagrees += 1
                    cur.execute(
                        """
                        REPLACE INTO category_suggestion
                          (src, transactie_id, hoofd, sub, score, unanimous,
                           neighbor_n, layer, disagrees)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            row["src"],
                            row["transactie_id"],
                            hoofd or payload["hoofd"] or "?",
                            sub or payload["sub"] or "?",
                            score,
                            unan,
                            n_nb,
                            "text" if sug else "none",
                            1 if mismatch else 0,
                        ),
                    )
                    written += 1
                print(
                    f"  written={written}/{stats['indexed']} "
                    f"disagrees={disagrees} text={text_n} none={none_n}"
                )
        print(
            f"OK written={written} disagrees={disagrees} "
            f"text={text_n} none={none_n}"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
