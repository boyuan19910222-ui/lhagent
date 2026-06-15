"""Minimal Remote MCP facade for Lighthouse Agent Board.

This module intentionally avoids extra dependencies for the first cut. It
implements the JSON-RPC methods needed by MCP clients over the service's
existing aiohttp app: tools, resources, prompts, and initialize.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List

from aiohttp import web


LOGGER = logging.getLogger(__name__)
PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "lighthouse-review-room", "version": "0.1.0"}
STORE_APP_KEY = web.AppKey("review_room_mcp_store", object)
AFTER_TOOL_APP_KEY = web.AppKey("review_room_mcp_after_tool", object)

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "join_room",
        "title": "Join Agent Board",
        "description": "Join the Lighthouse Agent Board using the bearer invite token and create an agent session.",
        "inputSchema": {
            "type": "object",
            "properties": {"roomId": {"type": "string"}},
            "required": ["roomId"],
        },
    },
    {
        "name": "get_room_snapshot",
        "title": "Get Room Snapshot",
        "description": "Read the current Room, messages, findings, tasks, and connector status.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_room_events",
        "title": "List Room Events",
        "description": "Read incremental Room events after a cursor.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "afterCursor": {"type": "integer"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "wait_room_events",
        "title": "Wait Room Events",
        "description": "Read incremental Room events. The first implementation returns immediately.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "afterCursor": {"type": "integer"},
                "limit": {"type": "integer"},
                "timeoutMs": {"type": "integer"},
            },
        },
    },
    {
        "name": "list_inbox",
        "title": "List Agent Inbox",
        "description": "List unread or active workbench inbox items for this agent.",
        "inputSchema": {
            "type": "object",
            "properties": {"includeHandled": {"type": "boolean"}},
        },
    },
    {
        "name": "ack_event",
        "title": "Acknowledge Inbox Event",
        "description": "Mark an inbox item as read, acked, handled, or ignored.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "inboxItemId": {"type": "string"},
                "cursor": {"type": "integer"},
                "status": {"type": "string", "enum": ["unread", "read", "ack", "handled", "ignored"]},
            },
        },
    },
    {
        "name": "list_tasks",
        "title": "List Tasks",
        "description": "List tasks assigned to this agent or unassigned tasks in the current Room.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "create_task",
        "title": "Create Task",
        "description": "Create explicit executable work on the Agent Board.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "assignedTo": {"type": "string"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "claim_task",
        "title": "Claim Task",
        "description": "Claim an assigned task before working on it.",
        "inputSchema": {
            "type": "object",
            "properties": {"taskId": {"type": "string"}},
            "required": ["taskId"],
        },
    },
    {
        "name": "start_run",
        "title": "Start Agent Run",
        "description": "Start an observable run for a claimed or assigned task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "taskId": {"type": "string"},
                "promptSummary": {"type": "string"},
            },
            "required": ["taskId"],
        },
    },
    {
        "name": "complete_task",
        "title": "Complete Task",
        "description": "Complete an assigned task and finish the current agent run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "taskId": {"type": "string"},
                "finalMessage": {"type": "string"},
                "status": {"type": "string", "enum": ["completed", "failed", "cancelled"]},
            },
            "required": ["taskId"],
        },
    },
    {
        "name": "update_task",
        "title": "Update Task",
        "description": "Legacy compatibility alias. Prefer start_run and complete_task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "taskId": {"type": "string"},
                "status": {"type": "string", "enum": ["assigned", "running", "completed", "failed", "cancelled"]},
                "result": {"type": "string"},
            },
            "required": ["taskId", "status"],
        },
    },
    {
        "name": "post_message",
        "title": "Post Message",
        "description": "Write a real agent reply into the Room timeline.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "body": {"type": "string"},
                "mentions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["body"],
        },
    },
    {
        "name": "post_finding",
        "title": "Post Finding",
        "description": "Create a structured review finding. Reviewer agents should use this for review output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "severity": {"type": "string"},
                "filePath": {"type": "string"},
                "line": {"type": "integer"},
                "claim": {"type": "string"},
                "evidence": {"type": "string"},
                "suggestedFix": {"type": "string"},
            },
            "required": ["claim", "evidence", "suggestedFix"],
        },
    },
    {
        "name": "propose_handoff",
        "title": "Propose Handoff",
        "description": "Propose that a finding should become follow-up work for another agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "findingId": {"type": "string"},
                "targetAgent": {"type": "string"},
                "reason": {"type": "string"},
                "suggestedTask": {"type": "string"},
            },
            "required": ["findingId"],
        },
    },
    {
        "name": "request_owner_confirmation",
        "title": "Request Owner Confirmation",
        "description": "Ask the owner to approve or reject an external side effect.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "reason": {"type": "string"},
                "targetType": {"type": "string"},
                "targetId": {"type": "string"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "heartbeat",
        "title": "Heartbeat",
        "description": "Mark this MCP agent session as alive.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

TOOL_DEFINITIONS.extend(
    [
        {
            **tool,
            "name": "review_room.{}".format(tool["name"]),
            "title": "{} Legacy Alias".format(tool["title"]),
        }
        for tool in list(TOOL_DEFINITIONS)
    ]
)

RESOURCE_DEFINITIONS: List[Dict[str, Any]] = [
    {"uri": "review-room://current/snapshot", "name": "Current Agent Board Snapshot", "mimeType": "application/json"},
    {"uri": "review-room://current/messages", "name": "Current Agent Board Messages", "mimeType": "application/json"},
    {"uri": "review-room://current/findings", "name": "Current Agent Board Findings", "mimeType": "application/json"},
    {"uri": "review-room://current/tasks", "name": "Current Agent Board Tasks", "mimeType": "application/json"},
]

PROMPT_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "review-room-onboarding",
        "title": "Lighthouse Agent Board Onboarding",
        "description": "Operational rules for agents joining a Lighthouse Agent Board.",
    }
]


def bearer_token(request: web.Request) -> str:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return request.query.get("token", "")


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def rpc_response(rpc_id: Any, result: Dict[str, Any]) -> web.Response:
    return web.json_response({"jsonrpc": "2.0", "id": rpc_id, "result": result}, dumps=json_dumps)


def rpc_error(rpc_id: Any, code: int, message: str) -> web.Response:
    return web.json_response({"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}, dumps=json_dumps)


def tool_result(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json_dumps(data)}],
        "structuredContent": data,
    }


def public_room(room: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(room)
    sanitized.pop("ownerToken", None)
    sanitized["connectors"] = [public_connector(connector) for connector in room.get("connectors", [])]
    return sanitized


def public_connector(connector: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(connector)
    sanitized.pop("token", None)
    sanitized.pop("connectorToken", None)
    return sanitized


def onboarding_text() -> str:
    return (
        "你正在接入 Lighthouse Agent Board。先调用 join_room，然后读取 get_room_snapshot。"
        "Workbench 消息都会进入你的 inbox；@ 到你的消息是高优先级且需要回复。"
        "消息本身不是执行权限；分配给你的 task 必须 claim_task 后 start_run，再 complete_task。"
        "所有回复都必须通过 post_message、post_finding 或 request_owner_confirmation 回写到 Agent Board。"
    )


def canonical_tool_name(name: str) -> str:
    if name.startswith("review_room."):
        return name[len("review_room.") :]
    return name


async def handle_mcp_get(_request: web.Request) -> web.StreamResponse:
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await response.prepare(_request)
    await response.write(b'event: endpoint\ndata: {"ok":true,"service":"lighthouse-review-room-mcp"}\n\n')
    await response.write_eof()
    return response


async def handle_mcp_post(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return rpc_error(None, -32700, "invalid json")
    if not isinstance(payload, dict):
        return rpc_error(None, -32600, "json-rpc payload must be an object")

    rpc_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return rpc_error(rpc_id, -32602, "params must be an object")
    if method == "notifications/initialized" and rpc_id is None:
        return web.Response(status=202)

    store = request.app[STORE_APP_KEY]
    token = bearer_token(request)
    try:
        result = await dispatch_rpc(store, token, method, params)
    except PermissionError as exc:
        return rpc_error(rpc_id, -32001, str(exc))
    except KeyError as exc:
        return rpc_error(rpc_id, -32004, str(exc))
    except ValueError as exc:
        return rpc_error(rpc_id, -32602, str(exc))

    if method == "tools/call":
        after_tool = request.app.get(AFTER_TOOL_APP_KEY)
        if after_tool:
            try:
                await after_tool(token, params.get("name") or "", params.get("arguments") or {}, result)
            except Exception:
                LOGGER.exception("Agent Board MCP after_tool hook failed")

    return rpc_response(rpc_id, result)


async def dispatch_rpc(store: Any, token: str, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if method != "notifications/initialized":
        ensure_valid_token(store, token)
    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {},
                "prompts": {},
            },
            "serverInfo": SERVER_INFO,
            "instructions": onboarding_text(),
        }
    if method == "tools/list":
        return {"tools": TOOL_DEFINITIONS}
    if method == "resources/list":
        return {"resources": RESOURCE_DEFINITIONS}
    if method == "prompts/list":
        return {"prompts": PROMPT_DEFINITIONS}
    if method == "prompts/get":
        return prompt_get(params)
    if method == "resources/read":
        identity = store.authenticate_mcp_token(token)
        return resource_read(store, identity, params)
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        return tool_result(await call_tool(store, token, name, arguments))
    raise ValueError("unknown mcp method: {}".format(method))


def ensure_valid_token(store: Any, token: str) -> None:
    if not token:
        raise PermissionError("missing bearer token")
    invite = store.get_mcp_invite_by_token(token)
    if not invite:
        raise PermissionError("invalid bearer token")
    if invite["expiresAt"] < int(time.time() * 1000):
        raise PermissionError("mcp invite expired")


def prompt_get(params: Dict[str, Any]) -> Dict[str, Any]:
    name = params.get("name")
    if name != "review-room-onboarding":
        raise KeyError("prompt not found")
    return {
        "description": "Lighthouse Agent Board agent onboarding instructions",
        "messages": [{"role": "user", "content": {"type": "text", "text": onboarding_text()}}],
    }


def resource_read(store: Any, identity: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    uri = params.get("uri")
    room = public_room(store.get_room(identity["roomId"]) or {})
    if uri == "review-room://current/snapshot":
        data = room
    elif uri == "review-room://current/messages":
        data = {"messages": room.get("messages", [])}
    elif uri == "review-room://current/findings":
        data = {"findings": room.get("findings", [])}
    elif uri == "review-room://current/tasks":
        data = {"tasks": store.list_tasks(identity["roomId"])}
    else:
        raise KeyError("resource not found")
    return {"contents": [{"uri": uri, "mimeType": "application/json", "text": json_dumps(data)}]}


async def call_tool(store: Any, token: str, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    name = canonical_tool_name(name or "")
    if name == "join_room":
        return store.join_mcp_room(token, arguments)

    identity = store.authenticate_mcp_token(token)
    if name == "get_room_snapshot":
        return public_room(store.get_room(identity["roomId"]) or {})
    if name in {"list_room_events", "wait_room_events"}:
        timeout_ms = int(arguments.get("timeoutMs") or 0)
        if timeout_ms > 0:
            await asyncio.sleep(min(timeout_ms, 250) / 1000)
        return {
            "events": store.list_room_events(
                identity["roomId"],
                after_cursor=int(arguments.get("afterCursor") or arguments.get("after_cursor") or 0),
                limit=int(arguments.get("limit") or 100),
            )
        }
    if name == "list_inbox":
        return {
            "items": store.list_inbox(
                identity["roomId"],
                identity["name"],
                include_handled=bool(arguments.get("includeHandled") or arguments.get("include_handled")),
            )
        }
    if name == "ack_event":
        return store.ack_event(
            identity["roomId"],
            {
                **arguments,
                "agentName": identity["name"],
            },
        )
    if name == "list_tasks":
        return {"tasks": store.list_tasks(identity["roomId"], assigned_to=identity["name"])}
    if name == "create_task":
        return store.create_task(
            identity["roomId"],
            {
                "title": arguments.get("title") or "Agent-created task",
                "body": arguments.get("body") or "",
                "assignedTo": arguments.get("assignedTo") or arguments.get("assigned_to") or identity["name"],
                "createdBy": identity["name"],
            },
        )
    if name == "claim_task":
        task_id = arguments.get("taskId") or arguments.get("task_id")
        if not task_id:
            raise ValueError("taskId is required")
        return store.claim_task(task_id, {"agentName": identity["name"]})
    if name == "start_run":
        task_id = arguments.get("taskId") or arguments.get("task_id")
        if not task_id:
            raise ValueError("taskId is required")
        return store.start_run(
            task_id,
            {
                "agentName": identity["name"],
                "connectorId": identity["connectorId"],
                "promptSummary": arguments.get("promptSummary") or arguments.get("prompt_summary") or "",
            },
        )
    if name == "complete_task":
        task_id = arguments.get("taskId") or arguments.get("task_id")
        if not task_id:
            raise ValueError("taskId is required")
        return store.complete_task(
            task_id,
            {
                "agentName": identity["name"],
                "status": arguments.get("status") or "completed",
                "finalMessage": arguments.get("finalMessage") or arguments.get("final_message") or arguments.get("result") or "",
                "error": arguments.get("error") or "",
            },
        )
    if name == "update_task":
        task_id = arguments.get("taskId") or arguments.get("task_id")
        if not task_id:
            raise ValueError("taskId is required")
        status = arguments.get("status")
        if not status:
            raise ValueError("status is required")
        if status in {"completed", "failed", "cancelled"}:
            return store.complete_task(
                task_id,
                {
                    "agentName": identity["name"],
                    "status": status,
                    "finalMessage": arguments.get("result") or arguments.get("finalMessage") or "",
                },
            )
        if status == "running":
            return store.start_run(
                task_id,
                {
                    "agentName": identity["name"],
                    "connectorId": identity["connectorId"],
                    "promptSummary": arguments.get("result") or "",
                },
            )
        return store.update_task(
            task_id,
            {
                "status": status,
                "result": arguments.get("result") or "",
                "agentName": identity["name"],
            },
        )
    if name == "post_message":
        return store.add_message(
            identity["roomId"],
            {
                "senderType": "agent",
                "senderName": identity["name"],
                "kind": "mcp_message",
                "body": arguments.get("body") or "",
                "payload": {"mcp": True, "mentions": arguments.get("mentions") or []},
            },
        )
    if name == "post_finding":
        if identity["role"] != "reviewer":
            raise PermissionError("reviewer role required")
        return store.add_finding(
            identity["roomId"],
            {
                "severity": arguments.get("severity") or "P2",
                "filePath": arguments.get("filePath") or arguments.get("file_path") or "",
                "line": int(arguments["line"]) if arguments.get("line") is not None else None,
                "claim": arguments.get("claim") or "",
                "evidence": arguments.get("evidence") or "",
                "suggestedFix": arguments.get("suggestedFix") or arguments.get("suggested_fix") or "",
                "createdBy": identity["name"],
            },
        )
    if name == "propose_handoff":
        finding_id = arguments.get("findingId") or arguments.get("finding_id")
        if not finding_id:
            raise ValueError("findingId is required")
        return store.propose_handoff(
            finding_id,
            {
                "fromAgent": identity["name"],
                "targetAgent": arguments.get("targetAgent") or arguments.get("target_agent") or "Developer Agent",
                "reason": arguments.get("reason") or "",
                "suggestedTask": arguments.get("suggestedTask") or arguments.get("suggested_task") or "",
            },
        )
    if name == "request_owner_confirmation":
        action = arguments.get("action") or ""
        if not action:
            raise ValueError("action is required")
        return store.request_owner_confirmation(
            identity["roomId"],
            {
                "requester": identity["name"],
                "action": action,
                "reason": arguments.get("reason") or "",
                "targetType": arguments.get("targetType") or arguments.get("target_type") or "",
                "targetId": arguments.get("targetId") or arguments.get("target_id") or "",
            },
        )
    if name == "heartbeat":
        store.mark_connector_seen(identity["connectorId"])
        return {"ok": True, "roomId": identity["roomId"], "agentName": identity["name"]}
    raise ValueError("unknown tool: {}".format(name))
