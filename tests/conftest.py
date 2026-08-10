import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def search_response() -> dict:
    """Recorded response from POST /v3/notices/search (SE, CPV 72*, July 2026)."""
    return json.loads((FIXTURES / "ted_search_response.json").read_text())
