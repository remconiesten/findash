"""TransactieID = MD5 over ruwe velden, zelfde concatenatie als n8n. Geen separators."""

from __future__ import annotations

import hashlib
from typing import Any


def _part(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def md5_hex(*parts: Any) -> str:
    raw = "".join(_part(p) for p in parts)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def bank_txid(
    datum: Any,
    naam_omschrijving: Any,
    mededelingen: Any,
    saldo_na_mutatie: Any,
) -> str:
    """MD5(Datum + Naam/Omschrijving + Mededelingen + Saldo na mutatie) op raw."""
    return md5_hex(datum, naam_omschrijving, mededelingen, saldo_na_mutatie)


def cc_txid(datum: Any, omschrijving: Any, typ: Any, mutatie: Any) -> str:
    """MD5(Datum + Omschrijving + Type + Mutatie) op de PDF-parser-uitvoer."""
    return md5_hex(datum, omschrijving, typ, mutatie)
