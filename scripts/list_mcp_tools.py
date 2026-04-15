#!/usr/bin/env python3
"""
Smoke test: connect to **bds-mcp-server** using the MCP Python client's **HTTP SSE
transport** (``GET /sse`` on this process) and print **MCP tool names**.

This is **not** specific to BDS “stream” routes on the Core API. The catalog may
include many **GET** snapshot tools and zero or more **SSE** tools—only routes with
``"sse": true`` in ``endpoints.json`` (e.g. ``/mpp/stream/allTrades``) map to SSE
upstream; the rest are ordinary GETs to ``BDS_MCP_BASE_URL``.

Requires the ``mcp`` package (same as the server).

Usage::

    export BDS_MCP_SSE_API_KEY=your_powerloom_api_key
    # optional: export BDS_MCP_SSE_URL=http://127.0.0.1:8808/sse
    uv run python scripts/list_mcp_tools.py
"""

from __future__ import annotations

import asyncio
import os
import sys

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


async def _run() -> None:
    url = os.environ.get("BDS_MCP_SSE_URL", "http://127.0.0.1:8808/sse")
    key = os.environ.get("BDS_MCP_SSE_API_KEY") or os.environ.get("BDS_API_KEY")
    if not key:
        print(
            "Set BDS_MCP_SSE_API_KEY or BDS_API_KEY to your Powerloom API key.",
            file=sys.stderr,
        )
        sys.exit(1)
    headers = {"Authorization": f"Bearer {key}"}
    async with sse_client(
        url,
        headers=headers,
        timeout=60.0,
        sse_read_timeout=300.0,
    ) as streams:
        read_s, write_s = streams
        async with ClientSession(read_s, write_s) as session:
            await session.initialize()
            res = await session.list_tools()
            for t in res.tools:
                print(t.name)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
