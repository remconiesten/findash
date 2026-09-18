"""Load gitignored .env without printing secrets."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

REQUIRED = (
    "MARIADB_HOST",
    "MARIADB_PORT",
    "MARIADB_USER",
    "MARIADB_PASSWORD",
    "MARIADB_DATABASE",
)


def load_env(path: Path = ENV_PATH) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {path}. Copy .env.example to .env and set MARIADB_PASSWORD."
        )
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'").strip('"')
    missing = [key for key in REQUIRED if not values.get(key)]
    if missing:
        raise ValueError(f"Empty or missing in {path.name}: {', '.join(missing)}")
    return values
