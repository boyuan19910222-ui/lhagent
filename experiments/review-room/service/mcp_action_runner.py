#!/usr/bin/env python3
"""Persistent MCP action-loop runner for Review Room P0 tests.

This is intentionally a thin protocol runner. It proves that a connector can
stay alive, call the standard MCP tools, and answer explicit Review Room
actions. It does not run Codex, edit repositories, or perform external effects.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from aiohttp import ClientSession, ClientTimeout
except ModuleNotFoundError:  # pragma: no cover - runtime dependency guard.
    ClientSession = None
    ClientTimeout = None

from review_room_service import MCP_ENCODING_PROBE


RUNNER_NAME = "mcp-action-runner"
DEFAULT_SERVER_URL = "http://127.0.0.1/api/mcp"
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "review-room.sqlite3")
DEFAULT_STATE_DIR = os.path.join(os.path.dirname(__file__), "runner-state")
DEFAULT_ROLES = ("reviewer",)
DEFAULT_POLL_TIMEOUT_MS = 25000
DEFAULT_DISCOVERY_INTERVAL = 2.0
DEFAULT_LIMIT = 20
MCP_PROTOCOL_VERSION = "2025-03-26"


@dataclass(frozen=True)
class ConnectorRecord:
    id: str
    room_id: str
    name: str
    role: str
    token: str
    status: str
    adapter_type: str
    created_at: int
    updated_at: int


@dataclass
class RunnerConfig:
    server_url: str = DEFAULT_SERVER_URL
    db_path: str = DEFAULT_DB_PATH
    state_dir: str = DEFAULT_STATE_DIR
    roles: Tuple[str, ...] = DEFAULT_ROLES
    response_style: str = "diagnostic"
    poll_timeout_ms: int = DEFAULT_POLL_TIMEOUT_MS
    discovery_interval: float = DEFAULT_DISCOVERY_INTERVAL
    limit: int = DEFAULT_LIMIT
    request_timeout_seconds: float = 35.0
    reconnect_delay_seconds: float = 3.0
    client_name: str = RUNNER_NAME
    client_version: str = "0.1.0"


def parse_roles(value: str) -> Tuple[str, ...]:
    roles = tuple(item.strip() for item in value.split(",") if item.strip())
    return roles or DEFAULT_ROLES


def env_config() -> RunnerConfig:
    return RunnerConfig(
        server_url=os.environ.get("REVIEW_ROOM_MCP_SERVER", DEFAULT_SERVER_URL),
        db_path=os.environ.get("REVIEW_ROOM_RUNNER_DB", DEFAULT_DB_PATH),
        state_dir=os.environ.get("REVIEW_ROOM_RUNNER_STATE_DIR", DEFAULT_STATE_DIR),
        roles=parse_roles(os.environ.get("REVIEW_ROOM_RUNNER_ROLES", ",".join(DEFAULT_ROLES))),
        response_style=os.environ.get("REVIEW_ROOM_RUNNER_RESPONSE_STYLE", "diagnostic"),
        poll_timeout_ms=int(os.environ.get("REVIEW_ROOM_RUNNER_POLL_TIMEOUT_MS", str(DEFAULT_POLL_TIMEOUT_MS))),
        discovery_interval=float(os.environ.get("REVIEW_ROOM_RUNNER_DISCOVERY_INTERVAL", str(DEFAULT_DISCOVERY_INTERVAL))),
        limit=int(os.environ.get("REVIEW_ROOM_RUNNER_LIMIT", str(DEFAULT_LIMIT))),
        request_timeout_seconds=float(os.environ.get("REVIEW_ROOM_RUNNER_REQUEST_TIMEOUT", "35")),
        reconnect_delay_seconds=float(os.environ.get("REVIEW_ROOM_RUNNER_RECONNECT_DELAY", "3")),
        client_version=os.environ.get("REVIEW_ROOM_RUNNER_VERSION", "0.1.0"),
    )


def connect_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def discover_connectors(db_path: str, roles: Sequence[str] = DEFAULT_ROLES) -> List[ConnectorRecord]:
    if not os.path.exists(db_path):
        return []
    role_values = tuple(roles) or DEFAULT_ROLES
    placeholders = ",".join("?" for _ in role_values)
    query = """
        SELECT id, room_id, name, agent_role, token, status, adapter_type, created_at, updated_at
        FROM connectors
        WHERE adapter_type = 'mcp-remote'
          AND status != 'revoked'
          AND token != ''
          AND agent_role IN ({})
        ORDER BY created_at ASC
    """.format(placeholders)
    conn = connect_db(db_path)
    try:
        rows = conn.execute(query, role_values).fetchall()
    finally:
        conn.close()
    return [
        ConnectorRecord(
            id=row["id"],
            room_id=row["room_id"],
            name=row["name"],
            role=row["agent_role"],
            token=row["token"],
            status=row["status"],
            adapter_type=row["adapter_type"],
            created_at=int(row["created_at"] or 0),
            updated_at=int(row["updated_at"] or 0),
        )
        for row in rows
    ]


def connector_state_path(state_dir: str, connector_id: str) -> str:
    safe_id = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in connector_id)
    return os.path.join(state_dir, "{}.json".format(safe_id))


def load_connector_state(state_dir: str, connector_id: str) -> Dict[str, Any]:
    path = connector_state_path(state_dir, connector_id)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
            return loaded if isinstance(loaded, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_connector_state(state_dir: str, connector_id: str, state: Dict[str, Any]) -> None:
    os.makedirs(state_dir, exist_ok=True)
    path = connector_state_path(state_dir, connector_id)
    tmp_path = "{}.tmp".format(path)
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, sort_keys=True)
    os.replace(tmp_path, path)


def utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def b64_utf8(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def structured_content(response: Dict[str, Any]) -> Dict[str, Any]:
    result = response.get("result") or {}
    content = result.get("structuredContent")
    if isinstance(content, dict):
        return content
    return result if isinstance(result, dict) else {}


def action_event(action: Dict[str, Any]) -> Dict[str, Any]:
    event = action.get("event")
    return event if isinstance(event, dict) else {}


def action_cursor(action: Dict[str, Any]) -> str:
    event = action_event(action)
    return str(event.get("cursor") or event.get("sequence") or "")


def action_message(action: Dict[str, Any]) -> Dict[str, Any]:
    event = action_event(action)
    message = event.get("message")
    if isinstance(message, dict):
        return message
    payload = event.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("message"), dict):
        return payload["message"]
    return {}


def diagnostic_reply_body(action: Dict[str, Any], record: ConnectorRecord) -> str:
    message_id = action.get("messageId") or action_message(action).get("id") or ""
    cursor = action_cursor(action)
    return (
        "Review Room \u5e38\u9a7b MCP \u6d4b\u8bd5 Agent \u5df2\u6536\u5230\u8fd9\u6761 @{} \u884c\u52a8\u3002\n"
        "- messageId: {}\n"
        "- cursor: {}\n"
        "- time: {}\n"
        "- runner: {}\n"
        "\u8bf4\u660e\uff1a\u6211\u53ea\u9a8c\u8bc1 MCP action-loop \u53ef\u4ee5\u5e38\u9a7b\u6536\u5230 action \u5e76\u56de\u590d\uff1b"
        "\u6211\u4e0d\u6267\u884c\u4efb\u52a1\u3001\u4e0d\u8bbf\u95ee\u4ed3\u5e93\u3001\u4e0d\u4ea7\u751f\u5916\u90e8\u526f\u4f5c\u7528\u3002"
    ).format(record.role, message_id, cursor, utc_now_text(), RUNNER_NAME)


def unsupported_action_body(action: Dict[str, Any], record: ConnectorRecord) -> str:
    kind = action.get("kind") or "unknown"
    task_id = action.get("taskId") or ""
    cursor = action_cursor(action)
    return (
        "Review Room \u5e38\u9a7b MCP \u6d4b\u8bd5 Agent \u6536\u5230 {} action\uff0c"
        "\u4f46\u8fd9\u4e2a runner \u53ea\u505a\u534f\u8bae\u9a8c\u8bc1\uff0c\u4e0d claim \u4efb\u52a1\u3001\u4e0d start_run\u3002\n"
        "- taskId: {}\n"
        "- cursor: {}\n"
        "- runner: {}"
    ).format(kind, task_id, cursor, RUNNER_NAME)


class MpcClient:
    def __init__(self, record: ConnectorRecord, config: RunnerConfig):
        if ClientSession is None or ClientTimeout is None:
            raise RuntimeError("aiohttp is required to run the MCP action runner")
        self.record = record
        self.config = config
        self.session_id = ""
        self._session: Optional[ClientSession] = None

    async def __aenter__(self) -> "MpcClient":
        timeout = ClientTimeout(total=self.config.request_timeout_seconds)
        self._session = ClientSession(timeout=timeout, json_serialize=lambda value: json.dumps(value, ensure_ascii=False))
        return self

    async def __aexit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        if self._session:
            await self._session.close()

    def headers(self, include_session: bool = True) -> Dict[str, str]:
        headers = {
            "Authorization": "Bearer {}".format(self.record.token),
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json; charset=utf-8",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        if include_session and self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    async def json_rpc(self, payload: Dict[str, Any], include_session: bool = True) -> Dict[str, Any]:
        assert self._session is not None
        async with self._session.post(
            self.config.server_url,
            json=payload,
            headers=self.headers(include_session),
        ) as response:
            text = await response.text()
            if response.status >= 400:
                raise RuntimeError("MCP HTTP {}: {}".format(response.status, text))
            session_id = response.headers.get("Mcp-Session-Id")
            if session_id:
                self.session_id = session_id
            return json.loads(text) if text else {}

    async def initialize(self) -> None:
        await self.json_rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": self.config.client_name, "version": self.config.client_version},
                },
            },
            include_session=False,
        )

    async def call_tool(self, request_id: int, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        response = await self.json_rpc(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        return structured_content(response)

    async def connect(self) -> Dict[str, Any]:
        return await self.call_tool(
            2,
            "review_room.connect",
            {
                "roomId": self.record.room_id,
                "encodingProbe": MCP_ENCODING_PROBE,
                "clientName": self.config.client_name,
                "clientVersion": self.config.client_version,
            },
        )

    async def set_status(self, status: str, detail: str = "") -> None:
        await self.call_tool(
            3,
            "review_room.set_status",
            {"roomId": self.record.room_id, "status": status, "detail": detail or "{} waiting for action".format(RUNNER_NAME)},
        )

    async def poll_events(self, cursor: str, limit: int = 200) -> Dict[str, Any]:
        return await self.call_tool(
            4,
            "review_room.poll_events",
            {"roomId": self.record.room_id, "cursor": cursor, "limit": limit},
        )

    async def wait_for_action(self, cursor: str) -> Dict[str, Any]:
        return await self.call_tool(
            5,
            "review_room.wait_for_action",
            {
                "roomId": self.record.room_id,
                "cursor": cursor,
                "timeoutMs": self.config.poll_timeout_ms,
                "limit": self.config.limit,
            },
        )

    async def post_message(self, body: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.call_tool(
            6,
            "review_room.post_message",
            {
                "roomId": self.record.room_id,
                "bodyUtf8Base64": b64_utf8(body),
                "payload": payload,
            },
        )


async def latest_cursor(client: MpcClient) -> str:
    cursor = "0"
    while True:
        result = await client.poll_events(cursor, 200)
        cursor = str(result.get("nextCursor") or cursor)
        if not result.get("hasMore"):
            return cursor


async def handle_action(client: MpcClient, record: ConnectorRecord, action: Dict[str, Any]) -> None:
    kind = action.get("kind") or ""
    cursor = action_cursor(action)
    payload = {
        "runner": RUNNER_NAME,
        "diagnostic": True,
        "actionKind": kind,
        "handledCursor": cursor,
        "sourceEventId": action_event(action).get("id") or "",
    }
    if kind == "reply":
        message = action_message(action)
        message_id = action.get("messageId") or message.get("id") or ""
        payload.update({"replyToMessageId": message_id, "sourceMessageId": message_id})
        await client.post_message(diagnostic_reply_body(action, record), payload)
        return
    if kind in {"claim_or_start_run", "owner_decision"}:
        if action.get("taskId"):
            payload["taskId"] = action.get("taskId")
        if action.get("decisionId"):
            payload["decisionId"] = action.get("decisionId")
        await client.post_message(unsupported_action_body(action, record), payload)


async def run_connector_worker(
    record: ConnectorRecord,
    config: RunnerConfig,
    *,
    skip_backlog: bool = False,
    max_waits: Optional[int] = None,
    stop_after_actions: Optional[int] = None,
) -> int:
    state = load_connector_state(config.state_dir, record.id)
    handled = 0
    waits = 0
    async with MpcClient(record, config) as client:
        await client.initialize()
        await client.connect()
        await client.set_status("mcp_streaming")
        cursor = str(state.get("nextCursor") or "")
        if not cursor:
            cursor = await latest_cursor(client) if skip_backlog else "0"
            state = {**state, "nextCursor": cursor, "initializedAt": utc_now_text(), "skipBacklog": skip_backlog}
            save_connector_state(config.state_dir, record.id, state)

        while True:
            result = await client.wait_for_action(cursor)
            actions = result.get("actions") or []
            for action in actions:
                if isinstance(action, dict):
                    await handle_action(client, record, action)
                    handled += 1
            cursor = str(result.get("nextCursor") or cursor)
            state = {
                **state,
                "nextCursor": cursor,
                "updatedAt": utc_now_text(),
                "lastActionCount": len(actions),
            }
            save_connector_state(config.state_dir, record.id, state)
            await client.set_status("mcp_streaming")
            waits += 1
            if stop_after_actions is not None and handled >= stop_after_actions:
                return handled
            if max_waits is not None and waits >= max_waits:
                return handled


async def run_connector_forever(record: ConnectorRecord, config: RunnerConfig, *, skip_backlog: bool = False) -> None:
    while True:
        try:
            await run_connector_worker(record, config, skip_backlog=skip_backlog)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print("{} connector {} failed: {}".format(RUNNER_NAME, record.id, exc), flush=True)
            await asyncio.sleep(config.reconnect_delay_seconds)
            skip_backlog = False


async def run_manager(config: RunnerConfig) -> None:
    print("{} watching {} roles={} server={}".format(RUNNER_NAME, config.db_path, ",".join(config.roles), config.server_url), flush=True)
    tasks: Dict[str, Tuple[ConnectorRecord, asyncio.Task[None]]] = {}
    initial_scan = True
    while True:
        records = discover_connectors(config.db_path, config.roles)
        current_ids = {record.id for record in records}
        for connector_id, (_record, task) in list(tasks.items()):
            if connector_id not in current_ids:
                task.cancel()
                tasks.pop(connector_id, None)
        for record in records:
            existing = tasks.get(record.id)
            if existing and not existing[1].done() and existing[0].token == record.token:
                continue
            if existing:
                existing[1].cancel()
            skip_backlog = initial_scan and not load_connector_state(config.state_dir, record.id)
            task = asyncio.create_task(run_connector_forever(record, config, skip_backlog=skip_backlog))
            tasks[record.id] = (record, task)
            print("{} started connector {} room={} skip_backlog={}".format(RUNNER_NAME, record.id, record.room_id, skip_backlog), flush=True)
        initial_scan = False
        await asyncio.sleep(config.discovery_interval)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    defaults = env_config()
    parser = argparse.ArgumentParser(description="Run the Review Room MCP action-loop test runner")
    parser.add_argument("--server-url", default=defaults.server_url)
    parser.add_argument("--db", default=defaults.db_path)
    parser.add_argument("--state-dir", default=defaults.state_dir)
    parser.add_argument("--roles", default=",".join(defaults.roles))
    parser.add_argument("--response-style", default=defaults.response_style)
    parser.add_argument("--poll-timeout-ms", type=int, default=defaults.poll_timeout_ms)
    parser.add_argument("--discovery-interval", type=float, default=defaults.discovery_interval)
    parser.add_argument("--limit", type=int, default=defaults.limit)
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> RunnerConfig:
    config = env_config()
    config.server_url = args.server_url
    config.db_path = args.db
    config.state_dir = args.state_dir
    config.roles = parse_roles(args.roles)
    config.response_style = args.response_style
    config.poll_timeout_ms = args.poll_timeout_ms
    config.discovery_interval = args.discovery_interval
    config.limit = args.limit
    return config


def main() -> None:
    asyncio.run(run_manager(config_from_args(parse_args())))


if __name__ == "__main__":
    main()
