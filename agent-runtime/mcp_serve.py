"""
The agent's door into Aperture: a stdio MCP server whose tool list is derived from the
requester's active grants.

    claude mcp add aperture -e APERTURE_REQUESTER=u-newhire-1 -- python agent-runtime/mcp_serve.py

Always present: `request_access`, `my_access`. Everything else appears only while a
grant is active (see mcp_server.tools_for_grants) and is re-checked at call time; a
call without an active grant is logged as a bounced ACTION_EXECUTED and refused. When
the grant set changes the server sends tools/list_changed, so a revoke removes the tool
from the agent's session within seconds.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parents[1]))

from mcp_server import TOOL_SPECS, tools_for_grants  # noqa: E402
from shared.schemas import Grant  # noqa: E402

BACKEND = os.environ.get("APERTURE_BACKEND", "http://127.0.0.1:8000").rstrip("/")
REQUESTER = os.environ.get("APERTURE_REQUESTER", "u-newhire-1")
TOKEN = os.environ.get("APERTURE_TOKEN", "")
PROJECT = os.environ.get("APERTURE_PROJECT", "atlas-migration")
POLL_SECONDS = float(os.environ.get("APERTURE_POLL", "2"))

server = Server("aperture")
_session = None  # captured on first request so the poller can push tools/list_changed
_last_names: set[str] | None = None


def _headers() -> dict[str, str]:
    h = {"content-type": "application/json"}
    if TOKEN:
        h["authorization"] = f"Bearer {TOKEN}"
    return h


async def _get(path: str):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(BACKEND + path, headers=_headers())
        r.raise_for_status()
        return r.json()


async def _post(path: str, body: dict):
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(BACKEND + path, json=body, headers=_headers())
        return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)


async def _active_grants() -> list[Grant]:
    raw = await _get(f"/grants?requester_id={REQUESTER}")
    return [Grant.model_validate(g) for g in raw]


async def _audit(tool: str, grant: Grant | None, ok: bool, detail: str) -> None:
    await _post(
        "/audit",
        {
            "id": "mcp",
            "type": "action_executed",
            "actor": "agent",
            "detail": detail,
            "request_id": grant.request_id if grant else None,
            "grant_id": grant.id if grant else None,
            "payload": {"tool": tool, "status": "ok" if ok else "bounced", "requester_id": REQUESTER},
        },
    )


BASE_TOOLS = [
    types.Tool(
        name="request_access",
        description=(
            "Ask Aperture for task-bounded access. Describe the task in plain language, "
            "including which data you need and until when. Low-risk access is granted in "
            "seconds with an expiry; anything sensitive is escalated to a human. New tools "
            "appear in this server as grants are issued."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "What you are trying to do, and what you need for it."},
                "duration_days": {"type": "integer", "description": "How long you need it (optional)."},
            },
            "required": ["task"],
        },
    ),
    types.Tool(
        name="my_access",
        description="List the grants currently active for this agent, with expiry times.",
        inputSchema={"type": "object", "properties": {}},
    ),
]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    global _session, _last_names
    _session = server.request_context.session
    grants = await _active_grants()
    derived = tools_for_grants(grants)
    tools = list(BASE_TOOLS)
    for t in derived:
        schema: dict = {"type": "object", "properties": {}}
        if t["name"].startswith("bq_"):
            schema["properties"]["sql"] = {"type": "string", "description": "Read-only SQL."}
            schema["required"] = ["sql"]
        tools.append(types.Tool(name=t["name"], description=t["description"], inputSchema=schema))
    _last_names = {t.name for t in tools}
    return tools


def _text(s: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=s)]


async def _request_access(task: str, duration_days: int | None) -> str:
    status, body = await _post("/requests", {"raw_text": task, "requester_id": REQUESTER})
    if status != 200:
        # No Gemini key on this machine: fall back to a keyword match against the catalog.
        resources = await _get("/resources")
        ids = [r["id"] for r in resources if r["name"].replace("-", " ").split()[0].lower() in task.lower().replace("_", "-").replace("-", " ")]
        people = await _get("/people")
        me = next((p for p in people if p["id"] == REQUESTER), {"id": REQUESTER, "name": REQUESTER, "role": "agent", "team": "unknown"})
        status, body = await _post(
            "/requests",
            {"id": "mcp", "requester": me, "task_description": task, "project": PROJECT, "resource_ids": ids, "requested_duration_days": duration_days or 14, "raw_text": task},
        )
        if status != 200:
            return f"Request failed ({status}): {body}"
        note = "parsed locally (no Gemini key)"
    else:
        note = "parsed by Gemini"
    lines = [f"Request {body['request_id'][:8]} · {note}"]
    for r in body["results"]:
        if r["status"] == "granted":
            lines.append(f"  granted   {r['resource_id']} — a tool for it is now in tools/list")
        elif r["status"] == "escalated":
            lines.append(f"  escalated {r['resource_id']} — waiting on a human approver; the tool appears when approved")
        else:
            lines.append(f"  {r['status']:9} {r['resource_id']} — {r.get('reason', '')}")
    return "\n".join(lines)


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    arguments = arguments or {}
    if name == "request_access":
        return _text(await _request_access(str(arguments.get("task", "")), arguments.get("duration_days")))
    if name == "my_access":
        grants = await _active_grants()
        if not grants:
            return _text("No active grants. Call request_access.")
        return _text("\n".join(f"{g.resource_id} · until {g.expires_at.isoformat(timespec='minutes')} · grant {g.id[:8]}" for g in grants))

    # Grant-derived tools: re-check at call time. The list may be stale; the grant is the truth.
    grants = await _active_grants()
    live = {t["name"]: t for t in tools_for_grants(grants)}
    spec = live.get(name)
    if spec is None:
        await _audit(name, None, False, f"{name} · bounced · no active grant")
        return _text(f"Refused: no active grant for {name}. Call request_access to ask for it. (This attempt was recorded.)")
    grant = next(g for g in grants if g.id == spec["grant_id"])
    if name.startswith("gcs_"):
        out = "gs://atlas-analytics-raw/events/2026-09-18.parquet\ngs://atlas-analytics-raw/events/2026-09-19.parquet"
        await _audit(name, grant, True, f"{name} · 2 objects")
    else:
        sql = str(arguments.get("sql", ""))
        out = f"{sql.strip() or 'SELECT COUNT(*)'}\n+-------+\n| 48213 |\n+-------+"
        await _audit(name, grant, True, f"{name} · 1 row")
    return _text(out)


async def _poll_tool_changes() -> None:
    global _last_names
    while True:
        await asyncio.sleep(POLL_SECONDS)
        if _session is None or _last_names is None:
            continue
        try:
            names = {t.name for t in BASE_TOOLS} | {t["name"] for t in tools_for_grants(await _active_grants())}
        except Exception:
            continue
        if names != _last_names:
            _last_names = names
            try:
                await _session.send_tool_list_changed()
            except Exception:
                pass


async def main() -> None:
    async with stdio_server() as (read, write):
        poller = asyncio.create_task(_poll_tool_changes())
        try:
            await server.run(read, write, server.create_initialization_options())
        finally:
            poller.cancel()


if __name__ == "__main__":
    asyncio.run(main())
