"""Build an anonymized import preview. No Raw table. No IBANs in staging."""

from __future__ import annotations

import json
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.anonymize import AnonymizeRules, anonymize_text, is_rekening_label
from app.bank_csv import CsvFormatError, parse_bank_csv
from app.cc_parse import (
    cc_account_label,
    extract_cc_lines,
    parse_cc_lines,
    pdf_bytes_to_text,
    unmatched_cc_date_lines,
)
from pymysql.err import IntegrityError

from app.db import TimedCursor, tx_ident
from app.formatters import redact_text
from app.hybrid import memory_for_text
from app.txid import cc_txid

ROOT = Path(__file__).resolve().parent.parent
STAGE_TTL_SEC = 3600


def stage_dir() -> Path:
    from app.config import load_settings

    try:
        raw = (load_settings().get("FINDASH_STAGE_DIR") or "").strip()
    except ValueError:
        raw = ""
    if raw:
        return Path(raw)
    return ROOT / ".cache" / "import"


def _dec(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def default_pair(richting: str, cc_type: str | None = None) -> tuple[str, str]:
    if cc_type == "Incasso":
        return "Aflossing", "creditcard"
    if (richting or "").strip() == "Bij":
        return "Inkomsten", "overig"
    return "Overige uitgaven", "overig"


def choose_cats(
    richting: str,
    omschrijving: str,
    memory_rows: list[dict[str, Any]],
    cc_type: str | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Incasso is always CC settlement; otherwise text memory then fallback."""
    if cc_type == "Incasso":
        return (
            "Aflossing",
            "creditcard",
            {"mem_n": 0, "mem_share": None, "tone": "sure", "source": "regel"},
        )
    mem = memory_for_text(memory_rows, omschrijving, richting)
    if mem:
        cert = certainty(mem)
        cert["source"] = "text"
        return mem["hoofd"], mem["sub"], cert
    hoofd, sub = default_pair(richting, cc_type)
    cert = certainty(None)
    cert["source"] = "fallback"
    return hoofd, sub, cert


def _date_key(row: dict[str, Any]) -> int:
    raw = (row.get("datum") or "").replace("-", "")
    try:
        return int(raw)
    except ValueError:
        return 0


def _band(row: dict[str, Any]) -> int:
    if row.get("status") == "nieuw" and row.get("tone") == "doubt":
        return 0
    if row.get("status") == "nieuw" and row.get("tone") == "sure":
        return 1
    return 2


def sort_preview_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (_band(r), -_date_key(r)))


def _pack(kind: str, headers: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sort_preview_rows(rows)
    n_new = sum(1 for r in rows if r.get("status") == "nieuw")
    n_dupe = sum(1 for r in rows if r.get("status") == "dubbel")
    n_err = sum(1 for r in rows if r.get("status") == "fout")
    n_sure = sum(
        1 for r in rows if r.get("status") == "nieuw" and r.get("tone") == "sure"
    )
    n_doubt = sum(
        1 for r in rows if r.get("status") == "nieuw" and r.get("tone") == "doubt"
    )
    return {
        "kind": kind,
        "headers": headers,
        "n_new": n_new,
        "n_dupe": n_dupe,
        "n_err": n_err,
        "n_sure": n_sure,
        "n_doubt": n_doubt,
        "rows": rows,
    }


def existing_txids(cur: TimedCursor, src: str) -> set[str]:
    table = tx_ident("FinBotTransactions" if src == "bank" else "FinBotTransactionsCC")
    cur.execute(f"existing_{src}", f"SELECT TransactieID AS id FROM {table}")
    return {str(r["id"]) for r in cur.fetchall() if r.get("id")}


def certainty(mem: dict[str, Any] | None) -> dict[str, Any]:
    if not mem:
        return {"mem_n": 0, "mem_share": None, "tone": "doubt"}
    share = float(mem.get("share") or 0)
    n = int(mem.get("n") or 0)
    sure = bool(mem.get("unanimous")) and share >= 0.999 and n >= 3
    return {
        "mem_n": n,
        "mem_share": share,
        "tone": "sure" if sure else "doubt",
    }


def _display(omschrijving: str, txid: str, status: str, **extra: Any) -> dict[str, Any]:
    out = {
        "txid": txid,
        "status": status,
        "omschrijving": redact_text(omschrijving, limit=80),
        "rekening": extra.pop("rekening", ""),
        "entiteit": extra.pop("entiteit", ""),
        "neighbors": extra.pop("neighbors", []),
        "neighbors_mixed": False,
        "mem_n": extra.pop("mem_n", 0),
        "mem_share": extra.pop("mem_share", None),
        "tone": extra.pop("tone", ""),
        "source": extra.pop("source", ""),
    }
    out.update(extra)
    return out


def preview_bank(
    raw: bytes,
    rules: AnonymizeRules,
    existing: set[str],
    memory_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    parsed, headers = parse_bank_csv(raw)
    rows_out: list[dict[str, Any]] = []
    n_new = n_dupe = n_err = 0
    for item in parsed:
        txid = item["txid"]
        if item.get("error"):
            n_err += 1
            rows_out.append(
                _display("", txid, "fout", error=item["error"], richting="", bedrag="0", datum="")
            )
            continue
        naam = anonymize_text(item["naam"], rules)
        med = anonymize_text(item["mededelingen"], rules)
        rekening = anonymize_text(item["rekening_raw"], rules)
        if not is_rekening_label(rekening):
            rekening = ""
        tegen = anonymize_text(item["tegenrekening_raw"], rules)
        if not is_rekening_label(tegen):
            tegen = ""
        richting = item["richting"]
        hoofd, sub, cert = choose_cats(richting, naam, memory_rows)
        status = "dubbel" if txid in existing else "nieuw"
        if status == "dubbel":
            n_dupe += 1
            cert["tone"] = ""
        else:
            n_new += 1
        datum = f"{item['jaar']:04d}-{item['maand']:02d}-{item['dag']:02d}"
        rows_out.append(
            _display(
                naam,
                txid,
                status,
                richting=richting,
                bedrag=_dec(item["bedrag"]),
                datum=datum,
                hoofd=hoofd,
                sub=sub,
                rekening=rekening,
                mem_n=cert["mem_n"],
                mem_share=cert["mem_share"],
                tone=cert["tone"],
                source=cert.get("source") or "",
                insert={
                    "TransactieID": txid,
                    "Datum": int(item["datum_raw"]),
                    "Jaar": item["jaar"],
                    "Maand": item["maand"],
                    "Dag": item["dag"],
                    "Naam / Omschrijving": naam,
                    "Rekening": rekening,
                    "Tegenrekening": tegen,
                    "Code": item.get("code") or "",
                    "Af Bij": richting,
                    "Bedrag (EUR)": _dec(item["bedrag"]),
                    "Mutatiesoort": item.get("mutatiesoort") or "",
                    "Mededelingen": med,
                    "Saldo na mutatie": _dec(item["saldo"]),
                    "Hoofdcategorie": hoofd,
                    "Subcategorie": sub,
                    "Entiteit": "",
                }
                if status == "nieuw"
                else None,
            )
        )
    return _pack("bank", headers, rows_out)


def preview_cc(
    raw: bytes,
    rules: AnonymizeRules,
    existing: set[str],
    memory_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    text = pdf_bytes_to_text(raw)
    n_unmatched = unmatched_cc_date_lines(text)
    lines = extract_cc_lines(text)
    parsed = parse_cc_lines(lines) if lines else []
    rows_out: list[dict[str, Any]] = []
    n_new = n_dupe = 0
    n_err = n_unmatched
    for item in parsed:
        token = str(item["mutatie_hash_token"])
        txid = cc_txid(item["Datum"], item["Omschrijving"], item["Type"], token)
        typ = str(item["Type"])
        mutatie = item["Mutatie"]
        richting = "Bij" if typ == "Incasso" else "Af"
        naam = anonymize_text(str(item["Omschrijving"]), rules)
        hoofd, sub, cert = choose_cats(richting, naam, memory_rows, typ)
        status = "dubbel" if txid in existing else "nieuw"
        if status == "dubbel":
            n_dupe += 1
            cert["tone"] = ""
        else:
            n_new += 1
        jaar, maand, dag = int(item["Jaar"]), int(item["Maand"]), int(item["Dag"])
        datum = f"{jaar:04d}-{maand:02d}-{dag:02d}"
        bedrag = abs(mutatie) if isinstance(mutatie, Decimal) else mutatie
        rows_out.append(
            _display(
                naam,
                txid,
                status,
                richting=richting,
                bedrag=_dec(bedrag),
                datum=datum,
                hoofd=hoofd,
                sub=sub,
                rekening=cc_account_label(),
                typ=typ,
                mem_n=cert["mem_n"],
                mem_share=cert["mem_share"],
                tone=cert["tone"],
                source=cert.get("source") or "",
                insert={
                    "TransactieID": txid,
                    "Datum": item["Datum"],
                    "Jaar": jaar,
                    "Maand": maand,
                    "Dag": dag,
                    "Omschrijving": naam,
                    "Type": typ,
                    "Mutatie": token,
                    "Bedrag": _dec(bedrag),
                    "Af Bij": richting,
                    "Rekening": cc_account_label(),
                    "Hoofdcategorie": hoofd,
                    "Subcategorie": sub,
                    "Entiteit": "",
                }
                if status == "nieuw"
                else None,
            )
        )
    return _pack("cc", [], rows_out)


def save_stage(payload: dict[str, Any]) -> str:
    folder = stage_dir()
    folder.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    path = folder / f"{token}.json"
    slim = {
        "kind": payload["kind"],
        "created": time.time(),
        "n_new": payload["n_new"],
        "n_dupe": payload["n_dupe"],
        "n_err": payload["n_err"],
        "inserts": [r["insert"] for r in payload["rows"] if r.get("insert")],
    }
    path.write_text(json.dumps(slim), encoding="utf-8")
    return token


def load_stage(token: str) -> dict[str, Any] | None:
    if not token or any(ch not in "0123456789abcdef" for ch in token) or len(token) != 32:
        return None
    path = stage_dir() / f"{token}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if time.time() - float(data.get("created") or 0) > STAGE_TTL_SEC:
        path.unlink(missing_ok=True)
        return None
    return data


def drop_stage(token: str) -> None:
    if not token or len(token) != 32:
        return
    path = stage_dir() / f"{token}.json"
    path.unlink(missing_ok=True)


def attach_preview_neighbors(rows: list[dict[str, Any]], settings: dict[str, str]) -> None:
    from app.embed import get_embedder
    from app.qdrant_io import _client, qdrant_enabled, search_own
    from app.studio import suggestion_from_neighbors

    if not qdrant_enabled(settings):
        return
    fresh = [r for r in rows if r.get("status") == "nieuw" and r.get("omschrijving")]
    if not fresh:
        return
    client = None
    try:
        embedder = get_embedder(settings)
        client = _client(settings, timeout=20)
        batch = 32
        for start in range(0, len(fresh), batch):
            chunk = fresh[start : start + batch]
            vectors = embedder.embed_queries(
                [row.get("omschrijving") or "" for row in chunk]
            )
            for row, vector in zip(chunk, vectors):
                neighbors = search_own(
                    settings,
                    vector,
                    limit=5,
                    richting=row.get("richting") or None,
                    client=client,
                )
                row["neighbors"] = neighbors
                sug = suggestion_from_neighbors(neighbors)
                mixed = bool(sug and sug.get("mixed"))
                row["neighbors_mixed"] = mixed
                if mixed and row.get("source") != "regel":
                    row["tone"] = "doubt"
    except Exception:
        return
    finally:
        if client is not None:
            client.close()


def apply_overrides(
    inserts: list[dict[str, Any]],
    form: Any,
    pairs: set[tuple[str, str]],
) -> None:
    from app.embed import strip_iban

    for rec in inserts:
        txid = str(rec.get("TransactieID") or "")
        hoofd = str(form.get(f"hoofd-{txid}") or rec.get("Hoofdcategorie") or "").strip()
        sub = str(form.get(f"sub-{txid}") or rec.get("Subcategorie") or "").strip()
        ent = str(form.get(f"entiteit-{txid}") or rec.get("Entiteit") or "").strip()
        if not hoofd or not sub:
            raise ValueError("unknown pair")
        if (hoofd, sub) not in pairs:
            raise ValueError("unknown pair")
        rec["Hoofdcategorie"] = hoofd
        rec["Subcategorie"] = sub
        rec["Entiteit"] = strip_iban(ent)[:191]


def insert_new(cur: TimedCursor, kind: str, inserts: list[dict[str, Any]]) -> int:
    if not inserts:
        return 0
    table = tx_ident("FinBotTransactions" if kind == "bank" else "FinBotTransactionsCC")
    n = 0
    for rec in inserts:
        cols = list(rec.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        quoted = ", ".join("`" + c.replace("`", "") + "`" for c in cols)
        sql = f"INSERT INTO {table} ({quoted}) VALUES ({placeholders})"
        try:
            cur.execute("import_insert", sql, [rec[c] for c in cols])
            n += 1
        except IntegrityError:
            continue
    return n
