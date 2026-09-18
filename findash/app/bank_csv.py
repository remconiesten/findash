"""ING/FinBot bank CSV. Hash on raw cells; no IBAN in returned display fields."""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any

from app.amounts import parse_nl_amount
from app.cc_parse import bank_ymd
from app.txid import bank_txid

HASH_COLS = (
    "Datum",
    "Naam / Omschrijving",
    "Mededelingen",
    "Saldo na mutatie",
)
NEED_COLS = HASH_COLS + ("Af Bij", "Bedrag (EUR)", "Rekening")


class CsvFormatError(ValueError):
    def __init__(self, message: str, headers: list[str] | None = None):
        super().__init__(message)
        self.headers = headers or []


def _detect_dialect(sample: str) -> str:
    semi = sample.count(";")
    comma = sample.count(",")
    return ";" if semi >= comma else ","


def parse_bank_csv(raw: bytes | str) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (rows with raw cells + parsed fields, header names). No anonymize."""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8-sig")
        if "\ufffd" in text[:200] or (text and ord(text[0]) > 127 and "Datum" not in text[:200]):
            text = raw.decode("latin-1")
    else:
        text = raw
    if not text.strip():
        raise CsvFormatError("empty csv")
    dialect = _detect_dialect(text[:4096])
    reader = csv.DictReader(io.StringIO(text), delimiter=dialect)
    headers = [h.strip() for h in (reader.fieldnames or []) if h]
    missing = [c for c in NEED_COLS if c not in headers]
    if missing:
        raise CsvFormatError(
            "missing columns: " + ", ".join(missing),
            headers=headers,
        )
    rows: list[dict[str, Any]] = []
    for rec in reader:
        if not rec:
            continue
        cells = {k.strip(): (v if v is not None else "") for k, v in rec.items() if k}
        if not any(str(v).strip() for v in cells.values()):
            continue
        datum_raw = str(cells.get("Datum") or "").strip()
        naam = cells.get("Naam / Omschrijving") or ""
        med = cells.get("Mededelingen") or ""
        saldo_raw = cells.get("Saldo na mutatie")
        if saldo_raw is None:
            saldo_raw = ""
        txid = bank_txid(datum_raw, naam, med, saldo_raw)
        try:
            jaar, maand, dag = bank_ymd(datum_raw)
            bedrag = parse_nl_amount(cells.get("Bedrag (EUR)"))
            saldo = parse_nl_amount(saldo_raw) if str(saldo_raw).strip() else Decimal("0")
        except Exception as exc:
            rows.append(
                {
                    "txid": txid,
                    "error": type(exc).__name__,
                    "cells": cells,
                    "jaar": None,
                }
            )
            continue
        richting = str(cells.get("Af Bij") or "").strip()
        rows.append(
            {
                "txid": txid,
                "error": None,
                "cells": cells,
                "jaar": jaar,
                "maand": maand,
                "dag": dag,
                "datum_raw": datum_raw,
                "naam": naam,
                "mededelingen": med,
                "saldo_raw": str(saldo_raw),
                "saldo": saldo,
                "bedrag": abs(bedrag),
                "richting": richting,
                "rekening_raw": cells.get("Rekening") or "",
                "tegenrekening_raw": cells.get("Tegenrekening") or "",
                "code": cells.get("Code") or "",
                "mutatiesoort": cells.get("Mutatiesoort") or "",
            }
        )
    return rows, headers
