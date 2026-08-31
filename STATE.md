# Läge — tender-scan

<!-- Genererad av scripts/state.py vid varje sessionsstart.
     Redigera inte de genererade avsnitten för hand; de skrivs över.
     Allt mellan MANUELLT:START och MANUELLT:SLUT behålls som det är. -->

_Genererad 2026-08-31 22:50 UTC._

## Planen och kontakterna

<!-- MANUELLT:START -->
### Var jag är

_Den här delen skrivs aldrig över av generatorn. Håll den kort och ärlig._

- **Läge:** M0–M6 klara och testade. Hela kedjan finns i kod: takvolym ur notisen →
  vinnare → betalningar matchade på både leverantör och betalande köpare →
  utnyttjandegrad med täckningsgrad.
- **Batch 1 är ute och inkorgen är läst.** 20 kommuner mejlade 2026-08-31,
  loggade i `foia_requests`. Gmail genomsökt 2026-08-31 22:50 UTC: **12 av 20
  har svarat, 8 är helt tysta** — inte ens ett autosvar. Huddinge har skickat
  avtalskatalogen men inte reskontran, och står rätt som `partial`.
  Dag 3 (påminnelse) förfaller 2026-09-03 — kör `tender-scan foia due`.
- **Avläsningen är ännu inte i databasen.** Sessionen som läste Gmail körde i en
  molnbehållare utan `data/tender_scan.db`. Fynden ligger i
  `scripts/registrera_batch1_svar.py` och skrivs in med `--live` på maskinen som
  har databasen. Tills dess är `foia_requests` orört.
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
### Vad batch 1 faktiskt svarade

Läst i Gmail 2026-08-31 22:50 UTC. Alla 20 utskicken finns i `Skickat`
(09:15–09:18 UTC), så ingen begäran fastnade i utkorgen och ingen studsade.

| Kommun | Svar | Diarienummer |
| --- | --- | --- |
| Huddinge | **Avtalskatalogen.xlsx bifogad** 12:19; ekonomienheten svarar separat om reskontran | 2026SC66301 |
| Hässleholm | **Avgift 161 kr** för ca 19 filer; Oscar accepterade 22:16 och bad om betalningsinstruktion | – |
| Falun | Bekräftat; sekretessbedömning av leverantörsfakturor kan dra ut på tiden, kostnad kan tillkomma | FK-2608-11504 |
| Haninge | Bekräftat; avgift kan tas ut, alternativt läsning på plats gratis | 2026HAN19344 |
| Enköping | Bekräftat, vidare till kommunledningsförvaltningen | KC202639332 |
| Helsingborg | Bekräftat, vidare till berörd förvaltning | KC-#254868 |
| Gävle | Bekräftat | KC2026136671 |
| Borås | Bekräftat, vidare till koncerninköp och leverantörsreskontra | – |
| Kalmar | Bekräftat, vidarebefordrat för handläggning | – |
| Jönköping | Automatisk bekräftelse | – |
| Halmstad | Automatiskt svar från diariet | – |
| Grästorp | Autosvar | – |

**Helt tysta:** Göteborgs stad, Eskilstuna, Karlstad, Katrineholm, Härnösand,
Aneby, Bjurholm, Dorotea.

Två rättelser mot vad som antogs innan inkorgen lästes. Bekräftelser kom
**inte** från "typ alla" utan från 12 av 20 — de åtta tysta har inte hört av sig
över huvud taget, vilket är den grupp dag 3-påminnelsen är till för. Och
Huddinges delleverans är verifierad: `Avtalskatalogen.xlsx` från Katarina
Svärdgren, inköpssamordnare, med reskontran uttryckligen utlovad separat.

Ingen har avslagit. Ingen har levererat allt. Därför ändras ingen status — bara
`notes` — och klockan fortsätter gå på samtliga 20.

### NÄSTA JOBB: skriv in avläsningen och skicka dag 3-påminnelserna

På maskinen som har databasen, i den ordningen:

1. **Registrera svaren.** `python3 scripts/registrera_batch1_svar.py` visar vad
   som skulle skrivas; `--live` skriver. Tolv `foia note`, ingen statusändring.
   Säker att köra om — varje anteckning bär sin egen markör.
2. **Spara Huddinges bilaga.** `Avtalskatalogen.xlsx` ligger i mejlet
   "Avtalskatalogen" från Katarina.Svardgren@huddinge.se (2026-08-31 12:19 UTC).
   Lägg den där svarsfiler ska bo. **Kör inte `foia ingest` på den än** — den
   sätter status till `received` och stänger klockan, och reskontran som är
   halva begäran återstår. `ingest` när ekonomienheten hör av sig, inte förr.
3. **Dag 3, 2026-09-03:** `tender-scan foia due` listar alla 20. De åtta tysta
   är de som behöver en riktig påminnelse; de tolv som bekräftat behöver en
   annan formulering, eftersom bekräftelsen är kvittot en eskalering vilar på.
4. **Hässleholm väntar på betalningsinstruktion.** 161 kr, accepterat men inte
   betalt. Kommer ingen faktura eller inget bankgiro inom rimlig tid är det den
   tråden som ska ryckas i, inte en allmän påminnelse.

Hitta inte på. Registrera bara det som står i ett faktiskt mejl, med
diarienummer och datum där det finns.

<!-- MANUELLT:SLUT -->

## Kod

- Gren: `claude/state-md-next-job-868omh`
- Ingen uppström satt — inget är pushat någonstans
- Arbetsträd: rent

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
