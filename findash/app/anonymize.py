"""Load local IBAN/name rules. Never log mapping keys or last_name."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL_PATH = ROOT / "config" / "anonymize.local.json"
EXAMPLE_PATH = ROOT / "config" / "anonymize.example.json"
REPLACEMENT = "<geanonimiseerd>"
_IBAN_COMPACT = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$")
_REKENING_LABEL = re.compile(r"^Rekening .+$")


def is_rekening_label(value: str) -> bool:
    return bool(_REKENING_LABEL.match(value or ""))


@dataclass(frozen=True)
class AnonymizeRules:
    last_name: str
    iban_to_label: tuple[tuple[str, str], ...]
    iban_n: int
    last_name_set: bool


def _compact_iban(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def _configured_path() -> Path:
    from app.config import load_settings

    try:
        raw = (load_settings().get("FINDASH_ANONYMIZE") or "").strip()
    except ValueError:
        raw = ""
    if raw:
        return Path(raw)
    return LOCAL_PATH


def load_anonymize_rules(path: Path | None = None) -> AnonymizeRules:
    target = path or _configured_path()
    if not target.is_file():
        raise FileNotFoundError(
            f"Missing {target.name}. Copy {EXAMPLE_PATH.name} and fill it in. "
            "Do not paste IBANs into chat."
        )
    try:
        target.chmod(0o600)
    except OSError:
        pass
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("anonymize config must be a JSON object")
    last_name = data.get("last_name") or ""
    if not isinstance(last_name, str):
        raise ValueError("last_name must be a string")
    last_name = last_name.strip()
    mapping = data.get("iban_to_label") or {}
    if not isinstance(mapping, dict):
        raise ValueError("iban_to_label must be an object")
    pairs: list[tuple[str, str]] = []
    for raw_iban, label in mapping.items():
        if not isinstance(raw_iban, str) or not isinstance(label, str):
            raise ValueError("iban_to_label keys and values must be strings")
        iban = _compact_iban(raw_iban)
        label = label.strip()
        if not _IBAN_COMPACT.match(iban):
            raise ValueError("iban_to_label has a key that is not an IBAN")
        if not is_rekening_label(label):
            raise ValueError("iban_to_label has a label that is not allowed")
        pairs.append((iban, label))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    return AnonymizeRules(
        last_name=last_name,
        iban_to_label=tuple(pairs),
        iban_n=len(pairs),
        last_name_set=bool(last_name),
    )


def rules_status(rules: AnonymizeRules) -> str:
    """Safe to print: counts only."""
    return f"iban_rules={rules.iban_n} last_name={'set' if rules.last_name_set else 'missing'}"


def anonymize_text(text: str | None, rules: AnonymizeRules) -> str:
    if not text:
        return ""
    out = str(text)
    compact_source = _compact_iban(out)
    for iban, label in rules.iban_to_label:
        if iban in compact_source or iban in out.upper().replace(" ", ""):
            out = _replace_iban_any_spacing(out, iban, label)
            compact_source = _compact_iban(out)
    if rules.last_name:
        out = re.sub(re.escape(rules.last_name), REPLACEMENT, out, flags=re.IGNORECASE)
    return out


def _replace_iban_any_spacing(text: str, iban: str, label: str) -> str:
    chars = r"\s*".join(re.escape(ch) for ch in iban)
    return re.sub(chars, label, text, flags=re.IGNORECASE)
