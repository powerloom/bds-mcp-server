from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BDS_MCP_", extra="ignore")

    base_url: str = Field(
        ...,
        description="Core API origin for /mpp/... calls",
    )
    metering_url: str = Field(
        ...,
        description="Metering service origin (auth + credits)",
    )
    catalog_path: str | None = Field(default=None, description="Local path to endpoints.json")
    catalog_url: str | None = Field(default=None, description="HTTP URL to endpoints.json")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8808)
    powerloom_rpc_url: str | None = Field(default=None, description="Powerloom chain JSON-RPC for verify_data_provenance")
    protocol_state_address: str = Field(
        default="0x1d0e010Ff11b781CA1dE34BD25a0037203e25E2a",
    )
    data_market_address: str = Field(
        default="0x26c44e5CcEB7Fe69Cffc933838CF40286b2dc01a",
    )
    internal_billing_secret: str | None = Field(
        default=None,
        description="Optional; reserved for future internal billing (Phase 2)",
    )
    catalog_path_prefixes: str = Field(
        default="/mpp",
        description="Comma-separated path prefixes to filter catalog (use 'all' for no filter)",
    )
    auth_cache_ttl_seconds: int = Field(default=60, ge=1, le=3600)

    def parsed_catalog_prefixes(self) -> tuple[str, ...] | None:
        """Return path prefixes, or None if no filtering."""
        raw = self.catalog_path_prefixes.strip()
        if not raw:
            return ("/mpp",)
        s = raw.lower()
        if s in ("*", "all"):
            return None
        parts = tuple(
            p if p.startswith("/") else f"/{p}"
            for p in (x.strip().rstrip("/") for x in raw.split(","))
            if p
        )
        return parts if parts else ("/mpp",)
