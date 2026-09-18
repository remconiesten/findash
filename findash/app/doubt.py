"""Known + learned doubt flags for the import-studio.

Shop-as-saving with a high Bij amount is doubt, not groceries:
k-NN sees 'Albert Heijn' and suggests boodschappen; the high credits
were spaaropnames. Small shop Bij under saving/income can be refunds.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.classify import as_decimal
from app.db import TimedCursor, tx_ident
from app.studio import SAVING_OK_ENTITEIT

REAL_INCOME_SUB = frozenset(
    {
        "salaris",
        "belastingteruggaaf",
        "kinderbijslag",
        "toeslagen",
        "bijdrage opa",
        "bijdrage kado",
        "uit bouwdepot",
        "crypto verkoop",
        "laadvergoeding",
    }
)
SAVING_OK = frozenset(s.casefold() for s in SAVING_OK_ENTITEIT)
LARGE_SHOP_SAVING = Decimal("50")
MAJORITY_MIN_N = 8
MAJORITY_SHARE = 0.75


def load_entity_stats(
    cur: TimedCursor,
) -> tuple[dict[str, tuple[str, str, int]], set[str]]:
    """Entiteit → (hoofd, sub, n) for stable expense shops, plus mixed labels."""
    cur.execute(
        "studio_entity_majority",
        f"""
        SELECT Entiteit AS e, Hoofdcategorie AS h, Subcategorie AS s, COUNT(*) AS n
        FROM {tx_ident("FinBotTransactions")}
        WHERE `Af Bij` = 'Af'
          AND Hoofdcategorie NOT IN ('Interne overboeking', 'Inkomsten')
          AND Subcategorie NOT IN ('sparen', 'creditcard', 'van spaarrekening')
          AND Entiteit IS NOT NULL AND TRIM(Entiteit) <> ''
        GROUP BY Entiteit, Hoofdcategorie, Subcategorie
        """,
    )
    buckets: dict[str, list[tuple[str, str, int]]] = {}
    for row in cur.fetchall():
        key = (row["e"] or "").strip().casefold()
        if not key:
            continue
        buckets.setdefault(key, []).append(
            (row["h"], row["s"], int(row["n"]))
        )
    out: dict[str, tuple[str, str, int]] = {}
    mixed: set[str] = set()
    for key, items in buckets.items():
        items.sort(key=lambda t: t[2], reverse=True)
        hoofd, sub, n = items[0]
        total = sum(t[2] for t in items)
        if n >= MAJORITY_MIN_N and (n / total) >= MAJORITY_SHARE:
            out[key] = (hoofd, sub, n)
        elif len(items) > 1 and total >= MAJORITY_MIN_N:
            mixed.add(key)
    return out, mixed


def load_expense_majority(cur: TimedCursor) -> dict[str, tuple[str, str, int]]:
    majority, _mixed = load_entity_stats(cur)
    return majority


def annotate(
    row: dict[str, Any],
    majority: dict[str, tuple[str, str, int]],
    drempel: Decimal,
    split_texts: set[str] | None = None,
    mixed_entities: set[str] | None = None,
) -> None:
    """Set flags, doubt, bulk_ok; may suppress a grocery k-NN on large saving shops."""
    key = (row.get("entiteit_key") or "").strip().casefold()
    maj = majority.get(key) if key else None
    is_shop = maj is not None
    bedrag = as_decimal(row.get("bedrag"))
    sub = (row.get("sub") or "").casefold()
    hoofd = row.get("hoofd") or ""
    kind = row.get("flow_kind") or ""
    richting = row.get("richting") or ""
    saving_shop = kind == "saving" and key not in SAVING_OK and bool(key)
    large = (
        saving_shop
        and richting == "Bij"
        and bedrag >= LARGE_SHOP_SAVING
    )
    flags: list[str] = []
    bulk_ok = False
    suggest = row.get("suggest")
    knn = row.get("knn") or suggest
    text_key = (row.get("text_key") or "").strip().casefold()
    splits = split_texts or set()
    mixed_ent = mixed_entities or set()
    if (
        suggest
        and (suggest.get("hoofd"), suggest.get("sub")) != (hoofd, row.get("sub"))
    ):
        flags.append("knn_mismatch")
    if knn and knn.get("mixed"):
        flags.append("knn_split")
    if text_key and text_key in splits:
        flags.append("split_text")
    if key and key in mixed_ent:
        flags.append("mixed_entity")

    if large:
        flags.append("shop_saving_large")
        row["suggest"] = None
        row["above"] = False
        bulk_ok = False
    elif saving_shop:
        flags.append("shop_saving_small")
        if maj:
            row["suggest"] = {
                "hoofd": maj[0],
                "sub": maj[1],
                "score": None,
                "unanimous": True,
                "neighbor_n": maj[2],
                "source": "regel",
            }
            row["above"] = True
            bulk_ok = True
    elif (
        hoofd == "Inkomsten"
        and sub == "overig"
        and is_shop
        and (row.get("sub") or "") not in REAL_INCOME_SUB
    ):
        flags.append("shop_as_income")
        if maj:
            row["suggest"] = {
                "hoofd": maj[0],
                "sub": maj[1],
                "score": None,
                "unanimous": True,
                "neighbor_n": maj[2],
                "source": "regel",
            }
            row["above"] = True
            bulk_ok = True
    elif sub == "overig":
        flags.append("overig")
        bulk_ok = bool(suggest and suggest.get("source") == "text")

    if kind == "unclassified" and "unclassified" not in flags:
        flags.append("unclassified")

    split_unsafe = any(f in flags for f in ("knn_split", "split_text", "mixed_entity"))
    rule = (row.get("suggest") or {}).get("source") == "regel"
    if split_unsafe and not rule:
        bulk_ok = False
        row["above"] = False

    row["flags"] = flags
    row["doubt"] = bool(flags)
    row["bulk_ok"] = bulk_ok and not row.get("corrected")
