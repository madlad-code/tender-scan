# Läge — tender-scan

<!-- Genererad av scripts/state.py vid varje sessionsstart.
     Redigera inte de genererade avsnitten för hand; de skrivs över.
     Allt mellan MANUELLT:START och MANUELLT:SLUT behålls som det är. -->

_Genererad 2026-09-12 12:22 UTC._

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
6. **Halmstad** vägrar maskinläsbart format — kräver besked: på plats eller
   papperskopior mot avgift (leverantörsreskontra 1 år ≈ 60 000 kr).
7. **Linköping**: avgift ≈ 70 000 kr (11 500 sidor), väntar fakturauppgifter.
8. **Luleå**: väntar avgiftsbesked (reskontra ≈ 10 000 sidor, avtalskatalog
   ≈ 2 806 sidor, 50 kr grundavgift + 5 kr/sida).
9. **Nacka** ber om en preciserad begäran innan de söker vidare.

### Gmail-triage av utskick 2 (2026-09-10, 16 nya kommuner + 4 påminnelser)

Kört i molnsession 2026-09-12. Facit:

- **Nedladdat till `data/raw/`:** Skellefteå (avtalskatalog, 162 KB), Malmö
  (avtalsdatabas, 224 KB), Luleå (ett provutdrag på en sida, inte leveransen).
- **Kan inte laddas ned härifrån — kräver lokal session:** Dorotea (~19 MB,
  2 filer), Växjö (~70 MB, 4 mejl: reskontra 2023–2026 + avtalsexport), Lund
  (~86 MB, reskontra 202501–202606). Gmail MCP-verktyget här saknar en
  bilage-hämtare; RAW-MIME-hämtning fungerar bara under ett par hundra KB och
  kraschar anslutningen över det (bekräftat vid 12,5 och 19 MB).
- **Malmös reskontra 2023–2026** delades via SharePoint/OneDrive, kräver
  Oscars egen Microsoft-inloggning — otillgängligt härifrån oavsett storlek.
- **Stockholm (handlingar.se)** har svarat, men domänen är blockerad av
  nätverksfiltret i den här miljön. Måste läsas och hämtas lokalt.
- Nya krav-på-svar ovan (6–9) kom ur samma genomgång.

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

- Gren: `claude/wizardly-cori-5b2ugv`
- Synkad med `origin/claude/wizardly-cori-5b2ugv`
- Arbetsträd: rent

| Commit | Datum | Vad |
| --- | --- | --- |
| `78f3988` | 2026-09-12 | docs(state): hand off the Gmail triage of batch 2 |
| `2690e69` | 2026-09-03 | style: run ruff format, fix CI |
| `f6f38e6` | 2026-09-03 | docs(state): link the Huddinge analysis and its strongest objection |
| `88dcad9` | 2026-09-03 | fix(m8): size an expiring contract from its own months, not the supplier's history |
| `e2b3689` | 2026-09-03 | chore(state): refresh after M8 |
| `d8fce29` | 2026-09-03 | feat(m8): lay the catalogue over the ledger and measure where they disagree |
| `96ae990` | 2026-09-02 | feat(m7): read what the municipalities actually sent back |
| `3da8faf` | 2026-09-01 | feat(m3): foia ingest --partial, so half a delivery does not retire a request |

## Vad som kör

- Inga tender-scan-containrar igång (eller ingen docker-daemon nåbar).

## Vad databasen innehåller

- Ingen databas på `data/tender_scan.db`. Kör `tender-scan scan` först.

## Utlämnandebegäranden

- Ingen databas ännu.

## Var siffrorna kommer ifrån

Utnyttjandegraden bygger på fakturarader som köparen publicerat som öppna data.
En grad utan sina två täckningstal — andel köpare och andel förflutna månader —
är en undre gräns, inte en mätning. Webbvyn och rapporten visar alltid båda.
Detaljerna står i README under *Utnyttjandegrad*.
