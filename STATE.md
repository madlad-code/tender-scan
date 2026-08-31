# Läge — tender-scan

<!-- Genererad av scripts/state.py vid varje sessionsstart.
     Redigera inte de genererade avsnitten för hand; de skrivs över.
     Allt mellan MANUELLT:START och MANUELLT:SLUT behålls som det är. -->

_Genererad 2026-08-31 19:52 UTC._

## Planen och kontakterna

<!-- MANUELLT:START -->
### Var jag är

_Den här delen skrivs aldrig över av generatorn. Håll den kort och ärlig._

- **Läge:** M0–M6 klara och testade. Hela kedjan finns i kod: takvolym ur notisen →
  vinnare → betalningar matchade på både leverantör och betalande köpare →
  utnyttjandegrad med täckningsgrad.
- **Den bindande begränsningen är täckning, inte kod.** Av 137 ramavtal är
  **1** mätbart hela vägen (109559-2026, Göteborgs Stad) — och det på en enda
  månads fakturadata av 17 förflutna, alltså 5,9 % periodtäckning. Fler laddare
  eller fler utlämnandebegäranden ändrar den siffran; mer kod gör det inte.
- **Vad som ännu inte går att påstå:** att verkligt avrop landar på en viss
  andel av uppskattat värde. Det bygger på n=1 och den punkten pekar åt fel
  håll. Säljargumentet är i stället att *fördelningen mellan vinnande
  leverantörer* inte finns publicerad någonstans alls.
- **Nästa beslut:** fler öppna reskontror (kod, säkert utfall, litet) eller
  fler utlämnandebegäranden (väntetid, osäkert utfall, stort). Inte båda.

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
- **11 commits opushade** till `origin/main`
- Arbetsträd: 1 ändrad fil

| Commit | Datum | Vad |
| --- | --- | --- |
| `08e38a6` | 2026-08-31 | feat(state): STATE.md, regenerated at every session start |
| `8b6acd5` | 2026-08-31 | feat(web): dashboard, per-framework report and prospect pages |
| `5bb4996` | 2026-08-28 | chore: stop tracking the runtime log |
| `561c6df` | 2026-08-28 | docs: document the utilization modules and what their numbers mean |
| `c3702aa` | 2026-08-28 | feat(m3): FOIA case handler for call-off data requests |
| `cf6479f` | 2026-08-28 | feat(m6): prospect list of suppliers on several framework agreements |
| `929b691` | 2026-08-28 | feat(m5): utilization view and report, with coverage attached to every rate |
| `1a2df39` | 2026-08-28 | feat(m4): open supplier-ledger loaders for VGR, Göteborg and Västerås |

## Vad som kör

| Container | Status | Image |
| --- | --- | --- |
| `tender-scan-app-1` | Up 13 minutes | `tender-scan-app` |
| `tender-scan-tailscale-1` | Up 46 minutes | `tailscale/tailscale:latest` |

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
| `foia_requests` | 0 ⚠️ tom | utlämnandebegäranden |

## Utlämnandebegäranden

- Inga begäranden registrerade. Tabellen finns och har fälten för hela klockan (`sent_at`, `reminder_1_at`, `reminder_2_at`, `decision_requested_at`) — den används bara inte ännu.
- Registrera ett: `tender-scan foia new --framework <notis> --org "<myndighet>"`, och `tender-scan foia sent <id>` när du faktiskt skickat det.

## Var siffrorna kommer ifrån

Utnyttjandegraden bygger på fakturarader som köparen publicerat som öppna data.
En grad utan sina två täckningstal — andel köpare och andel förflutna månader —
är en undre gräns, inte en mätning. Webbvyn och rapporten visar alltid båda.
Detaljerna står i README under *Utnyttjandegrad*.
