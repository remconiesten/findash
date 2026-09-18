"""EUR formatting, category colours, and IBAN redaction."""

from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")

HOOFD_COLORS = {
    "Huishouden": "#E76F51",
    "Wonen": "#2A9D8F",
    "Vrije tijd": "#E9C46A",
    "Vervoer": "#4CC9F0",
    "Telecom/tech": "#7B68EE",
    "Voorkomen": "#F4A261",
    "Medische kosten": "#E07A9A",
    "Verzekeringen": "#52B788",
    "Educatie": "#3D8BFF",
    "Overige uitgaven": "#C77DFF",
    "Interne overboeking": "#8D99AE",
    "Aflossing": "#8D99AE",
}


def redact_text(value: str | None, limit: int = 80) -> str:
    """Strip IBAN-like tokens before a description hits the template."""
    if not value:
        return ""
    text = _IBAN_RE.sub("…", str(value))
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def color_for(hoofd: str | None) -> str:
    if not hoofd:
        return "#E76F51"
    return HOOFD_COLORS.get(hoofd, "#E76F51")


def _nl_grouped(text: str) -> str:
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def format_eur(value: Any, locale: str = "nl") -> str:
    if value is None:
        value = Decimal("0")
    amount = Decimal(str(value))
    q = f"{amount.quantize(Decimal('0.01')):,.2f}"
    if locale == "en":
        return f"€{q}"
    q = _nl_grouped(q)
    if locale == "ru":
        return f"{q} €"
    return f"€ {q}"


def format_eur_auto(value: Any, locale: str = "nl") -> str:
    """Whole euros from 100 up; otherwise two decimals with a comma."""
    if value is None:
        value = Decimal("0")
    amount = Decimal(str(value))
    if abs(amount) >= 100:
        q = f"{amount.quantize(Decimal('1'), rounding=ROUND_HALF_UP):,.0f}"
    else:
        q = f"{amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"
    if locale == "en":
        return f"€{q}"
    q = _nl_grouped(q)
    if locale == "ru":
        return f"{q} €"
    return f"€ {q}"
