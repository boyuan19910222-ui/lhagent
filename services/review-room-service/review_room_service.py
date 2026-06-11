#!/usr/bin/env python3
"""Lighthouse Review Room connector service.

The service models the instance-side Review Room backend: rooms, realtime
messages, review findings, connector identities, and owner confirmations.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from aiohttp import web


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8707
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "review-room.sqlite3")


def now_ms() -> int:
    return int(time.time() * 1000)


def make_id(prefix: str) -> str:
    return "{}_{}".format(prefix, uuid.uuid4().hex[:16])


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        super().__exit__(exc_type, exc_value, traceback)
        self.close()


class ReviewRoomStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS rooms (
                  id TEXT PRIMARY KEY,
                  title TEXT NOT NULL,
                  provider TEXT NOT NULL,
                  mr_url TEXT NOT NULL,
                  owner_token TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL,
                  context_json TEXT NOT NULL,
                  participants_json TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                  id TEXT PRIMARY KEY,
                  room_id TEXT NOT NULL,
                  sender_type TEXT NOT NULL,
                  sender_name TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  body TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  FOREIGN KEY(room_id) REFERENCES rooms(id)
                );

                CREATE TABLE IF NOT EXISTS findings (
                  id TEXT PRIMARY KEY,
                  room_id TEXT NOT NULL,
                  severity TEXT NOT NULL,
                  status TEXT NOT NULL,
                  file_path TEXT NOT NULL,
                  line INTEGER,
                  claim TEXT NOT NULL,
                  evidence TEXT NOT NULL,
                  suggested_fix TEXT NOT NULL,
                  created_by TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  FOREIGN KEY(room_id) REFERENCES rooms(id)
                );

                CREATE TABLE IF NOT EXISTS connectors (
                  id TEXT PRIMARY KEY,
                  room_id TEXT NOT NULL,
                  name TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  agent_role TEXT NOT NULL,
                  endpoint TEXT NOT NULL,
                  token TEXT NOT NULL,
                  status TEXT NOT NULL,
                  event_count INTEGER NOT NULL,
                  last_seen_at INTEGER,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  FOREIGN KEY(room_id) REFERENCES rooms(id)
                );
                """
            )
            room_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(rooms)").fetchall()
            }
            if "owner_token" not in room_columns:
                conn.execute("ALTER TABLE rooms ADD COLUMN owner_token TEXT NOT NULL DEFAULT ''")
                for row in conn.execute("SELECT id FROM rooms WHERE owner_token = ''").fetchall():
                    conn.execute(
                        "UPDATE rooms SET owner_token = ? WHERE id = ?",
                        (make_id("rro"), row["id"]),
                    )

    def create_room(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = now_ms()
        participants = payload.get("participants") or [
            {"type": "human", "name": "review room owner", "role": "owner"},
            {"type": "agent", "name": "Reviewer Agent", "role": "reviewer"},
            {"type": "agent", "name": "Developer Agent", "role": "developer"},
        ]
        room = {
            "id": make_id("room"),
            "title": payload.get("title") or "未命名 Review Room",
            "provider": payload.get("provider") or "manual",
            "mrUrl": payload.get("mrUrl") or payload.get("mr_url") or "",
            "ownerToken": payload.get("ownerToken") or payload.get("owner_token") or make_id("rro"),
            "status": payload.get("status") or "open",
            "context": payload.get("context") or {},
            "participants": participants,
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO rooms
                  (id, title, provider, mr_url, owner_token, status, context_json, participants_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    room["id"],
                    room["title"],
                    room["provider"],
                    room["mrUrl"],
                    room["ownerToken"],
                    room["status"],
                    json_dumps(room["context"]),
                    json_dumps(room["participants"]),
                    room["createdAt"],
                    room["updatedAt"],
                ),
            )
        self.add_message(
            room["id"],
            {
                "senderType": "system",
                "senderName": "Lighthouse Review Room",
                "kind": "room_created",
                "body": "Review Room 已创建",
                "payload": {"provider": room["provider"], "mrUrl": room["mrUrl"]},
            },
        )
        return self.get_room(room["id"]) or room

    def list_rooms(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM rooms ORDER BY updated_at DESC").fetchall()
        return [self._room_from_row(row) for row in rows]

    def get_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            room_row = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
            if not room_row:
                return None
            message_rows = conn.execute(
                "SELECT * FROM messages WHERE room_id = ? ORDER BY created_at ASC",
                (room_id,),
            ).fetchall()
            finding_rows = conn.execute(
                "SELECT * FROM findings WHERE room_id = ? ORDER BY created_at ASC",
                (room_id,),
            ).fetchall()
            connector_rows = conn.execute(
                "SELECT * FROM connectors WHERE room_id = ? ORDER BY created_at ASC",
                (room_id,),
            ).fetchall()
        room = self._room_from_row(room_row)
        room["messages"] = [self._message_from_row(row) for row in message_rows]
        room["findings"] = [self._finding_from_row(row) for row in finding_rows]
        room["connectors"] = [self._connector_from_row(row) for row in connector_rows]
        return room

    def add_message(self, room_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.require_room(room_id)
        timestamp = now_ms()
        message = {
            "id": make_id("msg"),
            "roomId": room_id,
            "senderType": payload.get("senderType") or payload.get("sender_type") or "agent",
            "senderName": payload.get("senderName") or payload.get("sender_name") or "unknown",
            "kind": payload.get("kind") or "message",
            "body": payload.get("body") or "",
            "payload": payload.get("payload") or {},
            "createdAt": timestamp,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO messages
                  (id, room_id, sender_type, sender_name, kind, body, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message["id"],
                    room_id,
                    message["senderType"],
                    message["senderName"],
                    message["kind"],
                    message["body"],
                    json_dumps(message["payload"]),
                    timestamp,
                ),
            )
            conn.execute("UPDATE rooms SET updated_at = ? WHERE id = ?", (timestamp, room_id))
        return message

    def add_finding(self, room_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.require_room(room_id)
        timestamp = now_ms()
        finding = {
            "id": make_id("finding"),
            "roomId": room_id,
            "severity": payload.get("severity") or "P2",
            "status": payload.get("status") or "needs_developer_response",
            "filePath": payload.get("filePath") or payload.get("file_path") or "",
            "line": payload.get("line"),
            "claim": payload.get("claim") or "",
            "evidence": payload.get("evidence") or "",
            "suggestedFix": payload.get("suggestedFix") or payload.get("suggested_fix") or "",
            "createdBy": payload.get("createdBy") or payload.get("created_by") or "review-agent",
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO findings
                  (id, room_id, severity, status, file_path, line, claim, evidence, suggested_fix, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    finding["id"],
                    room_id,
                    finding["severity"],
                    finding["status"],
                    finding["filePath"],
                    finding["line"],
                    finding["claim"],
                    finding["evidence"],
                    finding["suggestedFix"],
                    finding["createdBy"],
                    timestamp,
                    timestamp,
                ),
            )
            conn.execute("UPDATE rooms SET updated_at = ? WHERE id = ?", (timestamp, room_id))
        self.add_message(
            room_id,
            {
                "senderType": "agent",
                "senderName": finding["createdBy"],
                "kind": "review_finding",
                "body": finding["claim"],
                "payload": {"findingId": finding["id"], "severity": finding["severity"]},
            },
        )
        return finding

    def update_finding(self, finding_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = now_ms()
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()
            if not row:
                raise KeyError("finding not found")
            status = payload.get("status") or row["status"]
            severity = payload.get("severity") or row["severity"]
            suggested_fix = payload.get("suggestedFix") or payload.get("suggested_fix") or row["suggested_fix"]
            conn.execute(
                """
                UPDATE findings
                SET status = ?, severity = ?, suggested_fix = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, severity, suggested_fix, timestamp, finding_id),
            )
            conn.execute("UPDATE rooms SET updated_at = ? WHERE id = ?", (timestamp, row["room_id"]))
            updated = conn.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()
        return self._finding_from_row(updated)

    def create_demo_session(self) -> Dict[str, Any]:
        room = self.create_room(
            {
                "title": "MR: Review Room 权限边界体验",
                "provider": "demo",
                "mrUrl": "https://git.example.com/lighthouse/review-room-demo/-/merge_requests/18",
                "context": {
                    "source": "demo",
                    "action": "open",
                    "repository": "lighthouse/review-room-demo",
                    "branch": "feature/review-room-connector",
                    "goal": "演示 MR 评审从 finding 到人工确认的闭环",
                },
                "participants": [
                    {"type": "human", "name": "开发者", "role": "owner"},
                    {"type": "agent", "name": "Reviewer Agent", "role": "reviewer"},
                    {"type": "agent", "name": "Developer Agent", "role": "implementer"},
                ],
            }
        )
        self.add_message(
            room["id"],
            {
                "senderType": "system",
                "senderName": "GitLab Webhook Adapter",
                "kind": "mr_webhook",
                "body": "收到 demo MR 更新，已创建 Review Room 并载入变更上下文。",
                "payload": {"repository": "lighthouse/review-room-demo", "action": "open"},
            },
        )
        self.add_finding(
            room["id"],
            {
                "severity": "P1",
                "filePath": "services/review-room-service/review_room_service.py",
                "line": 392,
                "claim": "Webhook 入口缺少 secret 校验，外部请求可能伪造 MR 事件。",
                "evidence": "POST /api/webhooks/merge-request 当前只解析 JSON 并直接创建 Room，没有校验来源签名。",
                "suggestedFix": "为 webhook 增加共享 secret 或签名校验，并在控制面展示校验状态。",
                "createdBy": "Reviewer Agent",
            },
        )
        return self.get_room(room["id"]) or room

    def respond_to_finding(self, finding_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = payload.get("body") or "我会处理这个 finding，并在修复后补充验证结果。"
        sender_name = payload.get("senderName") or payload.get("sender_name") or "Developer Agent"
        updated = self.update_finding(finding_id, {"status": "developer_responded"})
        self.add_message(
            updated["roomId"],
            {
                "senderType": "agent",
                "senderName": sender_name,
                "kind": "developer_response",
                "body": body,
                "payload": {"findingId": finding_id, "nextStatus": "developer_responded"},
            },
        )
        return self.get_finding(finding_id)

    def confirm_finding(self, finding_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        decision = payload.get("decision") or "accepted"
        status = "accepted" if decision == "accepted" else "rejected"
        body = payload.get("body") or ("确认采纳该 finding。" if status == "accepted" else "确认暂不采纳该 finding。")
        sync_target = payload.get("syncTarget") or payload.get("sync_target") or "MR 评论"
        updated = self.update_finding(finding_id, {"status": status})
        self.add_message(
            updated["roomId"],
            {
                "senderType": "human",
                "senderName": payload.get("senderName") or payload.get("sender_name") or "开发者",
                "kind": "human_confirmation",
                "body": body,
                "payload": {"findingId": finding_id, "decision": status},
            },
        )
        self.add_message(
            updated["roomId"],
            {
                "senderType": "system",
                "senderName": "MR Sync Adapter",
                "kind": "mr_sync_preview",
                "body": "已生成{}同步记录：{}。".format(sync_target, body),
                "payload": {"findingId": finding_id, "target": sync_target, "decision": status},
            },
        )
        self.refresh_room_status(updated["roomId"])
        return self.get_finding(finding_id)

    def register_connector(self, room_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.require_room(room_id)
        timestamp = now_ms()
        role = payload.get("role") or payload.get("agentRole") or payload.get("agent_role")
        kind = payload.get("kind") or ("remote-agent" if role == "reviewer" else "local-agent")
        agent_role = role or self.default_agent_role(kind)
        connector = {
            "id": make_id("connector"),
            "roomId": room_id,
            "name": payload.get("name") or self.default_connector_name(kind, agent_role),
            "kind": kind,
            "agentRole": agent_role,
            "endpoint": payload.get("endpoint") or "",
            "token": payload.get("connectorToken") or payload.get("connector_token") or payload.get("token") or make_id("rrc"),
            "status": payload.get("status") or "provisioned",
            "eventCount": 0,
            "lastSeenAt": None,
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        connector["connectorToken"] = connector["token"]
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO connectors
                  (id, room_id, name, kind, agent_role, endpoint, token, status, event_count, last_seen_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    connector["id"],
                    connector["roomId"],
                    connector["name"],
                    connector["kind"],
                    connector["agentRole"],
                    connector["endpoint"],
                    connector["token"],
                    connector["status"],
                    connector["eventCount"],
                    connector["lastSeenAt"],
                    connector["createdAt"],
                    connector["updatedAt"],
                ),
            )
            conn.execute("UPDATE rooms SET updated_at = ? WHERE id = ?", (timestamp, room_id))
        self.add_message(
            room_id,
            {
                "senderType": "system",
                "senderName": "Connector Registry",
                "kind": "connector_registered",
                "body": "{} 已注册为 {} connector。".format(connector["name"], connector["kind"]),
                "payload": {"connectorId": connector["id"], "kind": connector["kind"], "agentRole": connector["agentRole"]},
            },
        )
        return connector

    def ingest_connector_event(self, connector_id: str, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        connector = self.get_connector(connector_id)
        if not token or token != connector["token"]:
            raise PermissionError("invalid connector token")
        event_type = payload.get("type") or "message"
        self.mark_connector_seen(connector_id)
        if event_type == "finding":
            return self.add_finding(
                connector["roomId"],
                {
                    "severity": payload.get("severity") or "P2",
                    "status": payload.get("status") or "needs_developer_response",
                    "filePath": payload.get("filePath") or payload.get("file_path") or "",
                    "line": payload.get("line"),
                    "claim": payload.get("claim") or "",
                    "evidence": payload.get("evidence") or "",
                    "suggestedFix": payload.get("suggestedFix") or payload.get("suggested_fix") or "",
                    "createdBy": payload.get("createdBy") or payload.get("created_by") or connector["name"],
                },
            )
        return self.add_message(
            connector["roomId"],
            {
                "senderType": payload.get("senderType") or payload.get("sender_type") or "agent",
                "senderName": payload.get("senderName") or payload.get("sender_name") or connector["name"],
                "kind": payload.get("kind") or "connector_message",
                "body": payload.get("body") or "",
                "payload": {
                    "connectorId": connector_id,
                    "connectorKind": connector["kind"],
                    "agentRole": connector["agentRole"],
                    "event": payload.get("payload") or {},
                },
            },
        )

    def ingest_merge_request_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        attrs = payload.get("object_attributes") or payload.get("pull_request") or {}
        provider = "gitlab" if "object_attributes" in payload else "github"
        title = attrs.get("title") or payload.get("title") or "MR Review Room"
        url = attrs.get("url") or attrs.get("html_url") or payload.get("url") or ""
        room = self.create_room(
            {
                "title": title,
                "provider": provider,
                "mrUrl": url,
                "context": {
                    "source": "webhook",
                    "action": attrs.get("action") or payload.get("action"),
                    "repository": (payload.get("repository") or {}).get("full_name")
                    or (payload.get("project") or {}).get("path_with_namespace"),
                },
                "participants": [
                    {"type": "human", "name": "开发者", "role": "owner"},
                    {"type": "agent", "name": "Reviewer Agent", "role": "reviewer"},
                    {"type": "agent", "name": "Developer Agent", "role": "implementer"},
                ],
            }
        )
        self.add_message(
            room["id"],
            {
                "senderType": "system",
                "senderName": "Webhook Adapter",
                "kind": "mr_webhook",
                "body": "收到 {} 事件，已进入 Review Room".format(provider),
                "payload": {"raw": payload},
            },
        )
        return self.get_room(room["id"]) or room

    def get_finding(self, finding_id: str) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()
        if not row:
            raise KeyError("finding not found")
        return self._finding_from_row(row)

    def get_connector(self, connector_id: str) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM connectors WHERE id = ?", (connector_id,)).fetchone()
        if not row:
            raise KeyError("connector not found")
        return self._connector_from_row(row)

    def authenticate_room_token(self, room_id: str, token: str) -> Dict[str, Any]:
        if not token:
            raise PermissionError("missing room token")
        with self.connect() as conn:
            room = conn.execute("SELECT id, owner_token FROM rooms WHERE id = ?", (room_id,)).fetchone()
            if not room:
                raise KeyError("room not found")
            if token == room["owner_token"]:
                return {
                    "type": "owner",
                    "roomId": room_id,
                    "name": "review room owner",
                    "role": "owner",
                    "token": token,
                }
            connector = conn.execute(
                "SELECT * FROM connectors WHERE room_id = ? AND token = ?",
                (room_id, token),
            ).fetchone()
        if connector:
            data = self._connector_from_row(connector)
            return {
                "type": "connector",
                "roomId": room_id,
                "connectorId": data["id"],
                "name": data["name"],
                "role": data["agentRole"],
                "kind": data["kind"],
                "token": token,
            }
        raise PermissionError("invalid room token")

    def mark_connector_seen(self, connector_id: str) -> None:
        timestamp = now_ms()
        with self.connect() as conn:
            row = conn.execute("SELECT room_id FROM connectors WHERE id = ?", (connector_id,)).fetchone()
            if not row:
                raise KeyError("connector not found")
            conn.execute(
                """
                UPDATE connectors
                SET status = ?, event_count = event_count + 1, last_seen_at = ?, updated_at = ?
                WHERE id = ?
                """,
                ("connected", timestamp, timestamp, connector_id),
            )
            conn.execute("UPDATE rooms SET updated_at = ? WHERE id = ?", (timestamp, row["room_id"]))

    def refresh_room_status(self, room_id: str) -> None:
        terminal_statuses = {"accepted", "rejected"}
        timestamp = now_ms()
        with self.connect() as conn:
            rows = conn.execute("SELECT status FROM findings WHERE room_id = ?", (room_id,)).fetchall()
            if not rows:
                return
            room_status = "completed" if all(row["status"] in terminal_statuses for row in rows) else "open"
            conn.execute(
                "UPDATE rooms SET status = ?, updated_at = ? WHERE id = ?",
                (room_status, timestamp, room_id),
            )

    def require_room(self, room_id: str) -> None:
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM rooms WHERE id = ?", (room_id,)).fetchone()
        if not row:
            raise KeyError("room not found")

    @staticmethod
    def default_connector_name(kind: str, role: Optional[str] = None) -> str:
        if role == "reviewer" or kind == "remote-agent":
            return "远端 Reviewer Agent"
        if role == "developer":
            return "Developer Agent"
        if kind == "git":
            return "Git Connector"
        return "本地 Developer Agent"

    @staticmethod
    def default_agent_role(kind: str) -> str:
        if kind == "remote-agent":
            return "reviewer"
        if kind == "git":
            return "source"
        return "developer"

    @staticmethod
    def _room_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "roomId": row["id"],
            "title": row["title"],
            "provider": row["provider"],
            "mrUrl": row["mr_url"],
            "ownerToken": row["owner_token"],
            "status": row["status"],
            "context": json_loads(row["context_json"], {}),
            "participants": json_loads(row["participants_json"], []),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "roomId": row["room_id"],
            "senderType": row["sender_type"],
            "senderName": row["sender_name"],
            "kind": row["kind"],
            "body": row["body"],
            "payload": json_loads(row["payload_json"], {}),
            "createdAt": row["created_at"],
        }

    @staticmethod
    def _finding_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "roomId": row["room_id"],
            "severity": row["severity"],
            "status": row["status"],
            "filePath": row["file_path"],
            "line": row["line"],
            "claim": row["claim"],
            "evidence": row["evidence"],
            "suggestedFix": row["suggested_fix"],
            "createdBy": row["created_by"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _connector_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "roomId": row["room_id"],
            "name": row["name"],
            "kind": row["kind"],
            "agentRole": row["agent_role"],
            "endpoint": row["endpoint"],
            "token": row["token"],
            "connectorToken": row["token"],
            "status": row["status"],
            "eventCount": row["event_count"],
            "lastSeenAt": row["last_seen_at"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }


class ReviewRoomHandler(BaseHTTPRequestHandler):
    store: ReviewRoomStore

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self.send_html(index_html())
                return
            if parsed.path == "/health":
                self.send_json({"ok": True, "service": "lighthouse-review-room", "time": now_ms()})
                return
            if parsed.path == "/api/rooms":
                self.send_json({"rooms": self.store.list_rooms()})
                return
            match = re.match(r"^/api/rooms/([^/]+)$", parsed.path)
            if match:
                room = self.store.get_room(match.group(1))
                if not room:
                    self.send_error_json(HTTPStatus.NOT_FOUND, "room not found")
                    return
                self.send_json(room)
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "not found")
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            body = self.read_json()
            if parsed.path == "/api/rooms":
                self.send_json(self.store.create_room(body), HTTPStatus.CREATED)
                return
            if parsed.path == "/api/demo/session":
                self.send_json(self.store.create_demo_session(), HTTPStatus.CREATED)
                return
            if parsed.path == "/api/webhooks/merge-request":
                self.send_json(self.store.ingest_merge_request_webhook(body), HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/rooms/([^/]+)/messages$", parsed.path)
            if match:
                self.send_json(self.store.add_message(match.group(1), body), HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/rooms/([^/]+)/findings$", parsed.path)
            if match:
                self.send_json(self.store.add_finding(match.group(1), body), HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/rooms/([^/]+)/connectors$", parsed.path)
            if match:
                self.send_json(self.store.register_connector(match.group(1), body), HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/connectors/([^/]+)/events$", parsed.path)
            if match:
                self.send_json(
                    self.store.ingest_connector_event(match.group(1), self.read_bearer_token(body), body),
                    HTTPStatus.CREATED,
                )
                return
            match = re.match(r"^/api/findings/([^/]+)/developer-response$", parsed.path)
            if match:
                self.send_json(self.store.respond_to_finding(match.group(1), body), HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/findings/([^/]+)/confirm$", parsed.path)
            if match:
                self.send_json(self.store.confirm_finding(match.group(1), body), HTTPStatus.CREATED)
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "not found")
        except KeyError as exc:
            self.send_error_json(HTTPStatus.NOT_FOUND, str(exc))
        except PermissionError as exc:
            self.send_error_json(HTTPStatus.FORBIDDEN, str(exc))
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_PATCH(self) -> None:
        try:
            parsed = urlparse(self.path)
            body = self.read_json()
            match = re.match(r"^/api/findings/([^/]+)$", parsed.path)
            if match:
                self.send_json(self.store.update_finding(match.group(1), body))
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "not found")
        except KeyError as exc:
            self.send_error_json(HTTPStatus.NOT_FOUND, str(exc))
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.add_cors_headers()
        self.end_headers()

    def read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        if not raw.strip():
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid json: {}".format(exc))
        if not isinstance(value, dict):
            raise ValueError("json body must be an object")
        return value

    def read_bearer_token(self, body: Dict[str, Any]) -> str:
        header = self.headers.get("Authorization") or ""
        if header.lower().startswith("bearer "):
            return header.split(" ", 1)[1].strip()
        return body.get("token") or ""

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json_dumps(data).encode("utf-8")
        self.send_response(status)
        self.add_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_html(self, html: str) -> None:
        raw = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.add_cors_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"ok": False, "error": message}, status)

    def add_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization")

    def log_message(self, fmt: str, *args: Any) -> None:
        print("{} - {}".format(self.address_string(), fmt % args))


class RealtimeHub:
    def __init__(self, store: ReviewRoomStore):
        self.store = store
        self.connections: Dict[str, Dict[web.WebSocketResponse, Dict[str, Any]]] = {}

    async def add(self, room_id: str, websocket: web.WebSocketResponse, identity: Dict[str, Any]) -> None:
        self.connections.setdefault(room_id, {})[websocket] = identity
        await websocket.send_json({"type": "room.snapshot", "room": self.store.get_room(room_id), "identity": identity})
        await self.broadcast(room_id, {"type": "presence.updated", "presence": self.presence(room_id)})

    async def remove(self, room_id: str, websocket: web.WebSocketResponse) -> None:
        room_connections = self.connections.get(room_id)
        if not room_connections:
            return
        room_connections.pop(websocket, None)
        if room_connections:
            await self.broadcast(room_id, {"type": "presence.updated", "presence": self.presence(room_id)})
        else:
            self.connections.pop(room_id, None)

    async def broadcast(self, room_id: str, event: Dict[str, Any]) -> None:
        room_connections = list((self.connections.get(room_id) or {}).keys())
        stale = []
        for websocket in room_connections:
            if websocket.closed:
                stale.append(websocket)
                continue
            await websocket.send_json(event)
        for websocket in stale:
            (self.connections.get(room_id) or {}).pop(websocket, None)

    def presence(self, room_id: str) -> List[Dict[str, Any]]:
        return [
            {"type": identity["type"], "name": identity["name"], "role": identity["role"]}
            for identity in (self.connections.get(room_id) or {}).values()
        ]


STORE_KEY = web.AppKey("store", ReviewRoomStore)
HUB_KEY = web.AppKey("hub", RealtimeHub)


def bearer_token_from_request(request: web.Request) -> str:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return request.query.get("token", "")


async def request_json(request: web.Request) -> Dict[str, Any]:
    if not request.can_read_body:
        return {}
    try:
        data = await request.json()
    except json.JSONDecodeError as exc:
        raise web.HTTPBadRequest(
            text=json_dumps({"ok": False, "error": "invalid json: {}".format(exc)}),
            content_type="application/json",
        )
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(
            text=json_dumps({"ok": False, "error": "json body must be an object"}),
            content_type="application/json",
        )
    return data


def json_response(data: Any, status: int = 200) -> web.Response:
    return web.Response(
        text=json_dumps(data),
        status=status,
        content_type="application/json",
        charset="utf-8",
    )


def room_summary(room: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in room.items() if key != "ownerToken"}


def require_identity(store: ReviewRoomStore, room_id: str, token: str) -> Dict[str, Any]:
    try:
        return store.authenticate_room_token(room_id, token)
    except KeyError as exc:
        raise web.HTTPNotFound(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")
    except PermissionError as exc:
        raise web.HTTPForbidden(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")


def ensure_owner(identity: Dict[str, Any]) -> None:
    if identity["type"] != "owner":
        raise web.HTTPForbidden(text=json_dumps({"ok": False, "error": "owner token required"}), content_type="application/json")


async def handle_ws_event(
    store: ReviewRoomStore,
    hub: RealtimeHub,
    room_id: str,
    identity: Dict[str, Any],
    payload: Dict[str, Any],
    websocket: web.WebSocketResponse,
) -> None:
    event_type = payload.get("type")
    if event_type in {"message.create", "topic.continue"}:
        message = store.add_message(
            room_id,
            {
                "senderType": "human" if identity["type"] == "owner" else "agent",
                "senderName": identity["name"],
                "kind": payload.get("kind") or ("owner_topic" if identity["type"] == "owner" else "connector_message"),
                "body": payload.get("body") or "",
                "payload": {"eventType": event_type, "role": identity["role"]},
            },
        )
        await hub.broadcast(room_id, {"type": "message.created", "message": message})
        return

    if event_type == "finding.create":
        if identity["role"] != "reviewer":
            await websocket.send_json({"type": "error", "error": "reviewer connector required"})
            return
        finding = store.add_finding(
            room_id,
            {
                "severity": payload.get("severity") or "P2",
                "filePath": payload.get("filePath") or payload.get("file_path") or "",
                "line": payload.get("line"),
                "claim": payload.get("claim") or "",
                "evidence": payload.get("evidence") or "",
                "suggestedFix": payload.get("suggestedFix") or payload.get("suggested_fix") or "",
                "createdBy": identity["name"],
            },
        )
        await hub.broadcast(room_id, {"type": "finding.created", "finding": finding})
        return

    if event_type in {"finding.respond", "decision.propose"}:
        if identity["role"] != "developer":
            await websocket.send_json({"type": "error", "error": "developer connector required"})
            return
        finding_id = payload.get("findingId") or payload.get("finding_id")
        if not finding_id:
            await websocket.send_json({"type": "error", "error": "findingId required"})
            return
        finding = store.respond_to_finding(
            finding_id,
            {"senderName": identity["name"], "body": payload.get("body") or "Developer Agent 已响应。"},
        )
        await hub.broadcast(room_id, {"type": "finding.updated", "finding": finding})
        return

    if event_type in {"finding.confirm", "finding.reject"}:
        if identity["type"] != "owner":
            await websocket.send_json({"type": "error", "error": "owner token required"})
            return
        finding_id = payload.get("findingId") or payload.get("finding_id")
        if not finding_id:
            await websocket.send_json({"type": "error", "error": "findingId required"})
            return
        finding = store.confirm_finding(
            finding_id,
            {
                "senderName": identity["name"],
                "decision": payload.get("decision") or ("rejected" if event_type == "finding.reject" else "accepted"),
                "body": payload.get("body") or "",
                "syncTarget": payload.get("syncTarget") or "Review Room decision",
            },
        )
        await hub.broadcast(room_id, {"type": "finding.updated", "finding": finding})
        return

    await websocket.send_json({"type": "error", "error": "unknown event type"})


def build_app(store: Optional[ReviewRoomStore] = None) -> web.Application:
    app = web.Application()
    app[STORE_KEY] = store or ReviewRoomStore(DEFAULT_DB_PATH)
    app[HUB_KEY] = RealtimeHub(app[STORE_KEY])

    async def index(_request: web.Request) -> web.Response:
        return web.Response(text=index_html(), content_type="text/html", charset="utf-8")

    async def health(_request: web.Request) -> web.Response:
        return json_response({"ok": True, "service": "lighthouse-review-room", "time": now_ms()})

    async def list_rooms(_request: web.Request) -> web.Response:
        return json_response({"rooms": [room_summary(room) for room in app[STORE_KEY].list_rooms()]})

    async def create_room(request: web.Request) -> web.Response:
        return json_response(app[STORE_KEY].create_room(await request_json(request)), 201)

    async def demo_session(_request: web.Request) -> web.Response:
        return json_response(app[STORE_KEY].create_demo_session(), 201)

    async def get_room(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        room = app[STORE_KEY].get_room(room_id)
        if not room:
            raise web.HTTPNotFound(text=json_dumps({"ok": False, "error": "room not found"}), content_type="application/json")
        return json_response(room)

    async def register_connector(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        ensure_owner(identity)
        return json_response(app[STORE_KEY].register_connector(room_id, await request_json(request)), 201)

    async def connector_event(request: web.Request) -> web.Response:
        connector_id = request.match_info["connector_id"]
        body = await request_json(request)
        header = request.headers.get("Authorization", "")
        token = header.split(" ", 1)[1].strip() if header.lower().startswith("bearer ") else body.get("token", "")
        try:
            result = app[STORE_KEY].ingest_connector_event(connector_id, token, body)
        except KeyError as exc:
            raise web.HTTPNotFound(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")
        except PermissionError as exc:
            raise web.HTTPForbidden(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")
        await app[HUB_KEY].broadcast(result["roomId"], {"type": "room.snapshot", "room": app[STORE_KEY].get_room(result["roomId"])})
        return json_response(result, 201)

    async def add_message(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        message = app[STORE_KEY].add_message(room_id, await request_json(request))
        await app[HUB_KEY].broadcast(room_id, {"type": "message.created", "message": message})
        return json_response(message, 201)

    async def add_finding(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        finding = app[STORE_KEY].add_finding(room_id, await request_json(request))
        await app[HUB_KEY].broadcast(room_id, {"type": "finding.created", "finding": finding})
        return json_response(finding, 201)

    async def update_finding(request: web.Request) -> web.Response:
        finding = app[STORE_KEY].update_finding(request.match_info["finding_id"], await request_json(request))
        await app[HUB_KEY].broadcast(finding["roomId"], {"type": "finding.updated", "finding": finding})
        return json_response(finding)

    async def developer_response(request: web.Request) -> web.Response:
        finding = app[STORE_KEY].respond_to_finding(request.match_info["finding_id"], await request_json(request))
        await app[HUB_KEY].broadcast(finding["roomId"], {"type": "finding.updated", "finding": finding})
        return json_response(finding, 201)

    async def confirm_finding(request: web.Request) -> web.Response:
        finding = app[STORE_KEY].confirm_finding(request.match_info["finding_id"], await request_json(request))
        await app[HUB_KEY].broadcast(finding["roomId"], {"type": "finding.updated", "finding": finding})
        return json_response(finding, 201)

    async def merge_request_webhook(request: web.Request) -> web.Response:
        return json_response(app[STORE_KEY].ingest_merge_request_webhook(await request_json(request)), 201)

    async def websocket_room(request: web.Request) -> web.WebSocketResponse:
        room_id = request.match_info["room_id"]
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        await app[HUB_KEY].add(room_id, ws, identity)
        try:
            async for message in ws:
                if message.type != web.WSMsgType.TEXT:
                    continue
                try:
                    payload = json.loads(message.data)
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "error": "invalid json"})
                    continue
                if not isinstance(payload, dict):
                    await ws.send_json({"type": "error", "error": "json event must be object"})
                    continue
                try:
                    await handle_ws_event(app[STORE_KEY], app[HUB_KEY], room_id, identity, payload, ws)
                except KeyError as exc:
                    await ws.send_json({"type": "error", "error": str(exc)})
        finally:
            await app[HUB_KEY].remove(room_id, ws)
        return ws

    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/api/rooms", list_rooms)
    app.router.add_post("/api/rooms", create_room)
    app.router.add_post("/api/demo/session", demo_session)
    app.router.add_post("/api/webhooks/merge-request", merge_request_webhook)
    app.router.add_get("/api/rooms/{room_id}", get_room)
    app.router.add_post("/api/rooms/{room_id}/messages", add_message)
    app.router.add_post("/api/rooms/{room_id}/findings", add_finding)
    app.router.add_post("/api/rooms/{room_id}/connectors", register_connector)
    app.router.add_post("/api/connectors/{connector_id}/events", connector_event)
    app.router.add_patch("/api/findings/{finding_id}", update_finding)
    app.router.add_post("/api/findings/{finding_id}/developer-response", developer_response)
    app.router.add_post("/api/findings/{finding_id}/confirm", confirm_finding)
    app.router.add_get("/ws/rooms/{room_id}", websocket_room)
    return app


def index_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Lighthouse Review Room</title>
  <style>
    :root{--bg:#f5f7fb;--panel:#fff;--line:#d9e1ec;--text:#202938;--muted:#647084;--blue:#1663e9;--green:#08745f;--red:#c7362f;--amber:#a05f00}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    button,input,textarea{font:inherit}button{min-height:34px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--text);padding:0 12px;cursor:pointer}
    button.primary{border-color:var(--blue);background:var(--blue);color:#fff}button.success{border-color:var(--green);background:var(--green);color:#fff}button.danger{border-color:var(--red);background:var(--red);color:#fff}
    button:disabled{opacity:.55;cursor:not-allowed}input,textarea{width:100%;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--text);padding:9px 10px}textarea{min-height:88px;resize:vertical}
    header{border-bottom:1px solid var(--line);background:#fff}.shell{max-width:1280px;margin:0 auto;padding:18px}.topbar{display:flex;gap:16px;align-items:flex-start;justify-content:space-between}
    h1{margin:0 0 6px;font-size:24px;line-height:1.2}h2{margin:0;font-size:16px}h3{margin:0;font-size:14px}p{margin:6px 0 0;color:var(--muted);line-height:1.55}code{border-radius:4px;background:#eef3f9;padding:2px 6px}
    .grid{display:grid;grid-template-columns:320px minmax(0,1fr);gap:16px}.panel{border:1px solid var(--line);border-radius:8px;background:var(--panel);min-width:0}.panel-head{display:flex;align-items:center;justify-content:space-between;gap:10px;border-bottom:1px solid var(--line);padding:14px 16px}.panel-body{padding:16px}
    .actions{display:flex;flex-wrap:wrap;gap:8px}.form-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.field{display:grid;gap:6px}.field label{font-size:13px;font-weight:650}.room-list{display:grid;gap:8px}.room-item{width:100%;min-height:76px;text-align:left;padding:10px}.room-item.active{border-color:var(--blue);box-shadow:0 0 0 2px rgba(22,99,233,.12)}
    .tag{display:inline-flex;align-items:center;min-height:22px;border:1px solid var(--line);border-radius:999px;background:#f7f9fc;padding:0 8px;color:var(--muted);font-size:12px}.tag.online{border-color:#98d7c7;background:#eefaf6;color:var(--green)}.tag.p1{border-color:#f2aaa6;background:#fff1f0;color:var(--red)}.tag.waiting{border-color:#ecc77e;background:#fff8e8;color:var(--amber)}
    .role-row{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.role{border:1px solid var(--line);border-radius:8px;background:#fbfcfe;padding:12px}.chat-layout{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:16px}.timeline,.finding-list{display:grid;gap:10px}.message,.finding{border:1px solid var(--line);border-radius:8px;background:#fff;padding:12px}.message.owner{background:#edf4ff}.message.agent{background:#fbfcfe}.message-head,.finding-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px}.body{white-space:pre-wrap;line-height:1.55}.finding-title{font-weight:700}.finding-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}.empty{border:1px dashed var(--line);border-radius:8px;padding:24px 14px;text-align:center;color:var(--muted)}.notice{margin-top:10px;color:var(--muted);font-size:13px}.hidden{display:none}
    @media(max-width:960px){.grid,.chat-layout,.form-grid,.role-row{grid-template-columns:1fr}.topbar{display:grid}}
  </style>
</head>
<body>
  <header>
    <div class="shell topbar">
      <div>
        <h1>Lighthouse Review Room</h1>
        <p>纯 Review Room 产品能力：review room owner 通过 WebSocket 监督 Reviewer Agent 与 Developer Agent 的代码评审协作。</p>
      </div>
      <div class="actions">
        <button id="refreshRooms">刷新房间</button>
        <button class="primary" id="createRoom">创建真实 Room</button>
        <button id="createDemo">创建体验房间</button>
      </div>
    </div>
  </header>
  <main class="shell">
    <section class="panel">
      <div class="panel-body">
        <h2>代码评审房间</h2>
        <div class="form-grid">
          <div class="field"><label>Room 标题</label><input id="roomTitle" value="MR: WebSocket Review Room"></div>
          <div class="field"><label>仓库</label><input id="roomRepo" value="lighthouse/review-room"></div>
          <div class="field"><label>MR 地址</label><input id="roomMr" value="https://git.example.com/lighthouse/review-room/-/merge_requests/1"></div>
        </div>
        <p class="notice">REST: <code>POST /api/rooms</code>、<code>POST /api/rooms/{roomId}/connectors</code>、<code>POST /api/connectors/{connectorId}/events</code>、<code>/api/demo/session</code>。Realtime: <code>/ws/rooms/{roomId}?token=...</code> via <code>new WebSocket</code>。</p>
      </div>
    </section>
    <div class="grid" style="margin-top:16px">
      <aside class="panel">
        <div class="panel-head"><h2>Review Rooms</h2><span class="tag" id="roomCount">0</span></div>
        <div class="panel-body"><div class="room-list" id="roomList"></div></div>
      </aside>
      <section class="panel">
        <div class="panel-head">
          <div><h2 id="detailTitle">选择或创建房间</h2><p id="detailMeta">owner token 会保存在本机浏览器 localStorage。</p></div>
          <span class="tag" id="socketState">未连接</span>
        </div>
        <div class="panel-body" id="detailBody"><div class="empty">还没有可展示的 Room。</div></div>
      </section>
    </div>
  </main>
  <script>
    const state = { rooms: [], room: null, ws: null, tokens: JSON.parse(localStorage.getItem('reviewRoomOwnerTokens') || '{}') };
    const statusText = { open: '进行中', completed: '已完成', needs_developer_response: '等待 Developer Agent', developer_responded: '等待 owner 确认', accepted: '已确认', rejected: '已驳回' };
    function saveTokens(){ localStorage.setItem('reviewRoomOwnerTokens', JSON.stringify(state.tokens)); }
    function esc(v){ return String(v ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;'); }
    async function api(path, options={}){
      const res = await fetch(path, options);
      const data = await res.json();
      if(!res.ok) throw new Error(data.error || res.statusText);
      return data;
    }
    function authHeaders(roomId){ return { 'Content-Type':'application/json', Authorization:`Bearer ${state.tokens[roomId] || ''}` }; }
    function roleStatus(role){
      const found = ((state.room && state.room.connectors) || []).find(c => c.agentRole === role);
      return found ? `${found.name} · token ready` : '未注册';
    }
    async function loadRooms(){
      const data = await api('/api/rooms');
      state.rooms = data.rooms || [];
      document.getElementById('roomCount').textContent = `${state.rooms.length} 个`;
      renderRooms();
    }
    function renderRooms(){
      const list = document.getElementById('roomList');
      if(!state.rooms.length){ list.innerHTML = '<div class="empty">暂无房间</div>'; return; }
      list.innerHTML = state.rooms.map(room => `
        <button class="room-item ${state.room && state.room.id === room.id ? 'active' : ''}" data-room="${esc(room.id)}">
          <strong>${esc(room.title)}</strong>
          <p>${esc((room.context && room.context.repository) || room.mrUrl || room.provider)}</p>
        </button>`).join('');
      list.querySelectorAll('[data-room]').forEach(btn => btn.addEventListener('click', () => selectRoom(btn.dataset.room)));
    }
    async function createRoom(){
      const room = await api('/api/rooms', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
        title: document.getElementById('roomTitle').value || 'MR: Review Room',
        provider: 'lighthouse',
        mrUrl: document.getElementById('roomMr').value,
        context: { repository: document.getElementById('roomRepo').value, goal: 'WebSocket 多 Agent 代码评审协作' }
      })});
      state.tokens[room.id] = room.ownerToken;
      saveTokens();
      await loadRooms();
      await selectRoom(room.id);
    }
    async function createDemo(){
      const room = await api('/api/demo/session', { method:'POST', headers:{'Content-Type':'application/json'}, body:'{}' });
      state.tokens[room.id] = room.ownerToken;
      saveTokens();
      await loadRooms();
      await selectRoom(room.id);
    }
    async function selectRoom(roomId){
      const token = state.tokens[roomId];
      if(!token){ renderMissingToken(roomId); return; }
      state.room = await api(`/api/rooms/${encodeURIComponent(roomId)}`, { headers:{ Authorization:`Bearer ${token}` } });
      renderRooms();
      renderDetail();
      connectSocket();
    }
    function renderMissingToken(roomId){
      state.room = null;
      document.getElementById('detailTitle').textContent = roomId;
      document.getElementById('detailBody').innerHTML = '<div class="empty">本机没有这个房间的 owner token，无法进入。</div>';
    }
    async function registerConnector(role){
      if(!state.room) return;
      const name = role === 'reviewer' ? 'Reviewer Agent' : 'Developer Agent';
      await api(`/api/rooms/${encodeURIComponent(state.room.id)}/connectors`, {
        method:'POST',
        headers: authHeaders(state.room.id),
        body: JSON.stringify({ role, name })
      });
      await selectRoom(state.room.id);
    }
    function connectSocket(){
      if(!state.room) return;
      if(state.ws) state.ws.close();
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      state.ws = new WebSocket(`${proto}//${location.host}/ws/rooms/${encodeURIComponent(state.room.id)}?token=${encodeURIComponent(state.tokens[state.room.id])}`);
      state.ws.onopen = () => document.getElementById('socketState').textContent = '实时连接';
      state.ws.onclose = () => document.getElementById('socketState').textContent = '已断开';
      state.ws.onmessage = event => handleSocketEvent(JSON.parse(event.data));
    }
    function sendSocket(event){ if(state.ws && state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify(event)); }
    function handleSocketEvent(event){
      if(event.type === 'room.snapshot'){ state.room = event.room; renderDetail(); return; }
      if(event.type === 'message.created'){ state.room.messages.push(event.message); renderDetail(); return; }
      if(event.type === 'finding.created'){ state.room.findings.push(event.finding); renderDetail(); return; }
      if(event.type === 'finding.updated'){
        state.room.findings = state.room.findings.map(f => f.id === event.finding.id ? event.finding : f);
        renderDetail();
      }
    }
    function renderDetail(){
      const room = state.room;
      if(!room) return;
      document.getElementById('detailTitle').textContent = room.title;
      document.getElementById('detailMeta').textContent = `${(room.context && room.context.repository) || '未绑定仓库'} · ${room.mrUrl || '无 MR 地址'}`;
      const messages = room.messages || [];
      const findings = room.findings || [];
      document.getElementById('detailBody').innerHTML = `
        <div class="role-row">
          <div class="role"><h3>review room owner</h3><p>Web 端监督者 · owner token</p><span class="tag online">online</span></div>
          <div class="role"><h3>Reviewer Agent</h3><p>${esc(roleStatus('reviewer'))}</p><button data-role="reviewer">注册远端 Agent Connector</button></div>
          <div class="role"><h3>Developer Agent</h3><p>${esc(roleStatus('developer'))}</p><button data-role="developer">注册本地 Agent Connector</button></div>
        </div>
        <div class="chat-layout" style="margin-top:16px">
          <div>
            <h2>聊天室</h2>
            <div class="timeline">${messages.length ? messages.map(renderMessage).join('') : '<div class="empty">暂无消息</div>'}</div>
            <div class="field" style="margin-top:12px"><label>owner 发起话题</label><textarea id="topicInput">请评审这个 MR 的鉴权风险，并给出可执行修复建议。</textarea></div>
            <div class="actions" style="margin-top:8px"><button class="primary" id="sendTopic">发送话题</button></div>
          </div>
          <div>
            <h2>Finding / Decision</h2>
            <div class="finding-list">${findings.length ? findings.map(renderFinding).join('') : '<div class="empty">暂无 Finding / Decision</div>'}</div>
          </div>
        </div>`;
      document.querySelectorAll('[data-role]').forEach(btn => btn.addEventListener('click', () => registerConnector(btn.dataset.role)));
      document.getElementById('sendTopic').addEventListener('click', () => sendSocket({ type:'message.create', body:document.getElementById('topicInput').value }));
      document.querySelectorAll('[data-confirm]').forEach(btn => btn.addEventListener('click', () => sendSocket({ type:'finding.confirm', findingId:btn.dataset.confirm, decision:'accepted', body:'确认该修复方向。' })));
      document.querySelectorAll('[data-reject]').forEach(btn => btn.addEventListener('click', () => sendSocket({ type:'finding.reject', findingId:btn.dataset.reject, decision:'rejected', body:'驳回该结论，请继续讨论。' })));
    }
    function renderMessage(message){
      const cls = message.senderType === 'human' ? 'owner' : 'agent';
      return `<article class="message ${cls}"><div class="message-head"><h3>${esc(message.senderName)}</h3><span class="tag">${esc(message.kind)}</span></div><div class="body">${esc(message.body)}</div></article>`;
    }
    function renderFinding(finding){
      const canConfirm = finding.status === 'developer_responded';
      return `<article class="finding"><div class="finding-head"><span class="tag p1">${esc(finding.severity)}</span><span class="tag waiting">${esc(statusText[finding.status] || finding.status)}</span></div><div class="finding-title">${esc(finding.claim)}</div><p>${esc(finding.evidence)}</p><p><strong>建议：</strong>${esc(finding.suggestedFix)}</p><div class="finding-actions"><button class="success" data-confirm="${esc(finding.id)}" ${canConfirm ? '' : 'disabled'}>人工确认并同步</button><button class="danger" data-reject="${esc(finding.id)}" ${canConfirm ? '' : 'disabled'}>驳回并继续讨论</button><button disabled>Developer Agent 回复</button></div></article>`;
    }
    document.getElementById('createRoom').addEventListener('click', () => createRoom().catch(alert));
    document.getElementById('createDemo').addEventListener('click', () => createDemo().catch(alert));
    document.getElementById('refreshRooms').addEventListener('click', () => loadRooms().catch(alert));
    loadRooms().catch(alert);
  </script>
</body>
</html>"""


def build_handler(store: ReviewRoomStore):
    class Handler(ReviewRoomHandler):
        pass

    Handler.store = store
    return Handler


def run_server(host: str, port: int, db_path: str) -> None:
    store = ReviewRoomStore(db_path)
    print(
        "Lighthouse Review Room listening on http://{}:{} db={} websocket=/ws/rooms/<room_id>".format(
            host,
            port,
            db_path,
        ),
        flush=True,
    )
    web.run_app(build_app(store), host=host, port=port, print=None)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lighthouse Review Room connector service")
    parser.add_argument("--host", default=os.environ.get("REVIEW_ROOM_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("REVIEW_ROOM_PORT", DEFAULT_PORT)))
    parser.add_argument("--db", default=os.environ.get("REVIEW_ROOM_DB", DEFAULT_DB_PATH))
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    run_server(args.host, args.port, args.db)


if __name__ == "__main__":
    main()
