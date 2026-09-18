#!/usr/bin/env python3
"""Map Supervisor /data/options.json to env, then exec uvicorn. No secret logs."""

from __future__ import annotations

import json
import os
from pathlib import Path

OPTIONS = Path("/data/options.json")
MAP = {
    "mariadb_host": "MARIADB_HOST",
    "mariadb_port": "MARIADB_PORT",
    "mariadb_user": "MARIADB_USER",
    "mariadb_password": "MARIADB_PASSWORD",
    "mariadb_database": "MARIADB_DATABASE",
    "findash_database": "FINDASH_DATABASE",
    "qdrant_url": "QDRANT_URL",
    "qdrant_api_key": "QDRANT_API_KEY",
    "qdrant_collection": "FINDASH_QDRANT_COLLECTION",
    "default_locale": "FINDASH_DEFAULT_LOCALE",
    "cc_rekening": "FINDASH_CC_REKENING",
    "own_rekeningen": "FINDASH_OWN_REKENINGEN",
}


def main() -> None:
    os.environ.setdefault("FINDASH_EMBED_CACHE", "/data/fastembed")
    os.environ.setdefault("FINDASH_STAGE_DIR", "/data/import")
    os.environ.setdefault("FINDASH_ANONYMIZE", "/share/findash/anonymize.local.json")
    if OPTIONS.is_file():
        data = json.loads(OPTIONS.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise SystemExit("options.json must be an object")
        for src, dest in MAP.items():
            if src in data and data[src] is not None:
                os.environ[dest] = str(data[src])
    os.execvp(
        "uvicorn",
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"],
    )


if __name__ == "__main__":
    main()
