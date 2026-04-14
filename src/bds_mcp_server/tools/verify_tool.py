from __future__ import annotations

from typing import Any

import httpx
from eth_abi import decode, encode
from eth_utils import keccak, to_checksum_address

_MAX_SNAPSHOTS_CID_SELECTOR = keccak(text="maxSnapshotsCid(address,string,uint256)")[:4]


def _encode_max_snapshots_cid_call(
    data_market: str,
    project_id: str,
    epoch_id: int,
) -> bytes:
    return _MAX_SNAPSHOTS_CID_SELECTOR + encode(
        ["address", "string", "uint256"],
        [
            to_checksum_address(data_market),
            project_id,
            epoch_id,
        ],
    )


def _decode_max_snapshots_cid_return(result_hex: str) -> tuple[str, int]:
    h = (result_hex or "").strip()
    if not h or h == "0x":
        return "", 0
    if h.startswith("0x"):
        h = h[2:]
    raw = bytes.fromhex(h)
    cid, status_u8 = decode(["string", "uint8"], raw)
    return cid, int(status_u8)


async def verify_data_provenance(
    *,
    rpc_url: str,
    protocol_state_address: str,
    data_market_address: str,
    cid: str,
    epoch_id: int,
    project_id: str,
    data_market_override: str | None = None,
) -> dict[str, Any]:
    """
    Compare ``cid`` to on-chain ``maxSnapshotsCid`` via ProtocolState ``eth_call``.
    """
    dm = (data_market_override or data_market_address).strip()
    ps = protocol_state_address.strip()
    calldata = _encode_max_snapshots_cid_call(dm, project_id, epoch_id)
    to_addr = to_checksum_address(ps)
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": to_addr, "data": "0x" + calldata.hex()}, "latest"],
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(rpc_url, json=req)
        resp.raise_for_status()
        body = resp.json()

    if not isinstance(body, dict):
        return {"error": "RPC response is not an object", "verified": False}
    err = body.get("error")
    if err is not None:
        return {"error": f"RPC error: {err!r}", "verified": False}
    result_hex = body.get("result")
    if not isinstance(result_hex, str):
        return {"error": "RPC result missing or not a hex string", "verified": False}

    on_chain_cid, status = _decode_max_snapshots_cid_return(result_hex)
    response_cid = cid.strip()
    verified = on_chain_cid == response_cid
    return {
        "verified": verified,
        "on_chain_cid": on_chain_cid,
        "response_cid": response_cid,
        "status": status,
    }
