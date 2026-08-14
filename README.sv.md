# tender-scan

*[English version](README.md)*

Bevakar svenska offentliga upphandlingar från [TED](https://ted.europa.eu/) —
EU:s officiella upphandlingsdatabas — och lagrar dem lokalt för analys.

Byggd för små leverantörer som lägger anbud på ramavtal och vill veta mer än
konkurrenterna: vad annonseras, vad tilldelas, och (på sikt) hur mycket av
avtalens takvolymer som faktiskt avropas.

**Kundsida:** [tender-scan-se.netlify.app](https://tender-scan-se.netlify.app)

## Varför

Ett ramavtal annonseras med en takvolym — säg 4 MSEK. Men de verkliga pengarna
styrs av avropen under avtalstiden, och den siffran tittar nästan ingen på.
Skillnaden mellan lovat och levererat är beslutsunderlag inför nästa anbud.
tender-scan är motorn som samlar grunddatan. Se [docs/kallor.md](docs/kallor.md)
för hela kartan över svenska datakällor och [docs/saljprocess.md](docs/saljprocess.md)
för hur analysen paketeras mot kund.

## Vad den gör idag

- Hämtar upphandlingsannonser från TED:s öppna API (inget konto, ingen nyckel),
  filtrerat på land (Sverige) och CPV-kod
- Lagrar i lokal SQLite-databas (idempotent — kör hur ofta som helst), med
  alla delkontrakt, numeriska belopp + valuta och deadlines normaliserade till UTC
- Listar lagrade annonser i terminalen eller som mobilanpassad webbsida
- **Bygger ramavtalsrapport** ur en tilldelningsannons eForms-XML: takvolym,
  myndighetens egen prognos, vinnare, och jämförelse mot avropssiffror du matar in
  (markdown eller HTML)
- Körs i Docker bakom Tailscale — nåbar från mobilen, osynlig för internet

## Kom igång

Kräver Python 3.12+.

```bash
git clone git@github.com:madlad-code/tender-scan.git && cd tender-scan
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Hämta svenska IT-upphandlingar (CPV 72*) från senaste 30 dagarna
tender-scan scan --cpv "72*" --days 30

# Visa vad som lagrats
tender-scan list

# Ramavtalsrapport för en tilldelningsannons (markdown till stdout)
tender-scan rapport 214151-2026

# Webbvy på http://localhost:8000
tender-scan serve
```

Tester och lint (körs även i CI på varje push):

```bash
ruff check . && pytest
```

Testerna anropar aldrig TED live — de körs mot inspelade svar i `tests/fixtures/`.

## Arkitektur

```
src/tender_scan/
├── ted_client.py   # TED-klient: frågespråk, paginering, artig rate limiting
├── models.py       # Notice-dataklass + parser för TED:s flerspråkiga eForms-fält
├── storage.py      # SQLite (upsert på publikationsnummer — inga dubbletter)
├── report.py       # eForms-XML → ramavtalsrapport (takvolym, prognos, avrop)
├── cli.py          # typer-CLI: scan, list, rapport, serve
└── web.py          # skrivskyddad webbvy, enbart standardbiblioteket
```

Dataflöde: `ted_client` hämtar rå-annonser → `models.parse_notice` plattar till
(svensk/engelsk text, alla delkontrakt med belopp och valuta, tidigaste deadline
normaliserad till UTC ISO-8601) → `storage` upsertar till SQLite och behåller
hela rå-JSON för framtida analys.

Beloppen lagras numeriskt (`estimated_value REAL` + `currency TEXT`) och summeras
över delkontrakten när de delar valuta. Äldre databaser — där värdet låg som text
(`"18000000 SEK"`) och deadlines i TED:s blandade zonformat — migreras automatiskt
vid första öppning; en `<db>.bak`-kopia skrivs först och raderna tolkas om från
sparad rå-JSON.

`report.py` står för sig själv: den läser en annons eForms-XML direkt från TED
och rör aldrig SQLite-databasen.

## Ramavtalsrapport

`tender-scan rapport <id>` automatiserar arbetsflödet i
[docs/validering-vecka1.md](docs/validering-vecka1.md): den hämtar
tilldelningsannonsens eForms-XML från TED, plockar ut ramavtalsbeloppen och
renderar en jämförelserapport.

```bash
# Markdown till stdout
tender-scan rapport 214151-2026

# Med egna avropssiffror, som HTML till fil
tender-scan rapport 214151-2026 \
  --avrop "2025=12000000" --avrop "2026=6000000" \
  --format html --ut rapport.html

# Avrop från CSV (etikett,belopp — även ';' fungerar)
tender-scan rapport 214151-2026 --avrop-fil avrop.csv
```

Rapporten innehåller takvolym (`OverallMaximumFrameworkContractsAmount`),
myndighetens egen prognos (`OverallApproximateFrameworkContractsAmount`),
uppskattat kontraktsvärde, antal anbudsgivare, vinnare, tilldelningsdatum och
avtalsperiod — varje rad med sin eForms-källa utskriven. Fält som saknas i
annonsen märks *saknas i annonsen* i stället för att gissas.

**Ärlig begränsning:** faktiskt avropade belopp finns inte i någon öppen databas.
`--avrop`/`--avrop-fil` är till för siffror du fått ut enligt
offentlighetsprincipen (mall: [docs/begaran-mall.md](docs/begaran-mall.md)).
Utan dem redovisar rapporten tak vs prognos och säger uttryckligen att
avropsdata saknas.

XML-parsern matchar element på lokalt namn och struntar i namnrymder, så den
tål versionsdrift i eForms-schemat. `--xml <fil>` läser en lokal XML-fil i
stället för att gå mot nätet — så körs även testerna.

## Docker + Tailscale (nå den från mobilen)

```bash
cp .env.example .env   # fyll i TS_AUTHKEY från Tailscale-adminpanelen
docker compose up -d --build
docker compose exec app tender-scan scan --cpv "72*" --days 30
```

Öppna sedan **http://tender-scan:8000** i mobilen (Tailscale-appen igång).
Inga portar öppnas mot internet — sidan nås bara från dina egna enheter.

## Vägkarta

- **Avropsdata utan handpåläggning** — idag matas avropen in manuellt
  (`--avrop`); nästa steg är att koppla på Upphandlingsmyndighetens öppna
  statistikdata och hålla reda på inkomna utlämnanden per avtal
- **Rapport direkt ur databasen** — `rapport` går idag mot TED per annons-ID,
  inte mot lagrade annonser; koppla ihop dem och bevaka flera ramavtal i taget
- **PDF-utskrift** — markdown och HTML finns, kundfärdig PDF återstår
- **Fler källor** — adapterarkitektur för nationella annonsdatabaser, se [docs/kallor.md](docs/kallor.md)
- **n8n-integration** — daglig scan, diff och mejldigest utan handpåläggning

## Licens

MIT
