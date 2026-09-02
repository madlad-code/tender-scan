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
├── cli.py          # typer CLI: scan, list, rapport, serve + the utilization commands below
└── web.py          # read-only web view (dashboard, report, prospects), stdlib only

# The utilization modules, built on top of the pipeline above rather than into it
├── money.py        # amount normalization ("4,5 mkr" → 4500000) and ceiling phrases in prose
├── fx.py           # dated EUR→SEK via the ECB daily reference rates, cached, never hardcoded
├── orgnr.py        # organisationsnummer: one spelling, Luhn-checked
├── eforms.py       # notice XML → a resolved graph (lots, results, tenders, winners, buyers)
├── records.py      # row types for the v5 tables
├── frameworks.py   # M1: takvolym extraction with a documented reconciliation rule
├── winners.py      # M2: every supplier awarded a place, per lot, with rank
├── payments/       # M4: one loader per open supplier ledger (VGR, Göteborg, Västerås)
├── utilization.py  # M5: the utilization view and the report
├── prospects.py    # M6: suppliers sitting on several frameworks
├── foia.py         # M3: offentlighetsprincipen requests and their deadlines
├── municipal.py    # M7: the catalogues and ledgers records requests actually return
└── logging_setup.py
```

Data flow: `ted_client` yields raw notices → `models.parse_notice` flattens them (picks English/Swedish text, all lots with value and currency, earliest lot deadline normalized to UTC ISO-8601) → `storage` upserts into SQLite, keeping the full raw JSON for later analysis.

Values are stored numerically (`estimated_value REAL` + `currency TEXT`) and summed across lots when they share a currency. Databases written by earlier versions — where the value was text (`"18000000 SEK"`) and deadlines used TED's mixed zone formats — are migrated automatically on first open: a `<db>.bak` copy is written first, then rows are re-parsed from their stored raw JSON so the migration applies the same rules as a fresh scan.

`report.py` is independent of the database: it reads a notice's eForms XML straight from TED.

## Utnyttjandegrad — ceiling vs actual call-offs

The question the whole thing exists to answer: **how much of a framework
agreement's ceiling has actually been called off?** One number,
`utnyttjandegrad = observed call-offs / takvolym`, with everything needed to
say how much of it you can actually see.

```bash
# 1. Ceilings, from each notice's own eForms fields, into framework_agreements
tender-scan frameworks extract --cache data/xml_cache
tender-scan frameworks review          # the manual queue: no ceiling, or weak evidence
tender-scan frameworks validate --cache data/xml_cache   # hit rate per cap_source

# 2. Every supplier awarded a place, per lot, with rank where published
tender-scan winners extract --cache data/xml_cache
tender-scan winners list --orgnr 556599-4307

# 3. Actual payments, from the buyers who publish their supplier ledger
tender-scan payments sources
tender-scan payments load goteborg --url https://catalog.goteborg.se/store/6/resource/129628

# 4. The answer
tender-scan utilization --measurable    # every framework, one line each
tender-scan report 109559-2026          # the full report for one, markdown or --format html

# 5. Who to talk to: suppliers sitting on two or more frameworks
tender-scan prospects --cpv 72000000 --min-frameworks 2 --out prospects.csv

# 6. For buyers who publish nothing: a records request, and its deadlines
tender-scan foia new --framework 109559-2026 --org "Sundsvalls kommun"
tender-scan foia sent 1                 # you send it yourself; this starts the clock
tender-scan foia import batch1.csv      # or sync a whole outreach sheet at once
tender-scan foia due                    # day 3 reminder, day 5 call, day 10 written decision
tender-scan foia note 1 "bekräftelse mottagen, diarienr KS-2026-123"
tender-scan foia ingest 1 svar.csv
tender-scan foia ingest 7 svar.xlsx --partial   # part of it arrived; keep chasing the rest
```

```bash
# 7. What comes back: one reader per delivered format, then the pair they make
tender-scan kommun sources
tender-scan kommun ingest goteborg "Avtal 20230101-20260901.xlsx"
tender-scan kommun ingest boras "Öppna data 2025.xlsx" --ledger
tender-scan kommun list
tender-scan kommun rapport "Bjurholms kommun"
```

`foia_requests` is the record of truth for where each request stands — `foia due` reads it and nothing else. A sheet is an input to it via `foia import`, never a parallel copy of it.

`foia note` records what no other field captures. The common case is an acknowledgement: almost every registrator replies "vi har mottagit din begäran" long before a document arrives. That does not settle the request, so the status stays `sent` and the clock keeps running — but it is worth keeping, because it is the proof of receipt an escalation rests on, and because a silent authority and one that acknowledged then went quiet call for different wording in the reminder.

Batch outreach gets tracked in a spreadsheet first, because a spreadsheet is what you reach for when sending twenty emails on a Tuesday. That is a fine working surface and a useless clock: nothing in a sheet tells you that Huddinge is on day 6 and owes you a phone call. `foia import` syncs the sheet into `foia_requests`, matching on the authority's name so re-running after an edit updates rows rather than logging the same request twice.

The reader tolerates what a spreadsheet does to a file — a UTF-8 BOM on the first header, rows truncated to the last non-empty cell — and refuses anything that needs a guess. **Dates must be ISO-8601**: `03-04-26` is March 4th or April 3rd depending on a convention the file does not record, and silently picking one puts a reminder on the wrong day.

A sheet's `levererat_delvis` maps to the status `partial`, which is deliberately *not* settled. An authority that sent one year of three has answered without delivering; treating that as done is how the missing half gets forgotten, so the clock keeps running and `foia due` keeps listing it.

Every command takes `--db` and, where it writes, `--dry-run`.

### What the numbers mean, and what they do not

A utilization rate is **never** printed without its coverage ratio, in any
output. With payment data for one buyer of sixteen, or one month of
forty-seven, the figure is a lower bound, not a measurement — and the report
says so next to every percentage, under its own **Metodbegränsningar** heading.

Three rules that decide whether a figure is honest:

- **A payment only counts if the payer is a buyer the notice names.** Another
  authority paying the same supplier is not a call-off on this agreement.
- **A payment only counts if it falls inside the agreement's term.**
- **The ceiling and the estimate never share a column.** Where only a forecast
  is published, `cap_value_sek` is NULL and the report says the ceiling is
  unknown rather than dividing by a guess.

Measured against 137 real Swedish CPV-72 framework notices: a ceiling is
published in a structured eForms field for 94 of them and stated in prose for
one more, so 95 of 137 (69 %) get a ceiling and the remaining 42 go to the
manual review queue. Those 137 notices carry 1 771 award rows across 460
distinct suppliers, 99.5 % of them with a Luhn-valid organisationsnummer.

## Municipal catalogues and ledgers (M7)

A records request does not return a TED notice. It returns a municipality's own
**avtalskatalog** — one row per supplier per contract — and its
**leverantörsreskontra** — one row per invoice. Held together, the pair measures
what no open source publishes: how much of a municipality's spend reaches the
suppliers it signed contracts with, and how many of those suppliers get nothing.

Five municipalities answered the same request with five formats: an e-avrop
matrix with its header on row four, a Mercell export with the contract term
merged into one free-text column, a contract system's PDF, and two spreadsheets
whose column names agree on nothing. Each reader owns its format; nothing
downstream branches on which municipality a row came from.

### The rules the numbers obey

- **A rate needs both halves.** `avtalstrohet` is computed only for a buyer whose
  catalogue *and* ledger are stored, and always printed next to the ledger's own
  window. A catalogue with no ledger shows a dash, never a rate divided by nothing.
- **Only a complete ledger can be a denominator.** M4's `open_data` rows are
  filtered to framework winners before they are stored, so every one of them is
  contracted by construction. M7 reads `source = 'foia'` rows and no others.
- **Silence needs a year.** Below twelve months of ledger, "this supplier was paid
  nothing" describes the window, not the supplier, so the zero-call-off share is
  withheld rather than printed.
- **A catalogue is not a census.** Grästorp put it in writing: their database holds
  mainly framework agreements and omits construction procurements, direct awards
  and several central-body agreements. Spend outside a catalogue is therefore not
  proof of maverick buying, and every report says so.

Measured on the first batch: 9 790 contract rows from five municipalities and
11.1 bn SEK of ledger from two. One municipality delivered both halves —
Bjurholm, where contracted suppliers received 25.3 % of the spend over 22 months,
and half of the suppliers holding a live contract outside health and social care
were paid nothing at all.

## Quickstart

Requires Python 3.12+.

```bash
git clone <repo-url> && cd tender-scan
bash scripts/setup.sh   # picks a 3.12+ interpreter, installs, reports what the clone lacks
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

Serves a read-only, mobile-friendly site. No auth — meant for private networks only (localhost or a Tailscale tailnet), never public exposure.

| Path | What it shows |
| --- | --- |
| `/` | The utilisation dashboard: every framework agreement with its ceiling, observed spend, both utilisation rates and both coverage figures, largest observed spend first |
| `/ramavtal/<notice_id>` | The full M5 report for one agreement — the same text `tender-scan utnyttjandegrad rapport` prints, rendered by the same function so the two cannot drift apart |
| `/kommuner` | The municipal catalogues and ledgers records requests returned (M7), and what each pair can measure |
| `/kommun/<namn>` | One municipality's suppliers, including the ones holding a live contract with no call-off |
| `/prospekt` | Suppliers sitting on several framework agreements (M6) |
| `/notiser` | The stored notice list |

The dashboard obeys M5's rule that `utilization_rate` is never shown without `coverage_ratio`. In a table the caveat cannot travel as a paragraph, so every row carries its own coverage cells and a test asserts that no row renders a rate without them — a reader who sorts by "Grad" and stops reading has still seen how much of the picture is missing.

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

## STATE.md — where the project actually is

The project gets worked on from more than one place: an agent in the terminal that can read the code but knows nothing about what was decided in a browser, and an assistant in a browser that knows the plan but cannot see the repository. Each reconstructs the other's half by asking questions, badly and expensively.

[STATE.md](STATE.md) is the shared answer. It is committed, so anything that can read the repo can read it, and it is regenerated at the start of every session, so it is never the stale summary someone forgot to update.

```bash
python3 scripts/state.py           # rewrite STATE.md
python3 scripts/state.py --print   # rewrite, then print it
python3 scripts/state.py --check   # print without writing
```

Everything a machine can observe is generated: branch and whether it is pushed, recent commits, which containers run and how old their image is, row counts per table, open records requests. Everything a machine cannot observe — where you are in the plan, what you are waiting for, what you decided and why — lives between the `MANUELLT` markers and is copied through untouched.

`.claude/settings.json` runs the script as a `SessionStart` hook, so a session opens with the file fresh and already in context. `/lage` regenerates it mid-session. The script is standard library only, so it runs under the system interpreter without the project's virtualenv.

## Docs & site

- [docs/kallor.md](docs/kallor.md) — map of Swedish procurement data sources (what's free, what has an API)
- [docs/saljprocess.md](docs/saljprocess.md) — sales funnel and customer process (Swedish)
- [site/index.html](site/index.html) — customer-facing landing page, live at [tender-scan-se.netlify.app](https://tender-scan-se.netlify.app)
- [docs/validering-vecka1.md](docs/validering-vecka1.md) — week-1 validation: real framework agreement reconstructed from open data (Swedish)
- [docs/begaran-mall.md](docs/begaran-mall.md) — public-records request template for call-off data (Swedish)

## Roadmap

- **More buyers with open ledgers** — three are wired up (VGR, Göteborg, Västerås). Ale, Umeå, Södertälje, Trollhättan, Lidingö and DIGG publish the same shape and are the obvious next ones; each new buyer raises the coverage ratio, which is the number that decides whether a report is worth selling
- **Ingest FOIA answers into `supplier_payments`** — `foia ingest` links the file today; parsing it into rows with `source='foia'` is the missing step
- **PDF output** — markdown and HTML exist; a customer-ready PDF does not
- **Document autofill** — pre-fill recurring tender response documents from a supplier profile
- **n8n webhook integration** — push new matching notices to n8n workflows for alerting and downstream automation

## License

MIT
