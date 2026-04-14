from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _bds_mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BDS_MCP_BASE_URL", "https://node.example")
    monkeypatch.setenv("BDS_MCP_METERING_URL", "https://meter.example")
    catalog = Path(__file__).parent / "fixtures" / "endpoints.minimal.json"
    monkeypatch.setenv("BDS_MCP_CATALOG_PATH", str(catalog))
