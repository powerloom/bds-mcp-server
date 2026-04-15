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

After `git pull` or code changes, if **`uv tool install --force .`** still runs old code, run **`uv cache clean`** first, then **`uv tool install --force .`** again (uv may reuse wheels when the version string is unchanged). Editable: **`uv tool install --force --editable .`**.

With pip only:

```bash
pip install ".[dev]"
```

---

## Configuration

All settings use the **`BDS_MCP_`** prefix. Copy **`.env.example`** to **`.env`** and load it in your process manager or `docker run --env-file`.

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `BDS_MCP_BASE_URL` | **yes** | — | **Upstream** Core API origin (same role as **`BDS_BASE_URL`** for `bds-agent`): catalog tools call `GET` here. **Not** the URL of this MCP server. |
| `BDS_MCP_METERING_URL` | **yes** | — | Metering origin; server calls `GET {origin}/credits/balance` |
| `BDS_MCP_CATALOG_PATH` **or** `BDS_MCP_CATALOG_URL` | **yes** (one of) | — | Local filesystem path to `endpoints.json`, or HTTP URL to fetch at startup |
| `BDS_MCP_HOST` | no | `0.0.0.0` | Bind address for **this** MCP server |
| `BDS_MCP_PORT` | no | `8808` | Listen port (`/sse`, `/messages/`, `/health`) |
| `BDS_MCP_CATALOG_PATH_PREFIXES` | no | `/mpp` | Comma-separated path prefixes to **filter** catalog routes; use `all` to disable filtering |
| `BDS_MCP_POWERLOOM_RPC_URL` | no | — | JSON-RPC URL for **`verify_data_provenance`** (`eth_call`) |
| `BDS_MCP_PROTOCOL_STATE_ADDRESS` | no | mainnet BDS default | ProtocolState contract |
| `BDS_MCP_DATA_MARKET_ADDRESS` | no | mainnet BDS default | DataMarket contract |
| `BDS_MCP_AUTH_CACHE_TTL_SECONDS` | no | `60` | Cache successful metering checks (seconds) |
| `BDS_MCP_INTERNAL_BILLING_SECRET` | no | — | Reserved for future internal billing; not used in Phase 1 |

Clients reach **this** MCP server at **`http(s)://<your-host>:<port>`** (or your reverse proxy). That host is **not** `BDS_MCP_BASE_URL` (upstream Core API).

**Reference catalog:** BDS Mainnet Uniswap V3 [`endpoints.json`](https://raw.githubusercontent.com/powerloom/snapshotter-computes/refs/heads/bds_eth_uniswapv3_core/api/endpoints.json) in **snapshotter-computes** — mostly **`/mpp/...` GET** routes; a single **`"sse": true`** entry (**`/mpp/stream/allTrades`**) for the live trade stream. Use that URL as **`BDS_MCP_CATALOG_URL`** or copy the file locally for **`BDS_MCP_CATALOG_PATH`**.

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

One MCP tool per filtered **`endpoints.json`** route, same naming as local MCP: names typically start with **`bds_`**, derived from path and method. Most routes are **GET** snapshots against the Core API; only entries with **`"sse": true`** in the catalog use **SSE** upstream (in the [reference file](https://raw.githubusercontent.com/powerloom/snapshotter-computes/refs/heads/bds_eth_uniswapv3_core/api/endpoints.json) that is **`/mpp/stream/allTrades`** only)—those MCP tools collect up to **`max_events`** (default **5**, max **50**) and return `events` plus last known credit header.

### `verify_data_provenance` (fixed)

Parameters: **`cid`**, **`epoch_id`**, **`project_id`**, optional **`data_market`**.  
Requires **`BDS_MCP_POWERLOOM_RPC_URL`** and correct ProtocolState/DataMarket config. If RPC is not set, the tool returns a clear configuration error.

### `get_credit_balance` (fixed)

No parameters. Calls metering **`GET /credits/balance`** with the client’s Bearer token and returns the JSON body (e.g. balance and rate limit fields), depending on your metering API.

---

## Connect from MCP clients

**`bds-agent` is not this client.** The CLI’s **`bds-agent mcp`** command runs a **stdio** MCP server and talks to the Core API itself. **`bds-mcp-server`** is a **separate process** that listens on HTTP; any **MCP client** that supports **SSE** (or your wrapper) connects to **`/sse`** and sends the same Bearer token your agent would use against the Core API.

**What you need:** the **Powerloom API key** (the same one you use for `bds-agent` / `Authorization: Bearer` against the snapshotter). Put it in the **MCP client’s** config as `Authorization: Bearer <key>` on **both** the SSE GET and the message POSTs.

### Claude Code

Remote MCP is supported; use **`--transport sse`** and **`--header`** for the Bearer token (options must come **before** the server name). Example for a server on localhost:

```bash
claude mcp add --transport sse \
  --header "Authorization: Bearer YOUR_POWERLOOM_API_KEY" \
  bds-mcp-local \
  http://127.0.0.1:8808/sse
```

See Anthropic’s **[Claude Code MCP docs](https://docs.claude.com/en/docs/claude-code/mcp)** for `--scope`, JSON config, and `headersHelper` if you prefer not to paste the key on the command line. Their docs also show **streamable HTTP** transport; this server only implements **SSE** today.

### Claude Desktop / Cursor

If the product supports **remote MCP over SSE**, add a server entry for **`https://<host>:<port>/sse`** and set the **Authorization** header to **`Bearer <key>`** (exact UI varies by version).

### LangGraph / OpenClaw / CrewAI

Use their MCP adapter with the SSE URL and the same Bearer on all requests to this server.

### Quick test (no Claude)

**`scripts/list_mcp_tools.py`** connects to this server’s **`/sse`** using the MCP client’s **HTTP SSE transport** (how Claude/Cursor talk to *this* process). It lists **all** MCP tools—including mostly **GET** catalog tools and any **BDS stream** tool your catalog defines—not “SSE-only” upstream routes.

```bash
cd /path/to/bds-mcp-server
uv sync --extra dev
export BDS_MCP_SSE_API_KEY=your_key
uv run python scripts/list_mcp_tools.py
```

You should see one line per tool name (catalog tools + `verify_data_provenance` + `get_credit_balance`). **`curl http://127.0.0.1:8808/health`** checks the process only; **`GET /sse`** needs a valid Bearer and is easier to verify with this script than raw curl.

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
