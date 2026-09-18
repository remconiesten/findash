#!/usr/bin/env python3
"""Embed findash bank+CC rows into Qdrant collection findash_tx.

Counts only on stdout. No payloads, no omschrijving, no API key.
Skips structural flow_kind. Never writes to FinBot collections.
Requires: pip install -r requirements-qdrant.txt
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "findash"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.config import load_settings
from app.embed import Embedder
from app.ingest import build_points, fetch_index_rows
from app.qdrant_io import (
    OWN_COLLECTION,
    assert_own_collection,
    ensure_own_collection,
    own_points_count,
    qdrant_enabled,
    redact_qdrant_error,
    upsert_own_points,
)

BATCH = 64


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    try:
        target = assert_own_collection(
            settings.get("FINDASH_QDRANT_COLLECTION") or OWN_COLLECTION
        )
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 2
    if not qdrant_enabled(settings):
        print("FAIL: QDRANT_URL and QDRANT_API_KEY must be set")
        return 2
    cache_root = ROOT / ".cache"
    hf_home = cache_root / "huggingface"
    hf_home.mkdir(parents=True, exist_ok=True)
    (cache_root / "fastembed").mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(hf_home)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(hf_home)
    os.environ["HF_HUB_CACHE"] = str(hf_home)
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    print(f"ingest → {target}; api_key: set; dry_run={args.dry_run}")
    rows, stats = fetch_index_rows()
    print(
        f"  bank_read={stats['bank_read']} cc_read={stats['cc_read']} "
        f"skipped_structural={stats['skipped_structural']} indexed={stats['indexed']}"
    )
    if args.dry_run:
        print("OK: dry-run (no embed, no upsert)")
        return 0
    try:
        status = ensure_own_collection(settings)
        print(f"  collection: {status}")
        cache = ROOT / settings["FINDASH_EMBED_CACHE"]
        embedder = Embedder(
            model_name=settings["FINDASH_EMBED_MODEL"],
            cache_dir=cache,
        )
        upserted = 0
        for start in range(0, len(rows), BATCH):
            chunk = rows[start : start + BATCH]
            vectors = embedder.embed_passages([row["index_text"] for row in chunk])
            points = build_points(chunk, vectors)
            upserted += upsert_own_points(settings, points)
            if start == 0 or upserted == stats["indexed"] or upserted % 512 == 0:
                print(f"  upserted={upserted}/{stats['indexed']}")
        count = own_points_count(settings)
        print(f"  {target} points={count}")
    except Exception as exc:
        hint = ""
        text = str(exc).lower()
        if "download" in text or "huggingface" in text or "permission" in text:
            hint = " (model cache: .cache/fastembed and .cache/huggingface)"
        print(f"FAIL: {redact_qdrant_error(exc)}{hint}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
