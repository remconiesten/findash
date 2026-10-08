"""Creditcard PDF-regels.

Bekende types (Incasso, Betaling, Kosten) blijven 1:1 met de n8n-expressies,
inclusief de Kosten-quirk in de omschrijving. Een ander type-woord op dezelfde
regelvorm is een extra mutatie (terugboeking als het bedrag positief is).
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from app.amounts import cc_mutatie_hash_token, parse_nl_amount

def cc_account_label() -> str:
    from app.config import cc_rekening

    return cc_rekening()

# Eerste node: regels met datum + type + Europees bedrag.
_AMOUNT = r"[+-] ?\d{1,3}(?:\.\d{3})*,\d{2}"
_LINE_RE = re.compile(
    rf"^\d{{2}}-\d{{2}}-\d{{4}} .+ (Incasso|Betaling|Kosten) {_AMOUNT}$"
)
_DATE_RE = re.compile(r"^(\d{2}-\d{2}-\d{4})")
_TYPE_RE = re.compile(r"(Incasso|Betaling|Kosten)")
_AMOUNT_RE = re.compile(rf"({_AMOUNT})$")
# n8n stripte hier geen Kosten — niet wijzigen: Omschrijving zit in de MD5.
_DESC_TAIL_RE = re.compile(rf" (Incasso|Betaling) {_AMOUNT}$")
# Zelfde regelvorm, ander type-woord (Credit, Terugboeking, …). Minstens 3 letters.
_EXTRA_TYPE = r"[A-Za-z][A-Za-z]{2,}"
_EXTRA_LINE_RE = re.compile(
    rf"^\d{{2}}-\d{{2}}-\d{{4}} .+ ({_EXTRA_TYPE}) {_AMOUNT}$"
)
# Alleen een losse vervolgregele "Type + bedrag". Een kaal bedrag niet plakken:
# dan wordt het laatste woord van de omschrijving (vaak een plaats) het type.
_TAIL_RE = re.compile(rf"^{_EXTRA_TYPE} {_AMOUNT}$")
_KNOWN_TYPES = frozenset({"Incasso", "Betaling", "Kosten"})


def cc_richting(typ: str, mutatie: Decimal) -> str:
    """Incasso blijft Bij. Een positief ander bedrag is een terugboeking."""
    if typ == "Incasso" or mutatie > 0:
        return "Bij"
    return "Af"


def _is_tx_line(line: str) -> bool:
    return bool(_LINE_RE.match(line) or _EXTRA_LINE_RE.match(line))


def pdf_bytes_to_text(data: bytes) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def split_cc_lines(pdf_text: str) -> tuple[list[str], list[str]]:
    """Transactieregels, en datumregels die geen transactie zijn.

    Staat het type-woord én het bedrag samen op de volgende PDF-regel, dan
    plakken we die vast. Een kaal bedrag niet: het laatste woord van de
    omschrijving (vaak een plaats) zou anders het type worden.
    """
    raw_lines = [raw.strip() for raw in pdf_text.split("\n")]
    raw_lines = [line for line in raw_lines if line]
    matched: list[str] = []
    unmatched: list[str] = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        if _is_tx_line(line):
            matched.append(line)
            i += 1
            continue
        nxt = raw_lines[i + 1] if i + 1 < len(raw_lines) else ""
        if _DATE_RE.match(line) and nxt and _TAIL_RE.match(nxt):
            joined = f"{line} {nxt}"
            if _is_tx_line(joined):
                matched.append(joined)
                i += 2
                continue
        if _DATE_RE.match(line):
            unmatched.append(line)
        i += 1
    return matched, unmatched


def unmatched_cc_date_lines(pdf_text: str) -> int:
    """Datumregels die ook na het plakken geen transactie zijn."""
    return len(split_cc_lines(pdf_text)[1])


def extract_cc_lines(pdf_text: str) -> str:
    """Filter PDF-text naar transactieregels, zelfde als n8n TransactieText."""
    matched, _unmatched = split_cc_lines(pdf_text)
    return "\n".join(matched)


def _typ_of(line: str) -> str:
    if _LINE_RE.match(line):
        found = _TYPE_RE.search(line)
        if not found:
            raise ValueError("cc line did not match expected pattern")
        return found.group(1)
    extra = _EXTRA_LINE_RE.match(line)
    if not extra:
        raise ValueError("cc line did not match expected pattern")
    return extra.group(1)


def _omschrijving(line: str, typ: str) -> str:
    if typ in _KNOWN_TYPES:
        # Kosten blijft in de omschrijving; Incasso en Betaling niet.
        oms = _DESC_TAIL_RE.sub("", line)
    else:
        oms = re.sub(rf" {re.escape(typ)} {_AMOUNT}$", "", line)
    return re.sub(r"^\d{2}-\d{2}-\d{4} ", "", oms).strip()


def parse_cc_lines(transactie_text: str) -> list[dict[str, object]]:
    """Tweede node: Datum dd-MM-yyyy, Omschrijving, Type, Mutatie (signed Decimal)."""
    out: list[dict[str, object]] = []
    for raw in transactie_text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        date_m = _DATE_RE.match(line)
        amount_m = _AMOUNT_RE.search(line)
        if not (date_m and amount_m and _is_tx_line(line)):
            raise ValueError("cc line did not match expected pattern")
        datum = date_m.group(1)
        typ = _typ_of(line)
        bedrag_raw = amount_m.group(1)
        mutatie = parse_nl_amount(bedrag_raw.replace(" ", ""))
        omschrijving = _omschrijving(line, typ)
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
