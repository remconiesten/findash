# findash — projectregels

Lees bij de start van elke sessie `docs/briefing.md`. Dat is de opdracht, de afspraken en de al ontdekte data. Vraag de gebruiker niet opnieuw om context die daar al staat.

## Mapgrens (hard)

- Werk **alleen** in de git-root van deze clone. Geen paden buiten de repo.
- Niet lezen, zoeken of listen buiten deze map: geen home, Documents, Downloads, Library, Obsidian, andere projecten, shell-history, SSH-keys.
- Geen `mdfind`, Spotlight of `find` vanaf `$HOME`.
- Geen poortscans of DNS-enumeratie van het LAN, tenzij de gebruiker dat in deze sessie expliciet vraagt.
- Schema, credentials en dumps komen van de gebruiker **in deze map** (bijv. `.env`, `docs/`), of via MariaDB met gegevens uit `.env` in deze map.
- Uitzondering: Grok-productdocs onder `~/.grok/docs/` als de gebruiker naar TUI-gedrag vraagt. Verder niets onder `~/.grok/` (geen oude sessies).

Sandbox staat globaal op `strict`. Dat is de kernelgrens. Deze regels zijn de inhoudelijke grens: ook niet *vragen* om paden buiten de repo.

## Privacy

- Geen secrets, IBAN’s of wachtwoorden in git of in chat herhalen.
- `.env` staat in `.gitignore`. Inhoud van `.env` gaat wél naar het model als je hem leest — alleen lezen als nodig voor DB-connectie.
- Nooit `config/anonymize.local.json` lezen, dumpen of in chat herhalen. Alleen `config/anonymize.example.json`.
- Eerdere sessie heeft buiten deze map gelezen; die inhoud niet opnieuw ophalen.

## Werkwijze

- App-bron staat in `findash/app` (HA add-on-buildcontext). Lokaal: `PYTHONPATH=findash`.
- Dit is een **nieuw** product. Eerst ontwerp ter goedkeuring, daarna code. Niet implementeren tot de gebruiker het ontwerp goedkeurt.
- Code: controleren op fouten, leesbaarheid en kwetsbaarheden (SQL-injectie, secrets in frontend, te ruime DB-rechten).
- UI-wijzigingen in de browser verifiëren als die tools er zijn.
