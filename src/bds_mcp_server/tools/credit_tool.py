from __future__ import annotations

from typing import Any

import httpx


async def get_credit_balance(*, metering_url: str, api_key: str) -> dict[str, Any]:
    """GET /credits/balance with Bearer token."""
    base = metering_url.rstrip("/")
    url = f"{base}/credits/balance"
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=headers)
    if r.status_code == 401:
        return {"error": "Invalid or expired API key."}
    if r.status_code < 200 or r.status_code >= 300:
        return {"error": f"HTTP {r.status_code}: {r.text[:2000]}"}
    try:
        body = r.json()
    except Exception as e:
        return {"error": f"Response is not JSON: {e}"}
    if not isinstance(body, dict):
        return {"error": "Balance response must be a JSON object"}
    return body
