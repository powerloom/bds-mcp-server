from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from bds_mcp_server.auth import AuthError, MeteringAuthCache


@pytest.mark.asyncio
async def test_validate_request_error_is_502() -> None:
    cache = MeteringAuthCache("https://meter.example")
    with patch("bds_mcp_server.auth.httpx.AsyncClient") as client_cls:
        instance = AsyncMock()
        client_cls.return_value.__aenter__.return_value = instance
        instance.get.side_effect = httpx.ConnectError(
            "[Errno -2] Name or service not known",
            request=httpx.Request("GET", "https://meter.example/credits/balance"),
        )
        with pytest.raises(AuthError) as excinfo:
            await cache.validate("sk_test")
    err = excinfo.value
    assert err.status_code == 502
    assert "meter.example" in str(err)
    assert "BDS_MCP_METERING_URL" in str(err)
