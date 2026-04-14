from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bds_mcp_server.tools.credit_tool import get_credit_balance


@pytest.mark.asyncio
async def test_get_credit_balance_ok() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"balance": 42.5, "rate_limit": {"rpm": 60}}

    with patch("bds_mcp_server.tools.credit_tool.httpx.AsyncClient") as client_cls:
        inst = AsyncMock()
        inst.__aenter__.return_value = inst
        inst.__aexit__.return_value = None
        inst.get = AsyncMock(return_value=mock_resp)
        client_cls.return_value = inst

        out = await get_credit_balance(metering_url="https://meter.example", api_key="k")
    assert out["balance"] == 42.5
    assert "rate_limit" in out


@pytest.mark.asyncio
async def test_get_credit_balance_401() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 401

    with patch("bds_mcp_server.tools.credit_tool.httpx.AsyncClient") as client_cls:
        inst = AsyncMock()
        inst.__aenter__.return_value = inst
        inst.__aexit__.return_value = None
        inst.get = AsyncMock(return_value=mock_resp)
        client_cls.return_value = inst

        out = await get_credit_balance(metering_url="https://meter.example", api_key="bad")
    assert "error" in out
