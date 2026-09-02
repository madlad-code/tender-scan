# Läge — tender-scan

<!-- Genererad av scripts/state.py vid varje sessionsstart.
     Redigera inte de genererade avsnitten för hand; de skrivs över.
     Allt mellan MANUELLT:START och MANUELLT:SLUT behålls som det är. -->

_Genererad 2026-09-02 10:17 UTC._

## Planen och kontakterna

<!-- MANUELLT:START -->
### Var jag är

_Den här delen skrivs aldrig över av generatorn. Håll den kort och ärlig._

- **Läge:** M0–M6 klara och testade. Hela kedjan finns i kod: takvolym ur notisen →
  vinnare → betalningar matchade på både leverantör och betalande köpare →
  utnyttjandegrad med täckningsgrad.
- **Batch 1 är ute och inkorgen är läst tre gånger.** 20 kommuner mejlade
  2026-08-31. Senast genomsökt 2026-09-02 09:12 UTC: **17 av 20 har svarat,
  3 är helt tysta** (Eskilstuna, Aneby, Dorotea).
  **6 kommuner har skickat handlingar — 9 filer, drygt 100 MB.** En kommun,
  Bjurholm, har besvarat båda punkterna; fem har besvarat en av två.
  Dag 3 (påminnelse) förfaller 2026-09-03 — kör `tender-scan foia due`.
- **Filerna ligger kvar i Gmail.** Sessionerna som läst inkorgen har inget
  verktyg för att hämta bilagor, och Borås filer på 27–29 MB styck ska ändå
  inte gå genom en modellkontext. `scripts/hamta_bilagor.py --live` hämtar dem
  över IMAP med samma app-lösenord som `send_batch.py` redan använder, till
  `data/foia-svar/` som är gitignorerad.
- **De 5,9 % är troligen självförvållade.** `GoteborgLoader.covers` säger
  "monthly CSV, 2016 onwards" och `payments load goteborg` hämtar varje daterad
  distribution katalogen listar. Att bara en månad av 17 är inläst ser ut som
  ett inläsningsglapp, inte ett tak i verkligheten. **Kör
  `tender-scan payments load goteborg` innan något annat** — noll nya filer,
  noll ny kod. Se `docs/analys-berakningsunderlag.md`.
- **Ingen av de nio FOIA-filerna går att läsa in.** `LOADERS` har bara `vgr`,
  `goteborg` och `vasteras`, alla för öppna data-kataloger. Schemat tillåter
  `source='foia'` men ingen kod producerar en sådan rad. Borås tre år ligger
  och väntar på en adapter som ingen skrivit.
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
### Vad batch 1 faktiskt svarade

Läst i Gmail 2026-08-31 22:50, 2026-09-01 09:19 och 2026-09-02 09:12 UTC. Alla
20 utskicken finns i `Skickat`; ingen begäran studsade.

**17 av 20 har svarat. 3 är tysta:** Eskilstuna, Aneby, Dorotea.

#### Levererat handlingar — 6 kommuner, 9 filer

| Kommun | Fil | Punkt | Läge |
| --- | --- | --- | --- |
| Bjurholm | `Avtalsstatistik_09011048.xls` + `Leverantörsreskontraöversikt.xlsx` | 1 **och** 2 | **Enda fullständiga svaret.** Inget följebrev — kontrollera vilken period reskontran täcker innan den räknas som klar |
| Borås | `Öppna data 2023/2024/2025.xlsx` (27–29 MB st) | 2 | 2026-01-01–08-31 kommer 2026-09-09. Punkt 1 ligger kvar hos koncerninköp |
| Göteborg | `Avtal 20230101-20260901.xlsx` | 1 | Punkt 2 hänvisad till stadens öppna data, årsvis |
| Huddinge | `Avtalskatalogen.xlsx` | 1 | Ekonomienheten svarar separat om reskontran |
| Jönköping | `SH ContractExport 26091.pdf` | 1 | PDF, inte maskinläsbart. Ny avtalsdatabas införs; ekonomiavdelningen tar punkt 2 |
| Grästorp | `Avtalsdatabasen 20260616.xlsx` | 1 | Nulägesbild. Kommunen skriver att inga handlingar motsvarar punkt 1, och att databasen saknar entreprenad, direktupphandling, delar av Adda och Sinfra |

#### Vill ha betalt — 5 kommuner, plus 1 villkorat

| Kommun | Belopp | Läge |
| --- | --- | --- |
| Hässleholm | **161 kr** för ca 19 filer | Accepterat 08-31 22:16, väntar på betalningsinstruktion |
| Katrineholm | Enligt avgiftsförordningen, 10–16 stora filer | Taxan skickades som **bild**, beloppet går inte att läsa ur texten. Vill ha fakturaadress |
| Härnösand | Utlovad, ej angiven | "Vi återkommer om en exakt summa" |
| Haninge | Utlovad, ej angiven | Via Upphandling Södertörn; avgiftsinfo som PDF, RE-700008093 |
| Karlstad | **100 kr** för 50 sidor, sedan 2 kr/sida | Bedömer >49 sidor; vill ha ett principbesked innan de räknar exakt. Swish eller faktura |
| Falun | *Kan* tillkomma | Villkorat av mängd; sekretessbedömning pågår |

#### Bekräftat, inget mer

Helsingborg, Halmstad, Enköping, Gävle, Kalmar. Kalmar meddelade 2026-09-02 att
en sedvanlig sekretessprövning pågår. Gävle har uttryckligen
sagt ifrån: uttaget är "ett gigantiskt jobb", delårsbokslutet har prio 1, och de
återkommer efter det.

#### Vad som är värt att notera

**Ingen har avslagit.** Grästorp kommer närmast, men skickar ändå det som finns
och förklarar vad databasen saknar — det är en täckningsbegränsning, inte ett
avslag, och den sortens ärlighet är mer användbar än ett tomt nej.

**Öppna data dyker upp två gånger.** Göteborg hänvisar till sin sida, Borås
skickar sina filer och kallar dem "öppna data". Projektet mäter i dag Göteborg
på en månad av 17 — 5,9 % periodtäckning, siffran som binder hela analysen.
Två av tjugo kommuner säger alltså att materialet redan är publicerat. Det är
fortfarande inte verifierat.

**Avgifterna är små men trögheten är verklig.** 161 kr är inget hinder; att fyra
kommuner vill fakturera och två av dem ännu inte satt ett belopp betyder att
batchen inte blir klar av sig själv.

### NÄSTA JOBB: hämta filerna, skriv in avläsningen, påminn dag 3

På maskinen som har databasen, i den ordningen:

1. **Hämta de nio filerna.** `python3 scripts/hamta_bilagor.py` visar vad som
   skulle hämtas; `--live` hämtar till `data/foia-svar/`. Kräver `GMAIL_USER`
   och `GMAIL_APP_PASSWORD` — samma app-lösenord som `send_batch.py`.
2. **Registrera svaren.** `python3 scripts/registrera_batch1_svar.py --live`.
   24 anteckningar på 17 kommuner, ingen statusändring. Säker att köra om.
3. **Registrera filerna.** Bjurholm kan stängas helt:
   `foia ingest <id> <fil>`. Övriga fem behöver **`--partial`**, annars slutar
   `foia due` jaga den halva som fattas.
4. **Kör `tender-scan payments load goteborg`** — hela historiken, inte en
   månad. Detta avgör ensamt om 5,9 % var ett verkligt tak eller ett glapp.
   Kör sedan de två SQL-frågorna i `docs/analys-berakningsunderlag.md` §7:
   den första visar vilken kommuns reskontra som låser upp flest ramavtal, och
   den ska styra batch 2 i stället för att kommunerna väljs på måfå.
5. **Dag 3, 2026-09-03.** `docs/paminnelse-mall.md` har mallarna, men
   **grupperna måste räknas om** — den skrevs när 5 var tysta och 4 arbetade;
   nu är 3 tysta och 6 har levererat. Läs inkorgen igen precis innan utskick.
6. **Pengaspåren.** Hässleholm (161 kr, väntar på instruktion), Katrineholm
   (vill ha fakturaadress, belopp i en bild), Härnösand och Haninge (belopp
   utlovat). Alla fyra ska ryckas i via sina egna trådar.

Hitta inte på. Registrera bara det som står i ett faktiskt mejl, med
diarienummer och datum där det finns.
<!-- MANUELLT:SLUT -->

## Kod

- Gren: `claude/state-md-next-job-868omh`
- Synkad med `origin/claude/state-md-next-job-868omh`
- Arbetsträd: rent

| Commit | Datum | Vad |
| --- | --- | --- |
| `2f328da` | 2026-09-02 | feat(m3): fetch the answers' attachments, and the day the files arrived |
| `753e67d` | 2026-09-01 | feat(m3): ingest --partial, and the four answers that arrived overnight |
| `cc08409` | 2026-08-31 | feat(m3): the batch 1 inbox, read and written down |
| `128b1e1` | 2026-09-01 | docs(state): hand off the Gmail triage of batch 1 to the next session |
| `816268b` | 2026-09-01 | feat(m3): foia note, for what no other field captures |
| `d1ffebb` | 2026-08-31 | feat(state): warn when the running image predates the code |
| `260087a` | 2026-08-31 | chore(state): refresh |
| `269d539` | 2026-08-31 | fix(ci): put the repo root on sys.path for bare pytest |

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
