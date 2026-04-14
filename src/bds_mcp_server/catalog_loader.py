from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from bds_mcp_server.config import Settings


class CatalogLoadError(Exception):
    """Failed to load or filter catalog."""


def filter_catalog_by_path_prefixes(
    catalog: dict[str, Any],
    prefixes: tuple[str, ...],
) -> dict[str, Any]:
    """Return a shallow copy with ``endpoints`` restricted to matching path prefixes."""
    eps = catalog.get("endpoints")
    if not isinstance(eps, list):
        return dict(catalog)
    kept: list[dict[str, Any]] = []
    for e in eps:
        if not isinstance(e, dict):
            continue
        p = e.get("path")
        if not isinstance(p, str):
            continue
        if any(
            p == prefix or p.startswith(prefix + "/")
            for prefix in prefixes
        ):
            kept.append(e)
    out = dict(catalog)
    out["endpoints"] = kept
    return out


def load_catalog_sync(settings: Settings) -> dict[str, Any]:
    """Load endpoints.json from local path or URL (startup, synchronous)."""
    if settings.catalog_path:
        path = Path(settings.catalog_path)
        if not path.is_file():
            raise CatalogLoadError(f"Catalog file not found: {path}")
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw)
    if settings.catalog_url:
        with httpx.Client(timeout=60.0) as client:
            r = client.get(settings.catalog_url)
            r.raise_for_status()
            return r.json()
    raise CatalogLoadError(
        "Set BDS_MCP_CATALOG_PATH or BDS_MCP_CATALOG_URL to load endpoints.json",
    )


def apply_catalog_filter(settings: Settings, catalog: dict[str, Any]) -> dict[str, Any]:
    prefs = settings.parsed_catalog_prefixes()
    if prefs is None:
        return catalog
    filtered = filter_catalog_by_path_prefixes(catalog, prefs)
    eps = filtered.get("endpoints")
    if not isinstance(eps, list) or not eps:
        raise CatalogLoadError(
            "After BDS_MCP_CATALOG_PATH_PREFIXES filtering, the catalog has no endpoints. "
            f"Prefixes: {prefs!r}. Use BDS_MCP_CATALOG_PATH_PREFIXES=all to disable filtering.",
        )
    return filtered
