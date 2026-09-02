# Läge — tender-scan

<!-- Genererad av scripts/state.py vid varje sessionsstart.
     Redigera inte de genererade avsnitten för hand; de skrivs över.
     Allt mellan MANUELLT:START och MANUELLT:SLUT behålls som det är. -->

_Genererad 2026-09-02 10:34 UTC._

## Planen och kontakterna

<!-- MANUELLT:START -->
### Var jag är

_Den här delen skrivs aldrig över av generatorn. Håll den kort och ärlig._

- **Läge:** M0–M7 klara och testade. M7 är nytt: kommunernas egna avtalskataloger
  och leverantörsreskontror, inlästa ur det batch 1 faktiskt skickade tillbaka.
- **Batch 1 är triagerad mot Gmail (2026-09-02).** 6 av 20 har skickat handlingar,
  4 kräver avgift, 2 är helt tysta. Allt ligger i `foia_requests` med noteringar.
- **Täckningen har flyttat sig.** Databasen innehåller nu 9 790 avtalsrader från
  fem kommuner och 11,1 mdr kr i reskontra (Borås 2023–2025, Bjurholm 2024-10–2026-08).
  Se `tender-scan kommun list` och `http://tender-scan:8000/kommuner`.
- **Det som faktiskt går att mäta nu:** avtalstrohet 25,3 % i Bjurholm, och att
  50 % av leverantörerna med löpande avtal *utanför vård/omsorg* inte fick en krona
  på 22 månader. Vård/omsorg ligger på 94 % men är ramavtal för enskilda
  placeringar, där noll avrop är normalt — den siffran ska inte säljas som ett fynd.
- **Vad som fortfarande inte går att påstå:** takvolym mot verkligt avrop. Endast
  Jönköping publicerar avtalsvärden (480 avtal, 5,13 mdr) och Jönköping skickade
  ingen reskontra. Antalet kommuner där tak och utfall kan jämföras är noll.
- **Analysen och säljbedömningen** ligger som artefakt: *Avtal utan avrop*,
  https://claude.ai/code/artifact/5918f7bc-a528-4f58-ad7c-f3cff31bd97f

### KRÄVER SVAR AV DIG, i dag

1. **Katrineholm (#15)** vill ha fakturaadress innan de gör något. 10–16 filer.
2. **Karlstad (#8)** vill ha principbesked om avgift (100 kr/50 sidor + 2 kr/sida)
   innan de räknar sidor. Sätt ett tak i svaret.
3. **Hässleholm (#13)**: 161 kr accepterat 2026-08-31, 19 filer. Jaga fakturan.
4. **Aneby (#17) och Dorotea (#19)**: helt tysta. Dag 3-påminnelse förfaller
   2026-09-03 — kör `tender-scan foia due`.

### Nästa datajobb, i prioritetsordning

1. **Borås avtalskatalog** från Koncerninköp. Reskontran (10,75 mdr, 3 år) finns
   redan; katalogen gör den mätbar och ger par nummer två. 2026-filen utlovad 9 sep.
2. **Huddinges reskontra** från Ekonomiavdelningen. Katalogen (2 365 rader) är inne.
3. **Göteborgs reskontra** behöver ingen begäran — staden hänvisade till sin öppna
   data och repot har redan laddaren: `tender-scan payments load goteborg`.
   Obs: M4-raderna är filtrerade till TED-vinnare och används därför aldrig som
   nämnare i M7; en full inläsning behöver gå in som `source='foia'`.

### Utskicken bor utanför repot

`~/Desktop/OUTREACH/` — `batch1_pilot.csv`, `kommuner_290.csv` (290 kommuner),
`send_batch.py`, mallarna, och `ATTACHMENTS/` med de nio inkomna filerna (72 MB).
**Ingen versionshantering, ingen backup.** Samma filer finns i `data/ATTACHMENTS/`
(gitignorerat) och är inlästa därifrån. Sanningen om var varje ärende står ligger i
`foia_requests`; kalkylarket är arbetsytan.

### Skickade mejl och kontakter

_Utlämnandebegäranden spåras i databasen och listas automatiskt längre ned.
Allt annat — säljmejl, samtal, möten — skrivs för hand här._

| Datum | Vem | Vad | Status |
| --- | --- | --- | --- |
| – | – | Inget säljsamtal loggat ännu | – |

### Hur projektet nås

- **Terminalen och webben delar samma session.** Remote Control är påslaget för
  det här projektet (`remoteControlAtStartup` i `.claude/settings.local.json`,
  personlig och ocommittad). En session som startas här går att styra från
  claude.ai/code och Claude-appen — samma session, inte en kopia.
- **Priset:** den här maskinen måste vara igång med en session. Sover den finns
  ingenting att fjärrstyra.

### Vad som är facit, och vad som inte kör av sig självt

- **Facit = tabellen `foia_requests`.** `foia due` läser den och ingenting annat.
  `~/Desktop/OUTREACH/batch1_pilot.csv` är en *inmatning* via `foia import`,
  aldrig en parallell sanning.
- **Ingenting är automatiserat.** Ingen crontab, ingen systemd-timer, ingen
  schemalagd agent. `foia due` *listar* vad som förfallit när du kör den.
  `send_batch.py` skickar bara när du själv kör den med `--live`.

### Om du kör i en molncontainer

Kör `bash scripts/setup.sh` först. Den väljer en Python 3.12+ (obs: `python3`
är PyPy 3.11 på ägarens maskin), installerar CLI:t och listar vad klonen
saknar. Databasen och `data/ATTACHMENTS/` följer **aldrig** med — de är
gitignorerade med flit. Det är väntat, inte ett fel.

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
| `3da8faf` | 2026-09-01 | feat(m3): foia ingest --partial, so half a delivery does not retire a request |
| `3cd8b89` | 2026-09-01 | feat(setup): bootstrap a fresh clone and say what it lacks |
| `128b1e1` | 2026-09-01 | docs(state): hand off the Gmail triage of batch 1 to the next session |
| `816268b` | 2026-09-01 | feat(m3): foia note, for what no other field captures |
| `d1ffebb` | 2026-08-31 | feat(state): warn when the running image predates the code |
| `260087a` | 2026-08-31 | chore(state): refresh |
| `269d539` | 2026-08-31 | fix(ci): put the repo root on sys.path for bare pytest |
| `181ff4b` | 2026-08-31 | chore(state): refresh after push |

## Vad som kör

| Container | Status | Image |
| --- | --- | --- |
| `tender-scan-app-1` | Up 5 hours | `tender-scan-app` |
| `tender-scan-tailscale-1` | Up 5 hours | `tailscale/tailscale:latest` |

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
