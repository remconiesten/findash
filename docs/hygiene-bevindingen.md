# Categorisatie-hygiene (live n8n, 2026-09-09)

Read-only patrooncheck op `FinBotTransactions` (6595) en `FinBotTransactionsCC` (390). **Geen Raw.** Geen IBAN-dumps. Huishoudspecifieke labels (schoonmaakster, zakgeld, bijdrage opa) zijn **niet** als fout aangemerkt.

Gem. Confidence bank ~88,9; CC ~88,5. Geen lege hoofd/sub. 5 bank- + 2 CC-rijen zonder Entiteit.

## Hygiene (vrijwel zeker fout of dubbel)

| Bevinding | Omvang | Toelichting |
|---|---|---|
| Soft-hyphen `lekker­nijen` | 1 bank vs 77× `lekkernijen` | Zelfde sub, andere string. |
| Entiteit-alias NN | 55 `Nationale Nederlanden` + 110 `Nationale-Nederlanden` | Zelfde partij, twee spellings. |
| Sub onder verkeerd hoofd (1-offs) | `kleding` 1× Vrije tijd (328× Voorkomen); `tuin` 1× Huishouden (52× Wonen); `dansles` 1× Educatie (41× Vrije tijd); `laadpaal` 1× Overige uitgaven (47× Vervoer) | Minderheid vs stabiele hoop. |
| Entiteit `spaarrekening` als intern | **62** intern (57 Bij / 5 Af, conf ~96) naast 452 sparen-Af + 84 van-spaarrekening-Bij | Dashboard telt die 62 als intern, niet als sparen. Plus 1× `kado's` en 1× `uit eten` (conf 70). |
| Albert Heijn als inkomen/sparen | 5× Inkomsten/overig (Bij, €0,27–€52); 4× `van spaarrekening` (Bij) | 443 AH-rijen verder boodschappen. Statiegeld/terugboeking hoort refund, geen inkomen. |
| Lidl als inkomen | 1× Inkomsten/overig | |
| Hosting.nl als inkomen | 1× Inkomsten/overig naast 14× Telecom | |
| ING als zorgverzekering | 7× €4,35, Entiteit ING / ING BANK / ING BANK N.V. | Betaalkanaal, niet de verzekeraar. Sub kan kloppen. |

## CC-incasso (dashboard vangt dit al)

CC-`Bij` + `Type=Incasso`: 18× Aflossing/creditcard, 11× intern, 2× schuldaflossing. Zelfde mutatiesoort, wisselende hoofd. `flow_kind` gebruikt `Type`, niet de hoofd.

## Rommelig, niet per se fout

- **`overig`:** 349 bank (Vrije tijd 113, Overige uitgaven 71, Huishouden 51, Inkomsten 47, …) + 5 CC. Confidence &lt;50: 61 bankrijen, bijna allemaal `overig` / uitstapjes / kado's. 255 rijen in 50–69.
- Entiteit **`persoon`:** 281 rijen, 20 hoofd/sub-combinaties — te breed voor matching.
- Entiteit **ING** (en varianten): tot 7 cats (bankkosten, creditcard, geldopnames, zorgverzekering, …).
- Street Jump / Street Jump Alkmaar: dansles, sport, entertainment, uitstapjes.
- McDonald’s: 46× uit eten, 5× lekkernijen, 1× vakantie.
- Apple (CC): 53× software, 20× iCloud (~€10), 6× entertainment. iCloud zit waarschijnlijk deels in software.
- Kruidvat: 35× verzorging, 22× kleding, 11× boodschappen.
- Road B.V.: Af→laadpaal en Bij→laadvergoeding is consistent; 1× Inkomsten/overig en 1× Vervoer/laadvergoeding is ruis.
- Action: 183 boodschappen / 16 overig / 5 inrichting / 4 verzorging — grotendeels plausibel.

## Bewust niet aangevallen

Schoonmaakster, zakgeld, bijdrage opa, kado-Bij van `persoon` (~€6). Dat is prompt-/huishoudkennis, geen algemeen patroon.

## Qdrant-route (beoordeling, niet gebouwd)

Valide als **hybride**, niet als enige categoriseerder.

1. Harde regels eerst (intern, sparen, CC-incasso) — al in `app/classify.py`.
2. Exacte/majority-hit op genormaliseerde naam + Entiteit.
3. Qdrant k-NN op IBAN-vrije omschrijving + prefix (`Af\|A\|…`). Payload: hoofd, sub, entiteit, richting, rekening — geen IBAN.
4. Auto alleen bij hoge similarity én eensgezinde buren.
5. GUI voor de middenmoot; correctie meteen naar Qdrant **en** een findash-tabel. Schrijven naar `n8n` alleen na expliciete keuze (dashboard-user is bedoeld SELECT-only op FinBot).

Niet in de index als centroid: `persoon`, kale `ING`, `spaarrekening` zonder richting. 6,5k gelabelde rijen is genoeg voor k-NN. Confidence uit Grok/OpenAI is geen Qdrant-score.

## Volgende keer

- Read-only hygiene-rapport/queries (geen writes naar FinBot).
- Operator mag 1-offs en AH-als-inkomen in phpMyAdmin/FinBot rechtzetten.
- Qdrant+GUI alleen na ontwerp ter goedkeuring (schrijfrechten, n8n vs findash).
