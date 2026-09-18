# findash — briefing (handoff)

Laatste bijwerking: 2026-09-10. Dashboard v1 draait lokaal (127.0.0.1:8088). Schema `findash` geseed. Handoff: deze briefing + [`docs/hygiene-bevindingen.md`](hygiene-bevindingen.md). Nieuwe sessie starten; deze chat niet hervatten.

## Opdracht

Lokaal finance-dashboard op de bestaande MariaDB van n8n/FinBot. Doel: **gecategoriseerde uitgaven** zichtbaar maken, met filters, vrolijk/vriendelijk kleurgebruik, dynamische grafieken. Interne stromen (overboekingen, CC-aflossing, sparen) mogen niet als echte uitgaven/inkomsten meetellen, maar moeten wél ergens inzichtelijk zijn.

Ook:

- Read-only MariaDB-user. Add-on kan alleen `SELECT` op heel `n8n` (inclusief Raw). App en probes queryen Raw niet. Later eigen vertaaltabel.
- Indicatie als queries traag zijn, met hint welke kolommen een index kunnen gebruiken.
- Drie talen: Nederlands (standaard), Engels, Russisch. Termen uit de database (categorieën e.d.) via een vertaallijst in MariaDB; nieuwe termen vragen een app-update.

## Beslissingen tot nu toe

| Onderwerp | Keuze |
|---|---|
| Waar draait het dashboard | Lokaal. Mag in Docker. Later mogelijk Home Assistant Supervised. Niet publiek op internet. |
| Dashboard-login | Niet nodig. |
| Database | Bestaande MariaDB-add-on op Home Assistant. Geen Postgres op het werkstation: dat zou n8n-import meeslepen. |
| DB-user hosts | Add-on maakt altijd `'user'@'%'`. RFC1918-beperking zit niet in de GUI; poort 3306 niet op internet zetten. |
| Interne mutaties | Live counts bevestigen de werkhypothese (zie datamodel). Niet hardcoden tot het ontwerp. |
| Raw-tabel | `SELECT` op `n8n.*` geaccepteerd (add-on kan geen tabelrechten). Dashboard/probes queryen `FinBotTransactionsRaw` niet. |
| MariaDB-user aanmaken | Via de MariaDB-add-on GUI (`logins` + `rights`), daarna add-on (her)starten. Agent maakt geen admin-login. phpMyAdmin-GRANTs op tabelniveau worden bij herstart overschreven. |
| Credentials | Alleen `.env` in deze repo (gitignored, mode 600). Kopie van `.env.example`. Nooit in git of chat. |
| Privacy / zoekruimte | Globale Grok-sandbox `strict` (`~/.grok/config.toml`). Agent blijft in deze map. Nieuwe sessie starten; deze chat niet hervatten. |
| Implementatie | v1 goedgekeurd 2026-09-08, gebouwd. Stack FastAPI+HTMX; bind 127.0.0.1:8088. |
| Talen | Nederlands (standaard), Engels, Russisch. UI + termen uit de transactietabellen. Vertaallijst in MariaDB; geen live vertaal-editor in het dashboard. |

## Wat de gebruiker nog doet

1. `.env` in deze repo houden (gitignored). Wachtwoord niet in de chat.
2. MariaDB-add-on GUI: `findash` heeft `SELECT` op `n8n` (staat). Op `findash`.* heeft dezelfde user nu ALL (gebruikt om 001–003 te seeden). Optioneel later terugzetten naar SELECT, zodat de GUI-rechten een herstart overleven.
3. Schema `findash` bestaat; `scripts/apply_findash_schema.py` heeft 001–003 gedraaid (`/health` → `findash_schema: ok`).

## App-stand (2026-09-10)

Draaien: `PYTHONPATH=findash .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8088` (geen `--reload`; na codewijziging kill+start). Tests: `PYTHONPATH=findash .venv/bin/pytest -q`. Productie: HA-add-on, zie [`docs/addon.md`](addon.md).

Gebouwd sinds ontwerp-goedkeuring (niet uitputtend): chrome-header + Nunito; periodechips; zoom-pil in categoriekleur; sparen/opname/netto-KPI; interne stromen van→naar onderin; inkomstentabel; transacties uitklappen onder de rij + Sluiten; info-i op zes KPI’s; favicon = koraalrood logo. CC-aflossing blijft uit de UI (wel geclassificeerd).

Import-studio: `/import-studio`. Bank-CSV en CC-PDF: preview nieuw/dubbel vóór schrijven (MD5 TransactieID op raw). Geen Raw-write. HA-add-on is v2.

## Volgende sessie (volgorde)

1. Deze briefing + `AGENTS.md` + [`docs/hygiene-bevindingen.md`](hygiene-bevindingen.md).
2. Niet buiten deze git-root.
3. Hygiene of Qdrant: eerst ontwerp als het writes of nieuwe productvlakken zijn.

De SQL-bestanden in `docs/sql/` blijven als referentie. De add-on overschrijft tabel-GRANTs bij start met `GRANT … ON n8n.*`.

## Infrastructuur

MariaDB en Qdrant draaien als Home Assistant-add-ons op het LAN. Host/wachtwoord alleen in gitignored `.env` (laptop) of add-on-opties (productie). Voorbeeldhost in `.env.example`: `192.168.1.10`. Operator-notities (DNS, VLAN, echte host): gitignored `docs/briefing.local.md`.

Buitenshuis hangt MariaDB van VPN af; lock van het werkstation kan VPN kappen. `/health` time-outt dan — geen hung uvicorn, niet herstarten.

## Database-toegang

Veilig delen met de agent: alleen `.env` in deze map (gitignored, mode 600). Nooit wachtwoord in chat of git. Gegenereerde SQL met wachtwoord: `docs/sql/create-findash-user.local.sql` (gitignored). Publieke template: `docs/sql/create-findash-user.sql`. Test: `.venv/bin/python scripts/test_db_access.py`.

Status 2026-09-08: login ok (`findash@%`). `SELECT` op de twee anonieme tabellen ok, geen writes. Raw is technisch leesbaar; **niet queryen** (keuze 1). Host `%` is add-on-standaard. Testscript waarschuwt, faalt niet meer op Raw.

HA MariaDB-add-on (bron `mariadb-post/run`): bij elke start `CREATE USER '…'@'%'`, daarna `REVOKE ALL ON db.*` + `GRANT {privileges} ON db.*`.

Postgres op dit werkstation: afgewezen voor het dashboard.

## Datamodel (live, 2026-09-08)

Probe: `scripts/probe_schema.py` (geen Raw, geen IBAN-dump). MariaDB 11.4.10, InnoDB.

**Tabellen in `n8n`:** `FinBotTransactions` (6595 rijen), `FinBotTransactionsCC` (378), `FinBotTransactionsRaw` (~6400, niet queryen). Geen kolom `Tag`.

**Bank (`FinBotTransactions`):** `id` PK unsigned int; `TransactieID` char(40) UNIQUE; `Datum` **int(8)** yyyymmdd (min 20240101, max 20260831); `Jaar` smallint, `Maand`/`Dag` tinyint; `Naam / Omschrijving` tinytext; `Rekening` tinytext; `Tegenrekening` tinytext; `Code` tinytext; `Af Bij` tinytext; `Bedrag (EUR)` decimal(10,2); `Mutatiesoort` tinytext; `Mededelingen` text; `Saldo na mutatie` decimal(10,2); `Hoofdcategorie`/`Subcategorie`/`Entiteit` tinytext; `Confidence` tinyint.

**CC (`FinBotTransactionsCC`):** zelfde `id`/`TransactieID`/`Jaar`/`Maand`/`Dag`/`Af Bij`/`Hoofdcategorie`/`Subcategorie`/`Entiteit`/`Confidence`/`Rekening`. Anders: `Datum` **tinytext** `dd-mm-yyyy` (niet sorteren als datum; gebruik Jaar/Maand); `Omschrijving` i.p.v. `Naam / Omschrijving`; `Bedrag` i.p.v. `Bedrag (EUR)`; `Mutatie` text; `Type` tinytext (`Betaling` 346, `Incasso` 30, `Kosten` 2). Geen `Tegenrekening`, `Code`, `Saldo`.

**Rekeningen:** twee eigen bankrekeningen plus één CC-rekening (zelfde huishouden). Extra `Rekening …`-labels komen als tegenrekening, niet als filteroptie. `Entiteit` bevat o.a. `spaarrekening` en `Oranje Spaarrekening`. Live labels staan in `.env` (`FINDASH_OWN_REKENINGEN` / `FINDASH_CC_REKENING`), niet in git.

**Tegenrekening (bank):** merendeel leeg; verder IBAN/rekeningachtig (niet in deze repo dumpbaar) plus de rekeninglabels hierboven.

**Richting:** `Af` = uit, `Bij` = in. Bank: 6042 Af / 553 Bij. CC: 348 Af / 30 Bij.

**Indexen:** PK `id`, UNIQUE `TransactieID`; losse indexen op `Datum`, `Jaar`, `Maand`, `Dag`, `Af Bij` (prefix 1), `Hoofdcategorie`/`Subcategorie` (prefix **4** — krap), `Confidence`. Geen samengestelde (Jaar, Maand). Distincts/COUNT op 6.5k rijen: ~20–100 ms.

## Taxonomie (FinBot-categorisatie)

Hoofd → subs:

- Inkomsten: salaris, belastingteruggaaf, kinderbijslag, toeslagen, bijdrage opa, overig, laadvergoeding, bijdrage kado, uit bouwdepot, van spaarrekening, crypto verkoop, ERE
- Overige uitgaven: sparen, schuldaflossing, bankkosten, creditcard, debitrente, zakgeld, geldopnames, kinderopvang, overig, studiefonds kinderen, goede doelen, crypto
- Telecom/tech: AI, software, iCloud, internet, mobiel, home automation
- Vrije tijd: vakantie, kado's, sport, dansles, uit eten, uitstapjes, entertainment, abonnementen, lekkernijen
- Wonen: hypotheek, inrichting, elektriciteit, warmte, water, gemeentebelasting, waterschapsbelasting, belastingen overig, onderhoud, tuin, verbouwing
- Voorkomen: kleding, kapper, manicure/pedicure
- Medische kosten: zorgverzekering, eigen risico, eigen bijdrage, overig
- Verzekeringen: opstal, overlijdensrisico, uitvaart, fiets, WA, autoverzekering, overig
- Educatie: school, boeken, bibliotheek, cursus, zwemles, taalcursus, schoolbijdrage
- Vervoer: parkeren, tol, laadpaal, taxi
- Huishouden: boodschappen, hellofresh, katten, verzorging, schoonmaakster, glazenwassers, supplementen
- Interne overboeking: intern

Live bank: 12 hoofden, 75 subs, sluit aan op deze lijst. Extra/afwijkend: CC-hoofd **Aflossing** (niet in de bank-taxonomie); CC-subs **AI**, **iCloud**, **taalcursus**. `outstapjes` is in de DB gecorrigeerd naar `uitstapjes`. Nog 1 typo: `lekker` + soft-hyphen + `nijen`. Briefing-subs zonder rijen o.a. `taxi`, `crypto` (wel `crypto verkoop` onder Inkomsten). `Bij` komt ook voor op uitgavencategorieën (terugboekingen, o.a. boodschappen 6, kleding 5).

CC-match (live, na nainvoer): CC-tabel 390 rijen. Juni 2025 heeft weer aankopen (10 Af, 1 jun–28 jun) plus incasso 3 jun. Juli-incasso 1101,57 staat in beide tabellen. 31/31 CC-`Bij` matchen een bank-`creditcard`-Af (bedrag, bank 2–4 dagen later). 10 bank-`creditcard`-Af zonder CC-`Bij` = extra stortingen + jan 2024 (CC-`Bij` start feb 2024). Geen 31-dagen-gat meer; resterende gaten 16–19 dagen (rust tussen vaste afschrijvingen).

Categorieën: geen lege hoofd/sub. Geen volledige review nodig voor het dashboard. App-regels vangen intern/sparen/CC-incasso (CC-`Bij` heeft wisselende hoofden). Optionele hygiene later: 1× `lekker`+soft-hyphen; `overig` is een emmer (349 bankrijen); sommige subs onder twee hoofden (vaak terecht: boeken, dansles, laadvergoeding).

## Werkhypothese: geen echte uitgave/inkomen

| Soort | Live (bank tenzij CC) | In het dashboard |
|---|---|---|
| Interne overboeking tussen eigen rekeningen | `Interne overboeking` / `intern` | Apart blok “interne stromen”, default uit in uitgaven/inkomsten |
| CC-aflossing op de bank | `Overige uitgaven` / `creditcard`: Af op de CC-rekening | Weg uit uitgaven (kaartuitgaven staan in CC-tabel) |
| CC-bijschrijving (maandincasso) | CC: `Type=Incasso` Bij. Hoofd wisselt historisch. | Geen inkomen. Match bank: zelfde bedrag, bank 2–4 dagen later. |
| Extra CC-storting | Zelfde bankcategorie `creditcard` Af, **geen** bijbehorende CC-`Bij`. | Ook geen uitgave. |
| Sparen | `Overige uitgaven` / `sparen`: **468 Af**; `Inkomsten` / `van spaarrekening`: **88 Bij** | Apart “sparen/vermogen”, wél inzichtelijk |
| Zakgeld / bijdrage opa | `zakgeld` 146; `bijdrage opa` 32 Bij | echte uitgave/inkomen, meenemen |
| CC `schuldaflossing` Bij | 2 rijen | Nog niet classificeren; geen aanname |

Bestaande Grafana-query filtert alleen `Hoofdcategorie != 'Interne overboeking'` — te grof (CC en sparen blijven dan in de uitgaven). Extra Grafana-union op `Subcategorie = 'creditcard'` over beide tabellen.

Uitgaven bij voorkeur **één keer** tellen: CC-aankopen uit `FinBotTransactionsCC`; bank-aflossing en CC-`Aflossing`-bij niet als uitgave/inkomen.

Live distincts gedaan (zie datamodel + taxonomie). Vertaallijst-bron: hoofd/sub, `Af`/`Bij`, `Mutatiesoort`, CC-`Type`, rekeninglabels. `Entiteit` (~1155 waarden, dubbele schrijfwijzen) niet 1-op-1 vertalen — merchants as-is.

## Productwensen (origineel)

- Filters: tijd/maand, rekening, hoofd- en subcategorie, plus weglaten van interne categorieën in overzichten. Header-schakelaar **Kalender** (1–laatste) vs **Salaris** (named month start = vroegste `Inkomsten/salaris` op dag 20–25 van de vorige kalendermaand, anders de 25e; einde = dag vóór de volgende start). Cookie `findash_cycle`. Import-studio blijft kalender.
- Dynamische, overzichtelijke grafieken.
- Vriendelijk, vrolijk kleurschema.
- Query-performance: zien of het traag wordt; hint voor index op betrokken kolommen (waarschijnlijk `Datum`/`Jaar`/`Maand`, `Rekening`, `Hoofdcategorie`, `Subcategorie`, `Af Bij`).
- Code netjes, leesbaar, geen overbodige rechten, parameterized queries.
- Drie talen (NL/EN/RU); zie Talen.

## Talen

Dashboard-UI in **Nederlands (standaard)**, **Engels** en **Russisch**.

Brontermen (NL, live): 12+1 hoofden (plus CC `Aflossing`), ~75+ subs, `Af`/`Bij`, 10 mutatiesoorten, 3 CC-types, rekeninglabels. `Entiteit` te groot/rommelig voor een complete vertaallijst.

Vertaallijst **in MariaDB**, eigen tabel(len) van findash (niet in de FinBot-tabellen schrijven). Het dashboard **leest** vertalingen (`SELECT`). Nieuwe of gewijzigde vertalingen komen mee met een **app-update** (migratie/seed), bijvoorbeeld als FinBot een nieuwe categorie toevoegt. Geen vertaal-UI in het dashboard.

Ontbrekende vertaling: de bronterm tonen (Nederlands) tot de volgende update de EN/RU-rij toevoegt.

Gevolg voor rechten: `findash` blijft read-only; GRANT later ook `SELECT` op de vertaaltabel. Schrijven van vertalingen is geen runtime-recht van de dashboard-user. Exact schema (één tabel vs. key/locale, eigen database vs. `n8n`) volgt in het ontwerp.

## Volgende sessie

Zie boven (App-stand) en [`docs/hygiene-bevindingen.md`](hygiene-bevindingen.md). Nieuwe chat; briefing eerst lezen.

## Bewust niet in deze repo

IBAN’s, wachtwoorden, n8n-JSON’s, Obsidian-notities, CSV’s. Alleen wat hierboven nodig is om door te werken.
