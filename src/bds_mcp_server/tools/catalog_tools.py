from __future__ import annotations

from typing import Any

from bds_mcp_server.registry import EndpointTool, find_tool, invoke_tool


async def call_catalog_tool(
    tools: list[EndpointTool],
    name: str,
    arguments: dict[str, Any] | None,
    *,
    base_url: str,
    api_key: str,
) -> dict[str, Any]:
    """Dispatch a catalog tool by name."""
    spec = find_tool(tools, name)
    if spec is None:
        raise KeyError(name)
    return await invoke_tool(
        spec,
        dict(arguments or {}),
        base_url=base_url,
        api_key=api_key,
    )


__all__ = ["call_catalog_tool"]
