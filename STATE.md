# Läge — tender-scan

<!-- Genererad av scripts/state.py vid varje sessionsstart.
     Redigera inte de genererade avsnitten för hand; de skrivs över.
     Allt mellan MANUELLT:START och MANUELLT:SLUT behålls som det är. -->

_Genererad 2026-08-31 23:01 UTC._

## Planen och kontakterna

<!-- MANUELLT:START -->
### Var jag är

_Den här delen skrivs aldrig över av generatorn. Håll den kort och ärlig._

- **Läge:** M0–M6 klara och testade. Hela kedjan finns i kod: takvolym ur notisen →
  vinnare → betalningar matchade på både leverantör och betalande köpare →
  utnyttjandegrad med täckningsgrad.
- **Batch 1 är ute:** 20 kommuner mejlade 2026-08-31, loggade i `foia_requests`.
  Huddinge har svarat delvis (`partial`) och räknas fortfarande som obesvarad.
  Dag 3 (påminnelse) förfaller 2026-09-03 — kör `tender-scan foia due`.
- **Den bindande begränsningen är täckning, inte kod.** Av 137 ramavtal är
  **1** mätbart hela vägen (109559-2026, Göteborgs Stad) — och det på en enda
  månads fakturadata av 17 förflutna, alltså 5,9 % periodtäckning. Svaren på
  batch 1 är det som kan flytta den siffran.
- **Vad som ännu inte går att påstå:** att verkligt avrop landar på en viss
  andel av uppskattat värde. Det bygger på n=1 och den punkten pekar åt fel
  håll. Säljargumentet är i stället att *fördelningen mellan vinnande
  leverantörer* inte finns publicerad någonstans alls.

### Utskicken bor utanför repot

`~/Desktop/OUTREACH/` — `batch1_pilot.csv`, `kommuner_290.csv` (290 kommuner),
`send_batch.py`, mallarna. **Ingen versionshantering, ingen backup.** Sessionen
får läsa och skriva där via `permissions.additionalDirectories`. Sanningen om
var varje ärende står ligger i `foia_requests`; kalkylarket är arbetsytan.

### Skickade mejl och kontakter

_Utlämnandebegäranden spåras i databasen och listas automatiskt längre ned.
Allt annat — säljmejl, samtal, möten — skrivs för hand här._

| Datum | Vem | Vad | Status |
| --- | --- | --- | --- |
| – | – | Inget loggat ännu | – |
### Hur projektet nås

- **Terminalen och webben delar samma session.** Remote Control är påslaget för
  det här projektet (`remoteControlAtStartup` i `.claude/settings.local.json`,
  personlig och ocommittad). En session som startas här går att styra från
  claude.ai/code och Claude-appen — samma session, inte en kopia, så
  webbläsaren ser den här databasen, den här dockern och den här filen.
- **Priset:** den här maskinen måste vara igång med en session. Sover den finns
  ingenting att fjärrstyra.
### Vad som är facit, och vad som inte kör av sig självt

- **Facit = tabellen `foia_requests`.** `foia due` läser den och ingenting annat.
  `~/Desktop/OUTREACH/batch1_pilot.csv` är en *inmatning* via `foia import`,
  aldrig en parallell sanning. Redigerar du arket utan att importera är
  databasen orörd — och det är databasen som styr.
- **Ingenting är automatiserat.** Ingen crontab, ingen systemd-timer, ingen
  schemalagd agent. `foia due` *listar* vad som förfallit när du kör den.
  `send_batch.py` skickar bara när du själv kör den med `--live`. Inga mejl
  lämnar maskinen utan att du startat det.
### NÄSTA JOBB: läs Gmail, registrera svaren på batch 1

Gmail-kopplingen är aktiv (`claude mcp list` → Connected), men verktygen
registreras vid **sessionsstart** — sessionen som skickade batch 1 tappade dem
mitt i och kunde inte läsa inkorgen. En ny session har dem.

Uppdraget, för den session som läser detta:

1. Sök i Gmail efter svar på de 20 begärandena, skickade **2026-08-31**, ämne
   *"Begäran om utlämnande av allmän handling – avtalskatalog och
   leverantörsreskontra"*. Mottagarna står i `foia_requests` (`foia list`).
2. Avgör per kommun vad svaret faktiskt är:
   - bara mottagningsbekräftelse → `tender-scan foia note <id> "..."`
     (status ska **stå kvar** som `sent`, klockan fortsätter gå)
   - bifogade handlingar → spara filen, `tender-scan foia ingest <id> <fil>`
   - avslag → `tender-scan foia ingest <id> <fil> --refused`
   - avgift begärd → `foia note` med beloppet, betala inte automatiskt
3. Hitta inte på. Registrera bara det som står i ett faktiskt mejl, med
   diarienummer och datum där det finns.

Känt sedan tidigare: användaren uppger bekräftelser från "typ alla", och
material bara från Huddinge (delvis). Det är **inte** verifierat mot inkorgen —
verifiera det, ändra inte på det.
### Om du kör i en molncontainer

Kör `bash scripts/setup.sh` först. Den väljer en Python 3.12+ (obs: `python3`
är PyPy 3.11 på ägarens maskin), installerar CLI:t och listar vad klonen
saknar. Databasen och `~/Desktop/OUTREACH/` följer **aldrig** med — de är
gitignorerade med flit. Det är väntat, inte ett fel.

Du kan alltså läsa och skriva kod och köra hela testsviten härifrån, men inte
ändra det verkliga ärendeläget. Behöver du det: skriv ett skript som kör
`tender-scan foia ...`, **committa och pusha det**, och låt den lokala
sessionen köra det. Ett skript som bara ligger i containern försvinner när
sessionen tar slut.
<!-- MANUELLT:SLUT -->

## Kod

- Gren: `main`
- Synkad med `origin/main`
- Arbetsträd: 3 ändrade filer

| Commit | Datum | Vad |
| --- | --- | --- |
| `128b1e1` | 2026-09-01 | docs(state): hand off the Gmail triage of batch 1 to the next session |
| `816268b` | 2026-09-01 | feat(m3): foia note, for what no other field captures |
| `d1ffebb` | 2026-08-31 | feat(state): warn when the running image predates the code |
| `260087a` | 2026-08-31 | chore(state): refresh |
| `269d539` | 2026-08-31 | fix(ci): put the repo root on sys.path for bare pytest |
| `181ff4b` | 2026-08-31 | chore(state): refresh after push |
| `9a6db60` | 2026-08-31 | fix(state): only rewrite STATE.md when something actually changed |
| `dbe1ea3` | 2026-08-31 | feat(m3): import a hand-kept outreach sheet, and a status for a half-answer |

## Vad som kör

| Container | Status | Image |
| --- | --- | --- |
| `tender-scan-app-1` | Up About an hour | `tender-scan-app` |
| `tender-scan-tailscale-1` | Up 4 hours | `tailscale/tailscale:latest` |

- Image `tender-scan-app` byggd: 2026-08-31 23:33:04 UTC
- ⚠️ **Imagen är 1 h äldre än senaste commit — containern kör gammal kod.** Kör `docker compose up -d --build`.
- Nås bara över tailnet: **http://tender-scan:8000**. `localhost:8000` är avsiktligt stängt (`network_mode: service:tailscale`).

## Vad databasen innehåller

| Tabell | Rader | Vad |
| --- | --- | --- |
| `notices` | 0 ⚠️ tom | notiser från TED |
| `framework_agreements` | 137 | ramavtal med takvolym |
| `award_winners` | 1771 | tilldelade leverantörer |
| `framework_buyers` | 173 | avropsberättigade köpare |
| `supplier_payments` | 149 | fakturarader från öppna reskontror |
| `foia_requests` | 20 | utlämnandebegäranden |

## Utlämnandebegäranden

| # | Myndighet | Ramavtal | Skickat | Status |
| --- | --- | --- | --- | --- |
| 20 | Grästorps kommun | `–` | 2026-08-31 | sent |
| 19 | Dorotea kommun | `–` | 2026-08-31 | sent |
| 18 | Bjurholms kommun | `–` | 2026-08-31 | sent |
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
| 7 | Huddinge kommun | `–` | 2026-08-31 | partial |
| 6 | Gävle kommun | `–` | 2026-08-31 | sent |
| 5 | Eskilstuna kommun | `–` | 2026-08-31 | sent |
| 4 | Borås stad | `–` | 2026-08-31 | sent |
| 3 | Jönköpings kommun | `–` | 2026-08-31 | sent |
| 2 | Helsingborgs stad | `–` | 2026-08-31 | sent |
| 1 | Göteborgs stad | `–` | 2026-08-31 | sent |

- Deadlines räknas av `tender-scan foia due` — den här filen upprepar dem inte.

## Var siffrorna kommer ifrån

Utnyttjandegraden bygger på fakturarader som köparen publicerat som öppna data.
En grad utan sina två täckningstal — andel köpare och andel förflutna månader —
är en undre gräns, inte en mätning. Webbvyn och rapporten visar alltid båda.
Detaljerna står i README under *Utnyttjandegrad*.
