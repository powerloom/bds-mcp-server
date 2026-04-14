from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse


class AuthError(Exception):
    """API key rejected or credits exhausted."""

    def __init__(self, message: str, *, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


def extract_bearer(request: Request) -> str | None:
    """Return raw token from ``Authorization: Bearer ...``."""
    raw = request.headers.get("authorization") or request.headers.get("Authorization")
    if not raw or not isinstance(raw, str):
        return None
    parts = raw.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token if token else None


@dataclass
class _CacheEntry:
    expires_at: float
    balance: float | None
    rate_limit: Any


class MeteringAuthCache:
    """In-memory TTL cache for Metering ``GET /credits/balance``."""

    def __init__(self, metering_url: str, ttl_seconds: float = 60.0) -> None:
        self._base = metering_url.rstrip("/")
        self._ttl = ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}

    def _balance_url(self) -> str:
        return f"{self._base}/credits/balance"

    async def validate(self, api_key: str) -> dict[str, Any]:
        """
        Ensure the API key is accepted and has credits.

        Returns a JSON-serializable dict (balance info) on success.
        Raises AuthError on failure.
        """
        now = time.monotonic()
        ent = self._cache.get(api_key)
        if ent and ent.expires_at > now:
            if ent.balance is not None and ent.balance <= 0:
                raise AuthError(
                    "Credit balance is zero; add credits or use a different API key.",
                    status_code=402,
                )
            return {"balance": ent.balance, "rate_limit": ent.rate_limit}

        headers = {"Authorization": f"Bearer {api_key}"}
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(self._balance_url(), headers=headers)

        if r.status_code == 401:
            raise AuthError("Invalid or expired API key.", status_code=401)
        if r.status_code == 402:
            raise AuthError(
                "Credits exhausted or payment required (HTTP 402).",
                status_code=402,
            )
        if r.status_code < 200 or r.status_code >= 300:
            text = r.text[:2048]
            raise AuthError(f"Metering error HTTP {r.status_code}: {text}", status_code=502)

        try:
            body = r.json()
        except Exception as e:
            raise AuthError(f"Metering response is not JSON: {e}", status_code=502) from e
        if not isinstance(body, dict):
            raise AuthError("Metering balance response must be a JSON object.", status_code=502)

        balance_raw = body.get("balance")
        balance: float | None
        try:
            if balance_raw is None:
                balance = None
            else:
                balance = float(balance_raw)
        except (TypeError, ValueError):
            balance = None

        if balance is not None and balance <= 0:
            raise AuthError(
                "Credit balance is zero; add credits or use a different API key.",
                status_code=402,
            )

        self._cache[api_key] = _CacheEntry(
            expires_at=now + self._ttl,
            balance=balance,
            rate_limit=body.get("rate_limit"),
        )
        return body


def json_auth_error(exc: AuthError) -> JSONResponse:
    return JSONResponse(
        {"error": str(exc)},
        status_code=exc.status_code,
    )
