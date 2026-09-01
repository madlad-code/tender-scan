# Läge — tender-scan

<!-- Genererad av scripts/state.py vid varje sessionsstart.
     Redigera inte de genererade avsnitten för hand; de skrivs över.
     Allt mellan MANUELLT:START och MANUELLT:SLUT behålls som det är. -->

_Genererad 2026-08-31 23:38 UTC._

## Planen och kontakterna

<!-- MANUELLT:START -->
### Var jag är

_Den här delen skrivs aldrig över av generatorn. Håll den kort och ärlig._

- **Läge:** M0–M6 klara och testade. Hela kedjan finns i kod: takvolym ur notisen →
  vinnare → betalningar matchade på både leverantör och betalande köpare →
  utnyttjandegrad med täckningsgrad.
- **Batch 1 är ute och inkorgen är läst två gånger.** 20 kommuner mejlade
  2026-08-31. Gmail genomsökt 2026-08-31 22:50 och 2026-09-01 09:19 UTC:
  **15 av 20 har svarat, 5 är helt tysta.** Tre av gårdagens tysta — Göteborg,
  Härnösand, Karlstad — svarade under natten, vilket är argumentet för att läsa
  inkorgen strax före en påminnelse och inte dagen innan.
  **Två kommuner har skickat handlingar:** Huddinge avtalskatalogen, Göteborg
  sin avtalssammanställning. Båda gäller punkt 1 av två.
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

Läst i Gmail 2026-08-31 22:50 UTC och igen 2026-09-01 09:19 UTC. Alla 20
utskicken finns i `Skickat` (09:15–09:18 UTC 2026-08-31), så ingen begäran
fastnade i utkorgen och ingen studsade.

| Kommun | Svar | Diarienummer |
| --- | --- | --- |
| Göteborg | **`Avtal 20230101-20260901.xlsx` bifogad** 09-01; punkt 2 hänvisad till stadens öppna data, årsvis | – |
| Huddinge | **`Avtalskatalogen.xlsx` bifogad** 08-31; ekonomienheten svarar separat om reskontran | 2026SC66301 |
| Hässleholm | **Avgift 161 kr** för ca 19 filer; Oscar accepterade 08-31 22:16 och bad om betalningsinstruktion | – |
| Härnösand | Bekräftat 09-01; **kostnad utlovad, exakt summa meddelas senare** | – |
| Falun | Bekräftat; sekretessbedömning av leverantörsfakturor kan dra ut på tiden, kostnad kan tillkomma | FK-2608-11504 |
| Haninge | Bekräftat; avgift kan tas ut, alternativt läsning på plats gratis | 2026HAN19344 |
| Karlstad | Automatisk bekräftelse 09-01 | K202699134 |
| Enköping | Bekräftat, vidare till kommunledningsförvaltningen | KC202639332 |
| Helsingborg | Bekräftat, vidare till berörd förvaltning | KC-#254868 |
| Gävle | Bekräftat två gånger, med **två skilda ärendenummer** för samma begäran | KC2026136671, KC2026137233 |
| Borås | Bekräftat, vidare till koncerninköp och leverantörsreskontra | – |
| Kalmar | Bekräftat, vidarebefordrat för handläggning | – |
| Jönköping | Automatisk bekräftelse | – |
| Halmstad | Automatiskt svar från diariet | – |
| Grästorp | Autosvar | – |

**Helt tysta (5):** Eskilstuna, Katrineholm, Aneby, Bjurholm, Dorotea.

Ingen har avslagit. Ingen har levererat allt. De två som skickat filer har
skickat punkt 1 och lämnat punkt 2 öppen, vilket är exakt vad `partial` finns
för — och `foia ingest` har nu ett `--partial` som registrerar filen utan att
stänga klockan.

**Göteborg är den intressanta.** Diariet skriver att hela stadens
leverantörsreskontra ligger årsvis på stadens öppna data. Projektet mäter i dag
Göteborg på **en månad av 17**, alltså 5,9 % periodtäckning, och det är den
siffra som binder hela analysen. Stämmer hänvisningen finns resten redan
publicerad. Det är inte verifierat — länken ligger i anteckningen på Göteborgs
rad — och att kontrollera den är förmodligen den enskilt mest värdefulla
timmen som går att lägga just nu.

### NÄSTA JOBB: skriv in avläsningen, kontrollera Göteborgs öppna data

På maskinen som har databasen, i den ordningen:

1. **Registrera svaren.** `python3 scripts/registrera_batch1_svar.py` visar vad
   som skulle skrivas; `--live` skriver. 16 anteckningar på 15 kommuner
   (Gävle får två), ingen statusändring. Säker att köra om.
2. **Spara de två bilagorna och registrera dem.** `Avtalskatalogen.xlsx` från
   Katarina.Svardgren@huddinge.se (08-31 12:19 UTC) och
   `Avtal 20230101-20260901.xlsx` från stadsledningskontoret i Göteborg
   (09-01 07:49 UTC). Båda med **`--partial`**, annars sätts status till
   `received` och `foia due` slutar jaga den halva som fattas.
3. **Kontrollera Göteborgs öppna data-sida.** Täcker den 2023–2026 för
   leverantörsfakturor? Om ja: läs in och se vad periodtäckningen blir när den
   inte längre är 1/17. Om nej: återkom till diariet, som erbjudit sig att
   lämna sammanställningen på annat sätt.
4. **Dag 3, 2026-09-03.** `docs/paminnelse-mall.md` delar de 20 i fyra grupper
   och har mallarna: 5 tysta får mall A, 10 som bekräftat får mall B, 4 där
   arbete pågår ska ha ett riktat svar i befintlig tråd i stället, och Göteborg
   ingen påminnelse alls. Registrera med `foia did <id> reminder_1`.
5. **Hässleholm och Härnösand väntar på belopp.** Hässleholm: 161 kr accepterat,
   ingen betalningsinstruktion. Härnösand: kostnad utlovad, ingen summa. Båda
   ska ryckas i via sina egna trådar, inte via en allmän påminnelse.

Hitta inte på. Registrera bara det som står i ett faktiskt mejl, med
diarienummer och datum där det finns.

<!-- MANUELLT:SLUT -->

## Kod

- Gren: `claude/state-md-next-job-868omh`
- Synkad med `origin/claude/state-md-next-job-868omh`
- Arbetsträd: 1 ändrad fil

| Commit | Datum | Vad |
| --- | --- | --- |
| `cc08409` | 2026-08-31 | feat(m3): the batch 1 inbox, read and written down |
| `128b1e1` | 2026-09-01 | docs(state): hand off the Gmail triage of batch 1 to the next session |
| `816268b` | 2026-09-01 | feat(m3): foia note, for what no other field captures |
| `d1ffebb` | 2026-08-31 | feat(state): warn when the running image predates the code |
| `260087a` | 2026-08-31 | chore(state): refresh |
| `269d539` | 2026-08-31 | fix(ci): put the repo root on sys.path for bare pytest |
| `181ff4b` | 2026-08-31 | chore(state): refresh after push |
| `9a6db60` | 2026-08-31 | fix(state): only rewrite STATE.md when something actually changed |

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
