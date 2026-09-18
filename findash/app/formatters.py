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


GOLDEN_ANGLE = 137.508


def _rgb_to_hsl(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0
    mx, mn = max(r, g, b), min(r, g, b)
    light = (mx + mn) / 2.0
    if mx == mn:
        return 0.0, 0.0, light * 100.0
    delta = mx - mn
    sat = delta / (2.0 - mx - mn) if light > 0.5 else delta / (mx + mn)
    if mx == r:
        hue = (g - b) / delta + (6.0 if g < b else 0.0)
    elif mx == g:
        hue = (b - r) / delta + 2.0
    else:
        hue = (r - g) / delta + 4.0
    return (hue / 6.0) * 360.0, sat * 100.0, light * 100.0


def _hsl_to_rgb(h: float, s: float, light: float) -> tuple[int, int, int]:
    h = (h % 360.0) / 360.0
    s = max(0.0, min(100.0, s)) / 100.0
    light = max(0.0, min(100.0, light)) / 100.0

    def hue2rgb(p: float, q: float, t: float) -> float:
        if t < 0:
            t += 1
        if t > 1:
            t -= 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    if s == 0:
        v = int(round(light * 255))
        return v, v, v
    q = light * (1 + s) if light < 0.5 else light + s - light * s
    p = 2 * light - q
    r = hue2rgb(p, q, h + 1 / 3)
    g = hue2rgb(p, q, h)
    b = hue2rgb(p, q, h - 1 / 3)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


def hue_of(hex_color: str) -> float:
    return _rgb_to_hsl(_hex_to_rgb(hex_color))[0]


def hue_distance(a: str, b: str) -> float:
    d = abs(hue_of(a) - hue_of(b)) % 360.0
    return min(d, 360.0 - d)


def colors_for_keys(
    keys: list[str] | tuple[str, ...], parent: str | None = None
) -> dict[str, str]:
    """Stable colour per key. Parent set → hues stepped from that hoofd colour."""
    ordered = sorted({str(k or "") for k in keys})
    parent_hex = HOOFD_COLORS.get(parent or "") if parent else None
    out: dict[str, str] = {}
    if parent_hex:
        ph, ps, _pl = _rgb_to_hsl(_hex_to_rgb(parent_hex))
        sat = max(50.0, min(75.0, ps))
        for i, key in enumerate(ordered):
            h = (ph + i * GOLDEN_ANGLE) % 360.0
            light = 40.0 + (i % 3) * 8.0
            out[key] = _rgb_to_hex(_hsl_to_rgb(h, sat, light))
        return out
    for i, key in enumerate(ordered):
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
