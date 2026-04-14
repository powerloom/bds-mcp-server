from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bds_mcp_server.tools.verify_tool import verify_data_provenance


@pytest.mark.asyncio
async def test_verify_match() -> None:
    # Minimal ABI-encoded return: (string "QmOn", uint8 1)
    from eth_abi import encode

    payload = encode(["string", "uint8"], ["QmOn", 1])
    ret_hex = "0x" + payload.hex()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": ret_hex}
    mock_resp.raise_for_status = MagicMock()

    with patch("bds_mcp_server.tools.verify_tool.httpx.AsyncClient") as client_cls:
        inst = AsyncMock()
        inst.__aenter__.return_value = inst
        inst.__aexit__.return_value = None
        inst.post = AsyncMock(return_value=mock_resp)
        client_cls.return_value = inst

        out = await verify_data_provenance(
            rpc_url="http://rpc.test",
            protocol_state_address="0x0000000000000000000000000000000000000001",
            data_market_address="0x0000000000000000000000000000000000000002",
            cid="QmOn",
            epoch_id=1,
            project_id="proj:a",
        )
    assert out["verified"] is True
    assert out["response_cid"] == "QmOn"
    assert out["on_chain_cid"] == "QmOn"


@pytest.mark.asyncio
async def test_verify_mismatch() -> None:
    from eth_abi import encode

    payload = encode(["string", "uint8"], ["QmOther", 1])
    ret_hex = "0x" + payload.hex()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": ret_hex}
    mock_resp.raise_for_status = MagicMock()

    with patch("bds_mcp_server.tools.verify_tool.httpx.AsyncClient") as client_cls:
        inst = AsyncMock()
        inst.__aenter__.return_value = inst
        inst.__aexit__.return_value = None
        inst.post = AsyncMock(return_value=mock_resp)
        client_cls.return_value = inst

        out = await verify_data_provenance(
            rpc_url="http://rpc.test",
            protocol_state_address="0x0000000000000000000000000000000000000001",
            data_market_address="0x0000000000000000000000000000000000000002",
            cid="QmOn",
            epoch_id=1,
            project_id="proj:a",
        )
    assert out["verified"] is False


@pytest.mark.asyncio
async def test_verify_rpc_error() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "bad"}}
    mock_resp.raise_for_status = MagicMock()

    with patch("bds_mcp_server.tools.verify_tool.httpx.AsyncClient") as client_cls:
        inst = AsyncMock()
        inst.__aenter__.return_value = inst
        inst.__aexit__.return_value = None
        inst.post = AsyncMock(return_value=mock_resp)
        client_cls.return_value = inst

        out = await verify_data_provenance(
            rpc_url="http://rpc.test",
            protocol_state_address="0x0000000000000000000000000000000000000001",
            data_market_address="0x0000000000000000000000000000000000000002",
            cid="QmOn",
            epoch_id=1,
            project_id="proj:a",
        )
    assert out["verified"] is False
    assert "error" in out
