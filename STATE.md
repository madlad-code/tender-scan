# Läge — tender-scan

<!-- Genererad av scripts/state.py vid varje sessionsstart.
     Redigera inte de genererade avsnitten för hand; de skrivs över.
     Allt mellan MANUELLT:START och MANUELLT:SLUT behålls som det är. -->

_Genererad 2026-08-31 20:38 UTC._

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
<!-- MANUELLT:SLUT -->

## Kod

- Gren: `main`
- **12 commits opushade** till `origin/main`
- Arbetsträd: 7 ändrade filer

| Commit | Datum | Vad |
| --- | --- | --- |
| `ec3d335` | 2026-08-31 | docs(state): record that Remote Control is how the web reaches this project |
| `08e38a6` | 2026-08-31 | feat(state): STATE.md, regenerated at every session start |
| `8b6acd5` | 2026-08-31 | feat(web): dashboard, per-framework report and prospect pages |
| `5bb4996` | 2026-08-28 | chore: stop tracking the runtime log |
| `561c6df` | 2026-08-28 | docs: document the utilization modules and what their numbers mean |
| `c3702aa` | 2026-08-28 | feat(m3): FOIA case handler for call-off data requests |
| `cf6479f` | 2026-08-28 | feat(m6): prospect list of suppliers on several framework agreements |
| `929b691` | 2026-08-28 | feat(m5): utilization view and report, with coverage attached to every rate |

## Vad som kör

| Container | Status | Image |
| --- | --- | --- |
| `tender-scan-app-1` | Up About an hour | `tender-scan-app` |
| `tender-scan-tailscale-1` | Up 2 hours | `tailscale/tailscale:latest` |

- Image `tender-scan-app` byggd: 2026-08-31 21:38:15 UTC
- Byggs **inte** om av sig själv. Efter en kodändring: `docker compose up -d --build`.
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
