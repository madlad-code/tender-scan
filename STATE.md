# Läge — tender-scan

<!-- Genererad av scripts/state.py vid varje sessionsstart.
     Redigera inte de genererade avsnitten för hand; de skrivs över.
     Allt mellan MANUELLT:START och MANUELLT:SLUT behålls som det är. -->

_Genererad 2026-09-08 23:19 UTC._

## Planen och kontakterna

<!-- MANUELLT:START -->
### Var jag är

_Den här delen skrivs aldrig över av generatorn. Håll den kort och ärlig._

- **Läge:** M0–M8 klara. Sedan 3 september har korpusen vuxit från två kommuner
  till **fyra som går att räkna på** — Borås, Falun, Huddinge, Hässleholm.
  Falun och Kalmar levererade 2026-09-08.
- **Analysen ligger utanför CLI:t.** Fyrkommunsbasen bor i
  `data/analysis/tender.duckdb` (418 MB) med skripten `etl.py` → `build_db.py` →
  `a1`–`a8`, och resultaten som 29 csv-filer i `data/analysis/results/`.
  `data/tender_scan.db` känner fortfarande bara till 204 799 betalningsrader.
  **De två är inte synkade, och det är den största tekniska skulden just nu.**
- **Säljunderlaget är klart.** `data/outreach/ringlista_2026-09.md` — 27 bolag med
  verifierad telefon och e-post, ringordning, manus per segment. Underlaget är
  bolagens egna fakturarader i de fyra kommunerna.

### Vad som faktiskt går att påstå, med siffror

Fyra kommuner, **3 186 210 fakturarader, 12 737 leverantörer, 27,6 mdr kr**.
Efter att transfereringar, hyra, monopol och individuella placeringar tagits bort:
**11,1 mdr upphandlingsbart** inom varje kommuns täta fönster.

| Kommun | Fönster | Upphandlingsbart | Betalt utan avtal | Avtalsleverantörer med noll kr |
| --- | --- | --- | --- | --- |
| Borås | 2023-01–2025-12 (36 mån) | 3 407 mkr | 47,6 % | 41,5 % [37,7–45,3] |
| Falun | 2024-01–2026-09 (21 mån) | 3 099 mkr | 43,6 % | 68,0 % [64,3–71,4] |
| Huddinge | 2024-01–2025-12 (24 mån) | 2 465 mkr | 23,3 % | 44,4 % [41,0–47,8] |
| Hässleholm | 2023-01–2026-08 (44 mån) | 2 125 mkr | 38,4 % | 40,2 % [35,5–45,1] |

**Detta ersätter de tidigare Huddingesiffrorna.** 32,2 % utan avtal och 31,8 %
vilande avtal räknades över 44 månader. Huddinges 2023 och 2026 är fragment
(790 respektive 1 271 rader/månad mot 19 526 för 2024–25), så det täta fönstret
är 24 månader och siffrorna blev 23,3 % och 44,4 %.

**Faluns 68 % är den svagaste siffran i tabellen.** Faluns katalog innehåller
inte ett enda organisationsnummer på 1 174 rader, så kopplingen görs på namn —
och 27,2 % av de "vilande" leverantörerna har en trolig namnträff i reskontran
ändå. För Borås, Huddinge och Hässleholm är motsvarande fel 5,6–7,8 %.

**IT- och konsultskivan, som är den vi säljer mot:** 742 mkr i Huddinge (30 % av
det upphandlingsbara), 790 mkr i Borås, 632 mkr i Hässleholm, 308 mkr i Falun.
Av konsulttimmarna går **73–99 % till andra än de stora integratörerna** — det är
den marknad kunderna faktiskt konkurrerar på.

**Vad som fortfarande inte går att påstå:** takvolym mot verkligt avrop. Bara
Jönköping har lämnat avtalsvärden (447 tak), och Jönköping har inte lämnat
reskontra. Antalet kommuner där tak och utfall kan jämföras är fortfarande **noll**.
Rangordning saknas överallt utom hos Göteborg (1 486 rader) och Grästorp (50),
så varje dormanssiffra ovan är en **övre gräns**, inte en mätning.

Analysen av Huddinge ensam ligger som artefakt: *Avtalsglappet i Huddinge*,
https://claude.ai/code/artifact/621f7123-2b0d-4f90-ba85-d74a11f7d132 — dess
siffror är nu ersatta av tabellen ovan.

### KRÄVER SVAR AV DIG

1. **Betalkanalen finns inte.** Egenanställning eller eget bolag måste vara
   uppsatt innan första samtalet — och Katrineholm (#15) väntar dessutom på en
   fakturaadress som inte finns förrän du valt. Blockerar både sälj och data.
2. **Karlstad (#8)** vill ha principbesked om avgift. Svara med ett tak,
   förslagsvis 500 kr, annars räknar de aldrig sidorna.
3. **Borås 2026-fil** utlovades till 9 september. Det är idag.
4. **Huddinges följebrev är fortfarande inte läst.** Filerna identifierades på
   innehåll. Villkor eller avgift i det mejlet är okänt.
5. **Tio kommuner är tysta** och ligger på dag 8. `tender-scan foia due`.

### Nästa steg

Sälj före kod. Enda verkliga blockeraren i produkten är att
**exempelrapporten inte finns**. Säljplanen och datastrategin ligger lokalt,
utanför repot.

Teknisk skuld i prioritetsordning:

1. Fold fyrkommunsbasen in i `data/tender_scan.db` så CLI:t och webbvyn ser samma
   verklighet som analysen.
2. `tender-scan kundrapport --orgnr` — rapport nummer två får inte kräva ny SQL.
3. `edge benchmark` har äntligen underlag (fyra kommuner med kontobenämning).
   Kör den.
4. Göteborgs reskontra behöver ingen begäran — `tender-scan payments load goteborg`.
   Obs: M4-raderna är filtrerade till TED-vinnare och duger inte som nämnare;
   en full inläsning måste gå in som `source='foia'`.

### Allt bor i data/

`data/` — `tender_scan.db`, `analysis/` (DuckDB-basen och skripten), `raw/`
(alla inkomna handlingar, 532 MB), `workbench/` (den äldre analysen från 4 sep),
`outreach/` (ringlistan, säljlistan, mallarna, `send_batch.py`) och `backups/`.

**`data/` är gitignorerat två gånger om** — dels av rot-`.gitignore`, dels av
`data/.gitignore` som spärrar allt. Säljlistan och ringlistan kan alltså inte
committas av misstag, och får inte heller läggas någon annanstans.
**Ingen backup utanför maskinen.** Materialet innehåller personnummer
(enskilda firmor), tjänstemäns namn och myndighetsmaterial.

### Skickade mejl och kontakter

_Utlämnandebegäranden spåras i databasen och listas automatiskt längre ned.
Allt annat — säljmejl, samtal, möten — skrivs för hand här._

| Datum | Vem | Vad | Status |
| --- | --- | --- | --- |
| – | – | Inget säljsamtal loggat ännu | – |

### Vad som är facit, och vad som inte kör av sig självt

- **Facit = tabellen `foia_requests`.** `foia due` läser den och ingenting annat.
  Den var 2026-09-09 fyra leveranser efter verkligheten; Falun, Kalmar,
  Hässleholm och Gävle är nu inlagda som `partial`.
- **Kalmar lämnade ett delvis avslag** (KS 2026/0583, 2026-09-07): rader som rör
  socialtjänst är maskerade enligt 26 kap. 1 § OSL. Överklagbart till
  Kammarrätten i Jönköping till omkring 2026-09-29 — men de maskerade raderna är
  individplaceringar som ändå räknas bort, så överklaga inte.
- **Kalmars reskontra är inte fakturarader** utan leverantörssummor per år
  (2 687 rader/år, inget konto). Kalmar är alltså inte en femte mätbar kommun.
- **Det finns EN produktionsdatabas**, `data/tender_scan.db`, med åtta tabeller.
  `tender-scan db status` säger vad var och en är. DuckDB-basen i `data/analysis/`
  är en analysartefakt, inte en andra sanning — men den är just nu större.
- **Ingenting är automatiserat.** Ingen crontab, ingen timer, ingen schemalagd
  agent. `foia due` *listar* vad som förfallit när du kör den. `send_batch.py`
  skickar bara med `--live`.

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
- Arbetsträd: 4 ändrade filer

| Commit | Datum | Vad |
| --- | --- | --- |
| `2690e69` | 2026-09-03 | style: run ruff format, fix CI |
| `f6f38e6` | 2026-09-03 | docs(state): link the Huddinge analysis and its strongest objection |
| `88dcad9` | 2026-09-03 | fix(m8): size an expiring contract from its own months, not the supplier's history |
| `e2b3689` | 2026-09-03 | chore(state): refresh after M8 |
| `d8fce29` | 2026-09-03 | feat(m8): lay the catalogue over the ledger and measure where they disagree |
| `96ae990` | 2026-09-02 | feat(m7): read what the municipalities actually sent back |
| `3da8faf` | 2026-09-01 | feat(m3): foia ingest --partial, so half a delivery does not retire a request |
| `3cd8b89` | 2026-09-01 | feat(setup): bootstrap a fresh clone and say what it lacks |

## Vad som kör

| Container | Status | Image |
| --- | --- | --- |
| `tender-scan-app-1` | Up 37 minutes | `tender-scan-app` |
| `tender-scan-tailscale-1` | Up 37 minutes | `tailscale/tailscale:latest` |

- Image `tender-scan-app` byggd: 2026-09-03 08:53:00 UTC
- ⚠️ **Imagen är 29 min äldre än senaste commit — containern kör gammal kod.** Kör `docker compose up -d --build`.
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
| 13 | Hässleholms kommun | `–` | 2026-08-31 | partial |
| 12 | Kalmar kommun | `–` | 2026-08-31 | partial |
| 11 | Falu kommun | `–` | 2026-08-31 | partial |
| 10 | Haninge kommun | `–` | 2026-08-31 | sent |
| 9 | Halmstads kommun | `–` | 2026-08-31 | sent |
| 8 | Karlstads kommun | `–` | 2026-08-31 | sent |
| 7 | Huddinge kommun | `–` | 2026-08-31 | received |
| 6 | Gävle kommun | `–` | 2026-08-31 | partial |
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
