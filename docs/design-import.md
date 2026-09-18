# findash — eigen database, importstudio, n8n uitfaseren

| Veld | Waarde |
|---|---|
| Status | **Draft** — kopie-script mag; app leest tot cutover nog `n8n`. Geen importstudio tot goedkeuring. |
| Datum | 2026-09-15 |
| Hangt samen met | [`design-qdrant.md`](design-qdrant.md), [`refund-audit.md`](refund-audit.md), [`import-rules.md`](import-rules.md), [`briefing.md`](briefing.md) |

## Beslissingen (deze sessie)

- n8n verdwijnt uit de werkwijze. Bestaande rijen gaan **eenmalig** mee; daarna vult **alleen** de importstudio.
- Transactiekopie in het **bestaande** schema `findash` (naast `ui_string` / `term`). Geen derde database-naam.
- FinDash heeft ALL op `findash`; SELECT op `n8n` tot cutover.
- Dashboard-KPI’s lezen de nieuwe database; geaccepteerde categorieën tellen meteen (vraag C).
- Winkel-Bij op `Inkomsten` wordt refund op de uitgavecategorie ([`refund-audit.md`](refund-audit.md)).
- `Confidence` blijft het oude FinBot-cijfer. Nieuw veld **`Similarity`** (vector-score). Niet hergebruiken.
- Nieuwe Qdrant-collectie `findash_tx`. Accept in de studio upsert Qdrant.
- Importstudio is een **apart scherm**, achter het dashboard.

## Doelbeeld

```text
CSV bank  ──► importstudio ──► findash.FinBotTransactionsRaw
                                    │  anonimiseer + MD5 TransactieID
                                    ▼
                              FinBotTransactions  ──► dashboard KPI
                                    │                 Qdrant findash_tx
PDF/CSV CC ──► importstudio ──► FinBotTransactionsCC
```

n8n schrijft na cutover **niet** meer naar deze tabellen. `n8n.FinBot*` blijft als historisch origineel staan tot jij die add-on-kant zelf uitzet.

## Database-naam en rechten

Schema **`findash`** (bestaat; user heeft ALL). `n8n` blijft de bron tot de kopie klaar is.

### Waarom niet phpMyAdmin “kopieer n8n”

Dat zou `FinBotTransactionsRaw` meenemen (IBAN’s). Script kopieert **alleen** de twee geanonimiseerde tabellen, plus kolom `Similarity`.

### Credentials

Geen nieuw wachtwoord. `.env`: `MARIADB_DATABASE=n8n` (bron), `FINDASH_DATABASE=findash` (doel). Cutover later: `MARIADB_DATABASE=findash` zodat de app de kopie leest; daarna mag SELECT op `n8n` uit.

## Eenmalige kopie

`scripts/copy_n8n_to_findash.py`: `CREATE TABLE findash.T LIKE n8n.T` + `INSERT SELECT *` + `Similarity DECIMAL(6,4) NULL`. Geen Raw. Stdout: counts, geen rijen. Tweede run met gelijke counts is een no-op. Afwijkende dest-tabel wordt niet gedropt.

## TransactieID

Live: `char(40)` UNIQUE, 32 hex. Recept in [`import-rules.md`](import-rules.md): hash op **raw**, bank vier velden, CC vier velden. Herimporttest: oude CSV → 0 inserts.

## Anonimiseren

`config/anonymize.local.json` (niet in git, niet door agents gelezen). IBANs → rekeninglabels; achternaam → `<geanonimiseerd>`. Importstudio past dat toe **ná** de MD5, **vóór** de geanonimiseerde tabel. Raw (later) blijft het hash-input; dashboard/Qdrant lezen Raw niet.

## Creditcard

PDF-parser staat in `app/cc_parse.py` (n8n Edit Fields 1:1, inclusief Kosten-quirk). `Rekening` = `Rekening A`. Later een CSV-pad. `Type` moet overleven (`cc_settlement`).

## Similarity vs Confidence

| Kolom | Betekenis |
|---|---|
| `Confidence` | historisch FinBot/LLM, tinyint. Ongewijzigd meegenomen. Geen drempel voor auto-accept. |
| `Similarity` | cosine 0–1 (`DECIMAL(6,4)`). NULL na de kopie. Gezet bij suggestie-accept of auto-apply uit Qdrant. |

Majority-aandeel (niet-vector) blijft in `category_suggestion.score`, niet in `Similarity`.

## Importstudio (product)

Apart scherm, niet `/`, niet uitklap `/tx`.

1. Bestand kiezen (bank-CSV of CC-PDF).
2. Hash `TransactieID` op **ruwe** velden in-process. **Geen** write naar `FinBotTransactionsRaw`.
3. Preview **vóór** INSERT: tellingen + rijen **nieuw** / **al bekend** / **niet herkend**. Dubbelen zichtbaar. Geen stille skip.
4. Bevestigen schrijft alleen nieuwe rijen naar de geanonimiseerde tabellen. UNIQUE blijft vangrail.
5. Categorie: geheugen (zelfde tekst) of `overig` / `Inkomsten/overig`. k-NN is geen import-voorstel.

## Qdrant

Eigen collectie `findash_tx`. Overlay-COALESCE op live `n8n` **vervalt** na cutover: de app leest `findash`.

## Nog van jou

- `config/anonymize.local.json` vullen (IBANs + achternaam). Niet in chat.
- Cutover: `MARIADB_DATABASE=findash` in `.env` wanneer de kopie klopt.
