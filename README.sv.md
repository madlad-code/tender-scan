# tender-scan

*[English version](README.md)*

Bevakar svenska offentliga upphandlingar från [TED](https://ted.europa.eu/) —
EU:s officiella upphandlingsdatabas — och lagrar dem lokalt för analys.

Byggd för små leverantörer som lägger anbud på ramavtal och vill veta mer än
konkurrenterna: vad annonseras, vad tilldelas, och (på sikt) hur mycket av
avtalens takvolymer som faktiskt avropas.

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
- Lagrar i lokal SQLite-databas (idempotent — kör hur ofta som helst)
- Listar lagrade annonser i terminalen eller som mobilanpassad webbsida
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
├── cli.py          # typer-CLI: scan, list, serve
└── web.py          # skrivskyddad webbvy, enbart standardbiblioteket
```

Dataflöde: `ted_client` hämtar rå-annonser → `models.parse_notice` plattar till
(svensk/engelsk text, första delkontraktets värde, tidigaste deadline) →
`storage` upsertar till SQLite och behåller hela rå-JSON för framtida analys.

## Docker + Tailscale (nå den från mobilen)

```bash
cp .env.example .env   # fyll i TS_AUTHKEY från Tailscale-adminpanelen
docker compose up -d --build
docker compose exec app tender-scan scan --cpv "72*" --days 30
```

Öppna sedan **http://tender-scan:8000** i mobilen (Tailscale-appen igång).
Inga portar öppnas mot internet — sidan nås bara från dina egna enheter.

## Vägkarta

- **Avropsanalys** — jämför ramavtalens takvolymer mot faktiska avrop
  (Upphandlingsmyndighetens öppna statistikdata + offentlighetsprincipen)
- **Fler källor** — adapterarkitektur för nationella annonsdatabaser, se [docs/kallor.md](docs/kallor.md)
- **n8n-integration** — daglig scan, diff och mejldigest utan handpåläggning
- **Rapportgenerator** — från SQLite till kundfärdig PDF

## Licens

MIT
