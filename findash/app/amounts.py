"""European amounts → Decimal for MariaDB. Hash-tokens follow n8n/JS parseFloat."""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any

_SPACES = re.compile(r"\s+")


def parse_nl_amount(value: Any) -> Decimal:
    """'1.234,56', '+ 12,50', '-1,00' → Decimal. Rejects IEEE-float money in the DB."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("boolean is not an amount")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite amount")
        return Decimal(str(value))
    text = _SPACES.sub("", str(value).strip())
    if not text:
        raise ValueError("empty amount")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount {value!r}") from exc
    if not amount.is_finite():
        raise ValueError("non-finite amount")
    return amount


def js_number_to_string(value: float) -> str:
    """ECMAScript NumberToString enough for two-decimal money (CC hash)."""
    if not math.isfinite(value):
        raise ValueError("non-finite number")
    if value == 0:
        return "0"
    as_int = int(value)
    if value == as_int and abs(as_int) <= 2**53:
        return str(as_int)
    return format(value, ".15g")


def cc_mutatie_hash_token(bedrag_raw: str) -> str:
    """n8n: parseFloat(raw.replace dots, comma→dot, first space). Then JS ToString."""
    cleaned = bedrag_raw.replace(".", "").replace(",", ".").replace(" ", "", 1)
    return js_number_to_string(float(cleaned))
