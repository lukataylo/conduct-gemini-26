"""
The agent's door into Aperture: a stdio MCP server whose tool list is derived from the
requester's active grants.

    claude mcp add aperture -e APERTURE_REQUESTER=u-newhire-1 -- python agent-runtime/mcp_serve.py

Always present: `request_access`, `my_access`. Every other tool is gated by a grant
(see mcp_server.tools_for_grants), re-checked at call time; a call without an active
grant is logged as a bounced ACTION_EXECUTED and refused. By default (STATIC_TOOLS) the
whole catalog is listed from the start, because Claude Code ignores tools/list_changed;
with APERTURE_STATIC_TOOLS=0 tools appear/vanish with grants and the server sends
tools/list_changed for clients that honour it.
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
TICKET = os.environ.get("APERTURE_TICKET", "ATLAS-142")  # the engine refuses requests with no ticket/incident
POLL_SECONDS = float(os.environ.get("APERTURE_POLL", "2"))
# Claude Code 2.1.x ignores tools/list_changed (anthropics/claude-code#77314), so a tool that
# appears after an approval is invisible until the session restarts. With STATIC_TOOLS the
# full catalog is listed from the start and every call is gated by the grant at call time —
# the same check as before, the audit bounce is the visible beat. Set to 0 for clients that
# honour list_changed (MCP Inspector, Pydantic AI) to get the appear/vanish behaviour.
STATIC_TOOLS = os.environ.get("APERTURE_STATIC_TOOLS", "1") not in ("0", "false", "")

server = Server("aperture")
_session = None  # captured on first request so the poller can push tools/list_changed
_last_names: set[str] | None = None


def _headers() -> dict[str, str]:
    h = {"content-type": "application/json"}
    if TOKEN:
        h["authorization"] = f"Bearer {TOKEN}"
        h["x-demo-key"] = TOKEN  # the hub's write guard (DEMO_KEY) — same secret tonight
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


async def _pending_for(resource_id: str) -> list[str]:
    """Approver ids still to vote on a pending case for this requester + resource, or []."""
    try:
        cases = await _get("/escalations")
    except Exception:
        return []
    for c in cases:
        if c.get("requester_id") == REQUESTER and c.get("resource_id") == resource_id and c.get("status") == "pending":
            voted = {v["approver_id"] for v in c.get("votes", [])}
            return [a for a in c.get("required_approver_ids", []) if a not in voted] or c.get("required_approver_ids", [])
    return []


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
    tools = list(BASE_TOOLS)
    if STATIC_TOOLS:
        held = {t["resource_id"]: t for t in tools_for_grants(grants)}
        for rid, spec in TOOL_SPECS.items():
            live = held.get(rid)
            desc = (
                live["description"]
                if live
                else spec["description"].split(". Only while")[0]
                + f". Needs an active Aperture grant for {rid}: without one the call is refused and recorded. Ask via request_access."
            )
            tools.append(types.Tool(name=spec["name"], description=desc, inputSchema=_schema_for(spec["name"])))
    else:
        for t in tools_for_grants(grants):
            tools.append(types.Tool(name=t["name"], description=t["description"], inputSchema=_schema_for(t["name"])))
    _last_names = {t.name for t in tools}
    return tools


def _schema_for(name: str) -> dict:
    schema: dict = {"type": "object", "properties": {}}
    if name.startswith("bq_"):
        schema["properties"]["sql"] = {"type": "string", "description": "Read-only SQL."}
        schema["required"] = ["sql"]
    return schema


def _text(s: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=s)]


async def _request_access(task: str, duration_days: int | None) -> str:
    status, body = await _post("/requests", {"raw_text": task, "requester_id": REQUESTER, "context": {"active_jira_ticket": TICKET}})
    if status != 200:
        # No Gemini key on this machine: fall back to a keyword match against the catalog.
        resources = await _get("/resources")
        ids = [r["id"] for r in resources if r["name"].replace("-", " ").split()[0].lower() in task.lower().replace("_", "-").replace("-", " ")]
        people = await _get("/people")
        me = next((p for p in people if p["id"] == REQUESTER), {"id": REQUESTER, "name": REQUESTER, "role": "agent", "team": "unknown"})
        status, body = await _post(
            "/requests",
            {"id": "mcp", "requester": me, "task_description": task, "project": PROJECT, "resource_ids": ids, "requested_duration_days": duration_days or 14, "raw_text": task, "context": {"active_jira_ticket": TICKET}},
        )
        if status != 200:
            return f"Request failed ({status}): {body}"
        note = "parsed locally (no Gemini key)"
    else:
        note = "parsed by Gemini"
    lines = [f"Request {body['request_id'][:8]} · {note}"]
    for r in body["results"]:
        if r["status"] == "granted":
            lines.append(f"  granted   {r['resource_id']} — its tool now works")
        elif r["status"] == "escalated":
            lines.append(f"  escalated {r['resource_id']} — waiting on a human approver; its tool works once approved")
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
        rid = next((r for r, s in TOOL_SPECS.items() if s["name"] == name), name)
        pending = await _pending_for(rid)
        hint = f"An approval for {rid} is pending with {', '.join(pending)} — try again once it is approved." if pending else "Call request_access to ask for it."
        return _text(f"Refused: no active grant for {name}. {hint} (This attempt was recorded.)")
    grant = next(g for g in grants if g.id == spec["grant_id"])
    if name.startswith("gcs_"):
        out = "gs://atlas-analytics-raw/events/2026-09-18.parquet\ngs://atlas-analytics-raw/events/2026-09-19.parquet"
        await _audit(name, grant, True, f"{name} · 2 objects")
    elif name.startswith("gh_"):
        repo = spec["resource_id"].removeprefix("repo-")
        out = f"{repo}: main @ 3f9a2c1\n  README.md\n  pipeline/ingest.py\n  pipeline/schema.sql"
        await _audit(name, grant, True, f"{name} · main @ 3f9a2c1")
    else:
        sql = str(arguments.get("sql", ""))
        out = f"{sql.strip() or 'SELECT COUNT(*)'}\n+-------+\n| 48213 |\n+-------+"
        await _audit(name, grant, True, f"{name} · 1 row")
    return _text(out)


async def _poll_tool_changes() -> None:
    global _last_names
    while True:
        await asyncio.sleep(POLL_SECONDS)
        if STATIC_TOOLS or _session is None or _last_names is None:
            continue  # static listing never changes; the grant check happens at call time
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
