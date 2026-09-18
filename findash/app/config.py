"""Settings: process env wins, then .env. Add-on has no .env file."""

from __future__ import annotations

import os
import re
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PKG_ROOT / ".env"

MARIADB_REQUIRED = (
    "MARIADB_HOST",
    "MARIADB_PORT",
    "MARIADB_USER",
    "MARIADB_PASSWORD",
    "MARIADB_DATABASE",
)

SETTING_KEYS = (
    *MARIADB_REQUIRED,
    "FINDASH_DATABASE",
    "FINDASH_HOST",
    "FINDASH_PORT",
    "FINDASH_DEFAULT_LOCALE",
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "FINDASH_QDRANT_COLLECTION",
    "FINDASH_QDRANT_AUTO",
    "FINDASH_EMBED_MODEL",
    "FINDASH_EMBED_CACHE",
    "FINDASH_ANONYMIZE",
    "FINDASH_STAGE_DIR",
    "FINDASH_CC_REKENING",
    "FINDASH_OWN_REKENINGEN",
)

_REKENING_OK = re.compile(r"^Rekening [A-Za-z0-9 ._-]{1,80}$")

FINDASH_DB_ALLOWED = frozenset({"findash", "n8n"})


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def _env_file_candidates(path: Path | None) -> list[Path]:
    if path is not None:
        return [path]
    out: list[Path] = [ENV_PATH]
    parent = PKG_ROOT.parent / ".env"
    if parent != ENV_PATH:
        out.append(parent)
    return out


def load_settings(path: Path | None = None) -> dict[str, str]:
    values: dict[str, str] = {}
    for candidate in _env_file_candidates(path):
        if candidate.is_file():
            values.update(_parse_env(candidate))
            break
    for key in SETTING_KEYS:
        if key in os.environ:
            values[key] = os.environ[key]
    missing = [key for key in MARIADB_REQUIRED if not values.get(key)]
    if missing:
        raise ValueError(
            "Missing "
            + ", ".join(missing)
            + ". Set environment variables or copy .env.example to .env."
        )
    database = values.get("FINDASH_DATABASE") or "findash"
    if database not in FINDASH_DB_ALLOWED:
        raise ValueError("FINDASH_DATABASE must be findash or n8n")
    values["FINDASH_DATABASE"] = database
    values["FINDASH_HOST"] = values.get("FINDASH_HOST") or "127.0.0.1"
    values["FINDASH_PORT"] = values.get("FINDASH_PORT") or "8088"
    locale = (values.get("FINDASH_DEFAULT_LOCALE") or "nl").lower()
    if locale not in {"nl", "en", "ru"}:
        locale = "nl"
    values["FINDASH_DEFAULT_LOCALE"] = locale
    values["QDRANT_URL"] = values.get("QDRANT_URL") or ""
    values["QDRANT_API_KEY"] = values.get("QDRANT_API_KEY") or ""
    collection = values.get("FINDASH_QDRANT_COLLECTION") or "findash_tx"
    values["FINDASH_QDRANT_COLLECTION"] = collection
    values["FINDASH_QDRANT_AUTO"] = values.get("FINDASH_QDRANT_AUTO") or "0"
    values["FINDASH_EMBED_MODEL"] = (
        values.get("FINDASH_EMBED_MODEL")
        or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    values["FINDASH_EMBED_CACHE"] = values.get("FINDASH_EMBED_CACHE") or ".cache/fastembed"
    values["FINDASH_ANONYMIZE"] = values.get("FINDASH_ANONYMIZE") or ""
    values["FINDASH_STAGE_DIR"] = values.get("FINDASH_STAGE_DIR") or ""
    values["FINDASH_CC_REKENING"] = values.get("FINDASH_CC_REKENING") or "Rekening A"
    values["FINDASH_OWN_REKENINGEN"] = (
        values.get("FINDASH_OWN_REKENINGEN") or "Rekening A,Rekening B"
    )
    return values


def assert_rekening_label(value: str) -> str:
    text = (value or "").strip()
    if not _REKENING_OK.match(text):
        raise ValueError("invalid rekening label")
    return text


def sql_rekening_literal(value: str) -> str:
    text = assert_rekening_label(value)
    return "'" + text.replace("'", "''") + "'"


def cc_rekening() -> str:
    return assert_rekening_label(load_settings()["FINDASH_CC_REKENING"])


def own_rekeningen() -> tuple[str, ...]:
    raw = load_settings()["FINDASH_OWN_REKENINGEN"]
    out = [assert_rekening_label(part) for part in raw.split(",") if part.strip()]
    if not out:
        raise ValueError("FINDASH_OWN_REKENINGEN is empty")
    return tuple(out)
