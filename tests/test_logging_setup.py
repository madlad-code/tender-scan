"""Tests for the structured log: one JSON object per line, no double handlers."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from tender_scan.logging_setup import (
    DEFAULT_LOG_PATH,
    LOGGER_NAME,
    JsonFileHandler,
    configure,
    log_external_call,
)


@pytest.fixture(autouse=True)
def clean_logger() -> Iterator[logging.Logger]:
    """The package logger is process-global; restore it after every test."""
    logger = logging.getLogger(LOGGER_NAME)
    yield logger
    for handler in json_handlers(logger):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)
    logger.propagate = True


def json_handlers(logger: logging.Logger) -> list[JsonFileHandler]:
    return [h for h in logger.handlers if isinstance(h, JsonFileHandler)]


def read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_log_external_call_writes_one_json_line(tmp_path: Path) -> None:
    log_path = tmp_path / "calls.log"
    configure(log_path)

    log_external_call("https://data-api.ecb.europa.eu/service/data/EXR", 200, 123.4)

    entries = read_lines(log_path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["url"] == "https://data-api.ecb.europa.eu/service/data/EXR"
    assert entry["status"] == 200
    assert entry["elapsed_ms"] == pytest.approx(123.4)
    assert entry["ts"].endswith("Z")


def test_failed_call_logs_a_null_status_and_the_note(tmp_path: Path) -> None:
    log_path = tmp_path / "calls.log"
    configure(log_path)

    log_external_call("https://ted.europa.eu/x", None, 12.0, note="connect timeout")

    entry = read_lines(log_path)[0]
    assert entry["status"] is None
    assert entry["note"] == "connect timeout"


def test_configure_is_idempotent(tmp_path: Path) -> None:
    log_path = tmp_path / "calls.log"
    first = configure(log_path)
    second = configure(log_path)

    assert first is second
    assert len(json_handlers(second)) == 1

    log_external_call("https://example.invalid/a", 200, 1.0)
    assert len(read_lines(log_path)) == 1


def test_configure_honours_the_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / "from-env.log"
    monkeypatch.setenv("TENDER_SCAN_LOG", str(log_path))

    configure()
    log_external_call("https://example.invalid/b", 404, 2.5)

    assert read_lines(log_path)[0]["status"] == 404


def test_explicit_path_beats_the_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TENDER_SCAN_LOG", str(tmp_path / "ignored.log"))
    chosen = tmp_path / "chosen.log"

    configure(chosen)
    log_external_call("https://example.invalid/c", 200, 3.0)

    assert chosen.exists()
    assert not (tmp_path / "ignored.log").exists()


def test_log_level_filters_debug_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "calls.log"
    logger = configure(log_path, level=logging.WARNING)

    logger.debug("invisible")
    log_external_call("https://example.invalid/d", 200, 4.0)

    assert read_lines(log_path) == []


def test_unconfigured_call_still_lands_in_the_default_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TENDER_SCAN_LOG", raising=False)

    log_external_call("https://example.invalid/e", 200, 5.0)

    assert read_lines(tmp_path / DEFAULT_LOG_PATH)[0]["url"] == "https://example.invalid/e"
