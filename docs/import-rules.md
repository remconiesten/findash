# Importregels (n8n → findash)

Bron: operator, 2026-09-15. Hash en PDF-parse zitten in `app/txid.py`, `app/cc_parse.py`, `app/amounts.py`. Anonimiseren: `config/anonymize.local.json` (gitignored; agents lezen hem niet).

## TransactieID (MD5, raw, geen separators)

Bank: `Datum` + `Naam / Omschrijving` + `Mededelingen` + `Saldo na mutatie`  
CC: `Datum` + `Omschrijving` + `Type` + `Mutatie`  

Op de **ruwe** data, vóór anonimiseren. UTF-8, hex 32 tekens. UNIQUE in beide tabellen voorkomt dubbele import.

GUI-import toont **eerst** een preview (nieuw vs al bekend vs niet herkend) en schrijft pas na bevestiging. Geen Raw-tabel in dit pad.

Live check (`scripts/verify_txid.py`, alleen SQL-counts): bank 6595/6595 en CC 390/390 tegen opgeslagen `TransactieID`. Controlestest zonder `Mededelingen` is 0%. `Saldo na mutatie` is in Raw **tinytext** (CSV-string); niet het decimal uit de geanonimiseerde tabel. CC hasht de kolom `Mutatie` (n8n-`parseFloat`-string), niet `CAST(Bedrag AS CHAR)`.

CC-`Mutatie` in de hash is de JS-`parseFloat`-string van het Europese bedrag (`1.101,57` → `1101.57`, `12,00` → `12`). Bedragen in MariaDB zijn `DECIMAL`, geen IEEE-float.

## Datum → Jaar / Maand / Dag

- Bank: `Datum` als `yyyyMMdd` (Luxon `fromFormat`).
- CC: `Datum` als `dd-MM-yyyy`.

## CC uit PDF (twee n8n-nodes)

1. Filter regels: `^\d{2}-\d{2}-\d{4} .+ (Incasso|Betaling|Kosten) [+-] ?\d{1,3}(\.\d{3})*,\d{2}$`
2. Parse Datum, Type, bedrag; Omschrijving = rest. **n8n stripte `Kosten` niet uit de omschrijving** — Python doet hetzelfde, anders wijzigt de MD5.
3. Veld `Rekening` = altijd `Rekening A` (enige CC-rekening in het huishouden).

## Anonimiseren

- IBANs → `Rekening A` via lokale labels via lokale config (meerdere IBANs per label mag).
- Achternaam → `<geanonimiseerd>`.
- Config: `cp config/anonymize.example.json config/anonymize.local.json` en `chmod 600`. Niet in chat.

## Qdrant-collecties

findash schrijft **alleen** naar `findash_tx` (384-d cosine). Bestaande collecties (`FinBot`, `Finbot`, `FinBotv2-embedding-3-small`, `FinBotv2-embedding-ada-002`, en overige) zijn foreign: geen scroll, geen drop, geen upsert. Probe: `pip install -r requirements-qdrant.txt` daarna `PYTHONPATH=. .venv/bin/python scripts/test_qdrant.py`.

Ingest-recept: vector = IBAN-vrije **omschrijving** (geen Af/Bij, geen rekening, geen tegenrekening). Payload: hoofd/sub/entiteit/richting/rekening/flow_kind — geen IBAN. Index: expense, refund, income, saving, unclassified. Skip: intern, CC-incasso. k-NN zonder richting-filter. Model: MiniLM-L12 (384-d). `PYTHONPATH=. .venv/bin/python scripts/ingest_qdrant.py` (UUID5 upsert).

## Kopie n8n → findash

`PYTHONPATH=. .venv/bin/python scripts/copy_n8n_to_findash.py --dry-run`  
daarna zonder `--dry-run`. Blijft in MariaDB (`INSERT SELECT`). Geen Raw. Voegt `Similarity DECIMAL(6,4) NULL` toe.
