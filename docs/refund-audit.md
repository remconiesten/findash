# Bijschrijvingen: inkomen vs refund (live n8n, 2026-09-15)

Read-only audit op `FinBotTransactions` (6595) en `FinBotTransactionsCC` (390). **Geen Raw.** Geen `Tegenrekening`/`Mededelingen`. Geen persoonsnamen in dit overzicht. Probe: `scripts/probe_refunds.py`.

Doel: bijschrijvingen van statiegeld en soortgelijke winkelterugboekingen horen **refund op de betrokken uitgavencategorie**, niet bij inkomsten. Dashboard v1 doet dat al als FinBot de rij *niet* onder `Inkomsten` zet (`flow_kind = refund`). Fout zit in rijen die wél `Hoofdcategorie = Inkomsten` hebben.

Geen writes in deze pass. Voorgestelde herlabels zijn ter goedkeuring; uitvoeren ná kopie naar de nieuwe database (niet in `n8n`).

## Hoe het dashboard nu telt

| FinBot-rij | `flow_kind` | KPI |
|---|---|---|
| `Bij` + `Inkomsten` (behalve `van spaarrekening`) | `income` | inkomsten |
| `Bij` + sub `sparen` / `van spaarrekening` | `saving` | sparen (opname), geen inkomen |
| `Bij` + andere hoofd | `refund` | gaat van het uitgaven-netto af onder die hoofd/sub |
| `belastingteruggaaf` | `income` | echte inkomsten (belasting), geen winkelrefund |

## Bank-`Bij` in het groot

| Emmer | n | € |
|---|---:|---:|
| Echte inkomsten (`Inkomsten`, niet spaaropname) | 286 | 308.720 |
| Spaaropname (`van spaarrekening`) | 146 | 66.260 |
| Al refund (Bij op uitgavencategorie) | 75 | 2.340 |
| Intern | 46 | 19.833 |

Echte inkomsten per sub (klopt, niet herlabelen):

| Sub | n | € |
|---|---:|---:|
| salaris | 65 | 241.177 |
| uit bouwdepot | 43 | 19.360 |
| bijdrage kado | 39 | 293 |
| bijdrage opa | 32 | 3.200 |
| toeslagen | 19 | 4.563 |
| laadvergoeding | 15 | 1.234 |
| belastingteruggaaf | 13 | 26.740 |
| kinderbijslag | 12 | 6.933 |
| crypto verkoop | 2 | 1.738 |

`laadvergoeding` (Road B.V., werkgever) blijft inkomen: bedragen matchen niet met `laadpaal`-Af. Niet netten.

## Al goed: 75 refunds (€2.340)

Deze staan al op een uitgavencategorie + `Bij`. Dashboard trekt ze van uitgaven af. Voorbeelden: Action/Lidl/VOMAR/AH op boodschappen, Zara/Tommy/OTTO/TK Maxx op kleding, KPN op mobiel, HVC/Budget Energie op wonen.

Vier AH-Bij staan al als refund maar op **`Huishouden/overig`** (€30,09), niet op `boodschappen`. Optioneel meenemen in de herlabel-ronde.

## Probleem: `Inkomsten/overig` (46 rijen, €3.482)

FinBot dumpt hier zowel echte rest-inkomsten als winkelterugboekingen. Uitgesplitst:

### Winkel — herlabelen naar uitgavecategorie (dan `flow_kind=refund`)

| Entiteit | n | € | Voorstel hoofd/sub |
|---|---:|---:|---|
| Albert Heijn | 5 | 66,31 | Huishouden / boodschappen |
| Lidl | 1 | 9,97 | Huishouden / boodschappen |
| Hosting.nl | 1 | 11,92 | Telecom/tech / internet |
| Amazon | 1 | 24,90 | nader: Prime/abonnementen of huishouden |
| Karwei | 1 | 33,18 | Wonen / inrichting (of verbouwing) |
| Zalando | 1 | 9,95 | Voorkomen / kleding |
| Saniweb | 1 | 40,58 | Wonen / inrichting |

AH-bedragen in deze emmer: €52,00 / 0,27 / 1,60 / 0,56 / 11,88. De kleintjes zijn typisch statiegeld; €52 kan een grotere winkelterugboeking zijn — hoort nog steeds niet bij inkomsten.

FinBot-`Confidence` op deze winkelrijen is 50–90. Dat getal **niet** hergebruiken als vector-score.

### AH als spaaropname — erger

Vijf extra AH-`Bij` staan onder `Inkomsten/van spaarrekening` (€1.059,99). Dashboard telt ze als **spaaropname**, niet als inkomen en niet als boodschappen-refund.

| Bedrag | Opmerking |
|---:|---|
| 0,27–15,10 plus €13,99 | past bij statiegeld/kleine terugboeking |
| €198,90 / €312,00 / €520,00 | geen statiegeld; wél geen spaaropname |

Voorstel: alle vijf naar `Huishouden/boodschappen` (refund), tenzij jij de grote drie als iets anders herkent (cadeaukaart, terugstorting).

Eén AH-Bij (€5,75) staat al correct op `Huishouden/boodschappen`.

### Geen winkelrefund — niet automatisch herlabelen

| Patroon | n | € | Advies |
|---|---:|---:|---|
| `persoon` / Tikkie / genoemde mensen | 12+ | ~630 | kado, terugbetaalde etentjes, etc. Per rij in de studio, geen bulk |
| ING `STORTING ING` | 2 | 335 | contant storten ≠ inkomen; kandidaat: refund op `geldopnames` |
| ING Bank centen / €8,32 | 5 | ~18 | bankcorrectie; `Overige uitgaven/bankkosten` als refund, of laten |
| Mangopay / Vinted / Mollie | 6 | ~182 | verkoop tweedehands: inkomen *of* vrije-tijd-refund — jouw keuze |
| ABACUS MEDICINE 2× €350 | 2 | 700 | geen winkel; laten tot jij zegt wat het is |
| Bo-Mat / Bo-Rent | 2 | 549 | verhuurterugboeking? Wonen/overig of laten |
| Stichting Wakkerpolis €500 | 1 | 500 | verzekeringsuitkering: eerder inkomen/overig of verzekeringen-refund |
| Wise €183 | 1 | 183 | overboeking/FX, geen winkel |
| Berserker Bouw €71 | 1 | 71 | bouw; mogelijk Wonen/verbouwing-refund |

## CC

Alle 31 CC-`Bij` zijn `Type=Incasso` (aflossing). Geen winkelrefunds in de CC-tabel. Niets te herlabelen voor dit onderwerp.

## Voorstel bulk (na kopie, in de nieuwe database)

Alleen rijen waar de entiteit een winkel is die we al als uitgave kennen:

1. AH `Inkomsten/overig` (5) → `Huishouden/boodschappen`
2. AH `van spaarrekening` (5) → `Huishouden/boodschappen` (grote drie extra bevestigen)
3. Lidl `Inkomsten/overig` (1) → `Huishouden/boodschappen`
4. Hosting.nl (1) → `Telecom/tech/internet`
5. Zalando (1) → `Voorkomen/kleding`
6. Karwei (1) → `Wonen/inrichting`
7. Saniweb (1) → `Wonen/inrichting`
8. Amazon (1) → jij kiest sub
9. Optioneel: 4× AH `Huishouden/overig` Bij → `boodschappen`

Niet in bulk: `persoon`, Tikkie, ING-storting, Mangopay/Vinted/Mollie, Abacus, Bo-Mat, Wakkerpolis, Wise. Die komen in de importstudio-queue `overig`.

Effect op KPI’s als 1–8 doorgaan (orde van grootte): inkomsten −€~200 (plus AH-spaaropnames verdwijnen uit sparen); boodschappen-netto daalt met de refunds.

## TransactieID (voor de importtest, niet voor refunds)

Bank en CC: `char(40)`, **UNIQUE**, alle IDs **32 hex-tekens** (MD5). 6595/6595 en 390/390 distinct. Klaar als dedup-sleutel zodra de hash-receptuur bekend is.
