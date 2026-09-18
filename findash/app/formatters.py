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
FALLBACK_COLORS = (
    "#E76F51",
    "#2A9D8F",
    "#E9C46A",
    "#4CC9F0",
    "#7B68EE",
    "#F4A261",
    "#E07A9A",
    "#52B788",
)
INCOME_TONES = ("#2A9D8F", "#8ED0C6", "#C5E8E2")
EXPENSE_TONES = ("#E76F51", "#F3B09A", "#F8D4C8")


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


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    h = value.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))  # type: ignore[return-value]


def _shade(hex_color: str, t: float) -> str:
    rgb = _hex_to_rgb(hex_color)
    if t < 0:
        return _rgb_to_hex(_mix(rgb, (28, 36, 44), -t))
    return _rgb_to_hex(_mix(rgb, (255, 248, 238), t))


def colors_for_keys(
    keys: list[str] | tuple[str, ...], parent: str | None = None
) -> dict[str, str]:
    """Stable colour per key. Parent set → tints of that hoofd colour."""
    ordered = sorted({str(k or "") for k in keys})
    n = len(ordered)
    parent_hex = HOOFD_COLORS.get(parent or "") if parent else None
    out: dict[str, str] = {}
    for i, key in enumerate(ordered):
        if parent_hex:
            t = 0.0 if n <= 1 else (i / (n - 1)) * 1.05 - 0.28
            out[key] = _shade(parent_hex, t)
            continue
        if key in HOOFD_COLORS:
            out[key] = HOOFD_COLORS[key]
        else:
            out[key] = FALLBACK_COLORS[i % len(FALLBACK_COLORS)]
    return out


def series_tone(kind: str, index: int) -> str:
    tones = INCOME_TONES if kind == "income" else EXPENSE_TONES
    if index < 0:
        index = 0
    if index >= len(tones):
        return tones[-1]
    return tones[index]


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
