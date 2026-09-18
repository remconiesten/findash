"""Import-studio: queues, allowlist, in-place category writes on findash."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from app.classify import bank_flow_sql, CC_FLOW_SQL
from app.db import TimedCursor, tx_ident
from app.embed import index_text
from app.formatters import redact_text
from app.hybrid import memory_suggestions
from app.ingest import SKIP_KINDS, index_sql

TXID_RE = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)
SUB_SID_RE = re.compile(r"^sub-(?:bank|cc)-[0-9a-f]{32}$", re.IGNORECASE)
QUEUES = (
    "twijfel",
    "knn_mismatch",
    "split_text",
    "overig",
    "saving_odd",
    "unclassified",
    "corrected",
    "zoek",
    "all",
)
MENU_QUEUES = (
    "twijfel",
    "knn_mismatch",
    "split_text",
    "corrected",
    "zoek",
    "all",
)
Q_MAX = 80
EXTRA_PAIRS = frozenset(
    {
        ("Vervoer", "bekeuringen"),
        ("Vervoer", "taxi"),
        ("Educatie", "schoolbijdrage"),
        ("Aflossing", "creditcard"),
        ("Inkomsten", "ERE"),
        ("Huishouden", "glazenwassers"),
    }
)
PAGE_SIZE = 20
SAVING_OK_ENTITEIT = frozenset({"spaarrekening", "Oranje Spaarrekening"})
DEFAULT_DREMPEL = Decimal("0.70")


def is_structural_target(hoofd: str, sub: str) -> bool:
    if hoofd == "Interne overboeking":
        return True
    if hoofd == "Overige uitgaven" and sub == "creditcard":
        return True
    return False


def parse_txid(value: str | None) -> str | None:
    if not value or not TXID_RE.match(value):
        return None
    return value.lower()


def parse_sub_sid(value: str | None) -> str | None:
    raw = (value or "").strip()
    if SUB_SID_RE.match(raw):
        return raw
    return None


def parse_src(value: str | None) -> str | None:
    if value in ("bank", "cc"):
        return value
    return None


def parse_q(value: str | None) -> str:
    raw = (value or "").strip()[:Q_MAX]
    return "".join(ch for ch in raw if ch not in "%_\\")


def parse_drempel(value: str | None) -> Decimal:
    try:
        amount = Decimal(str(value))
    except Exception:
        return DEFAULT_DREMPEL
    if amount < 0 or amount > 1:
        return DEFAULT_DREMPEL
    return amount.quantize(Decimal("0.01"))


def load_memory_corpus(cur: TimedCursor) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for src in ("bank", "cc"):
        cur.execute(f"memory_corpus_{src}", index_sql(src))
        for row in cur.fetchall():
            out.append(
                {
                    "src": src,
                    "transactie_id": row["transactie_id"],
                    "index_text": index_text(row["omschrijving"]),
                    "richting": row["richting"] or "",
                    "hoofd": row["hoofd"] or "",
                    "sub": row["sub"] or "",
                }
            )
    return out


def memory_by_id(
    corpus: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any] | None]:
    hits = memory_suggestions(corpus)
    return {
        (row["src"], row["transactie_id"]): hit
        for row, hit in zip(corpus, hits)
    }


def ensure_suggestion_layer(cur: Any) -> None:
    check = """
        SELECT COUNT(*) AS n FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'category_suggestion'
          AND COLUMN_NAME = 'layer'
        """
    alter = """
        ALTER TABLE category_suggestion
        ADD COLUMN layer VARCHAR(16) NOT NULL DEFAULT 'none'
        AFTER neighbor_n
        """
    if isinstance(cur, TimedCursor):
        cur.execute("suggestion_layer", check)
        row = cur.fetchone()
        n = int((row or {}).get("n") or 0)
        if n == 0:
            cur.execute("suggestion_layer_add", alter)
        return
    cur.execute(check)
    row = cur.fetchone()
    n = int((row or {}).get("n") or 0) if isinstance(row, dict) else int((row or [0])[0] or 0)
    if n == 0:
        cur.execute(alter)


def suggestion_ready(cur: TimedCursor) -> bool:
    cur.execute(
        "suggestion_table",
        """
        SELECT COUNT(*) AS n FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'category_suggestion'
        """,
    )
    row = cur.fetchone()
    return bool(row and int(row["n"]) == 1)


def oorsprong_ready(cur: TimedCursor) -> bool:
    cur.execute(
        "oorsprong_cols",
        """
        SELECT COUNT(*) AS n FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'FinBotTransactions'
          AND COLUMN_NAME = 'oorsprong_hoofd'
        """,
    )
    row = cur.fetchone()
    return bool(row and int(row["n"]) == 1)


def pair_allowlist(cur: TimedCursor) -> set[tuple[str, str]]:
    cur.execute(
        "studio_pairs",
        f"""
        SELECT DISTINCT Hoofdcategorie AS hoofd, Subcategorie AS sub
        FROM {tx_ident("FinBotTransactions")}
        UNION
        SELECT DISTINCT Hoofdcategorie, Subcategorie
        FROM {tx_ident("FinBotTransactionsCC")}
        """,
    )
    found = {
        (r["hoofd"], r["sub"])
        for r in cur.fetchall()
        if r["hoofd"] and r["sub"]
    }
    return found | set(EXTRA_PAIRS)


def subs_for_hoofd(pairs: set[tuple[str, str]], hoofd: str) -> list[str]:
    return sorted({sub for h, sub in pairs if h == hoofd})


def _queue_sql(queue: str, alias: str = "s") -> tuple[str, list[Any]]:
    if queue == "twijfel":
        return (
            f" AND (LOWER({alias}.sub) = 'overig' OR {alias}.flow_kind = 'unclassified')"
            f" AND EXISTS ("
            f" SELECT 1 FROM category_suggestion cs"
            f" WHERE cs.src = {alias}.src AND cs.transactie_id = {alias}.transactie_id"
            f" AND cs.layer = 'text')",
            [],
        )
    if queue == "overig":
        return f" AND LOWER({alias}.sub) = 'overig'", []
    if queue == "saving_odd":
        placeholders = ", ".join(["%s"] * len(SAVING_OK_ENTITEIT))
        labels = list(SAVING_OK_ENTITEIT)
        return (
            f" AND {alias}.flow_kind = 'saving'"
            f" AND ({alias}.entiteit IS NULL OR {alias}.entiteit NOT IN ({placeholders}))",
            labels,
        )
    if queue == "knn_mismatch":
        return (
            f" AND EXISTS ("
            f" SELECT 1 FROM category_suggestion cs"
            f" WHERE cs.src = {alias}.src AND cs.transactie_id = {alias}.transactie_id"
            f" AND cs.disagrees = 1 AND cs.layer = 'text')",
            [],
        )
    if queue == "split_text":
        # Handled in list_rows (python group-by). Placeholder.
        return " AND 1=0", []
    if queue == "unclassified":
        return f" AND {alias}.flow_kind = 'unclassified'", []
    if queue == "corrected":
        return f" AND {alias}.oorsprong_hoofd IS NOT NULL", []
    if queue == "zoek":
        return "", []
    return "", []


def _search_sql(q: str, alias: str = "s") -> tuple[str, list[Any]]:
    if not q:
        return "", []
    pat = "%" + q + "%"
    return (
        f" AND ("
        f" {alias}.omschrijving LIKE %s"
        f" OR {alias}.entiteit LIKE %s"
        f" OR {alias}.hoofd LIKE %s"
        f" OR {alias}.sub LIKE %s"
        f" )",
        [pat, pat, pat, pat],
    )


def load_split_text_keys(cur: TimedCursor) -> set[str]:
    inner = _union_sql()
    cur.execute(
        "studio_split_keys",
        f"""
        SELECT LOWER(TRIM(s.omschrijving)) AS k
        FROM ({inner}) s
        WHERE s.omschrijving IS NOT NULL AND TRIM(s.omschrijving) <> ''
        GROUP BY LOWER(TRIM(s.omschrijving))
        HAVING COUNT(DISTINCT CONCAT(s.hoofd, CHAR(31), s.sub)) > 1
        """,
    )
    return {(r["k"] or "") for r in cur.fetchall() if r["k"]}


def _union_sql() -> str:
    skip = ", ".join("'" + k + "'" for k in sorted(SKIP_KINDS))
    return f"""
    SELECT src, transactie_id, Jaar, Maand, Dag, rekening, richting, bedrag,
           hoofd, sub, omschrijving, entiteit, oorsprong_hoofd, oorsprong_sub,
           Similarity AS similarity, flow_kind
    FROM (
      SELECT 'bank' AS src, TransactieID AS transactie_id, Jaar, Maand, Dag,
             Rekening AS rekening, `Af Bij` AS richting, `Bedrag (EUR)` AS bedrag,
             Hoofdcategorie AS hoofd, Subcategorie AS sub,
             `Naam / Omschrijving` AS omschrijving, Entiteit AS entiteit,
             oorsprong_hoofd, oorsprong_sub, Similarity,
             {bank_flow_sql()} AS flow_kind
      FROM {tx_ident("FinBotTransactions")}
      UNION ALL
      SELECT 'cc', TransactieID, Jaar, Maand, Dag, Rekening, `Af Bij`, Bedrag,
             Hoofdcategorie, Subcategorie, Omschrijving, Entiteit,
             oorsprong_hoofd, oorsprong_sub, Similarity,
             {CC_FLOW_SQL}
      FROM {tx_ident("FinBotTransactionsCC")}
    ) s
    WHERE s.flow_kind NOT IN ({skip})
    """


def _list_split_text(
    cur: TimedCursor,
    from_ym: int,
    to_ym: int,
    rekening: str | None,
    page: int,
    q: str = "",
) -> tuple[list[dict[str, Any]], int]:
    inner = _union_sql()
    params: list[Any] = [from_ym, to_ym]
    rek_sql = ""
    if rekening:
        rek_sql = " AND s.rekening = %s"
        params.append(rekening)
    cur.execute(
        "studio_split_scan",
        f"""
        SELECT * FROM ({inner}) s
        WHERE (s.Jaar * 100 + s.Maand) BETWEEN %s AND %s {rek_sql}
        """,
        params,
    )
    by_text: dict[str, list[dict[str, Any]]] = {}
    for item in cur.fetchall():
        key = (item["omschrijving"] or "").strip()
        if not key:
            continue
        by_text.setdefault(key, []).append(item)
    picked: list[dict[str, Any]] = []
    for items in by_text.values():
        cats = {(i["hoofd"], i["sub"]) for i in items}
        if len(cats) > 1:
            picked.extend(items)
    if q:
        needle = q.casefold()
        picked = [
            i
            for i in picked
            if needle in (i["omschrijving"] or "").casefold()
            or needle in (i["entiteit"] or "").casefold()
            or needle in (i["hoofd"] or "").casefold()
            or needle in (i["sub"] or "").casefold()
        ]
    picked.sort(
        key=lambda i: (int(i["Jaar"]), int(i["Maand"]), i["src"], i["transactie_id"]),
        reverse=True,
    )
    page = max(1, min(page, 500))
    start = (page - 1) * PAGE_SIZE
    return [_present(i) for i in picked[start : start + PAGE_SIZE]], len(picked)


def list_rows(
    cur: TimedCursor,
    *,
    from_ym: int,
    to_ym: int,
    queue: str,
    rekening: str | None,
    page: int,
    q: str = "",
) -> tuple[list[dict[str, Any]], int]:
    if queue not in QUEUES:
        queue = "twijfel"
    page = max(1, min(page, 500))
    q = parse_q(q)
    if queue == "zoek" and not q:
        return [], 0
    if queue == "split_text":
        return _list_split_text(cur, from_ym, to_ym, rekening, page, q)
    if queue in ("knn_mismatch", "twijfel") and not suggestion_ready(cur):
        extra, qparams = " AND 1=0", []
    else:
        extra, qparams = _queue_sql(queue)
    search_sql, search_params = _search_sql(q)
    params: list[Any] = [from_ym, to_ym, *qparams, *search_params]
    rek_sql = ""
    if rekening:
        rek_sql = " AND s.rekening = %s"
        params.append(rekening)
    period = " AND (s.Jaar * 100 + s.Maand) BETWEEN %s AND %s"
    inner = _union_sql()
    cur.execute(
        "studio_count",
        f"SELECT COUNT(*) AS n FROM ({inner}) s WHERE 1=1 {period}{extra}{search_sql}{rek_sql}",
        params,
    )
    total = int((cur.fetchone() or {}).get("n") or 0)
    offset = (page - 1) * PAGE_SIZE
    list_params = list(params) + [PAGE_SIZE + 1, offset]
    cur.execute(
        "studio_list",
        f"""
        SELECT * FROM ({inner}) s
        WHERE 1=1 {period}{extra}{search_sql}{rek_sql}
        ORDER BY s.Jaar DESC, s.Maand DESC, s.src, s.transactie_id DESC
        LIMIT %s OFFSET %s
        """,
        list_params,
    )
    raw = list(cur.fetchall())
    rows = []
    for item in raw[:PAGE_SIZE]:
        rows.append(_present(item))
    return rows, total


def fetch_row(cur: TimedCursor, src: str, transactie_id: str) -> dict[str, Any] | None:
    inner = _union_sql()
    cur.execute(
        "studio_one",
        f"SELECT * FROM ({inner}) s WHERE s.src = %s AND s.transactie_id = %s",
        (src, transactie_id),
    )
    item = cur.fetchone()
    if not item:
        return None
    return _present(item)


def _present(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "src": item["src"],
        "transactie_id": item["transactie_id"],
        "jaar": int(item["Jaar"]),
        "maand": int(item["Maand"]),
        "dag": int(item["Dag"] or 1),
        "rekening": item["rekening"],
        "richting": item["richting"],
        "bedrag": item["bedrag"],
        "hoofd": item["hoofd"],
        "sub": item["sub"],
        "omschrijving": redact_text(item["omschrijving"], limit=80),
        "embed_text": index_text(item["omschrijving"]),
        "text_key": (item["omschrijving"] or "").strip().casefold(),
        "entiteit": redact_text(item["entiteit"], limit=40),
        "entiteit_key": (item["entiteit"] or "").strip(),
        "oorsprong_hoofd": item["oorsprong_hoofd"],
        "oorsprong_sub": item["oorsprong_sub"],
        "similarity": item["similarity"],
        "flow_kind": item["flow_kind"],
        "corrected": bool(item["oorsprong_hoofd"]),
        "entity_options": [],
        "knn": None,
        "flags": [],
        "bulk_ok": False,
    }


def apply_correction(
    cur: TimedCursor,
    *,
    src: str,
    transactie_id: str,
    hoofd: str,
    sub: str,
    similarity: Decimal | None,
    pairs: set[tuple[str, str]],
    entiteit: str | None = None,
    sub_new: str | None = None,
) -> dict[str, Any] | None:
    from app.embed import strip_iban

    hoofd = (hoofd or "").strip()
    sub_new = (sub_new or "").strip()
    if sub_new:
        sub = strip_iban(sub_new)[:191].strip()
    sub = (sub or "").strip()
    if not hoofd or not sub:
        raise ValueError("empty")
    if (hoofd, sub) not in pairs and not sub_new:
        raise ValueError("pair")
    if is_structural_target(hoofd, sub):
        raise ValueError("structural")
    row = fetch_row(cur, src, transactie_id)
    if not row:
        return None
    if row["flow_kind"] in SKIP_KINDS:
        raise ValueError("source")
    table = tx_ident("FinBotTransactions" if src == "bank" else "FinBotTransactionsCC")
    params: list[Any] = [hoofd, sub, similarity]
    extra_set = ""
    if entiteit is not None and str(entiteit).strip():
        extra_set = ", Entiteit = %s"
        params.append(strip_iban(str(entiteit).strip())[:191])
    params.append(transactie_id)
    cur.execute(
        "studio_update",
        f"""
        UPDATE {table}
        SET oorsprong_hoofd = COALESCE(oorsprong_hoofd, Hoofdcategorie),
            oorsprong_sub = COALESCE(oorsprong_sub, Subcategorie),
            Hoofdcategorie = %s,
            Subcategorie = %s,
            Similarity = %s
            {extra_set}
        WHERE TransactieID = %s
        """,
        params,
    )
    return fetch_row(cur, src, transactie_id)


def undo_correction(
    cur: TimedCursor, *, src: str, transactie_id: str
) -> dict[str, Any] | None:
    row = fetch_row(cur, src, transactie_id)
    if not row or not row["oorsprong_hoofd"]:
        return row
    table = tx_ident("FinBotTransactions" if src == "bank" else "FinBotTransactionsCC")
    cur.execute(
        "studio_undo",
        f"""
        UPDATE {table}
        SET Hoofdcategorie = oorsprong_hoofd,
            Subcategorie = oorsprong_sub,
            oorsprong_hoofd = NULL,
            oorsprong_sub = NULL,
            Similarity = NULL
        WHERE TransactieID = %s AND oorsprong_hoofd IS NOT NULL
        """,
        (transactie_id,),
    )
    return fetch_row(cur, src, transactie_id)


def suggestion_from_neighbors(neighbors: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not neighbors:
        return None
    top = neighbors[0]
    counts: dict[tuple[str, str], int] = {}
    for n in neighbors:
        key = (n.get("hoofd") or "", n.get("sub") or "")
        counts[key] = counts.get(key, 0) + 1
    split = [
        {"hoofd": h, "sub": s, "n": n}
        for (h, s), n in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    same = len(counts) == 1
    return {
        "hoofd": top["hoofd"],
        "sub": top["sub"],
        "score": top["score"],
        "unanimous": same and len(neighbors) >= 3,
        "neighbor_n": len(neighbors),
        "mixed": not same,
        "split": split,
    }
