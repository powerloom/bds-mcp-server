from __future__ import annotations

import logging
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.lowlevel.server import request_ctx
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from bds_mcp_server.auth import AuthError, MeteringAuthCache, extract_bearer, json_auth_error
from bds_mcp_server.catalog_loader import CatalogLoadError, apply_catalog_filter, load_catalog_sync
from bds_mcp_server.client import BdsClientError
from bds_mcp_server.config import Settings
from bds_mcp_server.registry import EndpointTool, build_endpoint_tools, find_tool, invoke_tool, to_mcp_tools
from bds_mcp_server.tools import TOOL_GET_CREDIT_BALANCE, TOOL_VERIFY_DATA_PROVENANCE
from bds_mcp_server.tools.credit_tool import get_credit_balance
from bds_mcp_server.tools.verify_tool import verify_data_provenance

logger = logging.getLogger(__name__)


def _api_key_from_context() -> str | None:
    try:
        ctx = request_ctx.get()
    except LookupError:
        return None
    req = ctx.request
    if req is None:
        return None
    return extract_bearer(req)


def _verify_tool_definition() -> types.Tool:
    return types.Tool(
        name=TOOL_VERIFY_DATA_PROVENANCE,
        description=(
            "Verify that a BDS response's CID matches the on-chain finalized CID via "
            "ProtocolState.maxSnapshotsCid (Powerloom)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "cid": {"type": "string", "description": "CID from the response verification object"},
                "epoch_id": {"type": "integer", "description": "Epoch (block number)"},
                "project_id": {"type": "string", "description": "Full project identifier"},
                "data_market": {
                    "type": "string",
                    "description": "DataMarket contract address (defaults to deployment config)",
                },
            },
            "required": ["cid", "epoch_id", "project_id"],
        },
    )


def _credit_tool_definition() -> types.Tool:
    return types.Tool(
        name=TOOL_GET_CREDIT_BALANCE,
        description="Check the current credit balance for your API key.",
        inputSchema={"type": "object", "properties": {}},
    )


def build_mcp_server(
    settings: Settings,
    endpoint_tools: list[EndpointTool],
    auth_cache: MeteringAuthCache,
) -> Server:
    catalog_mcp = to_mcp_tools(endpoint_tools)
    extra = [_verify_tool_definition(), _credit_tool_definition()]
    all_tools = [*catalog_mcp, *extra]

    server = Server(
        "bds-mcp-server",
        version="0.1.0",
        instructions=(
            "Powerloom BDS HTTP tools (Bearer auth). Catalog tools map to GET routes from "
            "endpoints.json. Use verify_data_provenance to check CIDs on-chain; "
            "get_credit_balance queries the metering service."
        ),
    )

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return all_tools

    @server.call_tool()
    async def handle_call_tool(
        name: str,
        arguments: dict | None,
    ) -> dict[str, Any] | types.CallToolResult:
        api_key = _api_key_from_context()
        if not api_key:
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text="Missing API key: set Authorization: Bearer <key> on MCP HTTP requests.",
                    ),
                ],
                isError=True,
            )
        try:
            await auth_cache.validate(api_key)
        except AuthError as e:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=str(e))],
                isError=True,
            )

        if name == TOOL_VERIFY_DATA_PROVENANCE:
            return await _run_verify_tool(settings, dict(arguments or {}))

        if name == TOOL_GET_CREDIT_BALANCE:
            out = await get_credit_balance(metering_url=settings.metering_url, api_key=api_key)
            if "error" in out:
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=str(out["error"]))],
                    isError=True,
                )
            return out

        spec = find_tool(endpoint_tools, name)
        if spec is None:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Unknown tool: {name!r}")],
                isError=True,
            )
        try:
            return await invoke_tool(
                spec,
                dict(arguments or {}),
                base_url=settings.base_url,
                api_key=api_key,
            )
        except ValueError as e:
            logger.warning("MCP tool arg error: %s", e)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=str(e))],
                isError=True,
            )
        except BdsClientError as e:
            logger.warning("BDS HTTP error: %s", e)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=str(e))],
                isError=True,
            )
        except Exception as e:
            logger.exception("MCP tool failure")
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=str(e))],
                isError=True,
            )

    return server


async def _run_verify_tool(settings: Settings, arguments: dict[str, Any]) -> dict[str, Any]:
    rpc = settings.powerloom_rpc_url
    if not rpc or not str(rpc).strip():
        return {
            "verified": False,
            "error": (
                "Powerloom JSON-RPC is not configured. Set BDS_MCP_POWERLOOM_RPC_URL "
                "on the MCP server."
            ),
        }
    cid = arguments.get("cid")
    epoch_id = arguments.get("epoch_id")
    project_id = arguments.get("project_id")
    data_market = arguments.get("data_market")
    if not isinstance(cid, str) or not isinstance(project_id, str):
        return {"verified": False, "error": "cid and project_id must be strings"}
    if epoch_id is None:
        return {"verified": False, "error": "epoch_id is required"}
    try:
        ei = int(epoch_id)
    except (TypeError, ValueError):
        return {"verified": False, "error": "epoch_id must be an integer"}
    dm_override = data_market if isinstance(data_market, str) and data_market.strip() else None
    return await verify_data_provenance(
        rpc_url=str(rpc).strip(),
        protocol_state_address=settings.protocol_state_address,
        data_market_address=settings.data_market_address,
        cid=cid,
        epoch_id=ei,
        project_id=project_id,
        data_market_override=dm_override,
    )


def create_starlette_app(settings: Settings) -> Starlette:
    try:
        raw_catalog = load_catalog_sync(settings)
        catalog = apply_catalog_filter(settings, raw_catalog)
    except CatalogLoadError as e:
        raise SystemExit(f"Catalog error: {e}") from e

    endpoint_tools = build_endpoint_tools(catalog)
    if not endpoint_tools:
        raise SystemExit("No endpoints in catalog after load; refusing to start.")

    auth_cache = MeteringAuthCache(
        settings.metering_url,
        ttl_seconds=float(settings.auth_cache_ttl_seconds),
    )
    mcp_server = build_mcp_server(settings, endpoint_tools, auth_cache)
    sse = SseServerTransport("/messages/")

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "bds-mcp-server"})

    async def handle_sse(scope: object, receive: object, send: object) -> Response:
        request = Request(scope, receive)  # type: ignore[arg-type]
        key = extract_bearer(request)
        if not key:
            return JSONResponse(
                {"error": "Missing Authorization: Bearer <api_key>"},
                status_code=401,
            )
        try:
            await auth_cache.validate(key)
        except AuthError as e:
            return json_auth_error(e)

        async with sse.connect_sse(scope, receive, send) as streams:  # type: ignore[arg-type]
            await mcp_server.run(
                streams[0],
                streams[1],
                mcp_server.create_initialization_options(),
                raise_exceptions=False,
            )
        return Response()

    async def handle_post_message(scope: object, receive: object, send: object) -> None:
        request = Request(scope, receive)  # type: ignore[arg-type]
        key = extract_bearer(request)
        if not key:
            resp = JSONResponse(
                {"error": "Missing Authorization: Bearer <api_key>"},
                status_code=401,
            )
            await resp(scope, receive, send)
            return
        try:
            await auth_cache.validate(key)
        except AuthError as e:
            await json_auth_error(e)(scope, receive, send)
            return
        await sse.handle_post_message(scope, receive, send)  # type: ignore[arg-type]

    routes: list[Route | Mount] = [
        Route("/health", health, methods=["GET"]),
        Route("/sse", handle_sse, methods=["GET"]),
        Mount("/messages/", app=handle_post_message),
    ]
    return Starlette(routes=routes)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = Settings()
    app = create_starlette_app(settings)
    import uvicorn

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
