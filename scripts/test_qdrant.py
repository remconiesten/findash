#!/usr/bin/env python3
"""Connect to Qdrant: collection names + counts. Never print the API key or payloads.

Requires: pip install -r requirements-qdrant.txt
Does not read config/anonymize.local.json. Does not scroll points.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "findash"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.qdrant_io import (
    OWN_COLLECTION,
    ensure_own_collection,
    ping_collections,
    public_url,
    redact_qdrant_error,
)

ENV_PATH = ROOT / ".env"
_SECRET = re.compile(r"(?i)(api[_-]?key|authorization)[\"'\s:=]+[^\s,;]+")


def load_env_file(path: Path = ENV_PATH) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing {path}")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--init-collection",
        action="store_true",
        help=f"create {OWN_COLLECTION} if missing (never drops FinBot or others)",
    )
    args = parser.parse_args()
    try:
        env = load_env_file()
    except FileNotFoundError as exc:
        print(f"FAIL: {exc}")
        return 2
    url = env.get("QDRANT_URL") or ""
    key = env.get("QDRANT_API_KEY") or ""
    parsed = urlparse(url)
    print(f"QDRANT_URL={public_url(url) if url else 'missing'}")
    print(f"api_key: {'set' if key else 'missing'}")
    print(f"own_collection: {OWN_COLLECTION}")
    if not url or not key:
        print("FAIL: QDRANT_URL and QDRANT_API_KEY must be set in .env")
        return 2
    if parsed.hostname is None:
        print("FAIL: QDRANT_URL has no host")
        return 2
    settings = {
        "QDRANT_URL": url,
        "QDRANT_API_KEY": key,
        "FINDASH_QDRANT_COLLECTION": env.get("FINDASH_QDRANT_COLLECTION") or OWN_COLLECTION,
    }
    try:
        result = ping_collections(settings)
    except Exception as exc:
        print(f"FAIL: connect {redact_qdrant_error(exc)}")
        return 1
    print("collections:")
    foreign = []
    own_seen = False
    for row in result["collections"]:
        tag = "OWN" if row["own"] else "foreign"
        print(f"  {row['name']}  points={row['points']}  [{tag}]")
        if row["own"]:
            own_seen = True
        else:
            foreign.append(row["name"])
    if foreign:
        print(
            "existing collection(s) detected; findash remains on "
            f"{OWN_COLLECTION} and will not write to: {', '.join(foreign)}"
        )
    if args.init_collection:
        try:
            status = ensure_own_collection(settings)
        except Exception as exc:
            print(f"FAIL: init {redact_qdrant_error(exc)}")
            return 1
        print(f"{OWN_COLLECTION}: {status}")
        own_seen = True
    if not own_seen:
        print(f"note: {OWN_COLLECTION} not present yet (run with --init-collection)")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
