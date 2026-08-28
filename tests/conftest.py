import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def search_response() -> dict:
    """Recorded response from POST /v3/notices/search (SE, CPV 72*, July 2026)."""
    return json.loads((FIXTURES / "ted_search_response.json").read_text())


@pytest.fixture
def eforms_path() -> Path:
    """Recorded eForms XML: TED 214151-2026, Försvarsmakten "Standardbatterier"."""
    return FIXTURES / "eforms_214151-2026.xml"


@pytest.fixture
def eforms_xml(eforms_path: Path) -> bytes:
    return eforms_path.read_bytes()


@pytest.fixture
def eforms_1884() -> bytes:
    """Single-lot framework: ceiling 3 000 000 SEK, per-lot ceiling 1 500 000."""
    return (FIXTURES / "eforms_1884-2026.xml").read_bytes()


@pytest.fixture
def eforms_15840() -> bytes:
    """Three lots with ceilings 8M/8M/14M; the notice-level ceiling (8M) disagrees."""
    return (FIXTURES / "eforms_15840-2026.xml").read_bytes()


@pytest.fixture
def eforms_8020() -> bytes:
    """Framework with no ceiling published — only an approximate value of 28 000 000."""
    return (FIXTURES / "eforms_8020-2026.xml").read_bytes()


@pytest.fixture
def ecb_csv() -> str:
    """Recorded ECB daily SEK/EUR reference rates, 2026-06-29 .. 2026-07-06."""
    return (FIXTURES / "ecb_sek_eur.csv").read_text(encoding="utf-8")


@pytest.fixture
def eforms_431354() -> bytes:
    """Three structured ceilings that disagree: overall 4M, lot max 4M, framework max 8M."""
    return (FIXTURES / "eforms_431354-2026.xml").read_bytes()


@pytest.fixture
def eforms_470310() -> bytes:
    """Ranked framework: RankCode 1, one tender with PayableAmount 0 (value undisclosed)."""
    return (FIXTURES / "eforms_470310-2026.xml").read_bytes()


PAYMENT_FIXTURES = FIXTURES / "payments"


@pytest.fixture
def vgr_sample() -> bytes:
    """Recorded VGR monthly CSV: 4 rows, UTF-8, `;`, and a bare `\\r` terminator."""
    return (PAYMENT_FIXTURES / "vgr_sample.csv").read_bytes()


@pytest.fixture
def goteborg_sample() -> bytes:
    """Recorded Göteborg monthly CSV: 4 rows, UTF-16 LE with BOM, `,` decimals."""
    return (PAYMENT_FIXTURES / "goteborg_sample.csv").read_bytes()


@pytest.fixture
def vasteras_sample() -> bytes:
    """Recorded Västerås rowstore JSON: a UTF-8 BOM inside the first key."""
    return (PAYMENT_FIXTURES / "vasteras_sample.json").read_bytes()


@pytest.fixture
def vgr_catalogue() -> bytes:
    """Recorded EntryScape catalogue search for the VGR supplier ledger."""
    return (PAYMENT_FIXTURES / "vgr_catalogue.json").read_bytes()
