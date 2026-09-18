"""flow_kind rules, period helpers, CC matcher. Amounts are Decimal, never float."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable

from app.config import cc_rekening, sql_rekening_literal


def bank_flow_sql() -> str:
    cc = sql_rekening_literal(cc_rekening())
    return f"""
CASE
  WHEN Hoofdcategorie = 'Interne overboeking' THEN 'internal'
  WHEN Hoofdcategorie = 'Overige uitgaven'
   AND Subcategorie = 'creditcard'
   AND `Af Bij` = 'Af'
   AND Rekening = {cc} THEN 'cc_settlement'
  WHEN Subcategorie IN ('sparen', 'van spaarrekening') THEN 'saving'
  WHEN `Af Bij` = 'Bij' AND Hoofdcategorie = 'Inkomsten' THEN 'income'
  WHEN `Af Bij` = 'Bij' THEN 'refund'
  WHEN `Af Bij` = 'Af' THEN 'expense'
  ELSE 'unclassified'
END
"""

CC_FLOW_SQL = """
CASE
  WHEN `Af Bij` = 'Bij' AND `Type` = 'Incasso' THEN 'cc_settlement'
  WHEN `Af Bij` = 'Af' AND `Type` IN ('Betaling', 'Kosten') THEN 'expense'
  WHEN Hoofdcategorie = 'Interne overboeking' THEN 'internal'
  ELSE 'unclassified'
END
"""


def add_months(ym: int, delta: int) -> int:
    year, month = divmod(ym, 100)
    idx = year * 12 + (month - 1) + delta
    ny, nm = divmod(idx, 12)
    return ny * 100 + (nm + 1)


def first_day(ym: int) -> date:
    year, month = divmod(ym, 100)
    return date(year, month, 1)


def last_day(ym: int) -> date:
    year, month = divmod(ym, 100)
    return date(year, month, monthrange(year, month)[1])


def months_inclusive(from_ym: int, to_ym: int) -> list[int]:
    out: list[int] = []
    cur = from_ym
    while cur <= to_ym:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def default_from_to(to_ym: int) -> tuple[int, int]:
    return add_months(to_ym, -11), to_ym


def ym_of(d: date) -> int:
    return d.year * 100 + d.month


CYCLES = ("calendar", "salary")
PAYDAY = 25
PAYDAY_LOOKBACK = 20  # Dag 20 t/m 25: early salary still starts the next named month


def parse_cycle(raw: str | None) -> str:
    return raw if raw in CYCLES else "calendar"


def _fallback_start(named_ym: int) -> date:
    return first_day(add_months(named_ym, -1)).replace(day=PAYDAY)


def build_payday_starts(
    early: dict[int, int],
    from_ym: int,
    to_ym: int,
) -> dict[int, date]:
    """named_ym → start date. `early` maps calendar ym → min Dag (20–25) of salaris."""
    starts: dict[int, date] = {}
    named = add_months(from_ym, -1)
    last = add_months(to_ym, 2)
    while named <= last:
        prev = add_months(named, -1)
        py, pm = divmod(prev, 100)
        day = early.get(prev)
        if day is not None and PAYDAY_LOOKBACK <= day <= PAYDAY:
            starts[named] = date(py, pm, day)
        else:
            starts[named] = _fallback_start(named)
        named = add_months(named, 1)
    return starts


def salary_ym_of(d: date, starts: dict[int, date] | None = None) -> int:
    """Named month containing d. With starts: [start[M], start[M+1]). Else 25e-rule."""
    if starts:
        items = sorted(starts.items(), key=lambda kv: kv[1])
        for i, (named, start) in enumerate(items):
            nxt = items[i + 1][1] if i + 1 < len(items) else None
            if d >= start and (nxt is None or d < nxt):
                return named
    if d.day >= PAYDAY:
        return add_months(ym_of(d), 1)
    return ym_of(d)


def month_bounds(
    ym: int,
    cycle: str = "calendar",
    starts: dict[int, date] | None = None,
) -> tuple[date, date]:
    if cycle != "salary":
        return first_day(ym), last_day(ym)
    if starts and ym in starts:
        start = starts[ym]
        nxt = add_months(ym, 1)
        if nxt in starts:
            end = starts[nxt] - timedelta(days=1)
        else:
            end = first_day(ym).replace(day=PAYDAY - 1)
        return start, end
    prev = add_months(ym, -1)
    return first_day(prev).replace(day=PAYDAY), first_day(ym).replace(day=PAYDAY - 1)


def period_ymd(
    from_ym: int,
    to_ym: int,
    cycle: str = "calendar",
    starts: dict[int, date] | None = None,
) -> tuple[int, int]:
    start, _ = month_bounds(from_ym, cycle, starts)
    _, end = month_bounds(to_ym, cycle, starts)
    return (
        start.year * 10000 + start.month * 100 + start.day,
        end.year * 10000 + end.month * 100 + end.day,
    )


def bucket_sql(
    cycle: str,
    jaar: str = "Jaar",
    maand: str = "Maand",
    dag: str = "Dag",
    starts: dict[int, date] | None = None,
) -> str:
    if cycle != "salary":
        return f"({jaar} * 100 + {maand})"
    if starts:
        ymd_expr = f"({jaar} * 10000 + {maand} * 100 + {dag})"
        items = sorted(starts.items(), key=lambda kv: kv[1])
        whens: list[str] = []
        for i, (named, start) in enumerate(items):
            lo = start.year * 10000 + start.month * 100 + start.day
            if i + 1 < len(items):
                nxt = items[i + 1][1]
                hi = nxt.year * 10000 + nxt.month * 100 + nxt.day
                whens.append(f"WHEN {ymd_expr} >= {lo} AND {ymd_expr} < {hi} THEN {named}")
            else:
                whens.append(f"WHEN {ymd_expr} >= {lo} THEN {named}")
        if whens:
            return f"(CASE {' '.join(whens)} ELSE ({jaar} * 100 + {maand}) END)"
    return (
        f"(CASE WHEN {dag} >= {PAYDAY} THEN "
        f"CASE WHEN {maand} = 12 THEN ({jaar} + 1) * 100 + 1 "
        f"ELSE {jaar} * 100 + ({maand} + 1) END "
        f"ELSE {jaar} * 100 + {maand} END)"
    )


def period_presets(
    today: date,
    cycle: str = "calendar",
    starts: dict[int, date] | None = None,
) -> list[dict[str, int | str]]:
    """Shortcuts relative to today (calendar or salary named month)."""
    if cycle == "salary":
        named = salary_ym_of(today, starts)
        y, m = divmod(named, 100)
    else:
        y, m = today.year, today.month
        named = y * 100 + m
    q = (m - 1) // 3
    q_start = q * 3 + 1
    if q == 0:
        pq_y, pq_start = y - 1, 10
    else:
        pq_y, pq_start = y, (q - 1) * 3 + 1
    prev_m = add_months(named, -1)
    return [
        {
            "id": "this_year",
            "from_ym": y * 100 + 1,
            "to_ym": named,
        },
        {
            "id": "this_quarter",
            "from_ym": y * 100 + q_start,
            "to_ym": y * 100 + min(q_start + 2, m),
        },
        {
            "id": "last_quarter",
            "from_ym": pq_y * 100 + pq_start,
            "to_ym": pq_y * 100 + pq_start + 2,
        },
        {
            "id": "this_month",
            "from_ym": named,
            "to_ym": named,
        },
        {
            "id": "last_month",
            "from_ym": prev_m,
            "to_ym": prev_m,
        },
    ]


def as_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def match_cc_settlements(
    cc_rows: Iterable[dict[str, Any]],
    bank_rows: Iterable[dict[str, Any]],
    *,
    visible_from: date,
    visible_to: date,
) -> list[dict[str, Any]]:
    """Pair CC Incasso with bank creditcard Af. Inspect only; 2–4 day lag."""
    cc_list = sorted(
        list(cc_rows),
        key=lambda r: (r["cc_date"], r["id"]),
    )
    banks = list(bank_rows)
    used: set[int] = set()
    pairs: list[dict[str, Any]] = []

    for cc in cc_list:
        cc_date = cc["cc_date"]
        cc_amt = as_decimal(cc["bedrag"])
        cands: list[tuple[int, int, dict[str, Any]]] = []
        for bank in banks:
            bid = bank["id"]
            if bid in used:
                continue
            if as_decimal(bank["bedrag"]) != cc_amt:
                continue
            bdate = bank["bank_date"]
            delta = (bdate - cc_date).days
            if 2 <= delta <= 4:
                cands.append((abs(delta), bid, bank))
        if cands:
            cands.sort(key=lambda t: (t[0], t[1]))
            _, bid, bank = cands[0]
            used.add(bid)
            row = _pair_row(cc, bank, "matched")
            if _visible(row, visible_from, visible_to):
                pairs.append(row)
        else:
            row = _pair_row(cc, None, "unmatched_cc")
            if _visible(row, visible_from, visible_to):
                pairs.append(row)

    for bank in banks:
        if bank["id"] in used:
            continue
        row = _pair_row(None, bank, "unmatched_topup")
        if _visible(row, visible_from, visible_to):
            pairs.append(row)

    pairs.sort(key=lambda r: (r["sort_date"], r["status"], r.get("cc_id") or 0))
    return pairs


def _visible(row: dict[str, Any], start: date, end: date) -> bool:
    dates = [d for d in (row.get("cc_date"), row.get("bank_date")) if d]
    return any(start <= d <= end for d in dates)


SAVING_COUNTERPARTS = frozenset({"spaarrekening", "Oranje Spaarrekening"})
TX_KINDS = {
    "spend": ("expense", "refund"),
    "refund": ("refund",),
    "saving": ("saving",),
    "internal": ("internal",),
    "income": ("income",),
}


def known_counterpart(raw: str | None) -> str | None:
    if not raw:
        return None
    if raw in SAVING_COUNTERPARTS:
        return raw
    if raw.startswith("Rekening "):
        return raw
    return None


def intern_leg(
    rekening: str | None, af_bij: str | None, tegen: str | None, entiteit: str | None = None
) -> tuple[str | None, str | None]:
    """From → to without IBANs. Only known labels leave this function."""
    other = known_counterpart(tegen) or known_counterpart(entiteit)
    if af_bij == "Af":
        return rekening, other
    return other, rekening


def _pair_row(
    cc: dict[str, Any] | None,
    bank: dict[str, Any] | None,
    status: str,
) -> dict[str, Any]:
    bedrag = as_decimal((cc or bank)["bedrag"])
    cc_date = cc["cc_date"] if cc else None
    bank_date = bank["bank_date"] if bank else None
    sort_date = cc_date or bank_date
    return {
        "status": status,
        "bedrag": bedrag,
        "cc_date": cc_date,
        "bank_date": bank_date,
        "sort_date": sort_date,
        "cc_id": cc["id"] if cc else None,
        "bank_id": bank["id"] if bank else None,
        "rekening": (bank or cc).get("rekening"),
        "af_bij": (bank or cc).get("af_bij"),
        "hoofd": (cc or bank).get("hoofd"),
        "sub": (cc or bank).get("sub"),
        "cc_type": cc.get("cc_type") if cc else None,
    }
