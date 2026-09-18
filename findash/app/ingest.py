"""Build Qdrant points from findash tables. No Raw, no Mededelingen, no Tegenrekening."""

from __future__ import annotations

import uuid
from typing import Any, Iterable

from app.classify import bank_flow_sql, CC_FLOW_SQL
from app.db import connect, tx_ident
from app.embed import index_text, strip_iban

SKIP_KINDS = frozenset({"internal", "cc_settlement"})
POINT_NS = uuid.NAMESPACE_URL
FORBIDDEN_SQL = ("FinBotTransactionsRaw", "Mededelingen", "Tegenrekening", "Mutatie")


def point_id(src: str, transactie_id: str) -> str:
    return str(uuid.uuid5(POINT_NS, f"findash:{src}:{transactie_id}"))


def assert_sql_safe(sql: str) -> None:
    upper = sql.upper()
    for needle in FORBIDDEN_SQL:
        if needle.upper() in upper:
            raise ValueError(f"ingest SQL must not mention {needle}")


def _bank_base() -> str:
    table = tx_ident("FinBotTransactions")
    return f"""
    SELECT TransactieID AS transactie_id,
           `Af Bij` AS richting,
           Rekening AS rekening,
           `Naam / Omschrijving` AS omschrijving,
           Entiteit AS entiteit,
           Hoofdcategorie AS hoofd,
           Subcategorie AS sub,
           Jaar AS jaar,
           Maand AS maand,
           0 AS corrected,
           {bank_flow_sql()} AS flow_kind
    FROM {table}
    """


def _cc_base() -> str:
    table = tx_ident("FinBotTransactionsCC")
    return f"""
    SELECT TransactieID AS transactie_id,
           `Af Bij` AS richting,
           Rekening AS rekening,
           Omschrijving AS omschrijving,
           Entiteit AS entiteit,
           Hoofdcategorie AS hoofd,
           Subcategorie AS sub,
           Jaar AS jaar,
           Maand AS maand,
           0 AS corrected,
           {CC_FLOW_SQL} AS flow_kind
    FROM {table}
    """


def count_sql(src: str) -> str:
    base = _bank_base() if src == "bank" else _cc_base()
    sql = f"""
    SELECT flow_kind, COUNT(*) AS n FROM ({base}) s
    GROUP BY flow_kind
    """
    assert_sql_safe(sql)
    return sql


def index_sql(src: str) -> str:
    base = _bank_base() if src == "bank" else _cc_base()
    sql = f"""
    SELECT transactie_id, richting, rekening, omschrijving, entiteit,
           hoofd, sub, jaar, maand, corrected, flow_kind
    FROM ({base}) s
    WHERE flow_kind NOT IN ('internal', 'cc_settlement')
    """
    assert_sql_safe(sql)
    return sql


def row_to_payload(src: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "src": src,
        "transactie_id": row["transactie_id"],
        "hoofd": row["hoofd"] or "",
        "sub": row["sub"] or "",
        "entiteit": strip_iban(row["entiteit"]),
        "richting": row["richting"] or "",
        "rekening": row["rekening"] or "",
        "jaar": int(row["jaar"] or 0),
        "maand": int(row["maand"] or 0),
        "flow_kind": row["flow_kind"],
        "corrected": bool(row["corrected"]),
    }


def fetch_index_rows() -> tuple[list[dict[str, Any]], dict[str, int]]:
    conn = connect()
    stats: dict[str, int] = {
        "bank_read": 0,
        "cc_read": 0,
        "skipped_structural": 0,
        "indexed": 0,
    }
    try:
        with conn.cursor() as cur:
            for src, key in (("bank", "bank_read"), ("cc", "cc_read")):
                cur.execute(count_sql(src))
                for row in cur.fetchall():
                    n = int(row["n"])
                    stats[key] += n
                    if row["flow_kind"] in SKIP_KINDS:
                        stats["skipped_structural"] += n
            out: list[dict[str, Any]] = []
            for src in ("bank", "cc"):
                cur.execute(index_sql(src))
                for row in cur.fetchall():
                    out.append(
                        {
                            "src": src,
                            "transactie_id": row["transactie_id"],
                            "index_text": index_text(row["omschrijving"]),
                            "payload": row_to_payload(src, row),
                        }
                    )
            stats["indexed"] = len(out)
            return out, stats
    finally:
        conn.close()


def build_points(
    rows: Iterable[dict[str, Any]],
    vectors: list[list[float]],
) -> list[dict[str, Any]]:
    points = []
    for row, vector in zip(rows, vectors):
        points.append(
            {
                "id": point_id(row["src"], row["transactie_id"]),
                "vector": vector,
                "payload": row["payload"],
            }
        )
    return points
