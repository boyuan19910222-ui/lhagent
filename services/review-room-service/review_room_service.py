#!/usr/bin/env python3
"""Lighthouse Review Room connector service.

This service is intentionally dependency-free so it can run on a fresh
Lighthouse instance with only Python installed. It models the instance-side
connector/relay: rooms, messages, review findings, and webhook ingestion.
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

    def create_room(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = now_ms()
        room = {
            "id": make_id("room"),
            "title": payload.get("title") or "未命名 Review Room",
            "provider": payload.get("provider") or "manual",
            "mrUrl": payload.get("mrUrl") or payload.get("mr_url") or "",
            "status": payload.get("status") or "open",
            "context": payload.get("context") or {},
            "participants": payload.get("participants") or [],
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO rooms
                  (id, title, provider, mr_url, status, context_json, participants_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    room["id"],
                    room["title"],
                    room["provider"],
                    room["mrUrl"],
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
        kind = payload.get("kind") or "local-agent"
        connector = {
            "id": make_id("connector"),
            "roomId": room_id,
            "name": payload.get("name") or self.default_connector_name(kind),
            "kind": kind,
            "agentRole": payload.get("agentRole") or payload.get("agent_role") or self.default_agent_role(kind),
            "endpoint": payload.get("endpoint") or "",
            "token": payload.get("token") or make_id("rrc"),
            "status": payload.get("status") or "provisioned",
            "eventCount": 0,
            "lastSeenAt": None,
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
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
    def default_connector_name(kind: str) -> str:
        if kind == "remote-agent":
            return "远端 Reviewer Agent"
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
            "title": row["title"],
            "provider": row["provider"],
            "mrUrl": row["mr_url"],
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


def index_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Lighthouse Review Room</title>
  <style>
    :root {
      --bg: #f4f6f8;
      --panel: #ffffff;
      --line: #d8dee8;
      --text: #1f2933;
      --muted: #5c6675;
      --blue: #1464e9;
      --green: #0b8063;
      --red: #c7352f;
      --amber: #a36300;
      --ink: #111827;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    button, textarea, input, select { font: inherit; }
    button {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      cursor: pointer;
      min-height: 34px;
      padding: 0 12px;
    }
    button.primary { border-color: var(--blue); background: var(--blue); color: #fff; }
    button.success { border-color: var(--green); background: var(--green); color: #fff; }
    button:disabled { cursor: not-allowed; opacity: .55; }
    header {
      border-bottom: 1px solid var(--line);
      background: #fff;
    }
    .shell { max-width: 1280px; margin: 0 auto; padding: 20px; }
    .topbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
    h1 { margin: 0 0 6px; color: var(--ink); font-size: 24px; line-height: 1.25; }
    h2 { margin: 0; color: var(--ink); font-size: 16px; }
    h3 { margin: 0; color: var(--ink); font-size: 14px; }
    p { margin: 6px 0 0; color: var(--muted); line-height: 1.6; }
    code { border-radius: 4px; background: #eef2f7; padding: 2px 6px; color: #243042; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
    .layout {
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      gap: 16px;
      padding-top: 16px;
    }
    .panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      min-width: 0;
    }
    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      border-bottom: 1px solid var(--line);
      padding: 14px 16px;
    }
    .panel-body { padding: 16px; }
    .room-list { display: grid; gap: 8px; }
    .room-item {
      width: 100%;
      min-height: 88px;
      padding: 12px;
      text-align: left;
      background: #fff;
    }
    .room-item.active { border-color: var(--blue); box-shadow: 0 0 0 2px rgba(20,100,233,.12); }
    .room-title { display: block; overflow: hidden; color: var(--ink); font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
    .room-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .tag {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #f7f9fc;
      padding: 0 8px;
      color: var(--muted);
      font-size: 12px;
    }
    .tag.open { border-color: #91b8ff; background: #edf4ff; color: #174ea6; }
    .tag.completed { border-color: #9ed9c9; background: #eefaf6; color: var(--green); }
    .tag.p1 { border-color: #f0aaa6; background: #fff1f0; color: var(--red); }
    .tag.waiting { border-color: #e8c27a; background: #fff7e8; color: var(--amber); }
    .empty {
      border: 1px dashed var(--line);
      border-radius: 8px;
      padding: 28px 16px;
      color: var(--muted);
      text-align: center;
    }
    .detail-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(320px, .9fr);
      gap: 16px;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfe;
      padding: 12px;
    }
    .metric strong { display: block; margin-top: 4px; color: var(--ink); font-size: 18px; }
    .finding, .message {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 14px;
      margin-top: 10px;
    }
    .finding-head, .message-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 8px;
    }
    .finding-title { color: var(--ink); font-weight: 650; line-height: 1.45; }
    .finding-path { margin-top: 8px; color: var(--muted); font-size: 13px; }
    .finding-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .message { background: #fbfcfe; }
    .message-body { color: var(--text); line-height: 1.6; white-space: pre-wrap; }
    textarea, input, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      padding: 9px 10px;
    }
    textarea { min-height: 76px; resize: vertical; }
    .form-row { display: grid; gap: 8px; margin-top: 12px; }
    .control-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 14px;
    }
    .field { display: grid; gap: 6px; }
    .field label { color: var(--ink); font-size: 13px; font-weight: 650; }
    .field small { color: var(--muted); line-height: 1.45; }
    .connector-list { display: grid; gap: 10px; margin-top: 10px; }
    .connector-section { margin-bottom: 16px; }
    .connector-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 12px;
      min-width: 0;
    }
    .connector-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .connector-command {
      display: block;
      margin-top: 8px;
      max-width: 100%;
      overflow-x: auto;
      white-space: nowrap;
      font-size: 12px;
    }
    .flow {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-top: 14px;
    }
    .step {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 12px;
      min-height: 96px;
    }
    .step b { display: block; color: var(--ink); font-size: 13px; }
    .step span { display: block; margin-top: 6px; color: var(--muted); font-size: 12px; line-height: 1.5; }
    .toast {
      position: fixed;
      right: 18px;
      bottom: 18px;
      max-width: min(420px, calc(100vw - 36px));
      border: 1px solid #b8d2ff;
      border-radius: 8px;
      background: #edf4ff;
      padding: 12px 14px;
      color: #174ea6;
      box-shadow: 0 12px 30px rgba(15, 23, 42, .16);
    }
    .hidden { display: none; }
    @media (max-width: 960px) {
      .layout, .detail-grid, .summary, .flow, .control-grid { grid-template-columns: 1fr; }
      .topbar { display: grid; }
      .actions { justify-content: flex-start; }
    }
  </style>
</head>
<body>
  <header>
    <div class="shell topbar">
      <div>
        <h1>Lighthouse Review Room</h1>
        <p>Review Room 控制面由 Lighthouse 后端保存状态，本地 Agent 和远端 Agent 通过 Connector 接入同一个 MR 房间。</p>
      </div>
      <div class="actions">
        <button id="refresh-button">刷新</button>
        <button class="primary" id="real-room-button">创建真实 Room</button>
        <button class="primary" id="demo-button">创建体验房间</button>
      </div>
    </div>
  </header>

  <main class="shell">
    <section class="panel">
      <div class="panel-body">
        <h2>真实接入流程</h2>
        <div class="flow">
          <div class="step"><b>1. 创建真实 Room</b><span>填写仓库和 MR 地址，Lighthouse 后端创建 Room 主状态。</span></div>
          <div class="step"><b>2. 注册本地 Agent Connector</b><span>给 Codex/IDE Agent 一个 connector id 和 token。</span></div>
          <div class="step"><b>3. 注册远端 Agent Connector</b><span>给运行在 Lighthouse 实例或远端环境里的 Review Agent 一个接入口。</span></div>
          <div class="step"><b>4. Agent 事件进入 Room</b><span>Agent 调用 <code>/api/connectors/{connectorId}/events</code> 写入消息或 finding。</span></div>
        </div>
        <div class="control-grid">
          <div class="field">
            <label for="room-title-input">Room 标题</label>
            <input id="room-title-input" value="MR: Review Room product slice">
          </div>
          <div class="field">
            <label for="room-repo-input">仓库</label>
            <input id="room-repo-input" value="lighthouse/review-room">
          </div>
          <div class="field">
            <label for="room-mr-input">MR 地址</label>
            <input id="room-mr-input" value="https://git.example.com/lighthouse/review-room/-/merge_requests/1">
          </div>
        </div>
        <p>API 入口：<code>POST /api/rooms</code>、<code>POST /api/rooms/{roomId}/connectors</code>、<code>POST /api/connectors/{connectorId}/events</code>。保留“创建体验房间”只是样例种子，真实路径请从“创建真实 Room”开始。</p>
      </div>
    </section>

    <div class="layout">
      <aside class="panel">
        <div class="panel-head">
          <h2>Review Rooms</h2>
          <span class="tag" id="room-count">0</span>
        </div>
        <div class="panel-body">
          <div class="room-list" id="room-list"></div>
        </div>
      </aside>

      <section class="panel">
        <div class="panel-head">
          <div>
            <h2 id="detail-title">选择或创建一个房间</h2>
            <p id="detail-subtitle">点击“创建真实 Room”，然后注册本地/远端 Connector。</p>
          </div>
          <span class="tag" id="detail-status">待开始</span>
        </div>
        <div class="panel-body" id="detail-body">
          <div class="empty">还没有可展示的 Room。</div>
        </div>
      </section>
    </div>
  </main>

  <div class="toast hidden" id="toast"></div>

  <script>
    const state = { rooms: [], selectedRoomId: null, selectedRoom: null };
    const statusText = {
      open: '进行中',
      completed: '已完成',
      needs_developer_response: '等待 Developer Agent',
      developer_responded: '等待人工确认',
      accepted: '已采纳',
      rejected: '已拒绝'
    };

    function escapeHtml(value) {
      return String(value == null ? '' : value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    async function fetchJson(url, options) {
      const response = await fetch(url, options);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || response.statusText);
      return data;
    }

    function showToast(message) {
      const toast = document.getElementById('toast');
      toast.textContent = message;
      toast.classList.remove('hidden');
      setTimeout(() => toast.classList.add('hidden'), 2800);
    }

    function tagClass(value) {
      if (value === 'completed') return 'completed';
      if (value === 'P1') return 'p1';
      if (value === 'needs_developer_response' || value === 'developer_responded') return 'waiting';
      return 'open';
    }

    async function loadRooms(preferredRoomId) {
      const data = await fetchJson('/api/rooms');
      state.rooms = data.rooms || [];
      document.getElementById('room-count').textContent = `${state.rooms.length} 个`;
      renderRoomList();
      const nextId = preferredRoomId || state.selectedRoomId || (state.rooms[0] && state.rooms[0].id);
      if (nextId) {
        await selectRoom(nextId);
      } else {
        renderEmptyDetail();
      }
    }

    function renderRoomList() {
      const list = document.getElementById('room-list');
      if (!state.rooms.length) {
        list.innerHTML = '<div class="empty">暂无房间</div>';
        return;
      }
      list.innerHTML = state.rooms.map((room) => `
        <button class="room-item ${room.id === state.selectedRoomId ? 'active' : ''}" data-room-id="${escapeHtml(room.id)}">
          <span class="room-title">${escapeHtml(room.title)}</span>
          <div class="room-meta">
            <span class="tag ${tagClass(room.status)}">${escapeHtml(statusText[room.status] || room.status)}</span>
            <span class="tag">${escapeHtml(room.provider)}</span>
          </div>
          <p>${escapeHtml((room.context && room.context.repository) || room.mrUrl || '手动创建')}</p>
        </button>
      `).join('');
      list.querySelectorAll('[data-room-id]').forEach((item) => {
        item.addEventListener('click', () => selectRoom(item.getAttribute('data-room-id')));
      });
    }

    function renderEmptyDetail() {
      state.selectedRoom = null;
      document.getElementById('detail-title').textContent = '选择或创建一个房间';
      document.getElementById('detail-subtitle').textContent = '点击“创建真实 Room”，然后注册本地/远端 Connector。';
      document.getElementById('detail-status').textContent = '待开始';
      document.getElementById('detail-status').className = 'tag';
      document.getElementById('detail-body').innerHTML = '<div class="empty">还没有可展示的 Room。</div>';
    }

    async function selectRoom(roomId) {
      state.selectedRoomId = roomId;
      state.selectedRoom = await fetchJson(`/api/rooms/${encodeURIComponent(roomId)}`);
      renderRoomList();
      renderDetail();
    }

    function renderDetail() {
      const room = state.selectedRoom;
      if (!room) return renderEmptyDetail();
      const findings = room.findings || [];
      const messages = room.messages || [];
      const connectors = room.connectors || [];
      const status = document.getElementById('detail-status');
      document.getElementById('detail-title').textContent = room.title;
      document.getElementById('detail-subtitle').textContent = `${room.context.repository || '未绑定仓库'} · ${room.mrUrl || '无 MR 地址'}`;
      status.textContent = statusText[room.status] || room.status;
      status.className = `tag ${tagClass(room.status)}`;
      document.getElementById('detail-body').innerHTML = `
        <div class="summary">
          <div class="metric"><span>Finding</span><strong>${findings.length}</strong></div>
          <div class="metric"><span>消息</span><strong>${messages.length}</strong></div>
          <div class="metric"><span>Connector</span><strong>${connectors.length}</strong></div>
          <div class="metric"><span>状态</span><strong>${escapeHtml(statusText[room.status] || room.status)}</strong></div>
        </div>
        <section class="panel connector-section">
          <div class="panel-head">
            <h2>Connector 接入</h2>
            <div class="actions">
              <button data-action="add-local-connector">注册本地 Agent Connector</button>
              <button data-action="add-remote-connector">注册远端 Agent Connector</button>
            </div>
          </div>
          <div class="panel-body">
            ${connectors.length ? `<div class="connector-list">${connectors.map(renderConnector).join('')}</div>` : '<div class="empty">还没有 Connector。先注册本地 Agent 和远端 Review Agent。</div>'}
          </div>
        </section>
        <div class="detail-grid">
          <div>
            <h2>Review Findings</h2>
            ${findings.length ? findings.map(renderFinding).join('') : '<div class="empty">暂无 finding</div>'}
          </div>
          <div>
            <h2>房间时间线</h2>
            ${messages.length ? messages.map(renderMessage).join('') : '<div class="empty">暂无消息</div>'}
          </div>
        </div>
      `;
      document.querySelectorAll('[data-action="respond"]').forEach((button) => {
        button.addEventListener('click', () => respondFinding(button.getAttribute('data-finding-id')));
      });
      document.querySelectorAll('[data-action="confirm"]').forEach((button) => {
        button.addEventListener('click', () => confirmFinding(button.getAttribute('data-finding-id')));
      });
      document.querySelectorAll('[data-action="add-local-connector"]').forEach((button) => {
        button.addEventListener('click', () => registerConnector('local-agent'));
      });
      document.querySelectorAll('[data-action="add-remote-connector"]').forEach((button) => {
        button.addEventListener('click', () => registerConnector('remote-agent'));
      });
      document.querySelectorAll('[data-action="send-local-message"]').forEach((button) => {
        button.addEventListener('click', () => sendLocalMessage(button.getAttribute('data-connector-id')));
      });
      document.querySelectorAll('[data-action="send-remote-finding"]').forEach((button) => {
        button.addEventListener('click', () => sendRemoteFinding(button.getAttribute('data-connector-id')));
      });
    }

    function renderConnector(connector) {
      const endpoint = `/api/connectors/${connector.id}/events`;
      const command = `curl -X POST ${location.origin}${endpoint} -H 'Authorization: Bearer ${connector.token}' -H 'Content-Type: application/json' -d '{"type":"message","body":"agent connected"}'`;
      const canSendMessage = connector.kind === 'local-agent';
      const canSendFinding = connector.kind === 'remote-agent';
      return `
        <article class="connector-card">
          <div class="connector-head">
            <h3>${escapeHtml(connector.name)}</h3>
            <span class="tag ${connector.status === 'connected' ? 'completed' : 'open'}">${escapeHtml(connector.status)}</span>
          </div>
          <p>${escapeHtml(connector.kind)} · ${escapeHtml(connector.agentRole)} · events ${escapeHtml(connector.eventCount)}</p>
          <code class="connector-command">${escapeHtml(command)}</code>
          <div class="finding-actions">
            <button data-action="send-local-message" data-connector-id="${escapeHtml(connector.id)}" ${canSendMessage ? '' : 'disabled'}>发送本地 Agent 消息</button>
            <button data-action="send-remote-finding" data-connector-id="${escapeHtml(connector.id)}" ${canSendFinding ? '' : 'disabled'}>发送远端 Agent Finding</button>
          </div>
        </article>
      `;
    }

    function renderFinding(finding) {
      const canRespond = finding.status === 'needs_developer_response';
      const canConfirm = finding.status === 'developer_responded';
      return `
        <article class="finding">
          <div class="finding-head">
            <span class="tag ${tagClass(finding.severity)}">${escapeHtml(finding.severity)}</span>
            <span class="tag ${tagClass(finding.status)}">${escapeHtml(statusText[finding.status] || finding.status)}</span>
          </div>
          <div class="finding-title">${escapeHtml(finding.claim)}</div>
          <p>${escapeHtml(finding.evidence)}</p>
          <p><strong>建议修复：</strong>${escapeHtml(finding.suggestedFix)}</p>
          <div class="finding-path"><code>${escapeHtml(finding.filePath)}:${escapeHtml(finding.line || '-')}</code></div>
          <div class="finding-actions">
            <button class="primary" data-action="respond" data-finding-id="${escapeHtml(finding.id)}" ${canRespond ? '' : 'disabled'}>Developer Agent 回复</button>
            <button class="success" data-action="confirm" data-finding-id="${escapeHtml(finding.id)}" ${canConfirm ? '' : 'disabled'}>人工确认并同步</button>
          </div>
        </article>
      `;
    }

    function renderMessage(message) {
      return `
        <article class="message">
          <div class="message-head">
            <h3>${escapeHtml(message.senderName)}</h3>
            <span class="tag">${escapeHtml(message.kind)}</span>
          </div>
          <div class="message-body">${escapeHtml(message.body)}</div>
        </article>
      `;
    }

    async function createDemoSession() {
      const room = await fetchJson('/api/demo/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
      });
      showToast('已创建体验房间，可以开始处理 finding。');
      await loadRooms(room.id);
    }

    async function createRealRoom() {
      const title = document.getElementById('room-title-input').value.trim() || 'MR: Review Room';
      const repository = document.getElementById('room-repo-input').value.trim() || 'lighthouse/review-room';
      const mrUrl = document.getElementById('room-mr-input').value.trim();
      const room = await fetchJson('/api/rooms', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          provider: 'lighthouse',
          mrUrl,
          context: { source: 'control-plane', repository },
          participants: [
            { type: 'human', name: '开发者', role: 'owner' },
            { type: 'agent', name: 'Developer Agent', role: 'implementer' },
            { type: 'agent', name: 'Reviewer Agent', role: 'reviewer' }
          ]
        })
      });
      showToast('真实 Room 已创建，下一步注册本地和远端 Connector。');
      await loadRooms(room.id);
    }

    async function registerConnector(kind) {
      if (!state.selectedRoomId) return showToast('请先创建或选择一个 Room。');
      const connector = await fetchJson(`/api/rooms/${encodeURIComponent(state.selectedRoomId)}/connectors`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: kind === 'remote-agent' ? '远端 Reviewer Agent' : '本地 Codex Agent',
          kind,
          agentRole: kind === 'remote-agent' ? 'reviewer' : 'developer',
          endpoint: kind === 'remote-agent' ? 'https://agent.example.com/review-room' : 'http://127.0.0.1:8877/review-room'
        })
      });
      showToast(`${connector.name} 已注册，token 已生成。`);
      await loadRooms(state.selectedRoomId);
    }

    function connectorById(connectorId) {
      return (state.selectedRoom && state.selectedRoom.connectors || []).find((connector) => connector.id === connectorId);
    }

    async function sendConnectorEvent(connectorId, payload) {
      const connector = connectorById(connectorId);
      if (!connector) return showToast('Connector 不存在，请刷新后重试。');
      await fetchJson(`/api/connectors/${encodeURIComponent(connector.id)}/events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${connector.token}` },
        body: JSON.stringify(payload)
      });
      await loadRooms(state.selectedRoomId);
    }

    async function sendLocalMessage(connectorId) {
      await sendConnectorEvent(connectorId, {
        type: 'message',
        senderName: 'Developer Agent',
        body: '本地 Agent 已接入 Review Room，正在读取 MR 上下文和等待 review finding。'
      });
      showToast('本地 Agent 消息已进入 Room。');
    }

    async function sendRemoteFinding(connectorId) {
      await sendConnectorEvent(connectorId, {
        type: 'finding',
        severity: 'P1',
        filePath: 'services/review-room-service/review_room_service.py',
        line: 1,
        claim: '远端 Review Agent 发现 Connector 事件已经能写入 Room。',
        evidence: '该 finding 通过 /api/connectors/{connectorId}/events 携带 token 写入，而不是 demo seed。',
        suggestedFix: '下一步可把真实 git diff 和 agent 输出接入该 endpoint。'
      });
      showToast('远端 Agent finding 已进入 Room。');
    }

    async function respondFinding(findingId) {
      await fetchJson(`/api/findings/${encodeURIComponent(findingId)}/developer-response`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          senderName: 'Developer Agent',
          body: '我接受这个 finding，会补充 webhook secret 校验，并增加无签名请求被拒绝的测试。'
        })
      });
      showToast('Developer Agent 已回复，等待人工确认。');
      await selectRoom(state.selectedRoomId);
      await loadRooms(state.selectedRoomId);
    }

    async function confirmFinding(findingId) {
      await fetchJson(`/api/findings/${encodeURIComponent(findingId)}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          senderName: '开发者',
          decision: 'accepted',
          syncTarget: 'MR 评论',
          body: '同意该修复方向：补充 webhook secret 校验和回归测试。'
        })
      });
      showToast('已确认并生成 MR 同步记录，房间闭环完成。');
      await selectRoom(state.selectedRoomId);
      await loadRooms(state.selectedRoomId);
    }

    document.getElementById('demo-button').addEventListener('click', () => createDemoSession().catch((error) => showToast(error.message)));
    document.getElementById('real-room-button').addEventListener('click', () => createRealRoom().catch((error) => showToast(error.message)));
    document.getElementById('refresh-button').addEventListener('click', () => loadRooms().catch((error) => showToast(error.message)));
    loadRooms().catch((error) => showToast(error.message));
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
    httpd = ThreadingHTTPServer((host, port), build_handler(store))
    print("Lighthouse Review Room listening on http://{}:{} db={}".format(host, port, db_path), flush=True)
    httpd.serve_forever()


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
