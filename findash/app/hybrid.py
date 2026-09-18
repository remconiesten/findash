"""Induced memory (exact text / entity majority) and leave-one-out scoring.

No Qdrant import. No PII in returned fields beyond hoofd/sub labels already
used as category keys.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Callable

from app.embed import normalize

TEXT_MIN_N = 3
TEXT_SHARE = 0.80
ENTITY_MIN_N = 8
ENTITY_SHARE = 0.75
ENTITY_CENTROID_DENY_EXACT = frozenset({"persoon", "spaarrekening"})
_ING = re.compile(r"^ing(\s+bank(\s+nv)?)?$")


def entity_denied(entiteit: str | None) -> bool:
    key = (entiteit or "").strip().casefold()
    if not key or key in ENTITY_CENTROID_DENY_EXACT:
        return True
    compact = key.replace(".", "")
    return bool(_ING.fullmatch(compact))


def suggestion_from_others(
    others: list[tuple[str, str]],
    *,
    min_n: int,
    min_share: float,
) -> dict[str, Any] | None:
    n = len(others)
    if n < min_n:
        return None
    counts = Counter(others)
    (hoofd, sub), top = counts.most_common(1)[0]
    if not hoofd or not sub:
        return None
    share = top / n
    if share < min_share:
        return None
    return {
        "hoofd": hoofd,
        "sub": sub,
        "n": n,
        "share": share,
        "unanimous": len(counts) == 1,
        "layer": "exact" if len(counts) == 1 else "majority",
    }


def loo_by_key(
    rows: list[dict[str, Any]],
    key_fn: Callable[[dict[str, Any]], Any],
    *,
    min_n: int,
    min_share: float,
) -> list[dict[str, Any] | None]:
    groups: dict[Any, list[int]] = {}
    for i, row in enumerate(rows):
        key = key_fn(row)
        if key is None:
            continue
        groups.setdefault(key, []).append(i)
    out: list[dict[str, Any] | None] = [None] * len(rows)
    for idxs in groups.values():
        labels = [(rows[i]["hoofd"] or "", rows[i]["sub"] or "") for i in idxs]
        for pos, i in enumerate(idxs):
            others = labels[:pos] + labels[pos + 1 :]
            out[i] = suggestion_from_others(others, min_n=min_n, min_share=min_share)
    return out


def text_key(row: dict[str, Any]) -> tuple[str, str] | None:
    text = normalize(row.get("index_text") or row.get("omschrijving"))
    richting = (row.get("richting") or "").strip()
    if not text or not richting:
        return None
    return (text, richting)


def entity_key(row: dict[str, Any]) -> tuple[str, str] | None:
    ent = (row.get("entiteit") or "").strip()
    if entity_denied(ent):
        return None
    richting = (row.get("richting") or "").strip()
    if not ent or not richting:
        return None
    return (ent.casefold(), richting)


def memory_for_text(
    existing: list[dict[str, Any]],
    omschrijving: str,
    richting: str,
) -> dict[str, Any] | None:
    """Majority among existing rows with the same normalized text + richting."""
    key = text_key({"index_text": omschrijving, "richting": richting})
    if not key:
        return None
    others = [
        (row.get("hoofd") or "", row.get("sub") or "")
        for row in existing
        if text_key(row) == key
    ]
    hit = suggestion_from_others(others, min_n=TEXT_MIN_N, min_share=TEXT_SHARE)
    if hit:
        hit["source"] = "text"
        if hit.get("score") is None and hit.get("share") is not None:
            hit["score"] = hit["share"]
    return hit


def memory_suggestions(rows: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
    """Leave-one-out on normalized omschrijving + richting. No entiteit."""
    by_text = loo_by_key(rows, text_key, min_n=TEXT_MIN_N, min_share=TEXT_SHARE)
    out: list[dict[str, Any] | None] = []
    for text_hit in by_text:
        if text_hit:
            hit = dict(text_hit)
            hit["source"] = "text"
            out.append(hit)
        else:
            out.append(None)
    return out


def propose(
    memory_hit: dict[str, Any] | None,
    knn_sug: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Only text memory. k-NN is inspect-only and never a category proposal."""
    _ = knn_sug
    if not memory_hit:
        return None
    hit = dict(memory_hit)
    hit["source"] = "text"
    if hit.get("score") is None and hit.get("share") is not None:
        hit["score"] = hit["share"]
    return hit


def tally(
    gold: list[tuple[str, str]],
    suggested: list[dict[str, Any] | None],
) -> dict[str, Any]:
    if len(gold) != len(suggested):
        raise ValueError("gold/suggested length")
    n = len(gold)
    shown = 0
    hoofd_ok = 0
    pair_ok = 0
    for (gh, gs), sug in zip(gold, suggested):
        if not sug:
            continue
        shown += 1
        if sug.get("hoofd") == gh:
            hoofd_ok += 1
        if sug.get("hoofd") == gh and sug.get("sub") == gs:
            pair_ok += 1
    silent = n - shown
    return {
        "n": n,
        "shown": shown,
        "silent": silent,
        "hoofd_ok": hoofd_ok,
        "pair_ok": pair_ok,
        "hoofd_acc": (hoofd_ok / shown) if shown else None,
        "pair_acc": (pair_ok / shown) if shown else None,
    }


def first_non_null(*hits: dict[str, Any] | None) -> dict[str, Any] | None:
    for hit in hits:
        if hit:
            return hit
    return None
