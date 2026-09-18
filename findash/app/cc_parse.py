"""Creditcard PDF-regels, 1:1 met de twee n8n Edit Fields-expressies."""

from __future__ import annotations

import re
from datetime import datetime

from app.amounts import cc_mutatie_hash_token, parse_nl_amount

def cc_account_label() -> str:
    from app.config import cc_rekening

    return cc_rekening()

# Eerste node: regels met datum + type + Europees bedrag.
_LINE_RE = re.compile(
    r"^\d{2}-\d{2}-\d{4} .+ (Incasso|Betaling|Kosten) "
    r"[+-] ?\d{1,3}(?:\.\d{3})*,\d{2}$"
)
_DATE_RE = re.compile(r"^(\d{2}-\d{2}-\d{4})")
_TYPE_RE = re.compile(r"(Incasso|Betaling|Kosten)")
_AMOUNT_RE = re.compile(r"([+-] ?\d{1,3}(?:\.\d{3})*,\d{2})$")
# n8n stripte hier geen Kosten — niet wijzigen: Omschrijving zit in de MD5.
_DESC_TAIL_RE = re.compile(
    r" (Incasso|Betaling) [+-] ?\d{1,3}(?:\.\d{3})*,\d{2}$"
)


def pdf_bytes_to_text(data: bytes) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def unmatched_cc_date_lines(pdf_text: str) -> int:
    """Lines that look like a dated tx but fail the n8n regex."""
    n = 0
    for raw in pdf_text.split("\n"):
        line = raw.strip()
        if _DATE_RE.match(line) and not _LINE_RE.match(line):
            n += 1
    return n


def extract_cc_lines(pdf_text: str) -> str:
    """Filter PDF-text naar transactieregels, zelfde als n8n TransactieText."""
    rows = []
    for raw in pdf_text.split("\n"):
        line = raw.strip()
        if _LINE_RE.match(line):
            rows.append(line)
    return "\n".join(rows)


def parse_cc_lines(transactie_text: str) -> list[dict[str, object]]:
    """Tweede node: Datum dd-MM-yyyy, Omschrijving, Type, Mutatie (signed Decimal)."""
    out: list[dict[str, object]] = []
    for raw in transactie_text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        date_m = _DATE_RE.match(line)
        type_m = _TYPE_RE.search(line)
        amount_m = _AMOUNT_RE.search(line)
        if not (date_m and type_m and amount_m):
            raise ValueError("cc line did not match expected pattern")
        datum = date_m.group(1)
        typ = type_m.group(1)
        bedrag_raw = amount_m.group(1)
        mutatie = parse_nl_amount(bedrag_raw.replace(" ", ""))
        omschrijving = _DESC_TAIL_RE.sub("", line)
        omschrijving = re.sub(r"^\d{2}-\d{2}-\d{4} ", "", omschrijving).strip()
        jaar, maand, dag = cc_ymd(datum)
        out.append(
            {
                "Datum": datum,
                "Omschrijving": omschrijving,
                "Type": typ,
                "Mutatie": mutatie,
                "mutatie_hash_token": cc_mutatie_hash_token(bedrag_raw),
                "Jaar": jaar,
                "Maand": maand,
                "Dag": dag,
                "Rekening": cc_account_label(),
            }
        )
    return out


def cc_ymd(datum: str) -> tuple[int, int, int]:
    parsed = datetime.strptime(str(datum), "%d-%m-%Y")
    return parsed.year, parsed.month, parsed.day


def bank_ymd(datum: object) -> tuple[int, int, int]:
    parsed = datetime.strptime(str(datum), "%Y%m%d")
    return parsed.year, parsed.month, parsed.day
