# Läge — tender-scan

<!-- Genererad av scripts/state.py vid varje sessionsstart.
     Redigera inte de genererade avsnitten för hand; de skrivs över.
     Allt mellan MANUELLT:START och MANUELLT:SLUT behålls som det är. -->

_Genererad 2026-09-03 07:16 UTC._

## Planen och kontakterna

<!-- MANUELLT:START -->
### Var jag är

_Den här delen skrivs aldrig över av generatorn. Håll den kort och ärlig._

- **Läge:** M0–M8 klara och testade. M8 är nytt: `tender-scan edge`, verktygen
  som lägger avtalskatalogen ovanpå reskontran och räknar ut var de säger emot
  varandra.
- **Huddinge är komplett.** Reskontran kom 2026-09-02 (fyra filer, 488 954
  fakturarader 2023-01..2026-08, 8,11 mdr) och är inläst. Huddinge är enda
  kommunen vars reskontra namnger konto och ansvar — vad pengarna gick till och
  vilken enhet som köpte. Ärende #7 är `received`.
- **Två kompletta par nu:** Bjurholm (23 mån) och Huddinge (44 mån).
  Databasen har 9 790 avtalsrader och 204 799 betalningsrader, 19,4 mdr.

### Vad som faktiskt går att påstå, med siffror

Huddinge, 2023-01..2026-08, efter att transfereringar, hyra, monopol och
individuella placeringar tagits bort ur basen:

| | |
| --- | --- |
| Upphandlingsbart | 2,62 mdr av 8,11 mdr |
| Betalt till leverantör utan löpande avtal | 845 mkr (32,2 %) |
| Avtalsleverantörer med noll kronor på 44 mån | 237 av 745 — 31,8 % [28,6–35,2] |
| Samma sak, placeringsavtal (redovisas separat) | 137 av 346 — 39,6 % [34,6–44,8] |
| Avtal som löper ut inom 12 mån | 258 leverantörer, 970 mkr/år |

**Vad som fortfarande inte går att påstå:** takvolym mot verkligt avrop. Bara
Jönköping publicerar avtalsvärden (480 avtal, 5,13 mdr) och Jönköping har inte
skickat reskontra. Antalet kommuner där tak och utfall kan jämföras är noll.

**Kör `tender-scan db check`** för att se vilka kommuner som saknar vilken halva.

Analysen ligger som artefakt: *Avtalsglappet i Huddinge*,
https://claude.ai/code/artifact/621f7123-2b0d-4f90-ba85-d74a11f7d132
Den innehåller också invändningarna — viktigast: Huddinges katalog saknar
rangordning helt (0 av 2 365 rader), så 237 är en **övre gräns** på antalet
vilande avtal, inte en mätning. Be om rangkolumnen i nästa begäran.

### KRÄVER SVAR AV DIG

1. **Katrineholm (#15)** vill ha fakturaadress innan de gör något. 10–16 filer.
2. **Karlstad (#8)** vill ha principbesked om avgift (100 kr/50 sidor + 2 kr/sida)
   innan de räknar sidor. Sätt ett tak i svaret.
3. **Hässleholm (#13)**: 161 kr accepterat 2026-08-31, 19 filer. Jaga fakturan.
4. **19 ärenden ligger på dag 3-påminnelse.** `tender-scan foia due`.
5. **Huddinges följebrev är inte läst.** Filerna identifierades på innehållet,
   inte på ett mejl. Finns det en avgift eller ett villkor i det mejlet vet vi
   inte om det.

### Nästa datajobb, i prioritetsordning

1. **Borås avtalskatalog** från Koncerninköp. Reskontran (10,75 mdr, 3 år) finns
   redan; katalogen gör den mätbar och ger par nummer tre. 2026-filen utlovad 9 sep.
2. **Ett tredje par med konton.** Två kommuner är ingen jämförelsegrupp —
   `edge benchmark` säger ingenting förrän en tredje reskontra med konton kommer.
   Be uttryckligen om kontobenämning i nästa batch.
3. **Göteborgs reskontra** behöver ingen begäran — staden hänvisade till sin öppna
   data och repot har redan laddaren: `tender-scan payments load goteborg`.
   Obs: M4-raderna är filtrerade till TED-vinnare och används därför aldrig som
   nämnare i M7/M8; en full inläsning behöver gå in som `source='foia'`.

### Allt bor nu i data/

`data/` — databasen, `outreach/` (utskickslistan, mallarna, `send_batch.py`),
`ATTACHMENTS/` (alla inkomna handlingar, 108 MB) och `backups/`.
`~/Desktop/OUTREACH` finns inte längre; allt verifierades byte-identiskt först.

**`data/` är gitignorerat två gånger om** — dels av rot-`.gitignore`, dels av
`data/.gitignore` som spärrar allt. Ingenting härifrån kan committas av misstag.
**Ingen backup utanför maskinen.** Databasen innehåller personnummer
(enskilda firmor), tjänstemäns namn och myndighetsmaterial.

### Skickade mejl och kontakter

_Utlämnandebegäranden spåras i databasen och listas automatiskt längre ned.
Allt annat — säljmejl, samtal, möten — skrivs för hand här._

| Datum | Vem | Vad | Status |
| --- | --- | --- | --- |
| – | – | Inget säljsamtal loggat ännu | – |

### Vad som är facit, och vad som inte kör av sig självt

- **Facit = tabellen `foia_requests`.** `foia due` läser den och ingenting annat.
  `data/outreach/batch1_pilot.csv` är en *inmatning* via `foia import`,
  aldrig en parallell sanning.
- **Det finns EN databas**, `data/tender_scan.db`, med åtta tabeller.
  `tender-scan db status` säger vad var och en är och vilket kommando som fyller den.
- **Ingenting är automatiserat.** Ingen crontab, ingen systemd-timer, ingen
  schemalagd agent. `foia due` *listar* vad som förfallit när du kör den.
  `send_batch.py` skickar bara när du själv kör den med `--live`.

### Om du kör i en molncontainer

Kör `bash scripts/setup.sh` först. Den väljer en Python 3.12+ (obs: `python3`
är PyPy 3.11 på ägarens maskin), installerar CLI:t och listar vad klonen
saknar. Databasen och `data/` följer **aldrig** med — de är gitignorerade med
flit. Det är väntat, inte ett fel.

Behöver du ändra det verkliga ärendeläget: skriv ett skript som kör
`tender-scan foia ...`, **committa och pusha det**, och låt den lokala sessionen
köra det.
<!-- MANUELLT:SLUT -->

## Kod

- Gren: `main`
- Synkad med `origin/main`
- Arbetsträd: rent

| Commit | Datum | Vad |
| --- | --- | --- |
| `f6f38e6` | 2026-09-03 | docs(state): link the Huddinge analysis and its strongest objection |
| `88dcad9` | 2026-09-03 | fix(m8): size an expiring contract from its own months, not the supplier's history |
| `e2b3689` | 2026-09-03 | chore(state): refresh after M8 |
| `d8fce29` | 2026-09-03 | feat(m8): lay the catalogue over the ledger and measure where they disagree |
| `96ae990` | 2026-09-02 | feat(m7): read what the municipalities actually sent back |
| `3da8faf` | 2026-09-01 | feat(m3): foia ingest --partial, so half a delivery does not retire a request |
| `3cd8b89` | 2026-09-01 | feat(setup): bootstrap a fresh clone and say what it lacks |
| `128b1e1` | 2026-09-01 | docs(state): hand off the Gmail triage of batch 1 to the next session |

## Vad som kör

| Container | Status | Image |
| --- | --- | --- |
| `tender-scan-app-1` | Up 22 minutes | `tender-scan-app` |
| `tender-scan-tailscale-1` | Up 2 hours | `tailscale/tailscale:latest` |

- Image `tender-scan-app` byggd: 2026-09-03 08:53:00 UTC
- ⚠️ **Imagen är 8 min äldre än senaste commit — containern kör gammal kod.** Kör `docker compose up -d --build`.
- Nås bara över tailnet: **http://tender-scan:8000**. `localhost:8000` är avsiktligt stängt (`network_mode: service:tailscale`).

## Vad databasen innehåller

| Tabell | Rader | Vad |
| --- | --- | --- |
| `notices` | 0 ⚠️ tom | notiser från TED |
| `framework_agreements` | 137 | ramavtal med takvolym |
| `award_winners` | 1771 | tilldelade leverantörer |
| `framework_buyers` | 173 | avropsberättigade köpare |
| `supplier_payments` | 204799 | fakturarader från öppna reskontror |
| `foia_requests` | 20 | utlämnandebegäranden |

## Utlämnandebegäranden

| # | Myndighet | Ramavtal | Skickat | Status |
| --- | --- | --- | --- | --- |
| 20 | Grästorps kommun | `–` | 2026-08-31 | partial |
| 19 | Dorotea kommun | `–` | 2026-08-31 | sent |
| 18 | Bjurholms kommun | `–` | 2026-08-31 | partial |
| 17 | Aneby kommun | `–` | 2026-08-31 | sent |
| 16 | Härnösands kommun | `–` | 2026-08-31 | sent |
| 15 | Katrineholms kommun | `–` | 2026-08-31 | sent |
| 14 | Enköpings kommun | `–` | 2026-08-31 | sent |
| 13 | Hässleholms kommun | `–` | 2026-08-31 | sent |
| 12 | Kalmar kommun | `–` | 2026-08-31 | sent |
| 11 | Falu kommun | `–` | 2026-08-31 | sent |
| 10 | Haninge kommun | `–` | 2026-08-31 | sent |
| 9 | Halmstads kommun | `–` | 2026-08-31 | sent |
| 8 | Karlstads kommun | `–` | 2026-08-31 | sent |
| 7 | Huddinge kommun | `–` | 2026-08-31 | received |
| 6 | Gävle kommun | `–` | 2026-08-31 | sent |
| 5 | Eskilstuna kommun | `–` | 2026-08-31 | sent |
| 4 | Borås stad | `–` | 2026-08-31 | partial |
| 3 | Jönköpings kommun | `–` | 2026-08-31 | partial |
| 2 | Helsingborgs stad | `–` | 2026-08-31 | sent |
| 1 | Göteborgs stad | `–` | 2026-08-31 | partial |

- Deadlines räknas av `tender-scan foia due` — den här filen upprepar dem inte.

## Var siffrorna kommer ifrån

Utnyttjandegraden bygger på fakturarader som köparen publicerat som öppna data.
En grad utan sina två täckningstal — andel köpare och andel förflutna månader —
är en undre gräns, inte en mätning. Webbvyn och rapporten visar alltid båda.
Detaljerna står i README under *Utnyttjandegrad*.
