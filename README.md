# tender-scan

*[Svensk version](README.sv.md)*

Monitor Swedish public procurement notices from [TED (Tenders Electronic Daily)](https://ted.europa.eu/), the EU's official procurement journal.

Built for small suppliers who bid on framework agreements and want to track what gets tendered — with a roadmap toward analyzing tendered ceiling volumes versus actual call-off volumes.

## What it does

- Fetches procurement notices from the public TED Search API, filtered by country (Sweden) and CPV code
- Stores them in a local SQLite database, with every lot kept, values stored numerically alongside their currency, and deadlines normalized to UTC
- Lists stored notices as a table, sorted by tender deadline
- Builds a **framework agreement report** from a contract award notice's eForms XML: ceiling volume, the buyer's own forecast, winners, and a comparison against call-off figures you supply (markdown or HTML)

## TED API

The client uses the anonymous TED Search API — **no registration or API key is required** for reading published notices:

```
POST https://api.ted.europa.eu/v3/notices/search
```

Requests use TED's expert query syntax, e.g.:

```
(place-of-performance IN (SWE)) AND (classification-cpv IN (72*)) AND (publication-date >= 20260711)
```

Docs: [TED Developer Docs](https://docs.ted.europa.eu/api/latest/index.html). The client applies polite rate limiting (1 request/second by default). Tests never hit the live API — they run against a recorded response fixture.

## Architecture

```
src/tender_scan/
├── ted_client.py   # TED Search API client: expert query building, pagination, rate limiting
├── models.py       # Notice dataclass + parser for TED's multilingual eForms fields
├── storage.py      # SQLite persistence (idempotent upsert keyed on publication number)
├── report.py       # eForms XML → framework agreement report (ceiling, forecast, call-offs)
├── cli.py          # typer CLI: scan, list, rapport, serve
└── web.py          # read-only web view, standard library only
```

Data flow: `ted_client` yields raw notices → `models.parse_notice` flattens them (picks English/Swedish text, all lots with value and currency, earliest lot deadline normalized to UTC ISO-8601) → `storage` upserts into SQLite, keeping the full raw JSON for later analysis.

Values are stored numerically (`estimated_value REAL` + `currency TEXT`) and summed across lots when they share a currency. Databases written by earlier versions — where the value was text (`"18000000 SEK"`) and deadlines used TED's mixed zone formats — are migrated automatically on first open: a `<db>.bak` copy is written first, then rows are re-parsed from their stored raw JSON so the migration applies the same rules as a fresh scan.

`report.py` is independent of the database: it reads a notice's eForms XML straight from TED.

## Quickstart

Requires Python 3.12+.

```bash
git clone <repo-url> && cd tender-scan
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # optional: defaults work out of the box

# Fetch Swedish IT notices (CPV 72*) published in the last 30 days
tender-scan scan --cpv "72*" --days 30

# Show what's stored
tender-scan list

# Build a framework agreement report for one notice
tender-scan rapport 214151-2026
```

Run checks:

```bash
ruff check . && pytest
```

## Framework agreement report

`tender-scan rapport <id>` automates the manual workflow documented in [docs/validering-vecka1.md](docs/validering-vecka1.md): it fetches the contract award notice's eForms XML from TED, extracts the framework amounts, and renders a comparison report. The command and its options are named in Swedish, matching the report output.

```bash
# Markdown to stdout
tender-scan rapport 214151-2026

# With your own call-off figures, as HTML to a file
tender-scan rapport 214151-2026 \
  --avrop "2025=12000000" --avrop "2026=6000000" \
  --format html --ut rapport.html

# Call-offs from CSV (label,amount — ';' also works)
tender-scan rapport 214151-2026 --avrop-fil avrop.csv
```

The report covers the ceiling (`OverallMaximumFrameworkContractsAmount`), the buyer's own forecast (`OverallApproximateFrameworkContractsAmount`), estimated contract value, number of tenderers, winners, award date, and contract period — each row printing the eForms element it came from. Fields absent from the notice are marked as missing rather than guessed.

**Honest limitation:** actual call-off amounts are not published in any open database. `--avrop`/`--avrop-fil` exist for figures obtained through a public-records request (template: [docs/begaran-mall.md](docs/begaran-mall.md)). Without them the report covers ceiling vs forecast and states explicitly that call-off data is missing.

The XML parser matches elements by local name and ignores namespaces, so it tolerates eForms schema drift. `--xml <file>` reads a local XML file instead of going over the network — this is also how the tests run.

## Web view

```bash
tender-scan serve --port 8000
```

Serves a read-only, mobile-friendly page listing stored notices. No auth — meant for private networks only (localhost or a Tailscale tailnet), never public exposure.

## Docker + Tailscale (access from your phone)

The compose setup runs the web view behind a [Tailscale](https://tailscale.com/) sidecar: the app container shares the Tailscale container's network namespace, so it is reachable only from devices on your tailnet.

```bash
cp .env.example .env
# 1. Generate an auth key: https://login.tailscale.com/admin/settings/keys
# 2. Set TS_AUTHKEY=tskey-auth-... in .env
docker compose up -d --build

# Fetch data (from inside the container; database persists in ./data/)
docker compose exec app tender-scan scan --cpv "72*" --days 30
```

Then open **http://tender-scan:8000** on your phone (Tailscale app installed and connected, MagicDNS enabled). No ports are published on the host or the internet.

## Configuration

Via environment variables (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `TED_API_BASE_URL` | `https://api.ted.europa.eu` | API base URL (override for testing/proxying) |
| `TENDER_SCAN_DB` | `tender_scan.db` | SQLite database path |

No secrets are needed — the TED search endpoints are public.

## Docs & site

- [docs/kallor.md](docs/kallor.md) — map of Swedish procurement data sources (what's free, what has an API)
- [docs/saljprocess.md](docs/saljprocess.md) — sales funnel and customer process (Swedish)
- [site/index.html](site/index.html) — customer-facing landing page, live at [tender-scan-se.netlify.app](https://tender-scan-se.netlify.app)
- [docs/validering-vecka1.md](docs/validering-vecka1.md) — week-1 validation: real framework agreement reconstructed from open data (Swedish)
- [docs/begaran-mall.md](docs/begaran-mall.md) — public-records request template for call-off data (Swedish)

## Roadmap

- **Call-off data without manual entry** — call-offs are typed in by hand today (`--avrop`); next is wiring in the Swedish Procurement Agency's open statistics and tracking received records requests per agreement
- **Reports straight from the database** — `rapport` currently goes to TED per notice ID rather than reading stored notices; connecting the two allows watching several frameworks at once
- **PDF output** — markdown and HTML exist; a customer-ready PDF does not
- **Document autofill** — pre-fill recurring tender response documents from a supplier profile
- **n8n webhook integration** — push new matching notices to n8n workflows for alerting and downstream automation

## License

MIT
