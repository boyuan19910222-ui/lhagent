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

try:
    from aiohttp import web
except ModuleNotFoundError:
    web = None


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8707
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "review-room.sqlite3")
HOSTED_AGENT_ENV = "REVIEW_ROOM_ENABLE_HOSTED_AGENT"


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


def truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


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

                CREATE TABLE IF NOT EXISTS invites (
                  id TEXT PRIMARY KEY,
                  code TEXT NOT NULL UNIQUE,
                  room_id TEXT NOT NULL,
                  invite_type TEXT NOT NULL,
                  role TEXT NOT NULL,
                  name TEXT NOT NULL,
                  token TEXT NOT NULL,
                  connector_id TEXT NOT NULL,
                  permissions_json TEXT NOT NULL,
                  expires_at INTEGER,
                  used_at INTEGER,
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
            {"type": "human", "name": payload.get("ownerName") or payload.get("owner_name") or "review room owner", "role": "owner", "status": "online"},
        ]
        context = dict(payload.get("context") or {})
        if payload.get("objective") is not None:
            context["objective"] = payload.get("objective")
        if payload.get("tags") is not None:
            context["tags"] = payload.get("tags")
        if payload.get("contextAttachments") is not None:
            context["contextAttachments"] = payload.get("contextAttachments")
        room = {
            "id": make_id("room"),
            "title": payload.get("title") or "Untitled Review Room",
            "provider": payload.get("provider") or "topic",
            "mrUrl": payload.get("mrUrl") or payload.get("mr_url") or "",
            "ownerToken": payload.get("ownerToken") or payload.get("owner_token") or make_id("rro"),
            "status": payload.get("status") or "open",
            "context": context,
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
                "body": "Review Room 已创建，可以邀请外部成员或 Agent 加入讨论。",
                "payload": {"provider": room["provider"], "mrUrl": room["mrUrl"], "objective": context.get("objective")},
            },
        )
        return self.get_room(room["id"]) or room

    def list_rooms(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM rooms ORDER BY updated_at DESC").fetchall()
        rooms = [self._room_from_row(row) for row in rows]
        for room in rooms:
            room["statusSummary"] = self.room_status_summary(room["id"])
        return rooms

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
            invite_rows = conn.execute(
                "SELECT * FROM invites WHERE room_id = ? ORDER BY created_at ASC",
                (room_id,),
            ).fetchall()
        room = self._room_from_row(room_row)
        room["messages"] = [self._message_from_row(row) for row in message_rows]
        room["findings"] = [self._finding_from_row(row) for row in finding_rows]
        room["connectors"] = [self._connector_from_row(row) for row in connector_rows]
        room["invites"] = [self._invite_from_row(row) for row in invite_rows]
        room["statusSummary"] = self.room_status_summary(room_id)
        return room

    def create_invite(self, room_id: str, payload: Dict[str, Any], base_url: str = "") -> Dict[str, Any]:
        self.require_room(room_id)
        timestamp = now_ms()
        invite_type = payload.get("type") or payload.get("inviteType") or payload.get("invite_type") or "guest"
        if invite_type not in {"guest", "agent"}:
            raise ValueError("invite type must be guest or agent")
        role = payload.get("role") or ("guest" if invite_type == "guest" else "reviewer")
        name = payload.get("name") or ("外部成员" if invite_type == "guest" else self.default_connector_name("remote-agent", role))
        permissions = payload.get("permissions") or self.default_invite_permissions(invite_type, role)
        expires_at = payload.get("expiresAt") or payload.get("expires_at") or (timestamp + 7 * 24 * 60 * 60 * 1000)
        token = payload.get("token") or make_id("rrg" if invite_type == "guest" else "rrc")
        connector_id = ""
        if invite_type == "agent":
            connector = self.register_connector(
                room_id,
                {
                    "name": name,
                    "kind": payload.get("kind") or "remote-agent",
                    "agentRole": role,
                    "connectorToken": token,
                    "status": "invited",
                },
            )
            connector_id = connector["id"]
            token = connector["token"]
        invite = {
            "id": make_id("invite"),
            "code": make_id("join"),
            "roomId": room_id,
            "type": invite_type,
            "role": role,
            "name": name,
            "token": token,
            "connectorId": connector_id,
            "permissions": permissions,
            "expiresAt": expires_at,
            "usedAt": None,
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO invites
                  (id, code, room_id, invite_type, role, name, token, connector_id, permissions_json, expires_at, used_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invite["id"],
                    invite["code"],
                    invite["roomId"],
                    invite["type"],
                    invite["role"],
                    invite["name"],
                    invite["token"],
                    invite["connectorId"],
                    json_dumps(invite["permissions"]),
                    invite["expiresAt"],
                    invite["usedAt"],
                    invite["createdAt"],
                    invite["updatedAt"],
                ),
            )
            conn.execute("UPDATE rooms SET updated_at = ?, status = ? WHERE id = ?", (timestamp, "waiting_for_agent" if invite_type == "agent" else "open", room_id))
        self.add_message(
            room_id,
            {
                "senderType": "system",
                "senderName": "Review Room",
                "kind": "invite_created",
                "body": "{}邀请链接已创建。".format("Agent " if invite_type == "agent" else "访客"),
                "payload": {"inviteId": invite["id"], "type": invite_type, "role": role},
            },
        )
        return self.with_invite_url(invite, base_url)

    def get_invite_by_code(self, code: str, base_url: str = "") -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM invites WHERE code = ?", (code,)).fetchone()
        if not row:
            raise KeyError("invite not found")
        return self.with_invite_url(self._invite_from_row(row), base_url)

    def join_room(self, room_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        code = payload.get("inviteCode") or payload.get("invite_code")
        if not code:
            raise PermissionError("invite code required")
        invite = self.get_invite_by_code(code)
        if invite["roomId"] != room_id:
            raise PermissionError("invite does not belong to this room")
        if invite["type"] != "guest":
            raise ValueError("agent invite cannot join as a guest")
        if invite.get("expiresAt") and invite["expiresAt"] < now_ms():
            raise PermissionError("invite expired")
        name = (payload.get("nickname") or payload.get("name") or "").strip()
        if not name:
            raise ValueError("nickname required")
        token = make_id("rrg")
        participant = {
            "type": "human",
            "name": name,
            "role": "guest",
            "status": "online",
            "permissions": invite["permissions"],
            "token": token,
            "joinedAt": now_ms(),
        }
        self.add_participant(room_id, participant)
        with self.connect() as conn:
            conn.execute(
                "UPDATE invites SET used_at = ?, updated_at = ? WHERE code = ?",
                (participant["joinedAt"], participant["joinedAt"], code),
            )
        self.add_message(
            room_id,
            {
                "senderType": "system",
                "senderName": "Review Room",
                "kind": "member_joined",
                "body": "{} 通过分享链接加入了房间。".format(name),
                "payload": {"role": "guest"},
            },
        )
        return {"guestToken": token, "identity": {"type": "guest", "name": name, "role": "guest", "permissions": invite["permissions"]}, "room": self.get_room(room_id)}

    def add_participant(self, room_id: str, participant: Dict[str, Any]) -> None:
        timestamp = now_ms()
        with self.connect() as conn:
            row = conn.execute("SELECT participants_json FROM rooms WHERE id = ?", (room_id,)).fetchone()
            if not row:
                raise KeyError("room not found")
            participants = json_loads(row["participants_json"], [])
            participants.append(participant)
            conn.execute(
                "UPDATE rooms SET participants_json = ?, updated_at = ? WHERE id = ?",
                (json_dumps(participants), timestamp, room_id),
            )

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

    def create_hosted_agent_reply(self, room_id: str, source_message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not truthy_env(HOSTED_AGENT_ENV):
            return None
        if not self.should_hosted_agent_reply(source_message):
            return None
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM connectors
                WHERE room_id = ?
                  AND status NOT IN ('offline', 'error')
                ORDER BY
                  CASE agent_role
                    WHEN 'reviewer' THEN 0
                    WHEN 'observer' THEN 1
                    WHEN 'developer' THEN 2
                    ELSE 3
                  END,
                  created_at ASC
                LIMIT 1
                """,
                (room_id,),
            ).fetchone()
            if not row:
                return None
            connector = self._connector_from_row(row)
            timestamp = now_ms()
            conn.execute(
                """
                UPDATE connectors
                SET status = ?, event_count = event_count + 1, last_seen_at = ?, updated_at = ?
                WHERE id = ?
                """,
                ("online", timestamp, timestamp, connector["id"]),
            )
            conn.execute("UPDATE rooms SET status = ?, updated_at = ? WHERE id = ?", ("agent_working", timestamp, room_id))
        return self.add_message(
            room_id,
            {
                "senderType": "agent",
                "senderName": connector["name"],
                "kind": "connector_message",
                "body": self.build_hosted_agent_reply_body(connector, source_message),
                "payload": {
                    "connectorId": connector["id"],
                    "connectorKind": connector["kind"],
                    "agentRole": connector["agentRole"],
                    "hostedAgent": True,
                    "sourceMessageId": source_message.get("id"),
                },
            },
        )

    @staticmethod
    def should_hosted_agent_reply(message: Dict[str, Any]) -> bool:
        if message.get("senderType") != "human":
            return False
        if message.get("kind") not in {"owner_topic", "guest_message", "message"}:
            return False
        return bool((message.get("body") or "").strip())

    @staticmethod
    def build_hosted_agent_reply_body(connector: Dict[str, Any], source_message: Dict[str, Any]) -> str:
        text = " ".join((source_message.get("body") or "").split())
        if len(text) > 120:
            text = "{}...".format(text[:117])
        role = connector.get("agentRole") or "reviewer"
        if role == "developer":
            return "收到，我会把「{}」拆成可执行的修改步骤，并在需要 owner 决策时提醒你。".format(text)
        if role == "observer":
            return "收到，我会先旁观并记录关键分歧。你刚才提到：「{}」。".format(text)
        return "收到，我看到你的消息：「{}」。我会先从风险、证据和下一步建议三个角度继续协助。".format(text)

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
            conn.execute("UPDATE rooms SET status = ?, updated_at = ? WHERE id = ?", ("agent_working", timestamp, room_id))
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
            room_status = "needs_owner_decision" if status == "developer_responded" else "agent_working"
            if status in {"accepted", "rejected"}:
                room_status = "open"
            conn.execute("UPDATE rooms SET status = ?, updated_at = ? WHERE id = ?", (room_status, timestamp, row["room_id"]))
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
                "filePath": "experiments/review-room/service/review_room_service.py",
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
            "status": payload.get("status") or "invited",
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
            conn.execute("UPDATE rooms SET status = ?, updated_at = ? WHERE id = ?", ("waiting_for_agent", timestamp, room_id))
        self.add_message(
            room_id,
            {
                "senderType": "system",
                "senderName": "Review Room",
                "kind": "connector_registered",
                "body": "{} 已加入 Agent 邀请列表。".format(connector["name"]),
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
            room = conn.execute("SELECT id, owner_token, participants_json FROM rooms WHERE id = ?", (room_id,)).fetchone()
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
            for participant in json_loads(room["participants_json"], []):
                if participant.get("token") == token:
                    return {
                        "type": "guest",
                        "roomId": room_id,
                        "name": participant.get("name") or "guest",
                        "role": participant.get("role") or "guest",
                        "permissions": participant.get("permissions") or ["read", "message"],
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
                ("online", timestamp, timestamp, connector_id),
            )
            conn.execute("UPDATE rooms SET status = ?, updated_at = ? WHERE id = ?", ("agent_working", timestamp, row["room_id"]))

    def set_connector_status(self, connector_id: str, status: str) -> None:
        timestamp = now_ms()
        with self.connect() as conn:
            row = conn.execute("SELECT room_id FROM connectors WHERE id = ?", (connector_id,)).fetchone()
            if not row:
                raise KeyError("connector not found")
            last_seen_at = timestamp if status in {"online", "working", "needs_input", "connected"} else None
            conn.execute(
                """
                UPDATE connectors
                SET status = ?, last_seen_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, last_seen_at, timestamp, connector_id),
            )
            conn.execute("UPDATE rooms SET updated_at = ? WHERE id = ?", (timestamp, row["room_id"]))

    def refresh_room_status(self, room_id: str) -> None:
        terminal_statuses = {"accepted", "rejected"}
        timestamp = now_ms()
        with self.connect() as conn:
            rows = conn.execute("SELECT status FROM findings WHERE room_id = ?", (room_id,)).fetchall()
            if not rows:
                return
            statuses = [row["status"] for row in rows]
            if all(status in terminal_statuses for status in statuses):
                room_status = "completed"
            elif any(status == "developer_responded" for status in statuses):
                room_status = "needs_owner_decision"
            else:
                room_status = "agent_working"
            conn.execute(
                "UPDATE rooms SET status = ?, updated_at = ? WHERE id = ?",
                (room_status, timestamp, room_id),
            )

    def require_room(self, room_id: str) -> None:
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM rooms WHERE id = ?", (room_id,)).fetchone()
        if not row:
            raise KeyError("room not found")

    def room_status_summary(self, room_id: str) -> Dict[str, Any]:
        with self.connect() as conn:
            room_row = conn.execute("SELECT participants_json, updated_at FROM rooms WHERE id = ?", (room_id,)).fetchone()
            if not room_row:
                raise KeyError("room not found")
            connectors = conn.execute("SELECT status FROM connectors WHERE room_id = ?", (room_id,)).fetchall()
            findings = conn.execute("SELECT status FROM findings WHERE room_id = ?", (room_id,)).fetchall()
            messages = conn.execute("SELECT COUNT(*) AS count FROM messages WHERE room_id = ?", (room_id,)).fetchone()
        participants = self.sanitize_participants(json_loads(room_row["participants_json"], []))
        online_agents = sum(1 for row in connectors if row["status"] in {"online", "working", "needs_input", "connected"})
        active_agents = sum(1 for row in connectors if row["status"] in {"online", "working", "needs_input", "connected", "invited", "joining"})
        pending_findings = sum(1 for row in findings if row["status"] not in {"accepted", "rejected"})
        return {
            "memberCount": len(participants) + len(connectors),
            "humanCount": len(participants),
            "agentCount": len(connectors),
            "activeAgentCount": active_agents,
            "onlineAgentCount": online_agents,
            "pendingFindingCount": pending_findings,
            "messageCount": messages["count"] if messages else 0,
            "lastActiveAt": room_row["updated_at"],
        }

    @staticmethod
    def default_invite_permissions(invite_type: str, role: str) -> List[str]:
        if invite_type == "guest":
            return ["read", "message"]
        if role == "reviewer":
            return ["read", "message", "finding:create"]
        if role == "developer":
            return ["read", "message", "finding:respond"]
        return ["read", "message"]

    @staticmethod
    def with_invite_url(invite: Dict[str, Any], base_url: str = "") -> Dict[str, Any]:
        result = dict(invite)
        token = result.pop("token", "")
        prefix = base_url.rstrip("/") if base_url else ""
        result["inviteUrl"] = "{}/r/{}".format(prefix, invite["code"]) if prefix else "/r/{}".format(invite["code"])
        if invite["type"] == "agent":
            result["advanced"] = {
                "roomId": invite["roomId"],
                "role": invite["role"],
                "connectorToken": token,
            }
        return result

    @staticmethod
    def sanitize_participants(participants: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sanitized = []
        for participant in participants:
            item = dict(participant)
            item.pop("token", None)
            sanitized.append(item)
        return sanitized

    @staticmethod
    def default_connector_name(kind: str, role: Optional[str] = None) -> str:
        if role == "reviewer" or kind == "remote-agent":
            return "Reviewer Agent"
        if role == "developer":
            return "Developer Agent"
        if role == "observer":
            return "Observer Agent"
        if kind == "git":
            return "Git Connector"
        return "Developer Agent"

    @staticmethod
    def default_agent_role(kind: str) -> str:
        if kind == "remote-agent":
            return "reviewer"
        if kind == "git":
            return "source"
        return "developer"

    @staticmethod
    def _room_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        context = json_loads(row["context_json"], {})
        return {
            "id": row["id"],
            "roomId": row["id"],
            "title": row["title"],
            "provider": row["provider"],
            "mrUrl": row["mr_url"],
            "ownerToken": row["owner_token"],
            "status": row["status"],
            "objective": context.get("objective", ""),
            "tags": context.get("tags", []),
            "contextAttachments": context.get("contextAttachments", []),
            "context": context,
            "participants": ReviewRoomStore.sanitize_participants(json_loads(row["participants_json"], [])),
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

    @staticmethod
    def _invite_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "code": row["code"],
            "roomId": row["room_id"],
            "type": row["invite_type"],
            "role": row["role"],
            "name": row["name"],
            "token": row["token"],
            "connectorId": row["connector_id"],
            "permissions": json_loads(row["permissions_json"], []),
            "expiresAt": row["expires_at"],
            "usedAt": row["used_at"],
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
            match = re.match(r"^/r/([^/]+)$", parsed.path)
            if match:
                invite = self.store.get_invite_by_code(match.group(1), self.base_url())
                self.send_html(index_html(invite))
                return
            if parsed.path == "/health":
                self.send_json({"ok": True, "service": "lighthouse-review-room", "time": now_ms()})
                return
            if parsed.path == "/api/rooms":
                self.send_json({"rooms": [room_summary(room) for room in self.store.list_rooms()]})
                return
            match = re.match(r"^/api/rooms/([^/]+)$", parsed.path)
            if match:
                token = self.read_bearer_token({})
                identity = self.store.authenticate_room_token(match.group(1), token)
                room = self.store.get_room(match.group(1))
                if not room:
                    self.send_error_json(HTTPStatus.NOT_FOUND, "room not found")
                    return
                self.send_json(room_for_identity(room, identity))
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "not found")
        except KeyError as exc:
            self.send_error_json(HTTPStatus.NOT_FOUND, str(exc))
        except PermissionError as exc:
            self.send_error_json(HTTPStatus.FORBIDDEN, str(exc))
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
            match = re.match(r"^/api/rooms/([^/]+)/invites$", parsed.path)
            if match:
                identity = self.store.authenticate_room_token(match.group(1), self.read_bearer_token(body))
                if identity["type"] != "owner":
                    raise PermissionError("owner token required")
                self.send_json(self.store.create_invite(match.group(1), body, self.base_url()), HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/rooms/([^/]+)/join$", parsed.path)
            if match:
                result = self.store.join_room(match.group(1), body)
                result["room"] = room_for_identity(result["room"], result["identity"])
                self.send_json(result, HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/rooms/([^/]+)/messages$", parsed.path)
            if match:
                room_id = match.group(1)
                token = self.read_bearer_token(body)
                identity = self.store.authenticate_room_token(room_id, token)
                body = {
                    **body,
                    "senderType": "human" if identity["type"] in {"owner", "guest"} else "agent",
                    "senderName": identity["name"],
                    "kind": body.get("kind") or ("owner_topic" if identity["type"] == "owner" else "guest_message" if identity["type"] == "guest" else "connector_message"),
                }
                created = self.store.add_message(room_id, body)
                self.store.create_hosted_agent_reply(room_id, created)
                self.send_json(created, HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/rooms/([^/]+)/findings$", parsed.path)
            if match:
                identity = self.store.authenticate_room_token(match.group(1), self.read_bearer_token(body))
                require_reviewer_connector(identity)
                self.send_json(self.store.add_finding(match.group(1), {**body, "createdBy": identity["name"]}), HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/rooms/([^/]+)/connectors$", parsed.path)
            if match:
                identity = self.store.authenticate_room_token(match.group(1), self.read_bearer_token(body))
                require_owner_role(identity)
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
                finding = self.store.get_finding(match.group(1))
                identity = self.store.authenticate_room_token(finding["roomId"], self.read_bearer_token(body))
                require_developer_connector(identity)
                self.send_json(self.store.respond_to_finding(match.group(1), {**body, "senderName": identity["name"]}), HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/findings/([^/]+)/confirm$", parsed.path)
            if match:
                finding = self.store.get_finding(match.group(1))
                identity = self.store.authenticate_room_token(finding["roomId"], self.read_bearer_token(body))
                require_owner_role(identity)
                self.send_json(self.store.confirm_finding(match.group(1), {**body, "senderName": identity["name"]}), HTTPStatus.CREATED)
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
                finding = self.store.get_finding(match.group(1))
                identity = self.store.authenticate_room_token(finding["roomId"], self.read_bearer_token(body))
                require_owner_role(identity)
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

    def base_url(self) -> str:
        host = self.headers.get("Host") or "{}:{}".format(*self.server.server_address)
        return "http://{}".format(host)

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
        self.send_header("Cache-Control", "no-store")
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
        if identity["type"] == "connector":
            self.store.set_connector_status(identity["connectorId"], "online")
        self.connections.setdefault(room_id, {})[websocket] = identity
        room = self.store.get_room(room_id)
        await websocket.send_json({"type": "room.snapshot", "room": room_for_identity(room, identity) if room else None, "identity": identity})
        await self.broadcast(room_id, {"type": "presence.updated", "presence": self.presence(room_id)})
        await self.broadcast_snapshot(room_id)

    async def remove(self, room_id: str, websocket: web.WebSocketResponse) -> None:
        room_connections = self.connections.get(room_id)
        if not room_connections:
            return
        identity = room_connections.pop(websocket, None)
        if identity and identity.get("type") == "connector":
            self.store.set_connector_status(identity["connectorId"], "offline")
        if room_connections:
            await self.broadcast(room_id, {"type": "presence.updated", "presence": self.presence(room_id)})
            await self.broadcast_snapshot(room_id)
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

    async def broadcast_snapshot(self, room_id: str) -> None:
        room = self.store.get_room(room_id)
        room_connections = list((self.connections.get(room_id) or {}).items())
        for websocket, identity in room_connections:
            if not websocket.closed:
                await websocket.send_json({"type": "room.snapshot", "room": room_for_identity(room, identity) if room else None, "identity": identity})

    def presence(self, room_id: str) -> List[Dict[str, Any]]:
        return [
            {"type": identity["type"], "name": identity["name"], "role": identity["role"]}
            for identity in (self.connections.get(room_id) or {}).values()
        ]


def require_aiohttp() -> None:
    if web is None:
        raise RuntimeError("aiohttp is required for WebSocket Review Room; install experiments/review-room/service/requirements.txt")


STORE_KEY = web.AppKey("store", ReviewRoomStore) if web is not None else "store"
HUB_KEY = web.AppKey("hub", RealtimeHub) if web is not None else "hub"


def bearer_token_from_request(request: web.Request) -> str:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return request.query.get("token", "")


def base_url_from_aiohttp_request(request: web.Request) -> str:
    return "{}://{}".format(request.scheme, request.host)


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
    result = {key: value for key, value in room.items() if key not in {"ownerToken", "invites"}}
    result["participants"] = ReviewRoomStore.sanitize_participants(result.get("participants", []))
    result["connectors"] = [
        {key: value for key, value in connector.items() if key not in {"token", "connectorToken"}}
        for connector in result.get("connectors", [])
    ]
    return result


def room_for_identity(room: Dict[str, Any], identity: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(room)
    if identity["type"] == "owner":
        return result
    result.pop("ownerToken", None)
    result.pop("invites", None)
    result["connectors"] = [
        {key: value for key, value in connector.items() if key not in {"token", "connectorToken"}}
        for connector in result.get("connectors", [])
    ]
    return result


def require_owner_role(identity: Dict[str, Any]) -> None:
    if identity["type"] != "owner":
        raise PermissionError("owner token required")


def require_reviewer_connector(identity: Dict[str, Any]) -> None:
    if identity["type"] != "connector" or identity["role"] != "reviewer":
        raise PermissionError("reviewer connector required")


def require_developer_connector(identity: Dict[str, Any]) -> None:
    if identity["type"] != "connector" or identity["role"] != "developer":
        raise PermissionError("developer connector required")


def require_identity(store: ReviewRoomStore, room_id: str, token: str) -> Dict[str, Any]:
    try:
        return store.authenticate_room_token(room_id, token)
    except KeyError as exc:
        raise web.HTTPNotFound(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")
    except PermissionError as exc:
        raise web.HTTPForbidden(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")


def ensure_owner(identity: Dict[str, Any]) -> None:
    try:
        require_owner_role(identity)
    except PermissionError as exc:
        raise web.HTTPForbidden(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")


def ensure_reviewer_connector(identity: Dict[str, Any]) -> None:
    try:
        require_reviewer_connector(identity)
    except PermissionError as exc:
        raise web.HTTPForbidden(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")


def ensure_developer_connector(identity: Dict[str, Any]) -> None:
    try:
        require_developer_connector(identity)
    except PermissionError as exc:
        raise web.HTTPForbidden(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")


def require_finding_identity(store: ReviewRoomStore, finding_id: str, token: str) -> Dict[str, Any]:
    try:
        finding = store.get_finding(finding_id)
    except KeyError as exc:
        raise web.HTTPNotFound(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")
    return require_identity(store, finding["roomId"], token)


def ensure_owner_for_finding(store: ReviewRoomStore, finding_id: str, token: str) -> Dict[str, Any]:
    identity = require_finding_identity(store, finding_id, token)
    try:
        require_owner_role(identity)
    except PermissionError as exc:
        raise web.HTTPForbidden(text=json_dumps({"ok": False, "error": "owner token required"}), content_type="application/json")
    return identity


async def broadcast_hosted_agent_reply(store: ReviewRoomStore, hub: RealtimeHub, room_id: str, source_message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    reply = store.create_hosted_agent_reply(room_id, source_message)
    if not reply:
        return None
    await hub.broadcast(room_id, {"type": "message.created", "message": reply})
    await hub.broadcast_snapshot(room_id)
    return reply


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
        sender_type = "human" if identity["type"] in {"owner", "guest"} else "agent"
        default_kind = "owner_topic" if identity["type"] == "owner" else "guest_message" if identity["type"] == "guest" else "connector_message"
        message = store.add_message(
            room_id,
            {
                "senderType": sender_type,
                "senderName": identity["name"],
                "kind": payload.get("kind") or default_kind,
                "body": payload.get("body") or "",
                "payload": {"eventType": event_type, "role": identity["role"]},
            },
        )
        await hub.broadcast(room_id, {"type": "message.created", "message": message})
        await broadcast_hosted_agent_reply(store, hub, room_id, message)
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
    require_aiohttp()
    app = web.Application()
    app[STORE_KEY] = store or ReviewRoomStore(DEFAULT_DB_PATH)
    app[HUB_KEY] = RealtimeHub(app[STORE_KEY])

    async def index(_request: web.Request) -> web.Response:
        return web.Response(text=index_html(), content_type="text/html", charset="utf-8", headers={"Cache-Control": "no-store"})

    async def invite_page(request: web.Request) -> web.Response:
        invite = app[STORE_KEY].get_invite_by_code(request.match_info["invite_code"], base_url_from_aiohttp_request(request))
        return web.Response(text=index_html(invite), content_type="text/html", charset="utf-8", headers={"Cache-Control": "no-store"})

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
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        room = app[STORE_KEY].get_room(room_id)
        if not room:
            raise web.HTTPNotFound(text=json_dumps({"ok": False, "error": "room not found"}), content_type="application/json")
        return json_response(room_for_identity(room, identity))

    async def create_invite(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        ensure_owner(identity)
        return json_response(app[STORE_KEY].create_invite(room_id, await request_json(request), base_url_from_aiohttp_request(request)), 201)

    async def join_room(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        try:
            result = app[STORE_KEY].join_room(room_id, await request_json(request))
        except KeyError as exc:
            raise web.HTTPNotFound(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")
        except PermissionError as exc:
            raise web.HTTPForbidden(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")
        except ValueError as exc:
            raise web.HTTPBadRequest(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")
        result["room"] = room_for_identity(result["room"], result["identity"])
        await app[HUB_KEY].broadcast_snapshot(room_id)
        return json_response(result, 201)

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
        await app[HUB_KEY].broadcast_snapshot(result["roomId"])
        return json_response(result, 201)

    async def add_message(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        body = await request_json(request)
        body = {
            **body,
            "senderType": "human" if identity["type"] in {"owner", "guest"} else "agent",
            "senderName": identity["name"],
            "kind": body.get("kind") or ("owner_topic" if identity["type"] == "owner" else "guest_message" if identity["type"] == "guest" else "connector_message"),
        }
        message = app[STORE_KEY].add_message(room_id, body)
        await app[HUB_KEY].broadcast(room_id, {"type": "message.created", "message": message})
        await broadcast_hosted_agent_reply(app[STORE_KEY], app[HUB_KEY], room_id, message)
        return json_response(message, 201)

    async def add_finding(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        ensure_reviewer_connector(identity)
        body = await request_json(request)
        finding = app[STORE_KEY].add_finding(room_id, {**body, "createdBy": identity["name"]})
        await app[HUB_KEY].broadcast(room_id, {"type": "finding.created", "finding": finding})
        return json_response(finding, 201)

    async def update_finding(request: web.Request) -> web.Response:
        ensure_owner_for_finding(app[STORE_KEY], request.match_info["finding_id"], bearer_token_from_request(request))
        finding = app[STORE_KEY].update_finding(request.match_info["finding_id"], await request_json(request))
        await app[HUB_KEY].broadcast(finding["roomId"], {"type": "finding.updated", "finding": finding})
        return json_response(finding)

    async def developer_response(request: web.Request) -> web.Response:
        identity = require_finding_identity(app[STORE_KEY], request.match_info["finding_id"], bearer_token_from_request(request))
        ensure_developer_connector(identity)
        body = await request_json(request)
        finding = app[STORE_KEY].respond_to_finding(request.match_info["finding_id"], {**body, "senderName": identity["name"]})
        await app[HUB_KEY].broadcast(finding["roomId"], {"type": "finding.updated", "finding": finding})
        return json_response(finding, 201)

    async def confirm_finding(request: web.Request) -> web.Response:
        identity = ensure_owner_for_finding(app[STORE_KEY], request.match_info["finding_id"], bearer_token_from_request(request))
        body = await request_json(request)
        finding = app[STORE_KEY].confirm_finding(request.match_info["finding_id"], {**body, "senderName": identity["name"]})
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
    app.router.add_get("/r/{invite_code}", invite_page)
    app.router.add_get("/health", health)
    app.router.add_get("/api/rooms", list_rooms)
    app.router.add_post("/api/rooms", create_room)
    app.router.add_post("/api/demo/session", demo_session)
    app.router.add_post("/api/webhooks/merge-request", merge_request_webhook)
    app.router.add_get("/api/rooms/{room_id}", get_room)
    app.router.add_post("/api/rooms/{room_id}/invites", create_invite)
    app.router.add_post("/api/rooms/{room_id}/join", join_room)
    app.router.add_post("/api/rooms/{room_id}/messages", add_message)
    app.router.add_post("/api/rooms/{room_id}/findings", add_finding)
    app.router.add_post("/api/rooms/{room_id}/connectors", register_connector)
    app.router.add_post("/api/connectors/{connector_id}/events", connector_event)
    app.router.add_patch("/api/findings/{finding_id}", update_finding)
    app.router.add_post("/api/findings/{finding_id}/developer-response", developer_response)
    app.router.add_post("/api/findings/{finding_id}/confirm", confirm_finding)
    app.router.add_get("/ws/rooms/{room_id}", websocket_room)
    return app


def review_room_app_html(initial_invite: Optional[Dict[str, Any]] = None) -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Lighthouse Review Room</title>
  <style>
    :root{--bg:#f6f7f9;--panel:#fff;--panel-soft:#f9fafb;--line:#d9dde5;--text:#172033;--muted:#697386;--blue:#2457d6;--green:#067a62;--red:#c43d3d;--amber:#9a6500;--violet:#6d4bd1}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:14px}
    button,input,textarea,select{font:inherit}button{min-height:34px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--text);padding:0 12px;cursor:pointer}button:hover{border-color:#b9c0cd}button:disabled{opacity:.55;cursor:not-allowed}
    button.primary{border-color:var(--blue);background:var(--blue);color:#fff}button.subtle{background:var(--panel-soft)}button.danger{border-color:var(--red);color:var(--red)}
    input,textarea,select{width:100%;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--text);padding:9px 10px}textarea{min-height:76px;resize:vertical}
    h1,h2,h3,p{margin:0}h1{font-size:18px;line-height:1.2}h2{font-size:14px}h3{font-size:13px}.muted{color:var(--muted)}
    .app{height:100vh;display:grid;grid-template-rows:56px minmax(0,1fr)}.topbar{display:flex;align-items:center;justify-content:space-between;gap:16px;border-bottom:1px solid var(--line);background:#fff;padding:0 18px}.brand{display:flex;align-items:center;gap:10px}.brand-mark{width:28px;height:28px;border-radius:7px;background:#172033;color:#fff;display:grid;place-items:center;font-weight:750}
    .layout{min-height:0;display:grid;grid-template-columns:300px minmax(420px,1fr) 340px}.sidebar,.chat,.inspector{min-width:0;min-height:0;border-right:1px solid var(--line);background:#fff}.inspector{border-right:0;border-left:1px solid var(--line)}.sidebar,.inspector{display:grid;grid-template-rows:auto minmax(0,1fr)}.section{border-bottom:1px solid var(--line);padding:14px}.section-title{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}.stack{display:grid;gap:10px}.row{display:flex;align-items:center;gap:8px}.row.between{justify-content:space-between}.field{display:grid;gap:6px}.field label{font-size:12px;font-weight:700;color:#3d4658}
    .room-list{min-height:0;overflow:auto;padding:10px}.room-item{width:100%;display:grid;gap:6px;text-align:left;border:1px solid transparent;border-radius:7px;background:#fff;padding:10px}.room-item:hover,.room-item.active{border-color:#b8c7f5;background:#f6f8ff}.room-meta{display:flex;align-items:center;justify-content:space-between;gap:8px;color:var(--muted);font-size:12px}
    .chat{display:grid;grid-template-rows:auto minmax(0,1fr) auto;background:#f8f9fb}.chat-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;border-bottom:1px solid var(--line);background:#fff;padding:14px 16px}.chat-title{display:grid;gap:5px}.timeline{min-height:0;overflow:auto;padding:16px;display:grid;align-content:start;gap:10px}.composer{border-top:1px solid var(--line);background:#fff;padding:12px 16px}.composer textarea{min-height:70px}.composer-actions{display:flex;align-items:center;justify-content:space-between;margin-top:8px}
    .message{max-width:78%;border:1px solid var(--line);border-radius:8px;background:#fff;padding:10px 12px;box-shadow:0 1px 2px rgba(23,32,51,.04)}.message.owner{justify-self:end;background:#eef4ff;border-color:#c8d8ff}.message.agent{border-color:#dfe2ea}.message.system{justify-self:center;max-width:92%;background:#f0f2f5;color:#485266}.message.guest{background:#fff}.message-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:5px}.message-name{font-weight:700;font-size:13px}.message-body{white-space:pre-wrap;line-height:1.55}
    .finding-card{display:grid;gap:8px;border:1px solid #ecc77e;background:#fffaf0;border-radius:7px;padding:10px;margin-top:6px}.finding-card strong{font-size:13px}.finding-actions{display:flex;gap:8px;flex-wrap:wrap}
    .tag{display:inline-flex;align-items:center;min-height:22px;border:1px solid var(--line);border-radius:999px;background:#f7f8fb;padding:0 8px;color:var(--muted);font-size:12px;white-space:nowrap}.tag.open{border-color:#b8c7f5;background:#f4f7ff;color:var(--blue)}.tag.online{border-color:#99d8ca;background:#effaf7;color:var(--green)}.tag.waiting{border-color:#ecc77e;background:#fff8e8;color:var(--amber)}.tag.done{border-color:#a8d8c9;background:#effaf7;color:var(--green)}.tag.error{border-color:#edaaa8;background:#fff1f0;color:var(--red)}
    .stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.stat{border:1px solid var(--line);border-radius:7px;background:var(--panel-soft);padding:10px}.stat strong{display:block;font-size:18px}.member-list{display:grid;gap:8px}.member{display:grid;grid-template-columns:32px minmax(0,1fr) auto;gap:9px;align-items:center;border:1px solid var(--line);border-radius:7px;background:#fff;padding:8px}.avatar{width:32px;height:32px;border-radius:50%;background:#edf1f7;display:grid;place-items:center;font-weight:750;color:#3d4658}.invite-box{border:1px solid var(--line);border-radius:7px;background:var(--panel-soft);padding:10px;display:grid;gap:8px}.invite-link{word-break:break-all;border:1px dashed #bac2d0;border-radius:6px;background:#fff;padding:8px;color:#33405a}.empty{border:1px dashed var(--line);border-radius:8px;padding:18px;text-align:center;color:var(--muted);background:#fff}.hidden{display:none!important}details{border:1px solid var(--line);border-radius:7px;background:#fff;padding:8px}summary{cursor:pointer;font-weight:700}.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;white-space:pre-wrap;word-break:break-all;color:#2a3447}
    @media(max-width:1040px){.app{height:auto;min-height:100vh}.layout{grid-template-columns:1fr}.sidebar,.inspector{border-right:0;border-left:0;border-bottom:1px solid var(--line)}.message{max-width:96%}}
  </style>
</head>
<body>
  <div class="app">
    <header class="topbar">
      <div class="brand"><div class="brand-mark">LR</div><div><h1>Lighthouse Review Room</h1><p class="muted">话题房间里的 Human + Agent 协作</p></div></div>
      <div class="row"><span class="tag" id="connectionState">未连接</span><button class="subtle" id="refreshRooms">刷新</button></div>
    </header>
    <main class="layout">
      <aside class="sidebar">
        <div class="section">
          <div class="section-title"><h2>创建话题房间</h2></div>
          <div class="stack">
            <div class="field"><label>房间标题</label><input id="roomTitle" value="开放评审讨论"></div>
            <div class="field"><label>目标</label><textarea id="roomObjective">围绕一个问题、方案或变更，让人和 Agent 在同一个房间里讨论并沉淀决定。</textarea></div>
            <div class="field"><label>标签，可选</label><input id="roomTags" value="review,agent"></div>
            <button class="primary" id="createRoom">创建房间</button>
            <button class="subtle" id="createDemo">创建体验房间</button>
          </div>
        </div>
        <div class="room-list" id="roomList"></div>
      </aside>
      <section class="chat">
        <div class="chat-head">
          <div class="chat-title"><h2 id="detailTitle">选择或创建一个房间</h2><p class="muted" id="detailMeta">左侧是房间，中间是对话，右侧是成员与状态。</p></div>
          <span class="tag open" id="roomStatus">未选择</span>
        </div>
        <div class="timeline" id="timeline"><div class="empty">还没有进入房间。</div></div>
        <div class="composer" id="composer">
          <textarea id="messageInput" placeholder="输入消息，和房间里的成员继续讨论。"></textarea>
          <div class="composer-actions"><span class="muted" id="composerHint">真实 Agent 接入后，会在同一条时间线里回复。</span><button class="primary" id="sendMessage">发送</button></div>
        </div>
      </section>
      <aside class="inspector">
        <div class="section" id="statusPanel"></div>
        <div class="section" style="overflow:auto" id="membersPanel"></div>
      </aside>
    </main>
  </div>
  <script>
    window.REVIEW_ROOM_INVITE = __INITIAL_INVITE__;
    const state = {
      rooms: [],
      room: null,
      ws: null,
      identity: null,
      currentToken: '',
      invite: window.REVIEW_ROOM_INVITE,
      lastInvite: null,
      presence: [],
      ownerTokens: JSON.parse(localStorage.getItem('reviewRoomOwnerTokens') || '{}'),
      guestTokens: JSON.parse(localStorage.getItem('reviewRoomGuestTokens') || '{}')
    };
    const statusText = {
      open: '开放讨论',
      waiting_for_agent: '等待 Agent',
      agent_working: 'Agent 工作中',
      needs_owner_decision: '等待 owner 确认',
      completed: '已完成',
      archived: '已归档',
      needs_developer_response: '等待 Developer Agent',
      developer_responded: '等待 owner 确认',
      accepted: '已确认',
      rejected: '已驳回'
    };
    const agentStatusText = { invited:'已邀请', joining:'接入中', online:'在线', connected:'在线', working:'工作中', needs_input:'需要输入', error:'异常', offline:'离线' };
    function esc(value){ return String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;'); }
    function fmtTime(ms){ if(!ms) return '刚刚'; return new Date(ms).toLocaleString([], {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'}); }
    function saveTokens(){ localStorage.setItem('reviewRoomOwnerTokens', JSON.stringify(state.ownerTokens)); localStorage.setItem('reviewRoomGuestTokens', JSON.stringify(state.guestTokens)); }
    async function api(path, options={}){
      const res = await fetch(path, options);
      const data = await res.json();
      if(!res.ok) throw new Error(data.error || res.statusText);
      return data;
    }
    function authHeaders(){ return { 'Content-Type':'application/json', Authorization:`Bearer ${state.currentToken}` }; }
    function roomToken(roomId){ return state.ownerTokens[roomId] || state.guestTokens[roomId] || ''; }
    function isOwner(){ return state.identity && state.identity.type === 'owner'; }
    async function loadRooms(){
      const data = await api('/api/rooms');
      state.rooms = data.rooms || [];
      renderRooms();
      if(state.invite && !state.room){ renderInviteGate(state.invite); return; }
      if(!state.room && state.rooms.length){ await selectRoom(state.rooms[0].id).catch(() => renderEmptyRoom()); }
      if(!state.room && !state.rooms.length){ renderEmptyRoom(); }
    }
    function renderRooms(){
      const list = document.getElementById('roomList');
      if(!state.rooms.length){ list.innerHTML = '<div class="empty">暂无房间</div>'; return; }
      list.innerHTML = state.rooms.map(room => {
        const summary = room.statusSummary || {};
        const active = state.room && state.room.id === room.id ? 'active' : '';
        return `<button class="room-item ${active}" data-room="${esc(room.id)}">
          <strong>${esc(room.title)}</strong>
          <span class="muted">${esc(room.objective || (room.context && room.context.objective) || '开放话题房间')}</span>
          <span class="room-meta"><span>${esc(statusText[room.status] || room.status)}</span><span>${summary.onlineAgentCount || 0}/${summary.agentCount || 0} Agent</span></span>
        </button>`;
      }).join('');
      list.querySelectorAll('[data-room]').forEach(button => button.addEventListener('click', () => selectRoom(button.dataset.room).catch(alert)));
    }
    async function createRoom(){
      const tags = document.getElementById('roomTags').value.split(',').map(item => item.trim()).filter(Boolean);
      const room = await api('/api/rooms', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
        title: document.getElementById('roomTitle').value || '开放评审讨论',
        objective: document.getElementById('roomObjective').value,
        tags
      })});
      state.ownerTokens[room.id] = room.ownerToken;
      saveTokens();
      await loadRooms();
      await selectRoom(room.id);
    }
    async function createDemo(){
      const room = await api('/api/demo/session', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
      state.ownerTokens[room.id] = room.ownerToken;
      saveTokens();
      await loadRooms();
      await selectRoom(room.id);
    }
    async function selectRoom(roomId){
      const token = roomToken(roomId);
      if(!token){ renderLockedRoom(roomId); return; }
      state.currentToken = token;
      state.room = await api(`/api/rooms/${encodeURIComponent(roomId)}`, {headers:{Authorization:`Bearer ${token}`}});
      state.identity = state.ownerTokens[roomId] === token ? {type:'owner', name:'review room owner', role:'owner'} : {type:'guest', name:'guest', role:'guest'};
      state.lastInvite = null;
      state.presence = [];
      renderAll();
      connectSocket();
    }
    function renderLockedRoom(roomId){
      state.room = null; state.currentToken = ''; state.identity = null;
      state.presence = [];
      document.getElementById('detailTitle').textContent = roomId;
      document.getElementById('detailMeta').textContent = '这台浏览器没有这个房间的进入凭据。';
      document.getElementById('roomStatus').textContent = '未进入';
      document.getElementById('timeline').innerHTML = '<div class="empty">需要 owner 链接或分享链接才能进入。</div>';
      renderSidePanels();
    }
    function renderEmptyRoom(){
      document.getElementById('timeline').innerHTML = '<div class="empty">创建一个房间，或通过分享链接加入。</div>';
      renderSidePanels();
    }
    function renderInviteGate(invite){
      state.presence = [];
      const title = invite.type === 'agent' ? 'Agent 邀请' : '访客邀请';
      document.getElementById('detailTitle').textContent = title;
      document.getElementById('detailMeta').textContent = invite.type === 'agent' ? '把这条链接交给要接入的 Agent。' : '输入昵称后即可加入房间讨论。';
      document.getElementById('roomStatus').textContent = invite.type === 'agent' ? '等待 Agent' : '可加入';
      if(invite.type === 'agent'){
        document.getElementById('timeline').innerHTML = `<div class="empty"><strong>${esc(invite.name || 'Agent')}</strong><br>这个链接用于 Agent 接入。owner 页面会把它显示在右侧成员列表中。</div>`;
      } else {
        document.getElementById('timeline').innerHTML = `<div class="invite-box" style="max-width:420px;margin:auto">
          <h2>加入 Review Room</h2>
          <p class="muted">外部成员默认可以阅读和发言，确认决定仍由 owner 完成。</p>
          <div class="field"><label>你的昵称</label><input id="guestName" value="外部成员"></div>
          <button class="primary" id="joinRoom">进入房间</button>
        </div>`;
        document.getElementById('joinRoom').addEventListener('click', () => joinInvite(invite).catch(alert));
      }
      renderSidePanels();
    }
    async function joinInvite(invite){
      const result = await api(`/api/rooms/${encodeURIComponent(invite.roomId)}/join`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({inviteCode: invite.code, nickname: document.getElementById('guestName').value})});
      state.guestTokens[invite.roomId] = result.guestToken;
      state.currentToken = result.guestToken;
      state.identity = result.identity;
      state.room = result.room;
      state.presence = [];
      saveTokens();
      renderAll();
      connectSocket();
    }
    function connectSocket(){
      if(!state.room || !state.currentToken) return;
      if(state.ws) state.ws.close();
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      state.ws = new WebSocket(`${proto}//${location.host}/ws/rooms/${encodeURIComponent(state.room.id)}?token=${encodeURIComponent(state.currentToken)}`);
      state.ws.onopen = () => document.getElementById('connectionState').textContent = '实时连接';
      state.ws.onclose = () => document.getElementById('connectionState').textContent = '已断开';
      state.ws.onmessage = event => handleSocketEvent(JSON.parse(event.data));
    }
    function sendSocket(event){ if(state.ws && state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify(event)); }
    function handleSocketEvent(event){
      if(event.type === 'room.snapshot'){ state.room = event.room; state.identity = event.identity || state.identity; renderAll(); return; }
      if(event.type === 'presence.updated'){ state.presence = event.presence || []; renderSidePanels(); return; }
      if(event.type === 'message.created'){ state.room.messages.push(event.message); renderAll(); return; }
      if(event.type === 'finding.created'){ state.room.findings.push(event.finding); renderAll(); return; }
      if(event.type === 'finding.updated'){ state.room.findings = state.room.findings.map(f => f.id === event.finding.id ? event.finding : f); renderAll(); return; }
      if(event.type === 'error') alert(event.error);
    }
    function renderAll(){
      renderRooms();
      renderChat();
      renderSidePanels();
    }
    function renderChat(){
      const room = state.room;
      if(!room){ renderEmptyRoom(); return; }
      document.getElementById('detailTitle').textContent = room.title;
      document.getElementById('detailMeta').textContent = room.objective || (room.context && room.context.objective) || '开放话题房间';
      document.getElementById('roomStatus').textContent = statusText[room.status] || room.status;
      const messages = room.messages || [];
      document.getElementById('timeline').innerHTML = messages.length ? messages.map(renderMessage).join('') : '<div class="empty">房间已创建，发一条消息开始讨论。</div>';
      const timeline = document.getElementById('timeline');
      timeline.scrollTop = timeline.scrollHeight;
    }
    function renderMessage(message){
      const cls = message.senderType === 'system' ? 'system' : message.kind === 'guest_message' ? 'guest' : message.senderType === 'human' ? 'owner' : 'agent';
      const finding = message.payload && message.payload.findingId ? (state.room.findings || []).find(item => item.id === message.payload.findingId) : null;
      return `<article class="message ${cls}">
        <div class="message-head"><span class="message-name">${esc(message.senderName)}</span><span class="tag">${esc(messageKindText(message.kind, message))}</span></div>
        <div class="message-body">${esc(message.body)}</div>
        ${finding ? renderFindingCard(finding) : ''}
      </article>`;
    }
    function messageKindText(kind, message={}){
      if(message.payload && message.payload.hostedAgent) return '模拟 Agent';
      return {room_created:'系统', invite_created:'邀请', member_joined:'加入', owner_topic:'owner', guest_message:'guest', connector_message:'Agent', agent_working:'处理中', review_finding:'Finding', developer_response:'回复', human_confirmation:'确认', mr_sync_preview:'同步预览', mr_webhook:'外部事件'}[kind] || kind;
    }
    function renderFindingCard(finding){
      const canConfirm = isOwner() && finding.status === 'developer_responded';
      return `<div class="finding-card">
        <div class="row between"><strong>${esc(finding.claim || 'Review finding')}</strong><span class="tag waiting">${esc(statusText[finding.status] || finding.status)}</span></div>
        ${finding.evidence ? `<div class="muted">${esc(finding.evidence)}</div>` : ''}
        ${finding.suggestedFix ? `<div>${esc(finding.suggestedFix)}</div>` : ''}
        <div class="finding-actions"><button class="primary" data-confirm="${esc(finding.id)}" ${canConfirm ? '' : 'disabled'}>确认</button><button class="danger" data-reject="${esc(finding.id)}" ${canConfirm ? '' : 'disabled'}>驳回</button></div>
      </div>`;
    }
    function renderSidePanels(){
      const presence = state.presence || [];
      if(!state.room){
        document.getElementById('statusPanel').innerHTML = '<div class="empty">房间状态会显示在这里。</div>';
        document.getElementById('membersPanel').innerHTML = '<div class="empty">成员列表会显示在这里。</div>';
        return;
      }
      const summary = state.room.statusSummary || {};
      const onlineAgents = presence.filter(item => item.type === 'connector').length;
      document.getElementById('statusPanel').innerHTML = `<div class="section-title"><h2>房间状态</h2><span class="tag open">${esc(statusText[state.room.status] || state.room.status)}</span></div>
        <div class="stats">
          <div class="stat"><strong>${summary.memberCount || 0}</strong><span class="muted">成员</span></div>
          <div class="stat"><strong>${onlineAgents}</strong><span class="muted">在线 Agent</span></div>
          <div class="stat"><strong>${summary.pendingFindingCount || 0}</strong><span class="muted">待处理</span></div>
          <div class="stat"><strong>${fmtTime(summary.lastActiveAt || state.room.updatedAt)}</strong><span class="muted">最后活动</span></div>
        </div>
        <div class="stack" style="margin-top:12px">${renderInviteControls()}</div>`;
      document.getElementById('membersPanel').innerHTML = `<div class="section-title"><h2>房间角色</h2><span class="tag">${presence.length || 0} 在线</span></div><div class="member-list">${renderMembers(presence)}</div>`;
      bindInviteControls();
      document.querySelectorAll('[data-confirm]').forEach(button => button.addEventListener('click', () => sendSocket({type:'finding.confirm', findingId:button.dataset.confirm, decision:'accepted', body:'确认采纳这个结论。'})));
      document.querySelectorAll('[data-reject]').forEach(button => button.addEventListener('click', () => sendSocket({type:'finding.reject', findingId:button.dataset.reject, decision:'rejected', body:'暂不采纳，继续讨论。'})));
    }
    function renderMembers(presence=[]){
      const connectedAgents = new Set(presence.filter(item => item.type === 'connector').map(item => `${item.name}|${item.role}`));
      const humans = (state.room.participants || []).map(item => memberRow(item.name, item.role || item.type, item.status || 'online', item.role === 'owner' ? 'owner' : 'human'));
      const agents = (state.room.connectors || []).map(item => {
        const connected = connectedAgents.has(`${item.name}|${item.agentRole}`);
        const status = connected ? 'online' : (item.status === 'invited' ? 'invited' : 'offline');
        return memberRow(item.name, item.agentRole, status, 'agent');
      });
      return humans.concat(agents).join('') || '<div class="empty">暂无成员</div>';
    }
    function memberRow(name, role, status, type){
      const label = type === 'agent' ? (agentStatusText[status] || status) : (role === 'owner' ? 'owner' : 'guest');
      const cls = status === 'online' || status === 'connected' ? 'online' : status === 'error' ? 'error' : 'waiting';
      return `<div class="member"><div class="avatar">${esc(String(name || '?').slice(0,1).toUpperCase())}</div><div><strong>${esc(name)}</strong><p class="muted">${esc(role)}</p></div><span class="tag ${cls}">${esc(label)}</span></div>`;
    }
    function renderInviteControls(){
      if(!isOwner()) return '<div class="empty">你可以阅读和发言，邀请和确认操作由 owner 完成。</div>';
      const last = state.lastInvite ? `<div class="invite-box"><strong>邀请链接</strong><div class="invite-link">${esc(state.lastInvite.inviteUrl)}</div><button class="subtle" id="copyInvite">复制链接</button>${renderAdvancedInvite(state.lastInvite)}</div>` : '';
      return `<div class="invite-box">
        <strong>分享给外部成员</strong>
        <button id="createGuestInvite">生成访客链接</button>
      </div>
      <div class="invite-box">
        <strong>邀请 Agent</strong>
        <div class="field"><label>角色</label><select id="agentRole"><option value="reviewer">Reviewer</option><option value="developer">Developer</option><option value="observer">Observer</option><option value="custom">Custom</option></select></div>
        <div class="field"><label>名称</label><input id="agentName" value="Reviewer Agent"></div>
        <button id="createAgentInvite">生成 Agent 链接</button>
      </div>${last}`;
    }
    function renderAdvancedInvite(invite){
      if(invite.type !== 'agent' || !invite.advanced) return '';
      const roomUrl = `${location.origin}/ws/rooms/${invite.advanced.roomId}`;
      return `<details><summary>高级接入信息</summary><div class="mono">room: ${esc(invite.advanced.roomId)}
role: ${esc(invite.advanced.role)}
key: ${esc(invite.advanced.connectorToken)}
realtime: ${esc(roomUrl)}</div></details>`;
    }
    function bindInviteControls(){
      const guest = document.getElementById('createGuestInvite');
      if(guest) guest.addEventListener('click', () => createInvite({type:'guest'}).catch(alert));
      const agent = document.getElementById('createAgentInvite');
      if(agent) agent.addEventListener('click', () => createInvite({type:'agent', role:document.getElementById('agentRole').value, name:document.getElementById('agentName').value}).catch(alert));
      const copy = document.getElementById('copyInvite');
      if(copy) copy.addEventListener('click', () => navigator.clipboard && navigator.clipboard.writeText(state.lastInvite.inviteUrl));
    }
    async function createInvite(payload){
      const invite = await api(`/api/rooms/${encodeURIComponent(state.room.id)}/invites`, {method:'POST', headers:authHeaders(), body:JSON.stringify(payload)});
      await selectRoom(state.room.id);
      state.lastInvite = invite;
      renderSidePanels();
    }
    document.getElementById('createRoom').addEventListener('click', () => createRoom().catch(alert));
    document.getElementById('createDemo').addEventListener('click', () => createDemo().catch(alert));
    document.getElementById('refreshRooms').addEventListener('click', () => loadRooms().catch(alert));
    function submitMessage(){
      const input = document.getElementById('messageInput');
      if(!state.room || !input.value.trim()) return;
      sendSocket({type:'message.create', body:input.value.trim()});
      input.value = '';
    }
    document.getElementById('sendMessage').addEventListener('click', submitMessage);
    document.getElementById('messageInput').addEventListener('keydown', event => {
      if(event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
      event.preventDefault();
      submitMessage();
    });
    document.addEventListener('change', event => {
      if(event.target && event.target.id === 'agentRole'){
        const role = event.target.value;
        const name = role === 'developer' ? 'Developer Agent' : role === 'observer' ? 'Observer Agent' : role === 'custom' ? 'Custom Agent' : 'Reviewer Agent';
        const input = document.getElementById('agentName');
        if(input) input.value = name;
      }
    });
    loadRooms().catch(alert);
  </script>
</body>
</html>""".replace("__INITIAL_INVITE__", json_dumps(initial_invite) if initial_invite else "null")


def index_html(initial_invite: Optional[Dict[str, Any]] = None) -> str:
    return review_room_app_html(initial_invite)

def build_handler(store: ReviewRoomStore):
    class Handler(ReviewRoomHandler):
        pass

    Handler.store = store
    return Handler


def run_server(host: str, port: int, db_path: str) -> None:
    require_aiohttp()
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
