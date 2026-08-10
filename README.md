# tender-scan

Monitor Swedish public procurement notices from [TED (Tenders Electronic Daily)](https://ted.europa.eu/), the EU's official procurement journal.

Built for small suppliers who bid on framework agreements and want to track what gets tendered — with a roadmap toward analyzing tendered ceiling volumes versus actual call-off volumes.

## What it does

- Fetches procurement notices from the public TED Search API, filtered by country (Sweden) and CPV code
- Stores them in a local SQLite database
- Lists stored notices as a table, sorted by tender deadline

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
└── cli.py          # typer CLI: scan, list
```

Data flow: `ted_client` yields raw notices → `models.parse_notice` flattens them (picks English/Swedish text, first lot value, earliest lot deadline) → `storage` upserts into SQLite, keeping the full raw JSON for later analysis.

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
```

Run checks:

```bash
ruff check . && pytest
```

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

## Roadmap

- **AI analysis of call-off vs ceiling volumes** — compare the estimated/maximum values tendered in framework agreements against actual call-off (contract award) volumes, flagging frameworks that are under-utilized or nearly exhausted
- **Document autofill** — pre-fill recurring tender response documents from a supplier profile
- **n8n webhook integration** — push new matching notices to n8n workflows for alerting and downstream automation

## License

MIT
