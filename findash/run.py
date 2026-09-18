#!/usr/bin/env python3
"""Map Supervisor /data/options.json to env, then exec uvicorn. No secret logs."""

from __future__ import annotations

import json
import os
from pathlib import Path

OPTIONS = Path("/data/options.json")
ANONYMIZE_DATA = Path("/data/anonymize.local.json")
ANONYMIZE_SHARE = Path("/share/findash/anonymize.local.json")
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


def env_from_options(data: object) -> dict[str, str]:
    if not isinstance(data, dict):
        raise SystemExit("options.json must be an object")
    env: dict[str, str] = {}
    for src, dest in MAP.items():
        if src in data and data[src] is not None:
            env[dest] = str(data[src])
    return env


def persist_anonymize_json(raw: object, dest: Path) -> Path | None:
    """Write add-on anonymize_json to dest. Empty → None. Never log contents."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        parsed = raw
    else:
        text = str(raw).strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            raise SystemExit("anonymize_json is not valid JSON")
    if not isinstance(parsed, dict):
        raise SystemExit("anonymize_json must be a JSON object")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(parsed, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    try:
        dest.chmod(0o600)
    except OSError:
        pass
    return dest


def main() -> None:
    os.environ.setdefault("FINDASH_EMBED_CACHE", "/data/fastembed")
    os.environ.setdefault("FINDASH_STAGE_DIR", "/data/import")
    os.environ.setdefault("FINDASH_ANONYMIZE", str(ANONYMIZE_SHARE))
    if OPTIONS.is_file():
        data = json.loads(OPTIONS.read_text(encoding="utf-8"))
        for key, value in env_from_options(data).items():
            os.environ[key] = value
        written = persist_anonymize_json(
            data.get("anonymize_json") if isinstance(data, dict) else None,
            ANONYMIZE_DATA,
        )
        if written is not None:
            os.environ["FINDASH_ANONYMIZE"] = str(written)
    os.execvp(
        "uvicorn",
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"],
    )


if __name__ == "__main__":
    main()
