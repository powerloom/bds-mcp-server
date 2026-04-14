# bds-mcp-server

Hosted **Model Context Protocol (MCP)** server for Powerloom BDS: catalog-derived HTTP tools (same idea as `bds-agent mcp` on **stdio**), plus `verify_data_provenance` and `get_credit_balance`, exposed over **SSE/HTTP** so remote clients (OpenClaw, LangGraph, Claude Desktop with remote MCP, Cursor, etc.) can connect without running a local subprocess.

---

## Table of contents

- [Local stdio vs this server](#local-stdio-vs-this-server)
- [Prerequisites](#prerequisites)
- [Install](#install)
- [Configuration](#configuration)
- [Run](#run)
- [Usage: HTTP transport and auth](#usage-http-transport-and-auth)
- [Tools](#tools)
- [Connect from MCP clients](#connect-from-mcp-clients)
- [Docker](#docker)
- [Operations and troubleshooting](#operations-and-troubleshooting)
- [Development](#development)

---

## Local stdio vs this server

| | **`bds-agent mcp`** (bds-agent-py) | **`bds-mcp-server`** (this repo) |
|---|--------------------------------------|-----------------------------------|
| Transport | stdio (child process) | HTTP **SSE** + POST messages |
| Deploy | None; client starts `bds-agent mcp` | Run as a service (VM, K8s, Docker) |
| Auth | Profile / env API key in the child env | **`Authorization: Bearer`** on every HTTP request |
| Catalog | `BDS_API_ENDPOINTS_CATALOG_JSON` / `BDS_SOURCES_JSON` | **`BDS_MCP_CATALOG_PATH`** or **`BDS_MCP_CATALOG_URL`** |

Use **stdio** for Cursor/Claude on your laptop when the CLI can launch the process. Use **this server** when the agent runs elsewhere or you want a stable URL and shared deployment.

---

## Prerequisites

- **Python 3.12+**
- **Core API** reachable at `BDS_MCP_BASE_URL` with `/mpp/...` routes (same origin the catalog describes).
- **Metering** at `BDS_MCP_METERING_URL` exposing **`GET /credits/balance`** with Bearer auth (used to validate API keys before MCP traffic).
- An **`endpoints.json`** catalog (e.g. from snapshotter-computes `api/endpoints.json`).

---

## Install

With [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
```

Run commands via `uv run …` (see [Run](#run)). To put `bds-mcp-server` on your PATH:

```bash
uv tool install .
```

If the installed tool looks stale after local changes, `uv cache clean` then `uv tool install --force .`. Editable install while developing: `uv tool install --force --editable .`.

With pip only:

```bash
pip install ".[dev]"
```

---

## Configuration

All settings use the **`BDS_MCP_`** prefix. Copy **`.env.example`** to **`.env`** and load it in your process manager or `docker run --env-file`.

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `BDS_MCP_BASE_URL` | **yes** | — | Core API origin (no trailing path; e.g. `https://snapshotter.example`) |
| `BDS_MCP_METERING_URL` | **yes** | — | Metering origin; server calls `GET {origin}/credits/balance` |
| `BDS_MCP_CATALOG_PATH` **or** `BDS_MCP_CATALOG_URL` | **yes** (one of) | — | Local filesystem path to `endpoints.json`, or HTTP URL to fetch at startup |
| `BDS_MCP_HOST` | no | `0.0.0.0` | Bind address |
| `BDS_MCP_PORT` | no | `8808` | Listen port |
| `BDS_MCP_CATALOG_PATH_PREFIXES` | no | `/mpp` | Comma-separated path prefixes to **filter** catalog routes; use `all` to disable filtering |
| `BDS_MCP_POWERLOOM_RPC_URL` | no | — | JSON-RPC URL for **`verify_data_provenance`** (`eth_call`) |
| `BDS_MCP_PROTOCOL_STATE_ADDRESS` | no | mainnet BDS default | ProtocolState contract |
| `BDS_MCP_DATA_MARKET_ADDRESS` | no | mainnet BDS default | DataMarket contract |
| `BDS_MCP_AUTH_CACHE_TTL_SECONDS` | no | `60` | Cache successful metering checks (seconds) |
| `BDS_MCP_INTERNAL_BILLING_SECRET` | no | — | Reserved for future internal billing; not used in Phase 1 |

**Catalog filter:** Only routes whose `path` equals or starts with a listed prefix (after normalization) become MCP tools. If filtering removes every route, the server **refuses to start**.

---

## Run

Set env vars (or use **`.env`** with your process manager), then start the server.

**With uv (after `uv sync --extra dev`):**

```bash
export BDS_MCP_BASE_URL=https://your-core-api.example
export BDS_MCP_METERING_URL=https://your-metering.example
export BDS_MCP_CATALOG_PATH=/path/to/endpoints.json
uv run bds-mcp-server
# or: uv run python -m bds_mcp_server.server
```

**After `uv tool install .`:**

```bash
export BDS_MCP_BASE_URL=... BDS_MCP_METERING_URL=... BDS_MCP_CATALOG_PATH=...
bds-mcp-server
```

**With pip / plain Python:**

```bash
python -m bds_mcp_server.server
```

The process loads the catalog once at startup, then serves MCP until stopped.

---

## Usage: HTTP transport and auth

This server uses the MCP Python SDK **SSE transport** (see `mcp.server.sse.SseServerTransport`).

1. **Health (no auth)**  
   `GET /health` → JSON such as `{"status":"ok","service":"bds-mcp-server"}`.

2. **SSE session**  
   `GET /sse` with header **`Authorization: Bearer <your_powerloom_api_key>`**.  
   The server validates the key against metering (`GET /credits/balance`) before opening the stream.

3. **Client messages**  
   The SSE stream sends an initial **`endpoint`** event whose **`data`** is the **path + query** (e.g. `/messages/?session_id=...`) where the client must **POST** JSON-RPC MCP messages. **Every POST** to that URL must also send the same **`Authorization: Bearer`** header; the server validates again (with TTL cache).

4. **Upstream BDS calls**  
   For catalog tools, the MCP server forwards the **same Bearer token** to `BDS_MCP_BASE_URL`. Credits are deducted by the **Core API** middleware (Phase 1: no separate deduct in this service).

**Invalid or exhausted credits:** Metering returns **401** or **402**, or balance **≤ 0** → the server rejects the HTTP request with an error body; MCP methods are not executed.

---

## Tools

### Catalog tools (dynamic)

One MCP tool per filtered **`endpoints.json`** route, same naming as local MCP: names typically start with **`bds_`**, derived from path and method. **GET** snapshot routes return JSON via the vendored HTTP client; **SSE** routes collect up to **`max_events`** (default **5**, max **50**) and return `events` plus last known credit header.

### `verify_data_provenance` (fixed)

Parameters: **`cid`**, **`epoch_id`**, **`project_id`**, optional **`data_market`**.  
Requires **`BDS_MCP_POWERLOOM_RPC_URL`** and correct ProtocolState/DataMarket config. If RPC is not set, the tool returns a clear configuration error.

### `get_credit_balance` (fixed)

No parameters. Calls metering **`GET /credits/balance`** with the client’s Bearer token and returns the JSON body (e.g. balance and rate limit fields), depending on your metering API.

---

## Connect from MCP clients

Exact config depends on the client; common fields are:

- **SSE URL:** `https://<your-host>:<port>/sse` (or behind TLS termination / reverse proxy).
- **API key:** Your Powerloom API key as **`Authorization: Bearer`**.

**Claude Desktop / Cursor:** If the product supports **remote MCP over SSE**, add a server entry pointing at **`/sse`** and configure headers for the Bearer token (check the client’s current docs for “remote MCP” or “SSE”).

**LangGraph / OpenClaw / CrewAI:** Use their MCP adapter with the SSE endpoint URL and the same Bearer header model as in [MCP SSE transport docs](https://github.com/modelcontextprotocol/python-sdk) (transport-specific).

**Custom clients:** Implement the MCP client flow: `GET /sse` with Bearer → read SSE `endpoint` → `POST` JSON-RPC to the advertised path with the same Bearer.

---

## Docker

The **`Dockerfile`** uses **pip** against **`pyproject.toml`** (standard slim image). **`uv.lock`** is for local **`uv sync`** / CI; if you need the image to match the lockfile exactly, add a build step such as **`uv pip sync`** from an exported requirements file or use a **uv** base image—same idea as other Python services.

```bash
docker build -t bds-mcp-server .
docker run --env-file .env -p 8808:8808 bds-mcp-server
```

Ensure `.env` sets **`BDS_MCP_BASE_URL`**, **`BDS_MCP_METERING_URL`**, and **`BDS_MCP_CATALOG_PATH` or `BDS_MCP_CATALOG_URL`**. For production, put TLS on a reverse proxy in front of the container; do not expose metering or core secrets in the image.

---

## Operations and troubleshooting

| Symptom | What to check |
|--------|----------------|
| Process exits at startup | Catalog load failed (bad path/URL), or **no endpoints** after path-prefix filter — fix env and catalog |
| **401** on `/sse` or `/messages/` | Missing/wrong **`Authorization: Bearer`**, or metering rejects the key |
| **402** or “balance zero” | Add credits in metering; key is valid but not billable |
| **`verify_data_provenance` errors** | Set **`BDS_MCP_POWERLOOM_RPC_URL`**; verify ProtocolState/DataMarket addresses match the chain |
| Catalog tools return HTTP errors from core | **`BDS_MCP_BASE_URL`** wrong, or key lacks access; check Core API logs |

---

## Development

```bash
uv sync --extra dev
export BDS_MCP_BASE_URL=http://x BDS_MCP_METERING_URL=http://m \
  BDS_MCP_CATALOG_PATH=tests/fixtures/endpoints.minimal.json
uv run pytest tests/ -v
uv run ruff check src tests
```

Equivalent with pip: **`pip install -e ".[dev]"`** then **`pytest`** / **`ruff`** without **`uv run`**.

---

## License

Deploy as its own git repository; license file at repository root when published.
