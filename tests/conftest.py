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
