# FinDash op Home Assistant (add-on)

Laptop = test (`PYTHONPATH=findash .venv/bin/uvicorn …`). HA = productie. **Zelfde MariaDB en Qdrant.** Geen wachtwoorden in git. Geen scp vanaf de Mac: HA haalt de code zelf via GitHub.

Repo: `https://github.com/YOU/findash`. GitHub accepteert **geen accountwachtwoord** meer voor `git push` (fout: *Password authentication is not supported*). Gebruik een **Personal Access Token** of SSH. Token nooit in de chat of in git.

## 1. GitHub (eenmalig)

Doel: een repo **zonder secrets** die de HA Add-on Store kan clonen.

1. GitHub → **New repository** `findash` als die nog niet bestaat.
   - **Public** is het eenvoudigst voor de Store. Private kan; de Store kan daar vaak niet inloggen — gebruik dan pad 2b.
   - Geen README-init als de lokale git al bestaat.
2. **Token** (HTTPS, wat deze clone gebruikt):
   1. GitHub (ingelogd) → [Fine-grained token](https://github.com/settings/personal-access-tokens/new).
   2. Resource owner: jij. Repository: **Only select** → `findash`.
   3. Permissions → Repository → **Contents: Read and write**. Generate.
   4. Token één keer kopiëren. Niet in chat plakken.
   5. Oud wachtwoord uit macOS Keychain (anders blijft de fout):
      `printf "protocol=https\nhost=github.com\n" | git credential-osxkeychain erase`
   6. `git push -u origin main`
   7. Prompt: **username** = je GitHub-user, **password** = de token (niet je GitHub-wachtwoord). Keychain mag hem onthouden.
3. Op de laptop, remote staat al:

```bash
git remote -v   # origin = https://github.com/YOU/findash.git
git push -u origin main
```

3. GitHub → **Settings** van de repo:
   - **Secrets and variables** → geen `MARIADB_PASSWORD`, geen Qdrant-key, geen IBAN.
   - **Actions** mag uit (niet nodig).
   - **Pages** uit.
   - Collaborators: alleen jij.
4. Controle vóór de push: `git status` toont geen `.env` en geen `anonymize.local.json`. Die staan in `.gitignore`.

HA clonet daarna zelf. Jij pusht alleen vanaf de laptop.

## 2. Home Assistant — add-on installeren

### 2a. Add-on Store (voorkeur, alleen GUI)

1. **Instellingen → Add-ons → Add-on Store**.
2. Rechtsboven **⋮ → Repositories**.
3. Plak `https://github.com/YOU/findash` → **Add**.
4. Store verversen. Onder de repository **FinDash** → **Install**. Eerste build downloadt Python-packages (en later het embed-model naar `/data`); dat duurt.
5. **Niet starten** tot de configuratie hieronder klopt.

### 2b. Private repo (GUI-terminal, geen scp)

Alleen als 2a faalt omdat de repo private is.

1. GitHub → Settings → Developer settings → Personal access token (read-only `contents`). Token niet in git.
2. In de HA **Terminal**-add-on (protection mode uit als `addons/local` anders niet schrijfbaar):

```bash
cd /usr/share/hassio/addons/local
git clone https://github.com/YOU/findash.git findash-src
# Store-layout: de add-on zit in de submap findash/
ln -s findash-src/findash findash
```

3. HA: Add-on Store verversen; lokale add-on **FinDash** installeren.
4. Update later: `cd /usr/share/hassio/addons/local/findash-src && git pull` en in de GUI **Rebuild**.

## 3. Configuratie in de HA-GUI (blijft bij updates)

Add-on **FinDash → Configuratie**. Supervisor slaat dit op, niet in de image.

| Veld | Wat invullen |
|---|---|
| MariaDB-host | Hostname van **jouw** MariaDB-add-on. Vaak `core-mariadb`. Check: die add-on → **Info** (hostname). Niet het LAN-IP van de laptop-`.env`. |
| MariaDB-poort | `3306` |
| MariaDB-gebruiker | `findash` |
| MariaDB-wachtwoord | Zelfde als laptop-`.env`. Alleen hier, niet in git. |
| Transactieschema | `findash` |
| Vertalingsschema | `findash` |
| Qdrant-URL | `http://<qdrant-hostname>:6333` — hostname via Qdrant-add-on → **Info**. De default `http://qdrant:6333` is een gok; vervang hem. |
| Qdrant API-key | Key uit de Qdrant-add-onconfig. Roteren: Qdrant + dit veld + laptop-`.env` in één keer. |
| Qdrant-collectie | `findash_tx` |
| Standaardtaal | `nl` |

**Opslaan → Starten.** Zijbalk: **FinDash** (ingress, HA-login). Optioneel poort 8088 alleen op LAN, niet guest-VLAN/internet.

Na een nieuwe release: op de laptop `version:` in `findash/config.yaml` ophogen, `git push`, op HA **Update**. Deze velden blijven staan.

## 4. Anonimiseren op HA (niet via git)

Import-studio op HA leest `/share/findash/anonymize.local.json`.

1. Op de laptop: je hebt al `config/anonymize.local.json` (niet openen in de chat).
2. Op HA: **File Editor** of Studio Code → map `/share/findash/` aanmaken.
3. Bestand `anonymize.local.json` daar neerzetten (inhoud plakken in de editor, of upload via de share). `chmod 600` in de terminal als die map dat toelaat.
4. Geen IBANs in add-on-opties.

## 5. Hostnames opzoeken

**Instellingen → Add-ons → [MariaDB of Qdrant] → Info.** Daar staat de hostname op het interne net. FinDash als add-on moet **die** naam gebruiken, niet `192.168.1.10` (dat is voor de laptop/VPN).

## 6. Wat je niet doet

- Geen `.env` uploaden.
- Geen FinBot-Qdrant-collecties in het collectieveld.
- Laptop en HA niet tegelijk dezelfde studio-rij opslaan (zelfde DB).
- Agent installeert niets op de HA-host.
