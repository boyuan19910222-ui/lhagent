#!/usr/bin/env python3
"""Lighthouse Agent Board connector service.

The service models the instance-side Agent Board backend: rooms, realtime
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
from urllib.parse import parse_qs, quote, urlparse

from aiohttp import web

from review_room_mcp import AFTER_TOOL_APP_KEY as MCP_AFTER_TOOL_KEY
from review_room_mcp import STORE_APP_KEY as MCP_STORE_KEY
from review_room_mcp import handle_mcp_get, handle_mcp_post


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8707
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "review-room.sqlite3")
REMOTE_CLEANUP_BOUNDARY = (
    "Server-side access state only; this does not clean remote Agent machines, "
    "shell history, MCP config, transcripts, logs, caches, or workspace files."
)


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

                CREATE TABLE IF NOT EXISTS events (
                  cursor INTEGER PRIMARY KEY AUTOINCREMENT,
                  id TEXT NOT NULL,
                  room_id TEXT NOT NULL,
                  type TEXT NOT NULL,
                  actor_type TEXT NOT NULL,
                  actor_name TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  FOREIGN KEY(room_id) REFERENCES rooms(id)
                );

                CREATE TABLE IF NOT EXISTS tasks (
                  id TEXT PRIMARY KEY,
                  room_id TEXT NOT NULL,
                  title TEXT NOT NULL,
                  body TEXT NOT NULL,
                  status TEXT NOT NULL,
                  assigned_to TEXT NOT NULL,
                  claimed_by TEXT NOT NULL,
                  result TEXT NOT NULL,
                  created_by TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  FOREIGN KEY(room_id) REFERENCES rooms(id)
                );

                CREATE TABLE IF NOT EXISTS inbox_items (
                  id TEXT PRIMARY KEY,
                  room_id TEXT NOT NULL,
                  agent_name TEXT NOT NULL,
                  agent_role TEXT NOT NULL,
                  source_event_cursor INTEGER NOT NULL,
                  type TEXT NOT NULL,
                  source_type TEXT NOT NULL,
                  source_id TEXT NOT NULL,
                  priority TEXT NOT NULL,
                  requires_reply INTEGER NOT NULL,
                  status TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  FOREIGN KEY(room_id) REFERENCES rooms(id)
                );

                CREATE TABLE IF NOT EXISTS agent_runs (
                  id TEXT PRIMARY KEY,
                  room_id TEXT NOT NULL,
                  task_id TEXT NOT NULL,
                  connector_id TEXT NOT NULL,
                  agent_name TEXT NOT NULL,
                  status TEXT NOT NULL,
                  prompt_summary TEXT NOT NULL,
                  final_message TEXT NOT NULL,
                  error TEXT NOT NULL,
                  started_at INTEGER NOT NULL,
                  finished_at INTEGER,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  FOREIGN KEY(room_id) REFERENCES rooms(id)
                );

                CREATE TABLE IF NOT EXISTS decisions (
                  id TEXT PRIMARY KEY,
                  room_id TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  status TEXT NOT NULL,
                  requester TEXT NOT NULL,
                  action TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  target_type TEXT NOT NULL,
                  target_id TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  FOREIGN KEY(room_id) REFERENCES rooms(id)
                );

                CREATE TABLE IF NOT EXISTS handoffs (
                  id TEXT PRIMARY KEY,
                  room_id TEXT NOT NULL,
                  source_finding_id TEXT NOT NULL,
                  from_agent TEXT NOT NULL,
                  target_agent TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  suggested_task TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  FOREIGN KEY(room_id) REFERENCES rooms(id)
                );

                CREATE TABLE IF NOT EXISTS threads (
                  id TEXT PRIMARY KEY,
                  room_id TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  status TEXT NOT NULL,
                  title TEXT NOT NULL,
                  summary_json TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  FOREIGN KEY(room_id) REFERENCES rooms(id)
                );

                CREATE TABLE IF NOT EXISTS thread_messages (
                  id TEXT PRIMARY KEY,
                  thread_id TEXT NOT NULL,
                  sender_name TEXT NOT NULL,
                  body TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  FOREIGN KEY(thread_id) REFERENCES threads(id)
                );

                CREATE TABLE IF NOT EXISTS mcp_invites (
                  id TEXT PRIMARY KEY,
                  room_id TEXT NOT NULL,
                  agent_name TEXT NOT NULL,
                  agent_role TEXT NOT NULL,
                  token TEXT NOT NULL UNIQUE,
                  permissions_json TEXT NOT NULL,
                  status TEXT NOT NULL,
                  connector_id TEXT NOT NULL DEFAULT '',
                  expires_at INTEGER NOT NULL,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  FOREIGN KEY(room_id) REFERENCES rooms(id)
                );

                CREATE TABLE IF NOT EXISTS supervisor_invites (
                  id TEXT PRIMARY KEY,
                  room_id TEXT NOT NULL,
                  name TEXT NOT NULL,
                  token TEXT NOT NULL UNIQUE,
                  session_token TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL,
                  expires_at INTEGER NOT NULL,
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
            task_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
            }
            task_column_defaults = {
                "title": "TEXT NOT NULL DEFAULT ''",
                "body": "TEXT NOT NULL DEFAULT ''",
                "assigned_to": "TEXT NOT NULL DEFAULT ''",
                "claimed_by": "TEXT NOT NULL DEFAULT ''",
                "result": "TEXT NOT NULL DEFAULT ''",
            }
            for column, definition in task_column_defaults.items():
                if column not in task_columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN {} {}".format(column, definition))
                    task_columns.add(column)
            if "kind" in task_columns:
                conn.execute("UPDATE tasks SET title = kind WHERE title = ''")
            if "instruction" in task_columns:
                conn.execute("UPDATE tasks SET body = instruction WHERE body = ''")
            if "assigned_connector_id" in task_columns:
                conn.execute("UPDATE tasks SET assigned_to = assigned_connector_id WHERE assigned_to = ''")
            agent_run_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(agent_runs)").fetchall()
            }
            if "agent_name" not in agent_run_columns:
                conn.execute("ALTER TABLE agent_runs ADD COLUMN agent_name TEXT NOT NULL DEFAULT ''")
                conn.execute(
                    """
                    UPDATE agent_runs
                    SET agent_name = COALESCE(
                      (SELECT connectors.name FROM connectors WHERE connectors.id = agent_runs.connector_id),
                      ''
                    )
                    WHERE agent_name = ''
                    """
                )
                conn.execute(
                    """
                    UPDATE agent_runs
                    SET agent_name = COALESCE(
                      (SELECT tasks.claimed_by FROM tasks WHERE tasks.id = agent_runs.task_id),
                      ''
                    )
                    WHERE agent_name = ''
                    """
                )
                conn.execute(
                    """
                    UPDATE agent_runs
                    SET agent_name = COALESCE(
                      (SELECT tasks.assigned_to FROM tasks WHERE tasks.id = agent_runs.task_id),
                      'Agent'
                    )
                    WHERE agent_name = ''
                    """
                )
            decision_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(decisions)").fetchall()
            }
            decision_column_defaults = {
                "kind": "TEXT NOT NULL DEFAULT 'owner_decision'",
                "requester": "TEXT NOT NULL DEFAULT ''",
                "action": "TEXT NOT NULL DEFAULT ''",
                "reason": "TEXT NOT NULL DEFAULT ''",
                "target_type": "TEXT NOT NULL DEFAULT 'sync'",
                "target_id": "TEXT NOT NULL DEFAULT ''",
            }
            for column, definition in decision_column_defaults.items():
                if column not in decision_columns:
                    conn.execute("ALTER TABLE decisions ADD COLUMN {} {}".format(column, definition))
                    decision_columns.add(column)
            if "created_by" in decision_columns:
                conn.execute("UPDATE decisions SET requester = created_by WHERE requester = '' AND created_by != ''")
            if "requested_by_connector_id" in decision_columns:
                conn.execute(
                    """
                    UPDATE decisions
                    SET requester = COALESCE(
                      (SELECT connectors.name FROM connectors WHERE connectors.id = decisions.requested_by_connector_id),
                      requester
                    )
                    WHERE requester = ''
                    """
                )
            if "proposal" in decision_columns:
                conn.execute("UPDATE decisions SET action = proposal WHERE action = '' AND proposal != ''")
            if "question" in decision_columns:
                conn.execute("UPDATE decisions SET action = question WHERE action = '' AND question != ''")
            if "risk" in decision_columns:
                conn.execute("UPDATE decisions SET reason = risk WHERE reason = '' AND risk != ''")
            if "sync_target" in decision_columns:
                conn.execute("UPDATE decisions SET target_id = sync_target WHERE target_id = '' AND sync_target != ''")
            conn.execute("UPDATE decisions SET kind = 'owner_decision' WHERE kind = ''")
            conn.execute("UPDATE decisions SET requester = 'Agent' WHERE requester = ''")
            conn.execute("UPDATE decisions SET action = '请求负责人决策' WHERE action = ''")
            conn.execute("UPDATE decisions SET target_type = 'sync' WHERE target_type = ''")

            handoff_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(handoffs)").fetchall()
            }
            handoff_column_defaults = {
                "from_agent": "TEXT NOT NULL DEFAULT ''",
                "target_agent": "TEXT NOT NULL DEFAULT ''",
            }
            for column, definition in handoff_column_defaults.items():
                if column not in handoff_columns:
                    conn.execute("ALTER TABLE handoffs ADD COLUMN {} {}".format(column, definition))
                    handoff_columns.add(column)
            if "from_connector_id" in handoff_columns:
                conn.execute(
                    """
                    UPDATE handoffs
                    SET from_agent = COALESCE(
                      (SELECT connectors.name FROM connectors WHERE connectors.id = handoffs.from_connector_id),
                      from_agent
                    )
                    WHERE from_agent = ''
                    """
                )
            if "created_by" in handoff_columns:
                conn.execute("UPDATE handoffs SET from_agent = created_by WHERE from_agent = '' AND created_by != ''")
            if "target_json" in handoff_columns:
                for row in conn.execute("SELECT id, target_json FROM handoffs WHERE target_agent = ''").fetchall():
                    target = json_loads(row["target_json"], {})
                    target_agent = (
                        target.get("agentName")
                        or target.get("agent_name")
                        or target.get("name")
                        or target.get("role")
                        or ""
                    )
                    if target_agent:
                        conn.execute(
                            "UPDATE handoffs SET target_agent = ? WHERE id = ?",
                            (target_agent, row["id"]),
                        )
            conn.execute("UPDATE handoffs SET from_agent = 'Agent' WHERE from_agent = ''")
            conn.execute("UPDATE handoffs SET target_agent = 'Developer Agent' WHERE target_agent = ''")

            thread_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(threads)").fetchall()
            }
            if "title" not in thread_columns:
                conn.execute("ALTER TABLE threads ADD COLUMN title TEXT NOT NULL DEFAULT ''")
                thread_columns.add("title")
            if "question" in thread_columns:
                conn.execute("UPDATE threads SET title = question WHERE title = '' AND question != ''")
            conn.execute("UPDATE threads SET title = 'Agent thread' WHERE title = ''")

    def create_room(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = now_ms()
        participants = payload.get("participants") or [
            {"type": "human", "name": "Agent Board owner", "role": "owner"},
            {"type": "agent", "name": "Reviewer Agent", "role": "reviewer"},
            {"type": "agent", "name": "Developer Agent", "role": "developer"},
        ]
        room = {
            "id": make_id("room"),
            "title": payload.get("title") or "未命名 Agent Board",
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
                "senderName": "Lighthouse Agent Board",
                "kind": "room_created",
                "body": "Agent Board 已创建",
                "payload": {"provider": room["provider"], "mrUrl": room["mrUrl"]},
            },
        )
        return self.get_room(room["id"]) or room

    def list_rooms(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM rooms ORDER BY created_at DESC, updated_at DESC").fetchall()
        return [self._room_from_row(row) for row in rows]

    def create_workbench(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        context = dict(payload.get("context") or {})
        context.setdefault("template", payload.get("template") or "mr-review")
        context.setdefault("repository", payload.get("repository") or payload.get("repo") or "")
        context.setdefault("owner", payload.get("owner") or "Agent Board owner")
        context.setdefault(
            "workflow",
            ["intake", "review", "fix", "verify", "decision"],
        )
        room = self.create_room(
            {
                "title": payload.get("title") or "MR Review Workbench",
                "provider": payload.get("provider") or "lighthouse",
                "mrUrl": payload.get("mrUrl") or payload.get("mr_url") or "",
                "ownerToken": payload.get("ownerToken") or payload.get("owner_token"),
                "status": payload.get("status") or "open",
                "context": context,
                "participants": payload.get("participants"),
            }
        )
        self.record_event(
            room["id"],
            "workbench.created",
            {"workbench": self.workbench_summary(room), "template": context["template"]},
            actor_type="human",
            actor_name=context["owner"],
        )
        return self.get_room(room["id"]) or room

    def list_workbenches(self) -> List[Dict[str, Any]]:
        summaries = []
        for room in self.list_rooms():
            loaded = self.get_room(room["id"])
            if loaded:
                summaries.append(self.workbench_summary(loaded))
        return summaries

    def workbench_summary(self, room: Dict[str, Any]) -> Dict[str, Any]:
        context = room.get("context") or {}
        decisions = room.get("decisions") or []
        findings = room.get("findings") or []
        handoffs = room.get("handoffs") or []
        threads = room.get("threads") or []
        agent_runs = room.get("agentRuns") or []
        connectors = room.get("connectors") or []
        pending_owner_actions = sum(1 for decision in decisions if decision.get("status") == "pending")
        pending_owner_actions += sum(1 for finding in findings if finding.get("status") == "developer_responded")
        pending_owner_actions += sum(1 for handoff in handoffs if handoff.get("status") == "proposed")
        pending_owner_actions += sum(
            1
            for thread in threads
            if (thread.get("summary") or {}).get("needs_owner_decision")
        )
        active_run_count = sum(1 for run in agent_runs if run.get("status") in {"running", "started"})
        active_connectors = sum(
            1
            for connector in connectors
            if connector.get("status") in {"connected", "mcp_ready", "mcp_streaming"}
        )
        return {
            "id": room["id"],
            "roomId": room["id"],
            "title": room["title"],
            "status": room["status"],
            "template": context.get("template") or "mr-review",
            "provider": room["provider"],
            "mrUrl": room["mrUrl"],
            "repository": context.get("repository") or "",
            "updatedAt": room["updatedAt"],
            "createdAt": room["createdAt"],
            "counts": {
                "messages": len(room.get("messages") or []),
                "tasks": len(room.get("tasks") or []),
                "findings": len(findings),
                "connectors": len(connectors),
                "decisions": len(decisions),
                "handoffs": len(handoffs),
                "threads": len(threads),
                "inboxItems": len(room.get("inboxItems") or []),
                "agentRuns": len(agent_runs),
                "events": len(room.get("events") or []),
            },
            "pendingOwnerActions": pending_owner_actions,
            "activeRunCount": active_run_count,
            "connectorStatus": {
                "total": len(connectors),
                "active": active_connectors,
                "statuses": [connector.get("status") or "unknown" for connector in connectors],
            },
        }

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
            task_rows = conn.execute(
                "SELECT * FROM tasks WHERE room_id = ? ORDER BY created_at ASC",
                (room_id,),
            ).fetchall()
            inbox_rows = conn.execute(
                "SELECT * FROM inbox_items WHERE room_id = ? ORDER BY created_at ASC",
                (room_id,),
            ).fetchall()
            run_rows = conn.execute(
                "SELECT * FROM agent_runs WHERE room_id = ? ORDER BY created_at ASC",
                (room_id,),
            ).fetchall()
            decision_rows = conn.execute(
                "SELECT * FROM decisions WHERE room_id = ? ORDER BY created_at ASC",
                (room_id,),
            ).fetchall()
            handoff_rows = conn.execute(
                "SELECT * FROM handoffs WHERE room_id = ? ORDER BY created_at ASC",
                (room_id,),
            ).fetchall()
            thread_rows = conn.execute(
                "SELECT * FROM threads WHERE room_id = ? ORDER BY created_at ASC",
                (room_id,),
            ).fetchall()
            event_rows = conn.execute(
                "SELECT * FROM events WHERE room_id = ? ORDER BY cursor ASC",
                (room_id,),
            ).fetchall()
        room = self._room_from_row(room_row)
        room["messages"] = [self._message_from_row(row) for row in message_rows]
        room["findings"] = [self._finding_from_row(row) for row in finding_rows]
        room["connectors"] = [self._connector_from_row(row) for row in connector_rows]
        room["tasks"] = [self._task_from_row(row) for row in task_rows]
        room["inboxItems"] = [self._inbox_item_from_row(row) for row in inbox_rows]
        room["agentRuns"] = [self._agent_run_from_row(row) for row in run_rows]
        room["decisions"] = [self._decision_from_row(row) for row in decision_rows]
        room["handoffs"] = [self._handoff_from_row(row) for row in handoff_rows]
        room["threads"] = [self._thread_from_row(row) for row in thread_rows]
        room["events"] = [self._event_from_row(row) for row in event_rows]
        return room

    def require_owner_token(self, room_id: str, token: str) -> Dict[str, Any]:
        identity = self.authenticate_room_token(room_id, token)
        if identity["type"] != "owner":
            raise PermissionError("owner token required")
        return identity

    def update_workbench(self, room_id: str, payload: Dict[str, Any], token: str) -> Dict[str, Any]:
        identity = self.require_owner_token(room_id, token)
        room = self.get_room(room_id)
        if not room:
            raise KeyError("room not found")
        timestamp = now_ms()
        title = payload.get("title") or room["title"]
        status = payload.get("status") or room["status"]
        context = dict(room.get("context") or {})
        if "repository" in payload:
            context["repository"] = payload.get("repository") or ""
        if "template" in payload:
            context["template"] = payload.get("template") or "mr-review"
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE rooms
                SET title = ?, status = ?, context_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (title, status, json_dumps(context), timestamp, room_id),
            )
        event_type = "workbench.renamed" if title != room["title"] else "workbench.updated"
        self.record_event(
            room_id,
            event_type,
            {"title": title, "status": status, "context": context},
            actor_type="human",
            actor_name=identity["name"],
        )
        return self.get_room(room_id) or room

    def archive_workbench(self, room_id: str, token: str) -> Dict[str, Any]:
        identity = self.require_owner_token(room_id, token)
        room = self._set_workbench_status(room_id, "archived")
        self.record_event(
            room_id,
            "workbench.archived",
            {"status": "archived"},
            actor_type="human",
            actor_name=identity["name"],
        )
        return self.get_room(room_id) or room

    def restore_workbench(self, room_id: str, token: str) -> Dict[str, Any]:
        identity = self.require_owner_token(room_id, token)
        room = self._set_workbench_status(room_id, "open")
        self.record_event(
            room_id,
            "workbench.restored",
            {"status": "open"},
            actor_type="human",
            actor_name=identity["name"],
        )
        return self.get_room(room_id) or room

    def delete_workbench(self, room_id: str, payload: Dict[str, Any], token: str) -> Dict[str, Any]:
        identity = self.require_owner_token(room_id, token)
        if not payload.get("confirm"):
            raise ValueError("delete requires owner confirmation")
        cleanup_boundary = REMOTE_CLEANUP_BOUNDARY
        room = self._set_workbench_status(room_id, "deleted")
        self.record_event(
            room_id,
            "workbench.deleted",
            {
                "status": "deleted",
                "reason": payload.get("reason") or "",
                "cleanupBoundary": cleanup_boundary,
            },
            actor_type="human",
            actor_name=identity["name"],
        )
        deleted = self.get_room(room_id) or room
        deleted["cleanupBoundary"] = cleanup_boundary
        return deleted

    def _set_workbench_status(self, room_id: str, status: str) -> Dict[str, Any]:
        self.require_room(room_id)
        timestamp = now_ms()
        with self.connect() as conn:
            conn.execute(
                "UPDATE rooms SET status = ?, updated_at = ? WHERE id = ?",
                (status, timestamp, room_id),
            )
        room = self.get_room(room_id)
        if not room:
            raise KeyError("room not found")
        return room

    def record_event(
        self,
        room_id: str,
        event_type: str,
        payload: Dict[str, Any],
        actor_type: str = "system",
        actor_name: str = "Agent Board",
    ) -> Dict[str, Any]:
        self.require_room(room_id)
        timestamp = now_ms()
        event_id = make_id("evt")
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events
                  (id, room_id, type, actor_type, actor_name, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                RETURNING cursor
                """,
                (event_id, room_id, event_type, actor_type, actor_name, json_dumps(payload), timestamp),
            ).fetchone()["cursor"]
        return {
            "id": event_id,
            "cursor": cursor,
            "roomId": room_id,
            "type": event_type,
            "actorType": actor_type,
            "actorName": actor_name,
            "payload": payload,
            "createdAt": timestamp,
        }

    def list_room_events(self, room_id: str, after_cursor: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        self.require_room(room_id)
        safe_limit = max(1, min(int(limit or 100), 500))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM events
                WHERE room_id = ? AND cursor > ?
                ORDER BY cursor ASC
                LIMIT ?
                """,
                (room_id, int(after_cursor or 0), safe_limit),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def record_message_mentions(self, room_id: str, message: Dict[str, Any]) -> None:
        for agent in self.resolve_message_mentions(room_id, message):
            self.record_event(
                room_id,
                "mention.requires_reply",
                {"targetAgentName": agent["name"], "targetAgentId": agent.get("id", ""), "message": message},
                actor_type=message["senderType"],
                actor_name=message["senderName"],
            )

    def board_agents(self, room_id: str) -> List[Dict[str, str]]:
        room = self.get_room(room_id)
        if not room:
            return []
        agents: List[Dict[str, str]] = []
        seen = set()
        for participant in room.get("participants", []):
            if participant.get("type") != "agent" or not participant.get("name"):
                continue
            key = participant["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            agents.append({"name": participant["name"], "role": participant.get("role") or ""})
        for connector in room.get("connectors", []):
            key = connector["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            agents.append({"name": connector["name"], "role": connector.get("agentRole") or ""})
        return agents

    def record_message_inbox_items(
        self,
        room_id: str,
        message: Dict[str, Any],
        source_event: Dict[str, Any],
    ) -> None:
        if message.get("senderType") == "system":
            return
        mentions = {agent["name"] for agent in self.resolve_message_mentions(room_id, message)}
        timestamp = now_ms()
        rows = []
        for agent in self.board_agents(room_id):
            if message.get("senderType") == "agent" and message.get("senderName") == agent["name"]:
                continue
            mentioned = agent["name"] in mentions
            rows.append(
                (
                    make_id("inbox"),
                    room_id,
                    agent["name"],
                    agent.get("role", ""),
                    int(source_event["cursor"]),
                    "message",
                    "message",
                    message["id"],
                    "high" if mentioned else "normal",
                    1 if mentioned else 0,
                    "unread",
                    "mention" if mentioned else "supervision_message",
                    json_dumps({"message": message}),
                    timestamp,
                    timestamp,
                )
            )
        if not rows:
            return
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO inbox_items
                  (id, room_id, agent_name, agent_role, source_event_cursor, type, source_type,
                   source_id, priority, requires_reply, status, reason, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def list_inbox(self, room_id: str, agent_name: str, include_handled: bool = False) -> List[Dict[str, Any]]:
        self.require_room(room_id)
        with self.connect() as conn:
            if include_handled:
                rows = conn.execute(
                    """
                    SELECT * FROM inbox_items
                    WHERE room_id = ? AND agent_name = ?
                    ORDER BY source_event_cursor ASC, created_at ASC
                    """,
                    (room_id, agent_name),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM inbox_items
                    WHERE room_id = ? AND agent_name = ? AND status NOT IN ('handled', 'ignored')
                    ORDER BY source_event_cursor ASC, created_at ASC
                    """,
                    (room_id, agent_name),
                ).fetchall()
        return [self._inbox_item_from_row(row) for row in rows]

    def ack_event(self, room_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.require_room(room_id)
        agent_name = payload.get("agentName") or payload.get("agent_name")
        item_id = payload.get("inboxItemId") or payload.get("inbox_item_id")
        cursor = payload.get("cursor")
        status = payload.get("status") or "read"
        if not agent_name:
            raise ValueError("agentName is required")
        if status not in {"unread", "read", "ack", "handled", "ignored"}:
            raise ValueError("invalid inbox status")
        if not item_id and cursor is None:
            raise ValueError("inboxItemId or cursor is required")
        timestamp = now_ms()
        with self.connect() as conn:
            if item_id:
                row = conn.execute(
                    """
                    SELECT * FROM inbox_items
                    WHERE id = ? AND room_id = ? AND agent_name = ?
                    """,
                    (item_id, room_id, agent_name),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM inbox_items
                    WHERE source_event_cursor = ? AND room_id = ? AND agent_name = ?
                    """,
                    (int(cursor), room_id, agent_name),
                ).fetchone()
            if not row:
                raise KeyError("inbox item not found")
            conn.execute(
                "UPDATE inbox_items SET status = ?, updated_at = ? WHERE id = ?",
                (status, timestamp, row["id"]),
            )
            updated = conn.execute("SELECT * FROM inbox_items WHERE id = ?", (row["id"],)).fetchone()
        item = self._inbox_item_from_row(updated)
        self.record_event(
            room_id,
            "inbox.acknowledged",
            {"inboxItem": item},
            actor_type="agent",
            actor_name=agent_name,
        )
        return item

    def resolve_message_mentions(self, room_id: str, message: Dict[str, Any]) -> List[Dict[str, str]]:
        room = self.get_room(room_id)
        if not room:
            return []
        candidates: List[Dict[str, str]] = []
        for participant in room.get("participants", []):
            if participant.get("type") == "agent" and participant.get("name"):
                candidates.append(
                    {
                        "id": participant.get("id") or participant.get("name"),
                        "name": participant["name"],
                        "role": participant.get("role") or "",
                    }
                )
        for connector in room.get("connectors", []):
            candidates.append({"id": connector["id"], "name": connector["name"], "role": connector.get("agentRole") or ""})

        body = message.get("body") or ""
        structured = message.get("payload", {}).get("mentions") or message.get("payload", {}).get("mentionedAgents") or []
        if isinstance(structured, str):
            structured = [structured]
        structured_normalized = {str(item).strip().lower() for item in structured}
        body_normalized = body.lower()

        seen = set()
        matched: List[Dict[str, str]] = []
        for candidate in candidates:
            name = candidate["name"]
            candidate_id = candidate.get("id", "")
            if name in seen:
                continue
            if message.get("senderType") == "agent" and message.get("senderName") == name:
                continue
            aliases = self.mention_aliases(candidate)
            explicit_body_match = any(
                re.search(r"@{}\b".format(re.escape(alias)), body_normalized)
                for alias in aliases
            )
            structured_match = name.lower() in structured_normalized or candidate_id.lower() in structured_normalized
            structured_match = structured_match or any(alias in structured_normalized for alias in aliases)
            if explicit_body_match or structured_match:
                seen.add(name)
                matched.append(candidate)
        return matched

    def mention_aliases(self, candidate: Dict[str, str]) -> List[str]:
        name = (candidate.get("name") or "").strip().lower()
        role = (candidate.get("role") or "").strip().lower()
        aliases = {name}
        if name.endswith(" agent"):
            aliases.add(name[: -len(" agent")])
        if role:
            aliases.add(role)
        if role == "developer":
            aliases.add("dev")
        if role == "reviewer":
            aliases.add("review")
        return [alias for alias in aliases if alias]

    def create_task(self, room_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.require_room(room_id)
        timestamp = now_ms()
        task = {
            "id": make_id("task"),
            "roomId": room_id,
            "title": payload.get("title") or "未命名任务",
            "body": payload.get("body") or "",
            "status": payload.get("status") or "assigned",
            "assignedTo": payload.get("assignedTo") or payload.get("assigned_to") or "",
            "claimedBy": payload.get("claimedBy") or payload.get("claimed_by") or "",
            "result": payload.get("result") or "",
            "createdBy": payload.get("createdBy") or payload.get("created_by") or "Agent Board owner",
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        with self.connect() as conn:
            columns = [
                "id",
                "room_id",
                "title",
                "body",
                "status",
                "assigned_to",
                "claimed_by",
                "result",
                "created_by",
                "created_at",
                "updated_at",
            ]
            values: List[Any] = [
                task["id"],
                room_id,
                task["title"],
                task["body"],
                task["status"],
                task["assignedTo"],
                task["claimedBy"],
                task["result"],
                task["createdBy"],
                timestamp,
                timestamp,
            ]
            task_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
            }
            legacy_values = {
                "kind": task["title"],
                "instruction": task["body"],
                "target_json": json_dumps({"assignedTo": task["assignedTo"]}),
                "source_json": json_dumps({"createdBy": task["createdBy"]}),
                "assigned_connector_id": task["assignedTo"],
                "lease_expires_at": None,
            }
            for column, value in legacy_values.items():
                if column in task_columns and column not in columns:
                    columns.append(column)
                    values.append(value)
            conn.execute(
                "INSERT INTO tasks ({}) VALUES ({})".format(
                    ", ".join(columns),
                    ", ".join(["?"] * len(columns)),
                ),
                tuple(values),
            )
            conn.execute("UPDATE rooms SET updated_at = ? WHERE id = ?", (timestamp, room_id))
        self.record_event(room_id, "task.assigned", {"task": task}, actor_type="human", actor_name=task["createdBy"])
        return task

    def list_tasks(self, room_id: str, assigned_to: str = "") -> List[Dict[str, Any]]:
        self.require_room(room_id)
        with self.connect() as conn:
            if assigned_to:
                rows = conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE room_id = ? AND (assigned_to = ? OR assigned_to = '')
                    ORDER BY created_at ASC
                    """,
                    (room_id, assigned_to),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE room_id = ? ORDER BY created_at ASC",
                    (room_id,),
                ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def get_task(self, task_id: str) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise KeyError("task not found")
        return self._task_from_row(row)

    def claim_task(self, task_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        task = self.get_task(task_id)
        agent_name = payload.get("agentName") or payload.get("agent_name") or payload.get("claimedBy") or ""
        if task["assignedTo"] and agent_name and task["assignedTo"] != agent_name:
            raise PermissionError("task assigned to {}".format(task["assignedTo"]))
        if task["status"] not in {"assigned", "running"}:
            raise ValueError("task cannot be claimed from {}".format(task["status"]))
        return self.update_task(task_id, {"status": "running", "claimedBy": agent_name, "agentName": agent_name})

    def update_task(self, task_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        task = self.get_task(task_id)
        status = payload.get("status") or task["status"]
        if status not in {"assigned", "running", "completed", "failed", "cancelled"}:
            raise ValueError("invalid task status")
        timestamp = now_ms()
        claimed_by = payload.get("claimedBy") or payload.get("claimed_by") or payload.get("agentName") or task["claimedBy"]
        result = payload.get("result") if "result" in payload else task["result"]
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, claimed_by = ?, result = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, claimed_by, result or "", timestamp, task_id),
            )
            conn.execute("UPDATE rooms SET updated_at = ? WHERE id = ?", (timestamp, task["roomId"]))
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        updated = self._task_from_row(row)
        self.record_event(
            updated["roomId"],
            "task.updated",
            {"task": updated},
            actor_type="agent" if claimed_by else "system",
            actor_name=claimed_by or "Agent Board",
        )
        return updated

    def start_run(self, task_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        task = self.get_task(task_id)
        agent_name = payload.get("agentName") or payload.get("agent_name") or payload.get("claimedBy") or task["claimedBy"] or task["assignedTo"]
        if task["assignedTo"] and agent_name and task["assignedTo"] != agent_name:
            raise PermissionError("task assigned to {}".format(task["assignedTo"]))
        timestamp = now_ms()
        if task["status"] != "running" or task["claimedBy"] != agent_name:
            self.update_task(task_id, {"status": "running", "claimedBy": agent_name, "agentName": agent_name})
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT * FROM agent_runs
                WHERE task_id = ? AND agent_name = ? AND status = 'running'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (task_id, agent_name),
            ).fetchone()
            if existing:
                return self._agent_run_from_row(existing)
            run = {
                "id": make_id("run"),
                "roomId": task["roomId"],
                "taskId": task_id,
                "connectorId": payload.get("connectorId") or payload.get("connector_id") or "",
                "agentName": agent_name,
                "status": "running",
                "promptSummary": payload.get("promptSummary") or payload.get("prompt_summary") or task["title"],
                "finalMessage": "",
                "error": "",
                "startedAt": timestamp,
                "finishedAt": None,
                "createdAt": timestamp,
                "updatedAt": timestamp,
            }
            conn.execute(
                """
                INSERT INTO agent_runs
                  (id, room_id, task_id, connector_id, agent_name, status, prompt_summary,
                   final_message, error, started_at, finished_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run["id"],
                    run["roomId"],
                    run["taskId"],
                    run["connectorId"],
                    run["agentName"],
                    run["status"],
                    run["promptSummary"],
                    run["finalMessage"],
                    run["error"],
                    run["startedAt"],
                    run["finishedAt"],
                    run["createdAt"],
                    run["updatedAt"],
                ),
            )
        self.record_event(
            task["roomId"],
            "agent_run.started",
            {"agentRun": run},
            actor_type="agent",
            actor_name=agent_name,
        )
        return run

    def complete_task(self, task_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        task = self.get_task(task_id)
        agent_name = payload.get("agentName") or payload.get("agent_name") or task["claimedBy"] or task["assignedTo"]
        status = payload.get("status") or "completed"
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError("task completion status must be completed, failed, or cancelled")
        final_message = payload.get("finalMessage") or payload.get("final_message") or payload.get("result") or ""
        if not self._latest_running_run(task_id, agent_name):
            self.start_run(task_id, {"agentName": agent_name, "promptSummary": payload.get("promptSummary") or task["title"]})
        updated_task = self.update_task(
            task_id,
            {
                "status": status,
                "claimedBy": agent_name,
                "agentName": agent_name,
                "result": final_message,
            },
        )
        timestamp = now_ms()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_runs
                WHERE task_id = ? AND agent_name = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (task_id, agent_name),
            ).fetchone()
            if not row:
                raise KeyError("agent run not found")
            conn.execute(
                """
                UPDATE agent_runs
                SET status = ?, final_message = ?, error = ?, finished_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    final_message,
                    payload.get("error") or "",
                    timestamp,
                    timestamp,
                    row["id"],
                ),
            )
            updated_run = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (row["id"],)).fetchone()
        run = self._agent_run_from_row(updated_run)
        self.record_event(
            task["roomId"],
            "agent_run.completed" if status == "completed" else "agent_run.{}".format(status),
            {"agentRun": run, "task": updated_task},
            actor_type="agent",
            actor_name=agent_name,
        )
        return {"task": updated_task, "run": run, "roomId": task["roomId"]}

    def _latest_running_run(self, task_id: str, agent_name: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_runs
                WHERE task_id = ? AND agent_name = ? AND status = 'running'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (task_id, agent_name),
            ).fetchone()
        return self._agent_run_from_row(row) if row else None

    def request_owner_confirmation(self, room_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.require_room(room_id)
        timestamp = now_ms()
        decision = {
            "id": make_id("decision"),
            "roomId": room_id,
            "kind": payload.get("kind") or "owner_confirmation",
            "status": payload.get("status") or "pending",
            "requester": payload.get("requester") or payload.get("agentName") or payload.get("agent_name") or "Agent",
            "action": payload.get("action") or "",
            "reason": payload.get("reason") or "",
            "targetType": payload.get("targetType") or payload.get("target_type") or "",
            "targetId": payload.get("targetId") or payload.get("target_id") or "",
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO decisions
                  (id, room_id, kind, status, requester, action, reason, target_type, target_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision["id"],
                    room_id,
                    decision["kind"],
                    decision["status"],
                    decision["requester"],
                    decision["action"],
                    decision["reason"],
                    decision["targetType"],
                    decision["targetId"],
                    timestamp,
                    timestamp,
                ),
            )
        self.record_event(
            room_id,
            "decision.requested",
            {"decision": decision},
            actor_type="agent",
            actor_name=decision["requester"],
        )
        return decision

    def propose_handoff(self, finding_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        finding = self.get_finding(finding_id)
        timestamp = now_ms()
        handoff = {
            "id": make_id("handoff"),
            "roomId": finding["roomId"],
            "sourceFindingId": finding_id,
            "fromAgent": payload.get("fromAgent") or payload.get("from_agent") or payload.get("agentName") or finding["createdBy"],
            "targetAgent": payload.get("targetAgent") or payload.get("target_agent") or payload.get("target") or "Developer Agent",
            "reason": payload.get("reason") or "",
            "suggestedTask": payload.get("suggestedTask") or payload.get("suggested_task") or "",
            "status": payload.get("status") or "proposed",
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO handoffs
                  (id, room_id, source_finding_id, from_agent, target_agent, reason, suggested_task, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    handoff["id"],
                    handoff["roomId"],
                    handoff["sourceFindingId"],
                    handoff["fromAgent"],
                    handoff["targetAgent"],
                    handoff["reason"],
                    handoff["suggestedTask"],
                    handoff["status"],
                    timestamp,
                    timestamp,
                ),
            )
        self.record_event(
            handoff["roomId"],
            "handoff.proposed",
            {"handoff": handoff},
            actor_type="agent",
            actor_name=handoff["fromAgent"],
        )
        return handoff

    def create_mcp_invite(self, room_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.require_room(room_id)
        timestamp = now_ms()
        ttl_ms = int(payload.get("ttlMs") or payload.get("ttl_ms") or 24 * 60 * 60 * 1000)
        agent_role = payload.get("agentRole") or payload.get("agent_role") or payload.get("role") or "reviewer"
        permissions = (
            payload["permissions"]
            if "permissions" in payload and payload.get("permissions") is not None
            else self.default_mcp_permissions(agent_role)
        )
        invite = {
            "id": make_id("mcpi"),
            "roomId": room_id,
            "agentName": payload.get("agentName") or payload.get("agent_name") or "Remote Agent",
            "agentRole": agent_role,
            "token": payload.get("token") or make_id("mcp"),
            "permissions": permissions,
            "status": "provisioned",
            "connectorId": "",
            "expiresAt": timestamp + ttl_ms,
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO mcp_invites
                  (id, room_id, agent_name, agent_role, token, permissions_json, status, connector_id, expires_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invite["id"],
                    room_id,
                    invite["agentName"],
                    invite["agentRole"],
                    invite["token"],
                    json_dumps(invite["permissions"]),
                    invite["status"],
                    invite["connectorId"],
                    invite["expiresAt"],
                    invite["createdAt"],
                    invite["updatedAt"],
                ),
            )
        self.record_event(room_id, "mcp.invite_created", {"inviteId": invite["id"], "agentName": invite["agentName"]})
        return invite

    def create_supervisor_invite(self, room_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.require_room(room_id)
        timestamp = now_ms()
        ttl_ms = int(payload.get("ttlMs") or payload.get("ttl_ms") or 24 * 60 * 60 * 1000)
        invite = {
            "id": make_id("supi"),
            "roomId": room_id,
            "name": payload.get("name") or payload.get("supervisorName") or payload.get("supervisor_name") or "Supervisor",
            "role": "supervisor",
            "token": payload.get("token") or make_id("sup"),
            "sessionToken": "",
            "status": "provisioned",
            "expiresAt": timestamp + ttl_ms,
            "usedAt": None,
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO supervisor_invites
                  (id, room_id, name, token, session_token, status, expires_at, used_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invite["id"],
                    room_id,
                    invite["name"],
                    invite["token"],
                    invite["sessionToken"],
                    invite["status"],
                    invite["expiresAt"],
                    invite["usedAt"],
                    invite["createdAt"],
                    invite["updatedAt"],
                ),
            )
        self.record_event(
            room_id,
            "supervisor.invite_created",
            {"inviteId": invite["id"], "name": invite["name"]},
            actor_type="human",
            actor_name="Agent Board owner",
        )
        return invite

    def consume_supervisor_invite(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not token:
            raise PermissionError("missing supervisor invite token")
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM supervisor_invites WHERE token = ?", (token,)).fetchone()
        if not row:
            raise PermissionError("invalid supervisor invite token")
        invite = self._supervisor_invite_from_row(row)
        room_id = payload.get("roomId") or payload.get("room_id") or invite["roomId"]
        if room_id != invite["roomId"]:
            raise PermissionError("supervisor invite is scoped to another room")
        if invite["status"] != "provisioned" or invite["sessionToken"]:
            raise PermissionError("supervisor invite already used")
        if invite["expiresAt"] < now_ms():
            raise PermissionError("supervisor invite expired")
        timestamp = now_ms()
        session_token = make_id("rrs")
        with self.connect() as conn:
            result = conn.execute(
                """
                UPDATE supervisor_invites
                SET status = ?, session_token = ?, used_at = ?, updated_at = ?
                WHERE id = ? AND status = ? AND session_token = ?
                """,
                ("used", session_token, timestamp, timestamp, invite["id"], "provisioned", ""),
            )
            if result.rowcount != 1:
                raise PermissionError("supervisor invite already used")
        self.add_human_participant(room_id, invite["name"], "supervisor")
        self.record_event(
            room_id,
            "supervisor.joined",
            {"inviteId": invite["id"], "name": invite["name"]},
            actor_type="human",
            actor_name=invite["name"],
        )
        return {
            "roomId": room_id,
            "name": invite["name"],
            "role": "supervisor",
            "accessToken": session_token,
            "token": session_token,
            "room": self.get_room(room_id),
        }

    def add_human_participant(self, room_id: str, name: str, role: str) -> None:
        timestamp = now_ms()
        with self.connect() as conn:
            row = conn.execute("SELECT participants_json FROM rooms WHERE id = ?", (room_id,)).fetchone()
            if not row:
                raise KeyError("room not found")
            participants = json_loads(row["participants_json"], [])
            participant = {"type": "human", "name": name, "role": role}
            exists = any(
                item.get("type") == participant["type"]
                and item.get("name") == participant["name"]
                and item.get("role") == participant["role"]
                for item in participants
            )
            if exists:
                return
            participants.append(participant)
            conn.execute(
                "UPDATE rooms SET participants_json = ?, updated_at = ? WHERE id = ?",
                (json_dumps(participants), timestamp, room_id),
            )

    def remove_human_participant(self, room_id: str, name: str, role: str) -> None:
        timestamp = now_ms()
        with self.connect() as conn:
            row = conn.execute("SELECT participants_json FROM rooms WHERE id = ?", (room_id,)).fetchone()
            if not row:
                raise KeyError("room not found")
            participants = json_loads(row["participants_json"], [])
            filtered = [
                item
                for item in participants
                if not (
                    item.get("type") == "human"
                    and item.get("name") == name
                    and item.get("role") == role
                )
            ]
            conn.execute(
                "UPDATE rooms SET participants_json = ?, updated_at = ? WHERE id = ?",
                (json_dumps(filtered), timestamp, room_id),
            )

    def active_lifecycle_counts(self, room_id: str, connector: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
        connector_id = (connector or {}).get("id") or ""
        agent_name = (connector or {}).get("name") or ""
        active_task_statuses = {"assigned", "running", "started"}
        active_run_statuses = {"running", "started"}
        room = self.get_room(room_id)
        if not room:
            raise KeyError("room not found")
        tasks = room.get("tasks") or []
        runs = room.get("agentRuns") or []
        if agent_name:
            tasks = [
                task
                for task in tasks
                if task.get("assignedTo") == agent_name or task.get("claimedBy") == agent_name
            ]
            runs = [
                run
                for run in runs
                if run.get("connectorId") == connector_id or run.get("agentName") == agent_name
            ]
        return {
            "activeTaskCount": sum(1 for task in tasks if task.get("status") in active_task_statuses),
            "activeRunCount": sum(1 for run in runs if run.get("status") in active_run_statuses),
        }

    def leave_supervisor_session(self, room_id: str, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not token:
            raise PermissionError("missing supervisor token")
        timestamp = now_ms()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM supervisor_invites WHERE room_id = ? AND session_token = ? AND status = ?",
                (room_id, token, "used"),
            ).fetchone()
            if not row:
                raise PermissionError("invalid supervisor session")
            invite = self._supervisor_invite_from_row(row)
            conn.execute(
                "UPDATE supervisor_invites SET status = ?, updated_at = ? WHERE id = ?",
                ("left", timestamp, invite["id"]),
            )
        self.remove_human_participant(room_id, invite["name"], "supervisor")
        counts = self.active_lifecycle_counts(room_id)
        reason = payload.get("reason") or ""
        self.record_event(
            room_id,
            "supervisor.left",
            {
                "sessionId": invite["id"],
                "name": invite["name"],
                "reason": reason,
                **counts,
                "cleanupBoundary": REMOTE_CLEANUP_BOUNDARY,
            },
            actor_type="human",
            actor_name=invite["name"],
        )
        invite["status"] = "left"
        invite["updatedAt"] = timestamp
        invite["reason"] = reason
        invite["cleanupBoundary"] = REMOTE_CLEANUP_BOUNDARY
        return invite

    def get_mcp_invite_by_token(self, token: str) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM mcp_invites WHERE token = ?", (token,)).fetchone()
        if not row:
            raise PermissionError("invalid mcp token")
        return self._mcp_invite_from_row(row)

    def join_mcp_room(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        invite = self.get_mcp_invite_by_token(token)
        room_id = payload.get("roomId") or payload.get("room_id") or invite["roomId"]
        if room_id != invite["roomId"]:
            raise PermissionError("mcp token is scoped to another room")
        if invite["status"] == "revoked":
            raise PermissionError("mcp invite revoked")
        if invite["expiresAt"] < now_ms():
            raise PermissionError("mcp invite expired")
        connector_id = invite["connectorId"]
        if not connector_id:
            connector = self.register_connector(
                room_id,
                {
                    "name": invite["agentName"],
                    "kind": "mcp-agent",
                    "role": invite["agentRole"],
                    "token": token,
                    "status": "connected",
                },
            )
            connector_id = connector["id"]
            timestamp = now_ms()
            with self.connect() as conn:
                conn.execute(
                    """
                    UPDATE mcp_invites
                    SET status = ?, connector_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    ("joined", connector_id, timestamp, invite["id"]),
                )
        else:
            connector = self.get_connector(connector_id)
            if connector["status"] == "revoked":
                raise PermissionError("mcp connector revoked")
        self.mark_connector_seen(connector_id)
        identity = self.authenticate_mcp_token(token)
        self.record_event(room_id, "mcp.agent_joined", {"agentName": identity["name"], "agentRole": identity["role"]})
        return identity

    def authenticate_mcp_token(self, token: str) -> Dict[str, Any]:
        if not token:
            raise PermissionError("missing mcp token")
        with self.connect() as conn:
            connector = conn.execute("SELECT * FROM connectors WHERE token = ?", (token,)).fetchone()
        if not connector:
            raise PermissionError("mcp session has not joined a room")
        data = self._connector_from_row(connector)
        if data["status"] == "revoked":
            raise PermissionError("mcp connector revoked")
        if data["status"] == "disconnected":
            raise PermissionError("mcp agent left the room; call join_room before using tools")
        return {
            "type": "mcp-agent",
            "roomId": data["roomId"],
            "connectorId": data["id"],
            "name": data["name"],
            "role": data["agentRole"],
            "kind": data["kind"],
            "sessionToken": token,
            "token": token,
        }

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
        message_event = self.record_event(
            room_id,
            "message.created",
            {"message": message},
            actor_type=message["senderType"],
            actor_name=message["senderName"],
        )
        self.record_message_inbox_items(room_id, message, message_event)
        self.record_message_mentions(room_id, message)
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
        self.record_event(
            room_id,
            "finding.created",
            {"finding": finding},
            actor_type="agent",
            actor_name=finding["createdBy"],
        )
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
        finding = self._finding_from_row(updated)
        self.record_event(
            finding["roomId"],
            "finding.updated",
            {"finding": finding},
            actor_type=payload.get("actorType") or "system",
            actor_name=payload.get("actorName") or "Agent Board",
        )
        return finding

    def create_demo_session(self) -> Dict[str, Any]:
        room = self.create_room(
            {
                "title": "MR: Agent Board 权限边界体验",
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
                "body": "收到 demo MR 更新，已创建 Agent Board 并载入变更上下文。",
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
        if connector["status"] == "revoked":
            raise PermissionError("mcp connector revoked")
        if connector["status"] == "disconnected":
            raise PermissionError("mcp agent left the room; call join_room before using tools")
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
        title = attrs.get("title") or payload.get("title") or "MR Agent Board"
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
                "body": "收到 {} 事件，已进入 Agent Board".format(provider),
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

    def update_connector_status(self, connector_id: str, status: str) -> Dict[str, Any]:
        timestamp = now_ms()
        with self.connect() as conn:
            row = conn.execute("SELECT room_id FROM connectors WHERE id = ?", (connector_id,)).fetchone()
            if not row:
                raise KeyError("connector not found")
            conn.execute(
                "UPDATE connectors SET status = ?, updated_at = ? WHERE id = ?",
                (status, timestamp, connector_id),
            )
            conn.execute("UPDATE rooms SET updated_at = ? WHERE id = ?", (timestamp, row["room_id"]))
            updated = conn.execute("SELECT * FROM connectors WHERE id = ?", (connector_id,)).fetchone()
        return self._connector_from_row(updated)

    def leave_connector(self, connector_id: str, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        connector = self.get_connector(connector_id)
        if not token or token != connector["token"]:
            raise PermissionError("invalid connector token")
        if connector["status"] == "revoked":
            raise PermissionError("mcp connector revoked")
        updated = self.update_connector_status(connector_id, "disconnected")
        counts = self.active_lifecycle_counts(connector["roomId"], connector)
        reason = payload.get("reason") or ""
        self.record_event(
            connector["roomId"],
            "mcp.agent_left",
            {
                "connectorId": connector_id,
                "agentName": connector["name"],
                "agentRole": connector["agentRole"],
                "reason": reason,
                **counts,
                "cleanupBoundary": REMOTE_CLEANUP_BOUNDARY,
            },
            actor_type="agent",
            actor_name=connector["name"],
        )
        updated["reason"] = reason
        updated["cleanupBoundary"] = REMOTE_CLEANUP_BOUNDARY
        return updated

    def revoke_connector(self, room_id: str, connector_id: str, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        identity = self.require_owner_token(room_id, token)
        connector = self.get_connector(connector_id)
        if connector["roomId"] != room_id:
            raise PermissionError("connector is scoped to another room")
        updated = self.update_connector_status(connector_id, "revoked")
        timestamp = now_ms()
        with self.connect() as conn:
            conn.execute(
                "UPDATE mcp_invites SET status = ?, updated_at = ? WHERE connector_id = ?",
                ("revoked", timestamp, connector_id),
            )
        counts = self.active_lifecycle_counts(room_id, connector)
        reason = payload.get("reason") or ""
        self.record_event(
            room_id,
            "mcp.agent_revoked",
            {
                "connectorId": connector_id,
                "agentName": connector["name"],
                "agentRole": connector["agentRole"],
                "reason": reason,
                **counts,
                "cleanupBoundary": REMOTE_CLEANUP_BOUNDARY,
            },
            actor_type="human",
            actor_name=identity["name"],
        )
        updated["reason"] = reason
        updated["cleanupBoundary"] = REMOTE_CLEANUP_BOUNDARY
        return updated

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
                    "name": "Agent Board owner",
                    "role": "owner",
                    "token": token,
                }
            connector = conn.execute(
                "SELECT * FROM connectors WHERE room_id = ? AND token = ?",
                (room_id, token),
            ).fetchone()
            supervisor = conn.execute(
                "SELECT * FROM supervisor_invites WHERE room_id = ? AND session_token = ? AND status = ?",
                (room_id, token, "used"),
            ).fetchone()
        if connector:
            data = self._connector_from_row(connector)
            if data["status"] == "revoked":
                raise PermissionError("mcp connector revoked")
            if data["status"] == "disconnected":
                raise PermissionError("mcp agent left the room; call join_room before using tools")
            return {
                "type": "connector",
                "roomId": room_id,
                "connectorId": data["id"],
                "name": data["name"],
                "role": data["agentRole"],
                "kind": data["kind"],
                "token": token,
            }
        if supervisor:
            data = self._supervisor_invite_from_row(supervisor)
            return {
                "type": "supervisor",
                "roomId": room_id,
                "name": data["name"],
                "role": data["role"],
                "token": token,
            }
        raise PermissionError("invalid room token")

    def mark_connector_seen(self, connector_id: str) -> None:
        timestamp = now_ms()
        with self.connect() as conn:
            row = conn.execute("SELECT room_id FROM connectors WHERE id = ?", (connector_id,)).fetchone()
            if not row:
                raise KeyError("connector not found")
            connector = conn.execute("SELECT status FROM connectors WHERE id = ?", (connector_id,)).fetchone()
            if connector and connector["status"] == "revoked":
                raise PermissionError("mcp connector revoked")
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
    def default_mcp_permissions(role: str) -> List[str]:
        if role == "reviewer":
            return ["room:read", "message:write", "finding:write", "task:update"]
        if role == "developer":
            return ["room:read", "message:write", "finding:respond", "task:update"]
        return ["room:read", "message:write", "task:update"]

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

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "cursor": row["cursor"],
            "roomId": row["room_id"],
            "type": row["type"],
            "actorType": row["actor_type"],
            "actorName": row["actor_name"],
            "payload": json_loads(row["payload_json"], {}),
            "createdAt": row["created_at"],
        }

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "roomId": row["room_id"],
            "title": row["title"],
            "body": row["body"],
            "status": row["status"],
            "assignedTo": row["assigned_to"],
            "claimedBy": row["claimed_by"],
            "result": row["result"],
            "createdBy": row["created_by"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _inbox_item_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "roomId": row["room_id"],
            "agentName": row["agent_name"],
            "agentRole": row["agent_role"],
            "cursor": row["source_event_cursor"],
            "type": row["type"],
            "sourceType": row["source_type"],
            "sourceId": row["source_id"],
            "priority": row["priority"],
            "requiresReply": bool(row["requires_reply"]),
            "status": row["status"],
            "reason": row["reason"],
            "payload": json_loads(row["payload_json"], {}),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _agent_run_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "roomId": row["room_id"],
            "taskId": row["task_id"],
            "connectorId": row["connector_id"],
            "agentName": row["agent_name"],
            "status": row["status"],
            "promptSummary": row["prompt_summary"],
            "finalMessage": row["final_message"],
            "error": row["error"],
            "startedAt": row["started_at"],
            "finishedAt": row["finished_at"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _decision_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "roomId": row["room_id"],
            "kind": row["kind"],
            "status": row["status"],
            "requester": row["requester"],
            "action": row["action"],
            "reason": row["reason"],
            "targetType": row["target_type"],
            "targetId": row["target_id"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _handoff_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "roomId": row["room_id"],
            "sourceFindingId": row["source_finding_id"],
            "fromAgent": row["from_agent"],
            "targetAgent": row["target_agent"],
            "reason": row["reason"],
            "suggestedTask": row["suggested_task"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _thread_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "roomId": row["room_id"],
            "kind": row["kind"],
            "status": row["status"],
            "title": row["title"],
            "summary": json_loads(row["summary_json"], {}),
            "messages": [],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _mcp_invite_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "roomId": row["room_id"],
            "agentName": row["agent_name"],
            "agentRole": row["agent_role"],
            "token": row["token"],
            "permissions": json_loads(row["permissions_json"], []),
            "status": row["status"],
            "connectorId": row["connector_id"],
            "expiresAt": row["expires_at"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _supervisor_invite_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "roomId": row["room_id"],
            "name": row["name"],
            "role": "supervisor",
            "token": row["token"],
            "sessionToken": row["session_token"],
            "status": row["status"],
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
            if parsed.path == "/health":
                self.send_json({"ok": True, "service": "lighthouse-review-room", "time": now_ms()})
                return
            if parsed.path == "/api/rooms":
                self.send_json({"rooms": [room_summary(room) for room in self.store.list_rooms()]})
                return
            if parsed.path == "/api/workbenches":
                self.send_json({"workbenches": self.store.list_workbenches()})
                return
            match = re.match(r"^/api/workbenches/([^/]+)$", parsed.path)
            if match:
                token = self.read_bearer_token({})
                identity = self.store.authenticate_room_token(match.group(1), token)
                if identity["type"] not in {"owner", "supervisor"}:
                    raise PermissionError("owner or supervisor token required")
                room = self.store.get_room(match.group(1))
                if not room:
                    self.send_error_json(HTTPStatus.NOT_FOUND, "workbench not found")
                    return
                self.send_json(public_room(room))
                return
            match = re.match(r"^/api/rooms/([^/]+)$", parsed.path)
            if match:
                room = self.store.get_room(match.group(1))
                if not room:
                    self.send_error_json(HTTPStatus.NOT_FOUND, "room not found")
                    return
                self.send_json(public_room(room))
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
            if parsed.path == "/api/workbenches":
                self.send_json(self.store.create_workbench(body), HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/workbenches/([^/]+)/archive$", parsed.path)
            if match:
                self.send_json(self.store.archive_workbench(match.group(1), self.read_bearer_token(body)))
                return
            match = re.match(r"^/api/workbenches/([^/]+)/restore$", parsed.path)
            if match:
                self.send_json(self.store.restore_workbench(match.group(1), self.read_bearer_token(body)))
                return
            if parsed.path == "/api/demo/session":
                self.send_json(self.store.create_demo_session(), HTTPStatus.CREATED)
                return
            if parsed.path == "/api/webhooks/merge-request":
                self.send_json(self.store.ingest_merge_request_webhook(body), HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/rooms/([^/]+)/messages$", parsed.path)
            if match:
                identity = self.read_identity(match.group(1), body)
                self.require_room_writer(identity)
                self.send_json(
                    self.store.add_message(match.group(1), message_payload_for_identity(identity, body)),
                    HTTPStatus.CREATED,
                )
                return
            match = re.match(r"^/api/rooms/([^/]+)/findings$", parsed.path)
            if match:
                identity = self.read_identity(match.group(1), body)
                self.require_reviewer_or_owner(identity)
                self.send_json(self.store.add_finding(match.group(1), body), HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/rooms/([^/]+)/supervisor-invites$", parsed.path)
            if match:
                room_id = match.group(1)
                self.store.require_owner_token(room_id, self.read_bearer_token(body))
                invite = self.store.create_supervisor_invite(room_id, body)
                invite["url"] = supervisor_invite_url("http://{}".format(self.headers.get("Host")), room_id, invite["token"])
                self.send_json(invite, HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/rooms/([^/]+)/supervisor-invites/consume$", parsed.path)
            if match:
                result = self.store.consume_supervisor_invite(
                    self.read_bearer_token(body) or body.get("supervisorInvite") or body.get("supervisor_invite"),
                    {"roomId": match.group(1)},
                )
                result["room"] = public_room(result["room"]) if result.get("room") else None
                self.send_json(result, HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/rooms/([^/]+)/supervisor-session/leave$", parsed.path)
            if match:
                room_id = match.group(1)
                identity = self.read_identity(room_id, body)
                if identity["type"] != "supervisor":
                    raise PermissionError("supervisor token required")
                self.send_json(
                    self.store.leave_supervisor_session(room_id, self.read_bearer_token(body), body)
                )
                return
            match = re.match(r"^/api/rooms/([^/]+)/connectors$", parsed.path)
            if match:
                room_id = match.group(1)
                self.store.require_owner_token(room_id, self.read_bearer_token(body))
                self.send_json(self.store.register_connector(room_id, body), HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/rooms/([^/]+)/connectors/([^/]+)/revoke$", parsed.path)
            if match:
                self.send_json(
                    self.store.revoke_connector(
                        match.group(1),
                        match.group(2),
                        self.read_bearer_token(body),
                        body,
                    )
                )
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
                _finding, identity = self.read_finding_identity(match.group(1), body)
                self.require_developer_connector(identity)
                self.send_json(self.store.respond_to_finding(match.group(1), body), HTTPStatus.CREATED)
                return
            match = re.match(r"^/api/findings/([^/]+)/confirm$", parsed.path)
            if match:
                _finding, identity = self.read_finding_identity(match.group(1), body)
                self.require_owner_identity(identity)
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
            match = re.match(r"^/api/workbenches/([^/]+)$", parsed.path)
            if match:
                self.send_json(self.store.update_workbench(match.group(1), body, self.read_bearer_token(body)))
                return
            match = re.match(r"^/api/findings/([^/]+)$", parsed.path)
            if match:
                _finding, identity = self.read_finding_identity(match.group(1), body)
                self.require_owner_identity(identity)
                self.send_json(self.store.update_finding(match.group(1), body))
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

    def do_DELETE(self) -> None:
        try:
            parsed = urlparse(self.path)
            body = self.read_json()
            match = re.match(r"^/api/workbenches/([^/]+)$", parsed.path)
            if match:
                self.send_json(self.store.delete_workbench(match.group(1), body, self.read_bearer_token(body)))
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

    def read_identity(self, room_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.store.authenticate_room_token(room_id, self.read_bearer_token(body))

    def read_finding_identity(self, finding_id: str, body: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        finding = self.store.get_finding(finding_id)
        return finding, self.store.authenticate_room_token(finding["roomId"], self.read_bearer_token(body))

    @staticmethod
    def require_owner_identity(identity: Dict[str, Any]) -> None:
        if identity["type"] != "owner":
            raise PermissionError("owner token required")

    @staticmethod
    def require_room_writer(identity: Dict[str, Any]) -> None:
        if identity["type"] not in {"owner", "supervisor", "connector"}:
            raise PermissionError("room message writer token required")

    def require_reviewer_or_owner(self, identity: Dict[str, Any]) -> None:
        self.require_room_writer(identity)
        if identity["type"] != "owner" and identity["role"] != "reviewer":
            raise PermissionError("reviewer connector or owner token required")

    @staticmethod
    def require_developer_connector(identity: Dict[str, Any]) -> None:
        if identity["type"] != "connector" or identity["role"] != "developer":
            raise PermissionError("developer connector required")

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
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization")

    def log_message(self, fmt: str, *args: Any) -> None:
        print("{} - {}".format(self.address_string(), fmt % args))


class RealtimeHub:
    def __init__(self, store: ReviewRoomStore):
        self.store = store
        self.connections: Dict[str, Dict[web.WebSocketResponse, Dict[str, Any]]] = {}

    async def add(self, room_id: str, websocket: web.WebSocketResponse, identity: Dict[str, Any]) -> None:
        self.connections.setdefault(room_id, {})[websocket] = identity
        room = self.store.get_room(room_id)
        await websocket.send_json({"type": "room.snapshot", "room": public_room(room) if room else None, "identity": identity})
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


def public_connector(connector: Dict[str, Any]) -> Dict[str, Any]:
    safe = dict(connector)
    safe.pop("token", None)
    safe.pop("connectorToken", None)
    return safe


def public_room(room: Dict[str, Any]) -> Dict[str, Any]:
    safe = {key: value for key, value in room.items() if key != "ownerToken"}
    safe["connectors"] = [public_connector(connector) for connector in room.get("connectors", [])]
    return safe


def room_summary(room: Dict[str, Any]) -> Dict[str, Any]:
    return public_room(room)


def supervisor_invite_url(origin: str, room_id: str, token: str) -> str:
    return "{}?roomId={}&supervisorInvite={}".format(
        origin.rstrip("/") + "/",
        quote(room_id),
        quote(token),
    )


def message_payload_for_identity(identity: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    message = dict(payload)
    identity_type = identity.get("type")
    message["senderType"] = "human" if identity_type in {"owner", "supervisor"} else "agent"
    message["senderName"] = identity.get("name") or "unknown"

    if identity_type == "owner":
        message["kind"] = payload.get("kind") or "owner_topic"
    elif identity_type == "supervisor":
        message["kind"] = "supervisor_message"
    elif identity_type == "connector":
        message["kind"] = payload.get("kind") or "connector_message"
    else:
        message["kind"] = payload.get("kind") or "message"

    message_context = dict(payload.get("payload") or {})
    if "mentions" in payload:
        message_context["mentions"] = payload.get("mentions") or []
    if "mentionedAgents" in payload:
        message_context["mentionedAgents"] = payload.get("mentionedAgents") or []
    message_context.setdefault("role", identity.get("role") or "")
    message["payload"] = message_context
    return message


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


def ensure_human_room_reader(identity: Dict[str, Any]) -> None:
    if identity["type"] not in {"owner", "supervisor"}:
        raise web.HTTPForbidden(
            text=json_dumps({"ok": False, "error": "owner or supervisor token required"}),
            content_type="application/json",
        )


def ensure_room_writer(identity: Dict[str, Any]) -> None:
    if identity["type"] not in {"owner", "supervisor", "connector"}:
        raise web.HTTPForbidden(
            text=json_dumps({"ok": False, "error": "room message writer token required"}),
            content_type="application/json",
        )


def ensure_reviewer_or_owner(identity: Dict[str, Any]) -> None:
    ensure_room_writer(identity)
    if identity["type"] != "owner" and identity["role"] != "reviewer":
        raise web.HTTPForbidden(text=json_dumps({"ok": False, "error": "reviewer connector or owner token required"}), content_type="application/json")


def ensure_developer_connector(identity: Dict[str, Any]) -> None:
    if identity["type"] != "connector" or identity["role"] != "developer":
        raise web.HTTPForbidden(text=json_dumps({"ok": False, "error": "developer connector required"}), content_type="application/json")


def finding_identity(store: ReviewRoomStore, finding_id: str, token: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    try:
        finding = store.get_finding(finding_id)
        return finding, store.authenticate_room_token(finding["roomId"], token)
    except KeyError as exc:
        raise web.HTTPNotFound(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")
    except PermissionError as exc:
        raise web.HTTPForbidden(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")


async def handle_ws_event(
    store: ReviewRoomStore,
    hub: RealtimeHub,
    room_id: str,
    identity: Dict[str, Any],
    payload: Dict[str, Any],
    websocket: web.WebSocketResponse,
) -> None:
    event_type = payload.get("type")
    if identity["type"] == "supervisor" and event_type in {
        "finding.create",
        "finding.respond",
        "decision.propose",
        "finding.confirm",
        "finding.reject",
    }:
        await websocket.send_json({"type": "error", "error": "supervisor session can only post messages"})
        return
    if event_type in {"message.create", "topic.continue"}:
        mentions = payload.get("mentions") or payload.get("mentionedAgents") or []
        message = store.add_message(
            room_id,
            message_payload_for_identity(
                identity,
                {
                    "kind": payload.get("kind"),
                    "body": payload.get("body") or "",
                    "payload": {"eventType": event_type, "mentions": mentions},
                },
            ),
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
        finding = store.get_finding(finding_id)
        if finding["roomId"] != room_id:
            await websocket.send_json({"type": "error", "error": "finding must belong to the same room"})
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
        finding = store.get_finding(finding_id)
        if finding["roomId"] != room_id:
            await websocket.send_json({"type": "error", "error": "finding must belong to the same room"})
            return
        finding = store.confirm_finding(
            finding_id,
            {
                "senderName": identity["name"],
                "decision": payload.get("decision") or ("rejected" if event_type == "finding.reject" else "accepted"),
                "body": payload.get("body") or "",
                "syncTarget": payload.get("syncTarget") or "Agent Board decision",
            },
        )
        await hub.broadcast(room_id, {"type": "finding.updated", "finding": finding})
        return

    await websocket.send_json({"type": "error", "error": "unknown event type"})


def room_id_from_mcp_tool_result(result: Dict[str, Any]) -> str:
    structured = result.get("structuredContent") or {}
    if not isinstance(structured, dict):
        return ""
    room_id = structured.get("roomId") or structured.get("room_id")
    if isinstance(room_id, str):
        return room_id
    return ""


def build_app(store: Optional[ReviewRoomStore] = None) -> web.Application:
    app = web.Application()
    app[STORE_KEY] = store or ReviewRoomStore(DEFAULT_DB_PATH)
    app[MCP_STORE_KEY] = app[STORE_KEY]
    app[HUB_KEY] = RealtimeHub(app[STORE_KEY])

    async def after_mcp_tool(_token: str, _name: str, _arguments: Dict[str, Any], result: Dict[str, Any]) -> None:
        room_id = room_id_from_mcp_tool_result(result)
        if room_id:
            room = app[STORE_KEY].get_room(room_id)
            if room:
                await app[HUB_KEY].broadcast(room_id, {"type": "room.snapshot", "room": public_room(room)})

    app[MCP_AFTER_TOOL_KEY] = after_mcp_tool

    async def index(_request: web.Request) -> web.Response:
        return web.Response(text=index_html(), content_type="text/html", charset="utf-8")

    async def health(_request: web.Request) -> web.Response:
        return json_response({"ok": True, "service": "lighthouse-review-room", "time": now_ms()})

    async def list_rooms(_request: web.Request) -> web.Response:
        return json_response({"rooms": [room_summary(room) for room in app[STORE_KEY].list_rooms()]})

    async def create_room(request: web.Request) -> web.Response:
        return json_response(app[STORE_KEY].create_room(await request_json(request)), 201)

    async def list_workbenches(_request: web.Request) -> web.Response:
        return json_response({"workbenches": app[STORE_KEY].list_workbenches()})

    async def create_workbench(request: web.Request) -> web.Response:
        return json_response(app[STORE_KEY].create_workbench(await request_json(request)), 201)

    async def get_workbench(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        ensure_human_room_reader(identity)
        room = app[STORE_KEY].get_room(room_id)
        if not room:
            raise web.HTTPNotFound(text=json_dumps({"ok": False, "error": "workbench not found"}), content_type="application/json")
        return json_response(public_room(room))

    async def update_workbench(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        ensure_owner(identity)
        return json_response(app[STORE_KEY].update_workbench(room_id, await request_json(request), identity["token"]))

    async def archive_workbench(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        ensure_owner(identity)
        return json_response(app[STORE_KEY].archive_workbench(room_id, identity["token"]))

    async def restore_workbench(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        ensure_owner(identity)
        return json_response(app[STORE_KEY].restore_workbench(room_id, identity["token"]))

    async def delete_workbench(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        ensure_owner(identity)
        try:
            deleted = app[STORE_KEY].delete_workbench(room_id, await request_json(request), identity["token"])
        except ValueError as exc:
            raise web.HTTPBadRequest(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")
        return json_response(deleted)

    async def demo_session(_request: web.Request) -> web.Response:
        return json_response(app[STORE_KEY].create_demo_session(), 201)

    async def get_room(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        room = app[STORE_KEY].get_room(room_id)
        if not room:
            raise web.HTTPNotFound(text=json_dumps({"ok": False, "error": "room not found"}), content_type="application/json")
        return json_response(public_room(room))

    async def register_connector(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        ensure_owner(identity)
        return json_response(app[STORE_KEY].register_connector(room_id, await request_json(request)), 201)

    async def create_mcp_invite(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        ensure_owner(identity)
        return json_response(app[STORE_KEY].create_mcp_invite(room_id, await request_json(request)), 201)

    async def create_supervisor_invite(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        ensure_owner(identity)
        invite = app[STORE_KEY].create_supervisor_invite(room_id, await request_json(request))
        invite["url"] = supervisor_invite_url("{}://{}".format(request.scheme, request.host), room_id, invite["token"])
        return json_response(invite, 201)

    async def consume_supervisor_invite(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        body = await request_json(request)
        token = bearer_token_from_request(request) or body.get("token") or body.get("supervisorInvite")
        try:
            result = app[STORE_KEY].consume_supervisor_invite(token, {"roomId": room_id})
        except PermissionError as exc:
            raise web.HTTPForbidden(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")
        result["room"] = public_room(result["room"]) if result.get("room") else None
        await app[HUB_KEY].broadcast(room_id, {"type": "room.snapshot", "room": result["room"]})
        return json_response(result, 201)

    async def leave_supervisor_session(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        token = bearer_token_from_request(request)
        identity = require_identity(app[STORE_KEY], room_id, token)
        if identity["type"] != "supervisor":
            raise web.HTTPForbidden(
                text=json_dumps({"ok": False, "error": "supervisor token required"}),
                content_type="application/json",
            )
        try:
            result = app[STORE_KEY].leave_supervisor_session(room_id, token, await request_json(request))
        except PermissionError as exc:
            raise web.HTTPForbidden(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")
        room = app[STORE_KEY].get_room(room_id)
        if room:
            await app[HUB_KEY].broadcast(room_id, {"type": "room.snapshot", "room": public_room(room)})
        return json_response(result)

    async def list_tasks(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        return json_response({"tasks": app[STORE_KEY].list_tasks(room_id)})

    async def create_task(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        ensure_owner(identity)
        body = await request_json(request)
        body.setdefault("createdBy", identity.get("name") or "Agent Board owner")
        task = app[STORE_KEY].create_task(room_id, body)
        await app[HUB_KEY].broadcast(room_id, {"type": "task.created", "task": task})
        return json_response(task, 201)

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
        room = app[STORE_KEY].get_room(result["roomId"])
        if room:
            await app[HUB_KEY].broadcast(result["roomId"], {"type": "room.snapshot", "room": public_room(room)})
        return json_response(result, 201)

    async def revoke_connector(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        connector_id = request.match_info["connector_id"]
        try:
            result = app[STORE_KEY].revoke_connector(
                room_id,
                connector_id,
                bearer_token_from_request(request),
                await request_json(request),
            )
        except PermissionError as exc:
            raise web.HTTPForbidden(text=json_dumps({"ok": False, "error": str(exc)}), content_type="application/json")
        room = app[STORE_KEY].get_room(room_id)
        if room:
            await app[HUB_KEY].broadcast(room_id, {"type": "room.snapshot", "room": public_room(room)})
        return json_response(result)

    async def add_message(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        ensure_room_writer(identity)
        message = app[STORE_KEY].add_message(room_id, message_payload_for_identity(identity, await request_json(request)))
        await app[HUB_KEY].broadcast(room_id, {"type": "message.created", "message": message})
        return json_response(message, 201)

    async def add_finding(request: web.Request) -> web.Response:
        room_id = request.match_info["room_id"]
        identity = require_identity(app[STORE_KEY], room_id, bearer_token_from_request(request))
        ensure_reviewer_or_owner(identity)
        finding = app[STORE_KEY].add_finding(room_id, await request_json(request))
        await app[HUB_KEY].broadcast(room_id, {"type": "finding.created", "finding": finding})
        return json_response(finding, 201)

    async def update_finding(request: web.Request) -> web.Response:
        finding_id = request.match_info["finding_id"]
        _finding, identity = finding_identity(app[STORE_KEY], finding_id, bearer_token_from_request(request))
        ensure_owner(identity)
        finding = app[STORE_KEY].update_finding(finding_id, await request_json(request))
        await app[HUB_KEY].broadcast(finding["roomId"], {"type": "finding.updated", "finding": finding})
        return json_response(finding)

    async def developer_response(request: web.Request) -> web.Response:
        finding_id = request.match_info["finding_id"]
        _finding, identity = finding_identity(app[STORE_KEY], finding_id, bearer_token_from_request(request))
        ensure_developer_connector(identity)
        finding = app[STORE_KEY].respond_to_finding(finding_id, await request_json(request))
        await app[HUB_KEY].broadcast(finding["roomId"], {"type": "finding.updated", "finding": finding})
        return json_response(finding, 201)

    async def confirm_finding(request: web.Request) -> web.Response:
        finding_id = request.match_info["finding_id"]
        _finding, identity = finding_identity(app[STORE_KEY], finding_id, bearer_token_from_request(request))
        ensure_owner(identity)
        finding = app[STORE_KEY].confirm_finding(finding_id, await request_json(request))
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
    app.router.add_get("/api/workbenches", list_workbenches)
    app.router.add_post("/api/workbenches", create_workbench)
    app.router.add_get("/api/workbenches/{room_id}", get_workbench)
    app.router.add_patch("/api/workbenches/{room_id}", update_workbench)
    app.router.add_post("/api/workbenches/{room_id}/archive", archive_workbench)
    app.router.add_post("/api/workbenches/{room_id}/restore", restore_workbench)
    app.router.add_delete("/api/workbenches/{room_id}", delete_workbench)
    app.router.add_post("/api/demo/session", demo_session)
    app.router.add_post("/api/webhooks/merge-request", merge_request_webhook)
    app.router.add_get("/api/rooms/{room_id}", get_room)
    app.router.add_post("/api/rooms/{room_id}/messages", add_message)
    app.router.add_post("/api/rooms/{room_id}/findings", add_finding)
    app.router.add_post("/api/rooms/{room_id}/connectors", register_connector)
    app.router.add_post("/api/rooms/{room_id}/mcp-invites", create_mcp_invite)
    app.router.add_post("/api/rooms/{room_id}/supervisor-invites", create_supervisor_invite)
    app.router.add_post("/api/rooms/{room_id}/supervisor-invites/consume", consume_supervisor_invite)
    app.router.add_post("/api/rooms/{room_id}/supervisor-session/leave", leave_supervisor_session)
    app.router.add_post("/api/rooms/{room_id}/connectors/{connector_id}/revoke", revoke_connector)
    app.router.add_get("/api/rooms/{room_id}/tasks", list_tasks)
    app.router.add_post("/api/rooms/{room_id}/tasks", create_task)
    app.router.add_post("/api/connectors/{connector_id}/events", connector_event)
    app.router.add_patch("/api/findings/{finding_id}", update_finding)
    app.router.add_post("/api/findings/{finding_id}/developer-response", developer_response)
    app.router.add_post("/api/findings/{finding_id}/confirm", confirm_finding)
    app.router.add_get("/ws/rooms/{room_id}", websocket_room)
    app.router.add_get("/mcp", handle_mcp_get)
    app.router.add_post("/mcp", handle_mcp_post)
    return app


def index_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Lighthouse 工作台</title>
  <link rel="icon" href="data:,">
  <style>
    @font-face{font-family:"Share Tech Mono";font-style:normal;font-weight:400;font-display:swap;src:url(data:font/woff2;base64,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) format("woff2");unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}
    :root{--font-terminal:"Share Tech Mono","IBM Plex Mono","SFMono-Regular",Consolas,"Noto Sans SC","Microsoft YaHei UI",monospace;--font-cjk:"Noto Sans SC","Microsoft YaHei UI","PingFang SC","Hiragino Sans GB","Source Han Sans SC","Segoe UI",sans-serif;--font-ui:"Share Tech Mono","Noto Sans SC","Microsoft YaHei UI","PingFang SC","Hiragino Sans GB","Source Han Sans SC","Segoe UI",sans-serif;--bg:#010401;--surface:#031007;--panel:#06130a;--panel2:#091b0d;--line:#164822;--line2:#247335;--text:#d8f8dc;--muted:#7fac88;--matrix-green:#40ff6a;--matrix-green-soft:#8dff9b;--phosphor-glow:0 0 18px rgba(64,255,106,.28),0 0 2px rgba(64,255,106,.85);--lime:#40ff6a;--cyan:#66ffd1;--amber:#ffd166;--red:#ff5f63;--blue:#74f7ff;--shadow:rgba(0,0,0,.7)}
    *{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top left,rgba(20,96,39,.24),transparent 34rem),var(--bg);color:var(--text);font-family:var(--font-ui);letter-spacing:0}
    .matrix-terminal-shell{min-height:100vh}.matrix-noise,.terminal-scanline{position:fixed;inset:0;z-index:0;pointer-events:none}.matrix-noise{background-image:linear-gradient(rgba(64,255,106,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(64,255,106,.028) 1px,transparent 1px),radial-gradient(circle at 18% 12%,rgba(64,255,106,.1),transparent 22rem);background-size:32px 32px,32px 32px,auto;mix-blend-mode:screen}.terminal-scanline{background:repeating-linear-gradient(180deg,rgba(216,248,220,.035) 0,rgba(216,248,220,.035) 1px,transparent 1px,transparent 4px);opacity:.42}
    header,main,.modal{position:relative;z-index:1}button,input,textarea,select{font:inherit}button{min-height:34px;max-width:100%;border:1px solid var(--line2);border-radius:4px;background:linear-gradient(180deg,#0c2411,#061307);color:var(--text);padding:0 12px;cursor:pointer;box-shadow:inset 0 0 0 1px rgba(64,255,106,.06);text-transform:uppercase;white-space:nowrap}
    button:hover:not(:disabled),button:focus-visible{border-color:var(--matrix-green);color:#f2fff3;box-shadow:var(--phosphor-glow);outline:0}button.primary{border-color:var(--matrix-green);background:linear-gradient(180deg,#134b1d,#082110);color:#f2fff3;box-shadow:var(--phosphor-glow)}button.success{border-color:var(--matrix-green-soft);background:#0d2e14;color:#effff1}button.danger{border-color:var(--red);background:#2a080b;color:#ffe5e5}
    button:disabled{opacity:.48;cursor:not-allowed;box-shadow:none}input,textarea,select{width:100%;border:1px solid var(--line);border-radius:4px;background:#020904;color:var(--text);padding:9px 10px;box-shadow:inset 0 0 18px rgba(64,255,106,.045)}input:focus,textarea:focus,select:focus{border-color:var(--matrix-green);box-shadow:var(--phosphor-glow);outline:0}textarea{min-height:88px;resize:vertical}
    .mono,code,.tag,.metric,.event-type,h1,h2,h3,.field label,button,.tab,.eyebrow{font-family:var(--font-terminal)}p,.body,textarea,input,select{font-family:var(--font-cjk)}code{border:1px solid var(--line);border-radius:4px;background:#020904;padding:2px 6px;color:var(--matrix-green-soft);box-shadow:inset 0 0 12px rgba(64,255,106,.08)}
    header{position:sticky;top:0;z-index:4;border-bottom:1px solid var(--line);background:rgba(1,8,3,.92);backdrop-filter:blur(16px);box-shadow:0 10px 34px rgba(0,0,0,.5)}.shell{max-width:1440px;margin:0 auto;padding:16px}.topbar{display:flex;gap:16px;align-items:center;justify-content:space-between}
    h1{margin:0;font-size:22px;line-height:1.15;text-shadow:0 0 16px rgba(64,255,106,.24)}h2{margin:0;font-size:15px}h3{margin:0;font-size:13px}p{margin:5px 0 0;color:var(--muted);line-height:1.45}.eyebrow{color:var(--matrix-green);font-size:12px;text-transform:uppercase;text-shadow:var(--phosphor-glow)}
    .actions{display:flex;flex-wrap:wrap;gap:8px}.tabs{display:flex;gap:6px}.tab{border-color:var(--line);background:#020904;color:var(--muted)}.tab.active{border-color:var(--matrix-green);color:var(--matrix-green)}
    .panel{border:1px solid var(--line);border-radius:6px;background:linear-gradient(180deg,rgba(6,19,10,.96),rgba(2,9,4,.96));box-shadow:0 18px 44px var(--shadow),inset 0 0 26px rgba(64,255,106,.035);min-width:0}.panel-head{display:flex;align-items:center;justify-content:space-between;gap:10px;border-bottom:1px solid var(--line);padding:12px 14px;background:rgba(64,255,106,.035)}.panel-body{padding:14px}
    .hall-grid{display:grid;grid-template-columns:minmax(340px,420px) minmax(0,1fr);gap:14px}.form-grid{display:grid;grid-template-columns:1fr;gap:10px}.field{display:grid;gap:6px}.field label{font-size:12px;color:var(--muted);text-transform:uppercase}.template-line{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;border:1px solid var(--line);border-radius:6px;background:#020904;padding:12px;box-shadow:inset 0 0 20px rgba(64,255,106,.045)}
    .workbench-table{display:grid;gap:8px}.workbench-row{display:grid;grid-template-columns:minmax(160px,1.2fr) minmax(96px,.58fr) minmax(68px,.4fr) repeat(4,minmax(44px,.28fr)) minmax(64px,.42fr) minmax(86px,.55fr);gap:8px;align-items:center;width:100%;min-height:58px;text-align:left;border:1px solid var(--line);border-radius:6px;background:#020904;padding:10px;box-shadow:inset 0 0 18px rgba(64,255,106,.035)}.workbench-row[role="button"]{cursor:pointer}.workbench-row:hover,.workbench-row.active{border-color:var(--matrix-green);box-shadow:var(--phosphor-glow),inset 0 0 18px rgba(64,255,106,.08)}.room-actions{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.room-actions button{min-height:30px;padding:0 9px}
    .tag{display:inline-flex;align-items:center;gap:6px;min-height:22px;border:1px solid var(--line);border-radius:999px;background:#020904;padding:0 8px;color:var(--muted);font-size:11px}.tag.online{border-color:var(--matrix-green);color:var(--matrix-green-soft);box-shadow:var(--phosphor-glow)}.tag.waiting{border-color:#7b5f1a;color:var(--amber)}.tag.p1,.tag.danger{border-color:#713039;color:var(--red)}.tag.info{border-color:#227866;color:var(--cyan)}.tag.permission-locked{border-color:#485766;color:#96a4b2}
    .dot{width:7px;height:7px;border-radius:50%;background:var(--muted);display:inline-block}.dot.online{background:var(--matrix-green);box-shadow:0 0 10px var(--matrix-green)}.dot.waiting{background:var(--amber)}.dot.danger{background:var(--red)}.dot.info{background:var(--cyan)}
    .detail-grid{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:14px}.command-bar{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:center;margin-bottom:14px}
    .stream-layout{display:grid;grid-template-columns:minmax(0,1fr);gap:14px;margin-top:14px}.timeline,.finding-list,.audit-list,.object-list,.member-status-list{display:grid;gap:8px}.message,.finding,.object-row,.event-row,.member-row{border:1px solid var(--line);border-radius:6px;background:#020904;padding:10px;box-shadow:inset 0 0 18px rgba(64,255,106,.035)}.message.owner,.member-row.owner{border-color:#26764c}.message.agent,.member-row.agent{border-color:#2ca247}.member-head,.message-head,.finding-head,.event-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px}.member-meta,.capability-badges{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.permission-locked{opacity:.58;cursor:not-allowed}.body{white-space:pre-wrap;line-height:1.5;overflow-wrap:anywhere}.finding-title{font-weight:700;color:var(--matrix-green-soft)}.finding-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
    .metric{border:1px solid var(--line);border-radius:6px;background:#020904;padding:10px;box-shadow:inset 0 0 18px rgba(64,255,106,.035)}.metric strong{display:block;color:var(--matrix-green-soft);font-size:18px;text-shadow:var(--phosphor-glow)}.empty{border:1px dashed var(--line);border-radius:6px;padding:24px 14px;text-align:center;color:var(--muted);background:rgba(2,9,4,.6)}.notice{margin-top:10px;color:var(--muted);font-size:12px}.hidden{display:none}
    .audit-head-actions,.audit-controls{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap}.audit-controls{margin-top:10px}
    .composer-box{position:relative}.composer-box textarea{min-height:112px;padding-right:112px;padding-bottom:54px}.composer-box button{position:absolute;right:10px;bottom:10px;min-height:38px;width:88px}
    .modal{position:fixed;inset:0;z-index:20;display:grid;place-items:center;background:rgba(0,7,2,.78);padding:18px}.modal-card{width:min(620px,100%);border:1px solid var(--line2);border-radius:6px;background:#06130a;box-shadow:0 26px 80px var(--shadow),var(--phosphor-glow);padding:16px}.modal-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:14px}.modal-head>button{flex:0 0 auto}.modal.hidden{display:none}.invite-output{min-height:180px}
    @media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important}.terminal-scanline{opacity:.24}}
    @media(max-width:1100px){.hall-grid,.detail-grid,.stream-layout,.command-bar{grid-template-columns:1fr}.workbench-row{grid-template-columns:1fr 1fr}}
    @media(max-width:640px){.topbar{display:grid}.workbench-row{grid-template-columns:1fr}.shell{padding:12px}}
  </style>
</head>
<body data-theme="matrix-terminal" class="matrix-terminal-shell">
  <div class="matrix-noise" aria-hidden="true"></div>
  <div class="terminal-scanline" aria-hidden="true"></div>
  <header>
    <div class="shell topbar">
      <div>
        <div class="eyebrow mono">终端作战台</div>
        <h1>Lighthouse 工作台 / 智能体看板</h1>
        <p>MR 评审工作台控制台。消息进入上下文流；执行必须通过任务、认领、运行和负责人决策。</p>
      </div>
      <div class="actions">
        <button id="refreshRooms">刷新工作台</button>
        <button id="showArchivedRooms">已归档工作台 <span id="archivedRoomCount">0</span></button>
        <button class="primary" id="showHall">工作台大厅</button>
      </div>
    </div>
  </header>
  <main class="shell">
    <section id="hallView">
      <div class="hall-grid">
        <section class="panel">
          <div class="panel-head"><h2>工作台大厅</h2><span class="tag info">仅 MR 评审</span></div>
          <div class="panel-body">
            <div class="template-line">
              <div>
                <h3>MR 评审工作台</h3>
                <p>接入 -> 评审 -> 修复 -> 验证 -> 决策</p>
              </div>
              <span class="tag online"><span class="dot online"></span>已启用</span>
            </div>
            <div class="form-grid" style="margin-top:12px">
              <div class="field"><label>工作台标题</label><input id="roomTitle" value="MR：Lighthouse 智能体看板"></div>
              <div class="field"><label>负责人</label><input id="roomOwner" value="工作台负责人"></div>
            </div>
            <div class="actions" style="margin-top:12px"><button class="primary" id="createRoom">启动 MR 评审工作台</button></div>
            <p class="notice">生命周期操作会写入审计事件。删除只会生成服务端工作台墓碑，不会清理远端智能体机器。</p>
            <p class="notice mono">API: <code>/api/workbenches</code> · <code>/api/rooms/{roomId}/mcp-invites</code> · <code>/api/rooms/{roomId}/supervisor-invites</code> · <code>/mcp</code></p>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head"><h2 id="archiveModeLabel">最近工作台</h2><span class="tag" id="roomCount">0</span></div>
          <div class="panel-body">
            <div id="hallNotice" class="notice hidden"></div>
            <div class="workbench-row mono" style="min-height:34px;color:var(--muted)">
              <span>工作台</span><span>创建时间</span><span>状态</span><span>发现</span><span>任务</span><span>运行</span><span>负责人</span><span>MCP</span><span>&#25805;&#20316;</span>
            </div>
            <div class="workbench-table" id="roomList"></div>
          </div>
        </section>
      </div>
    </section>
    <section id="detailView" class="hidden">
      <div class="command-bar">
        <div>
          <div class="eyebrow mono">工作台详情</div>
          <h1 id="detailTitle">选择或创建工作台</h1>
          <p id="detailMeta">负责人令牌会保存在本机浏览器 localStorage。</p>
        </div>
        <div class="actions"><span class="tag" id="socketState">未连接</span><button id="backToHall">返回大厅</button><button id="detailLeaveSupervisor" class="danger">退出看板</button><button id="detailArchiveWorkbench">归档</button><button id="detailRestoreWorkbench" class="success">恢复</button><button id="detailDeleteWorkbench" class="danger">彻底删除</button><button class="primary" id="detailCreateTask">创建目标</button><button id="detailInviteSupervisor">邀请监督者</button><button id="detailInviteAgent">邀请智能体</button></div>
      </div>
      <div id="detailBody"><div class="empty">还没有可展示的工作台。</div></div>
    </section>
  </main>
  <div class="modal hidden" id="inviteModal" role="dialog" aria-modal="true" aria-labelledby="inviteModalTitle">
    <form class="modal-card" id="inviteForm">
      <div class="modal-head">
        <div>
          <h2 id="inviteModalTitle">邀请智能体</h2>
          <p>创建一个带名称和职责的远程 MCP 邀请。</p>
        </div>
        <button type="button" id="inviteClose">关闭</button>
      </div>
      <div class="form-grid">
        <div class="field"><label>名称</label><input id="inviteAgentName" autocomplete="off"></div>
        <div class="field">
          <label>职责 / 类型</label>
          <select id="inviteAgentRole">
            <option value="reviewer" selected>评审 Agent</option>
            <option value="developer">开发 Agent</option>
            <option value="agent">通用 Agent</option>
          </select>
        </div>
      </div>
      <div class="actions" style="margin-top:12px">
        <button class="primary" type="submit">生成邀请话术</button>
        <button type="button" id="inviteCancel">取消</button>
        <span class="tag hidden" id="inviteCopyStatus">待复制</span>
      </div>
      <div class="field hidden" id="inviteOutput" style="margin-top:12px">
        <label>邀请话术</label>
        <textarea class="invite-output" id="inviteCopyText" readonly></textarea>
        <div class="actions" style="margin-top:8px"><button type="button" id="inviteCopyButton">复制邀请话术</button></div>
      </div>
    </form>
  </div>
  <div class="modal hidden" id="supervisorInviteModal" role="dialog" aria-modal="true" aria-labelledby="supervisorInviteModalTitle">
    <form class="modal-card" id="supervisorInviteForm">
      <div class="modal-head">
        <div>
          <h2 id="supervisorInviteModalTitle">邀请监督者</h2>
          <p>创建一个具名的人类监督者入房授权 URL；首次打开后会换取房间访问会话。</p>
        </div>
        <button type="button" id="supervisorInviteClose">关闭</button>
      </div>
      <div class="form-grid">
        <div class="field"><label>名称</label><input id="supervisorInviteName" autocomplete="off"></div>
      </div>
      <div class="actions" style="margin-top:12px">
        <button class="primary" type="submit">生成授权 URL</button>
        <button type="button" id="supervisorInviteCancel">取消</button>
        <span class="tag hidden" id="supervisorInviteCopyStatus">待复制</span>
      </div>
      <div class="field hidden" id="supervisorInviteOutput" style="margin-top:12px">
        <label>一次性授权 URL</label>
        <textarea class="invite-output" id="supervisorInviteUrl" readonly></textarea>
        <div class="actions" style="margin-top:8px"><button type="button" id="supervisorInviteCopyButton">复制授权 URL</button></div>
      </div>
    </form>
  </div>
  <div class="modal hidden" id="supervisorLeaveModal" role="dialog" aria-modal="true" aria-labelledby="supervisorLeaveModalTitle">
    <form class="modal-card" id="supervisorLeaveForm">
      <div class="modal-head">
        <div>
          <h2 id="supervisorLeaveModalTitle">退出监督者会话</h2>
          <p>退出后，本设备将不再访问此看板。看板内容、任务和 Agent 运行不会受到影响。</p>
        </div>
        <button type="button" id="supervisorLeaveClose">关闭</button>
      </div>
      <div class="actions" style="margin-top:12px">
        <button class="danger" type="submit">退出看板</button>
        <button type="button" id="supervisorLeaveCancel">取消</button>
      </div>
    </form>
  </div>
  <div class="modal hidden" id="agentRevokeModal" role="dialog" aria-modal="true" aria-labelledby="agentRevokeModalTitle">
    <form class="modal-card" id="agentRevokeForm">
      <div class="modal-head">
        <div>
          <h2 id="agentRevokeModalTitle">撤销 Agent 访问</h2>
          <p>这会使 <span id="agentRevokeName">Agent</span> 的服务端访问失效，但不会清理远端机器上的 MCP 配置、日志、shell history、缓存或工作区文件。</p>
        </div>
        <button type="button" id="agentRevokeClose">关闭</button>
      </div>
      <div class="actions" style="margin-top:12px">
        <button class="danger" type="submit">撤销访问</button>
        <button type="button" id="agentRevokeCancel">取消</button>
      </div>
    </form>
  </div>
  <script>
    const AUDIT_PAGE_SIZE = 20;
    const state = { rooms: [], room: null, viewMode: 'active', ws: null, copyFallback: null, pendingInvites: {}, pendingRevokeConnector: null, hallNotice: '', audit: { expanded: false, page: 0 }, tokens: JSON.parse(localStorage.getItem('reviewRoomAccessTokens') || localStorage.getItem('reviewRoomOwnerTokens') || '{}'), supervisorTokens: JSON.parse(localStorage.getItem('reviewRoomSupervisorTokens') || '{}') };
    const statusText = { open: '进行中', archived: '已归档', deleted: '已删除', completed: '已完成', assigned:'已分配', running:'运行中', started:'已开始', pending:'待处理', proposed:'已提议', failed:'失败', needs_developer_response: '等待开发智能体', developer_responded: '等待负责人确认', accepted: '已确认', rejected: '已驳回' };
    const connectorStatusText = { connected:'已连接', disconnected:'已断开', invited:'已邀请', revoked:'已撤销', mcp_ready:'MCP 就绪', mcp_streaming:'MCP 在线' };
    const connectorKindText = { connector:'MCP', 'mcp-agent':'MCP', 'mcp-remote':'远程 MCP' };
    const agentRoleText = { reviewer:'评审 Agent', supervisor:'监督者', developer:'开发 Agent', agent:'通用 Agent' };
    function saveTokens(){
      localStorage.setItem('reviewRoomAccessTokens', JSON.stringify(state.tokens));
      localStorage.setItem('reviewRoomOwnerTokens', JSON.stringify(state.tokens));
    }
    function saveSupervisorTokens(){
      localStorage.setItem('reviewRoomSupervisorTokens', JSON.stringify(state.supervisorTokens));
    }
    function accessTokenForRoom(roomId){
      return state.tokens[roomId] || state.supervisorTokens[roomId] || '';
    }
    function canManageCurrentRoom(){
      return !!(state.room && state.tokens[state.room.id]);
    }
    function isSupervisorCurrentRoom(){
      return !!(state.room && !state.tokens[state.room.id] && state.supervisorTokens[state.room.id]);
    }
    function canPostMessagesCurrentRoom(){
      return !!(state.room && accessTokenForRoom(state.room.id) && !['archived','deleted'].includes(state.room.status));
    }
    function commandPermissionReason(action){
      if(!state.room) return '';
      if(state.room.status === 'archived') return '已归档工作台为只读状态。';
      if(isSupervisorCurrentRoom()) return '当前身份可发言和 @Agent，但没有管理权限。';
      if(!accessTokenForRoom(state.room.id)) return '需要有效的房间访问权限。';
      return '';
    }
    function applyCommandPermission(button, allowed, action){
      if(!button) return;
      button.disabled = !allowed;
      button.title = allowed ? '' : commandPermissionReason(action);
      button.classList.toggle('permission-locked', !allowed);
    }
    function activeRooms(){
      return state.rooms.filter(room => !['archived','deleted'].includes(room.status));
    }
    function archivedRooms(){
      return state.rooms.filter(room => room.status === 'archived');
    }
    function visibleRooms(){
      return state.viewMode === 'archived' ? archivedRooms() : activeRooms();
    }
    function cleanupStoredRoomAccess(roomId){
      delete state.tokens[roomId];
      delete state.supervisorTokens[roomId];
      saveTokens();
      saveSupervisorTokens();
    }
    function esc(v){ return String(v ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;'); }
    async function api(path, options={}){
      const res = await fetch(path, options);
      const data = await res.json();
      if(!res.ok) throw new Error(data.error || res.statusText);
      return data;
    }
    function authHeaders(roomId){ return { 'Content-Type':'application/json', Authorization:`Bearer ${accessTokenForRoom(roomId)}` }; }
    function showHall(){
      state.viewMode = 'active';
      document.getElementById('hallView').classList.remove('hidden');
      document.getElementById('detailView').classList.add('hidden');
      renderRooms();
    }
    function showArchivedRooms(){
      state.viewMode = 'archived';
      document.getElementById('hallView').classList.remove('hidden');
      document.getElementById('detailView').classList.add('hidden');
      renderRooms();
    }
    function showDetail(){
      document.getElementById('hallView').classList.add('hidden');
      document.getElementById('detailView').classList.remove('hidden');
    }
    function randomAgentSuffix(){
      return Math.random().toString(36).slice(2, 6).toUpperCase().padEnd(4, 'X');
    }
    function defaultAgentName(){
      return `Agent-${randomAgentSuffix()}`;
    }
    function defaultSupervisorName(){
      return `Supervisor-${randomAgentSuffix()}`;
    }
    function shortConnectorId(connector){
      const id = (connector && connector.id) || (connector && connector.connectorId) || '';
      return id ? id.slice(-6).toUpperCase() : '邀请中';
    }
    function memberIdentityLabel(member){
      if(member.kind === 'owner') return '负责人';
      if(member.kind === 'supervisor') return 'Human';
      if(member.kind === 'human') return '成员';
      return shortConnectorId(member);
    }
    function agentRoleLabel(role){
      return agentRoleText[role] || role || '通用 Agent';
    }
    function statusTagClass(status){
      if(['connected','mcp_ready','mcp_streaming','running','online'].includes(status)) return 'online';
      if(['revoked','failed','deleted'].includes(status)) return 'danger';
      if(['invited','pending','assigned','disconnected'].includes(status)) return 'waiting';
      return 'info';
    }
    function rememberPendingInvite(invite){
      const roomId = invite.roomId || (state.room && state.room.id);
      if(!roomId) return;
      const pending = state.pendingInvites[roomId] || [];
      state.pendingInvites[roomId] = [
        ...pending.filter(item => item.id !== invite.id),
        {
          id: invite.id,
          name: invite.agentName,
          agentRole: invite.agentRole,
          status: 'invited',
          connectorId: invite.connectorId || '',
          createdAt: invite.createdAt
        }
      ];
    }
    function pendingRoomInvites(room){
      const connectors = room.connectors || [];
      return (state.pendingInvites[room.id] || []).filter(invite => {
        return !connectors.some(connector => connector.name === invite.name && connector.agentRole === invite.agentRole);
      });
    }
    function memberWorkStatus(member, room, pendingMentions, pendingTasks){
      if(member.kind === 'owner'){
        const pendingDecisions = (room.decisions || []).filter(decision => decision.status === 'pending').length;
        const total = pendingMentions + pendingDecisions;
        return total ? `待处理 ${total} 项负责人事项` : '负责人令牌已就绪';
      }
      if(member.status === 'invited') return '待接入 MCP';
      if(member.status === 'disconnected') return '已离开，可由负责人撤销访问';
      if(member.status === 'revoked') return '访问已撤销';
      const runs = (room.agentRuns || []).filter(run => run.connectorId === member.connectorId || run.agentName === member.name);
      const activeRun = runs.find(run => ['running','started'].includes(run.status));
      if(activeRun) return `运行中 · ${activeRun.id}`;
      const tasks = (room.tasks || []).filter(task => task.assignedTo === member.name || task.claimedBy === member.name);
      const activeTask = tasks.find(task => ['assigned','running','started'].includes(task.status));
      if(activeTask) return `待执行任务 · ${activeTask.title}`;
      return pendingTasks && member.role === 'reviewer' ? `工作台有 ${pendingTasks} 项待执行任务` : '空闲';
    }
    function memberRows(room, pendingMentions, pendingTasks){
      const participants = room.participants || [];
      const connectors = room.connectors || [];
      const ownerName = (room.context && room.context.owner) || (participants.find(p => p.role === 'owner') || {}).name || '工作台负责人';
      const humans = participants
        .filter(participant => participant.type !== 'agent')
        .filter(participant => participant.role !== 'owner')
        .map(participant => ({
          kind: participant.role === 'supervisor' ? 'supervisor' : 'human',
          name: participant.name,
          role: participant.role || 'human',
          status: 'online',
          connectorId: '',
          work: '可参与监督与讨论'
        }));
      const agentRows = connectors.map(connector => ({
        kind: connector.agentRole === 'supervisor' ? 'supervisor' : 'agent',
        id: connector.id,
        name: connector.name,
        role: connector.agentRole,
        status: connector.status || 'connected',
        connectorId: connector.id,
        adapter: connectorKindText[connector.kind] || connector.kind || 'MCP'
      }));
      const pendingRows = pendingRoomInvites(room).map(invite => ({
        kind: invite.agentRole === 'supervisor' ? 'supervisor' : 'agent',
        name: invite.name,
        role: invite.agentRole,
        status: 'invited',
        connectorId: invite.connectorId || '',
        adapter: 'MCP'
      }));
      return [
        {
          kind: 'owner',
          name: ownerName,
          role: 'owner',
          status: 'online',
          connectorId: '',
          adapter: 'Web',
          work: null
        },
        ...humans,
        ...pendingRows,
        ...agentRows
      ].map(member => ({
        ...member,
        work: member.work || memberWorkStatus(member, room, pendingMentions, pendingTasks)
      }));
    }
    function renderMember(member){
      const statusTextValue = connectorStatusText[member.status] || statusText[member.status] || member.status || '在线';
      const cls = member.kind === 'agent' ? 'agent' : 'owner';
      return `<article class="member-row ${cls}">
        <div class="member-head">
          <h3>${esc(member.name)}</h3>
          <span class="tag ${statusTagClass(member.status)}"><span class="dot ${statusTagClass(member.status)}"></span>${esc(statusTextValue)}</span>
        </div>
        <p>${esc(agentRoleLabel(member.role))} · ${esc(member.work)}</p>
        <div class="member-meta">
          <span class="tag info">${esc(member.adapter || 'MCP')}</span>
          <span class="tag mono">${esc(memberIdentityLabel(member))}</span>
        </div>
        ${renderCapabilityBadges(member)}
        ${renderMemberActions(member)}
      </article>`;
    }
    function renderMemberActions(member){
      if(member.kind !== 'agent' || !canManageCurrentRoom() || !member.connectorId || member.status === 'revoked') return '';
      return `<div class="actions" style="margin-top:10px"><button type="button" class="danger" data-revoke-connector="${esc(member.connectorId)}" data-revoke-name="${esc(member.name)}">撤销访问</button></div>`;
    }
    function memberCapabilityBadges(member){
      if(member.kind === 'owner') return [
        { label:'可发言', capability:'message:create', cls:'info' },
        { label:'可邀请', capability:'member:invite', cls:'online' },
        { label:'可分配', capability:'task:create', cls:'online' },
        { label:'可批准', capability:'decision:approve', cls:'online' }
      ];
      if(member.kind === 'supervisor') return [
        { label:'可发言', capability:'message:create', cls:'info' },
        { label:'可 @Agent', capability:'message:mention_agent', cls:'info' },
        { label:'不可邀请', capability:'member:invite', cls:'permission-locked' }
      ];
      if(member.kind === 'human') return [
        { label:'可发言', capability:'message:create', cls:'info' },
        { label:'不可管理', capability:'room:manage', cls:'permission-locked' }
      ];
      if(member.role === 'reviewer') return [
        { label:'可回消息', capability:'message:create', cls:'info' },
        { label:'可 Finding', capability:'finding:create', cls:'online' },
        { label:'按任务执行', capability:'task:assigned_run', cls:'waiting' }
      ];
      if(member.role === 'developer') return [
        { label:'可回消息', capability:'message:create', cls:'info' },
        { label:'可响应 Finding', capability:'finding:respond', cls:'online' },
        { label:'按任务执行', capability:'task:assigned_run', cls:'waiting' }
      ];
      return [
        { label:'可回消息', capability:'message:create', cls:'info' },
        { label:'按任务执行', capability:'task:assigned_run', cls:'waiting' }
      ];
    }
    function renderCapabilityBadges(member){
      return `<div class="capability-badges">${memberCapabilityBadges(member).map(badge => `<span class="tag ${esc(badge.cls)}" data-capability="${esc(badge.capability)}">${esc(badge.label)}</span>`).join('')}</div>`;
    }
    function renderMembers(room, pendingMentions, pendingTasks, latestCursor){
      const rows = memberRows(room, pendingMentions, pendingTasks);
      const agentCount = rows.filter(row => row.kind === 'agent').length;
      return `<div class="member-status-list">
        ${rows.map(renderMember).join('')}
        ${agentCount ? '' : '<div class="empty">暂无已邀请或已接入的 Agent</div>'}
      </div>
      <div class="actions" style="margin-top:12px">
        <span class="tag waiting">待回复 @ ${esc(pendingMentions)}</span>
        <span class="tag waiting">待执行任务 ${esc(pendingTasks)}</span>
        <span class="tag info">MCP 游标 ${esc(latestCursor)}</span>
      </div>`;
    }
    const successfulAgentStatuses = new Set(['connected', 'mcp_ready', 'mcp_streaming']);
    function mentionableAgents(room){
      const seen = new Set();
      return ((room && room.connectors) || [])
        .filter(connector => connector && connector.name && successfulAgentStatuses.has(connector.status || 'connected'))
        .filter(connector => {
          const key = connector.name.toLowerCase();
          if(seen.has(key)) return false;
          seen.add(key);
          return true;
        })
        .map(connector => connector.name);
    }
    function renderMentionControls(room){
      const names = mentionableAgents(room);
      if(!names.length) return '';
      return names.map(name => `<button type="button" data-mention="${esc(name)}">@${esc(name)}</button>`).join('');
    }
    function renderMentionBar(room){
      const controls = renderMentionControls(room);
      return controls ? `<div class="actions" style="margin-top:8px">${controls}</div>` : '';
    }
    function extractMentionNames(body, room=state.room){
      const text = body || '';
      const normalized = text.toLowerCase();
      return mentionableAgents(room).filter(name => {
        const mention = `@${name}`;
        return text.includes(mention) || normalized.includes(mention.toLowerCase());
      });
    }
    function insertMention(name){
      const input = document.getElementById('topicInput');
      if(!input) return;
      const mention = `@${name} `;
      const start = input.selectionStart ?? input.value.length;
      const end = input.selectionEnd ?? input.value.length;
      const prefix = input.value.slice(0, start);
      const suffix = input.value.slice(end);
      const spacer = prefix && !/\\s$/.test(prefix) ? ' ' : '';
      input.value = `${prefix}${spacer}${mention}${suffix}`;
      const next = (prefix + spacer + mention).length;
      input.focus();
      input.setSelectionRange(next, next);
    }
    function sendTopicMessage(){
      const input = document.getElementById('topicInput');
      if(!input) return;
      const body = input.value;
      const kind = isSupervisorCurrentRoom() ? 'supervisor_message' : 'owner_topic';
      sendSocket({ type:'message.create', kind, body, mentions:extractMentionNames(body) });
    }
    function formatDateTime(value){
      if(!value) return '未知';
      const date = new Date(value);
      if(Number.isNaN(date.getTime())) return '未知';
      return date.toLocaleString([], { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' });
    }
    function auditPageCount(events){
      return Math.max(1, Math.ceil(((events || []).length) / AUDIT_PAGE_SIZE));
    }
    function ensureAuditState(events){
      if(!state.room) return;
      if(state.audit.roomId !== state.room.id){
        state.audit = { expanded: false, page: 0, roomId: state.room.id };
      }
      const maxPage = auditPageCount(events) - 1;
      state.audit.page = Math.max(0, Math.min(state.audit.page, maxPage));
    }
    function auditPageEvents(events){
      const newestFirst = [...(events || [])].reverse();
      const start = state.audit.page * AUDIT_PAGE_SIZE;
      return newestFirst.slice(start, start + AUDIT_PAGE_SIZE);
    }
    function renderAuditControls(){
      const events = (state.room && state.room.events) || [];
      if(!state.audit.expanded || !events.length) return '';
      const totalPages = auditPageCount(events);
      const currentPage = Math.min(state.audit.page + 1, totalPages);
      return `<div class="audit-controls">
        <button type="button" data-audit-page="prev" ${state.audit.page <= 0 ? 'disabled' : ''}>上一页</button>
        <span class="tag">第 ${esc(currentPage)} / ${esc(totalPages)} 页</span>
        <button type="button" data-audit-page="next" ${state.audit.page >= totalPages - 1 ? 'disabled' : ''}>下一页</button>
        <span class="tag info">每页 ${esc(AUDIT_PAGE_SIZE)} 条</span>
      </div>`;
    }
    function renderAuditPanel(events){
      ensureAuditState(events);
      const rows = auditPageEvents(events);
      const body = state.audit.expanded
        ? `<div class="audit-list">${rows.length ? rows.map(renderEvent).join('') : '<div class="empty">暂无审计事件</div>'}</div>${renderAuditControls()}`
        : '<div class="empty">审计日志已折叠，展开后查看事件明细。</div>';
      return `<section class="panel" style="margin-top:14px">
        <div class="panel-head">
          <h2>活动 / 审计日志</h2>
          <div class="audit-head-actions">
            <span class="tag">${esc(events.length)} 条事件</span>
            <button type="button" data-audit-toggle>${state.audit.expanded ? '收起' : '展开'}</button>
          </div>
        </div>
        <div class="panel-body">${body}</div>
      </section>`;
    }
    function bindAuditControls(){
      const toggle = document.querySelector('[data-audit-toggle]');
      if(toggle){
        toggle.addEventListener('click', () => {
          state.audit.expanded = !state.audit.expanded;
          state.audit.page = 0;
          renderDetail();
        });
      }
      document.querySelectorAll('[data-audit-page]').forEach(button => {
        button.addEventListener('click', () => {
          const direction = button.dataset.auditPage === 'next' ? 1 : -1;
          const events = (state.room && state.room.events) || [];
          state.audit.page = Math.max(0, Math.min(state.audit.page + direction, auditPageCount(events) - 1));
          renderDetail();
        });
      });
    }
    async function loadRooms(){
      const data = await api('/api/workbenches');
      state.rooms = data.workbenches || [];
      document.getElementById('roomCount').textContent = `${visibleRooms().length} 个`;
      document.getElementById('archivedRoomCount').textContent = archivedRooms().length;
      renderRooms();
    }
    function renderRoomLifecycleControls(room){
      if(!state.tokens[room.id]){
        return '<span class="tag">&#21482;&#35835;</span>';
      }
      if(room.status === 'archived'){
        return `<span class="room-actions">
          <button type="button" class="success" data-room-action="restore" data-room-id="${esc(room.id)}">&#24674;&#22797;</button>
          <button type="button" class="danger" data-room-action="delete" data-room-id="${esc(room.id)}">&#24443;&#24213;&#21024;&#38500;</button>
        </span>`;
      }
      if(room.status === 'deleted'){
        return '';
      }
      return `<span class="room-actions"><button type="button" data-room-action="archive" data-room-id="${esc(room.id)}">&#24402;&#26723;</button></span>`;
    }
    function renderRooms(){
      const list = document.getElementById('roomList');
      const rooms = visibleRooms();
      const hallNotice = document.getElementById('hallNotice');
      if(hallNotice){
        hallNotice.textContent = state.hallNotice || '';
        hallNotice.classList.toggle('hidden', !state.hallNotice);
      }
      document.getElementById('archiveModeLabel').textContent = state.viewMode === 'archived' ? '已归档工作台' : '最近工作台';
      document.getElementById('roomCount').textContent = `${rooms.length} 个`;
      if(!rooms.length){
        list.innerHTML = state.viewMode === 'archived'
          ? '<div class="empty">暂无已归档工作台</div>'
          : '<div class="empty">暂无工作台</div>';
        return;
      }
      list.innerHTML = rooms.map(room => `
        <div class="workbench-row ${state.room && state.room.id === room.id ? 'active' : ''}" role="button" tabindex="0" data-room="${esc(room.id)}">
          <span><strong>${esc(room.title)}</strong><p class="mono">${esc(room.provider || room.template || 'workbench')}</p></span>
          <span class="metric mono">${esc(formatDateTime(room.createdAt))}</span>
          <span class="tag ${room.status === 'open' ? 'online' : room.status === 'deleted' ? 'danger' : 'waiting'}">${esc(statusText[room.status] || room.status)}</span>
          <span class="metric">${esc((room.counts && room.counts.findings) || 0)}</span>
          <span class="metric">${esc((room.counts && room.counts.tasks) || 0)}</span>
          <span class="metric">${esc(room.activeRunCount || 0)}</span>
          <span class="metric">${esc(room.pendingOwnerActions || 0)}</span>
          <span class="metric">${esc((room.connectorStatus && room.connectorStatus.active) || 0)}/${esc((room.connectorStatus && room.connectorStatus.total) || 0)}</span>
          ${renderRoomLifecycleControls(room)}
        </div>`).join('');
      bindRoomLifecycleControls();
    }
    function bindRoomLifecycleControls(){
      const list = document.getElementById('roomList');
      list.querySelectorAll('[data-room]').forEach(row => {
        row.addEventListener('click', event => {
          if(event.target.closest('[data-room-action]')) return;
          selectRoom(row.dataset.room).catch(alert);
        });
        row.addEventListener('keydown', event => {
          if(event.target.closest('[data-room-action]')) return;
          if(event.key === 'Enter' || event.key === ' '){
            event.preventDefault();
            selectRoom(row.dataset.room).catch(alert);
          }
        });
      });
      list.querySelectorAll('[data-room-action]').forEach(button => button.addEventListener('click', event => {
        event.stopPropagation();
        const roomId = button.dataset.roomId;
        const action = button.dataset.roomAction;
        if(action === 'archive') archiveRoomFromHall(roomId).catch(alert);
        if(action === 'restore') restoreRoomFromHall(roomId).catch(alert);
        if(action === 'delete') deleteRoomFromHall(roomId).catch(alert);
      }));
    }
    async function archiveRoomFromHall(roomId){
      await api(`/api/workbenches/${encodeURIComponent(roomId)}/archive`, { method:'POST', headers:authHeaders(roomId), body:JSON.stringify({}) });
      if(state.room && state.room.id === roomId) state.room = null;
      state.viewMode = 'active';
      await loadRooms();
    }
    async function restoreRoomFromHall(roomId){
      await api(`/api/workbenches/${encodeURIComponent(roomId)}/restore`, { method:'POST', headers:authHeaders(roomId), body:JSON.stringify({}) });
      if(state.room && state.room.id === roomId) state.room = null;
      state.viewMode = 'active';
      await loadRooms();
    }
    async function deleteRoomFromHall(roomId){
      const confirmed = confirm('彻底删除会从工作台列表移除这个工作台，但只会生成服务端 tombstone 和审计记录，不清理远端 Agent 机器、MCP 配置、日志或工作区文件。继续？');
      if(!confirmed) return;
      await api(`/api/workbenches/${encodeURIComponent(roomId)}`, {
        method:'DELETE',
        headers:authHeaders(roomId),
        body:JSON.stringify({ confirm:true, reason:'owner removed archived workbench from hall UI' })
      });
      cleanupStoredRoomAccess(roomId);
      if(state.room && state.room.id === roomId) state.room = null;
      state.viewMode = 'archived';
      await loadRooms();
    }
    async function createRoom(){
      const room = await api('/api/workbenches', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
        title: document.getElementById('roomTitle').value || 'MR：Lighthouse 智能体看板',
        provider: 'lighthouse',
        owner: document.getElementById('roomOwner').value || '工作台负责人',
        template: 'mr-review',
        context: { goal: 'MR 评审工作台' }
      })});
      state.tokens[room.id] = room.ownerToken;
      saveTokens();
      await loadRooms();
      await selectRoom(room.id);
    }
    async function selectRoom(roomId){
      const token = accessTokenForRoom(roomId);
      if(!token){ renderMissingToken(roomId); return; }
      state.room = await api(`/api/workbenches/${encodeURIComponent(roomId)}`, { headers:{ Authorization:`Bearer ${token}` } });
      renderRooms();
      renderDetail();
      connectSocket();
      showDetail();
    }
    async function reloadCurrentRoom(roomId){
      state.room = await api(`/api/workbenches/${encodeURIComponent(roomId)}`, { headers:{ Authorization:`Bearer ${accessTokenForRoom(roomId)}` } });
      renderRooms();
      renderDetail();
      connectSocket();
      showDetail();
    }
    async function archiveCurrentRoom(){
      if(!state.room) return;
      const roomId = state.room.id;
      await api(`/api/workbenches/${encodeURIComponent(roomId)}/archive`, { method:'POST', headers:authHeaders(roomId), body:JSON.stringify({}) });
      state.viewMode = 'archived';
      await loadRooms();
      await reloadCurrentRoom(roomId);
    }
    async function restoreCurrentRoom(){
      if(!state.room) return;
      const roomId = state.room.id;
      await api(`/api/workbenches/${encodeURIComponent(roomId)}/restore`, { method:'POST', headers:authHeaders(roomId), body:JSON.stringify({}) });
      state.viewMode = 'active';
      await loadRooms();
      await reloadCurrentRoom(roomId);
    }
    async function deleteCurrentRoom(){
      if(!state.room) return;
      const roomId = state.room.id;
      const confirmed = confirm('彻底删除会从工作台列表移除这个工作台，但只会生成服务端 tombstone 和审计记录，不清理远端 Agent 机器、MCP 配置、日志或工作区文件。继续？');
      if(!confirmed) return;
      await api(`/api/workbenches/${encodeURIComponent(roomId)}`, {
        method:'DELETE',
        headers:authHeaders(roomId),
        body:JSON.stringify({ confirm:true, reason:'owner removed archived workbench from local UI' })
      });
      cleanupStoredRoomAccess(roomId);
      state.room = null;
      if(state.ws) state.ws.close();
      state.viewMode = 'archived';
      await loadRooms();
      showArchivedRooms();
    }
    function renderMissingToken(roomId){
      state.room = null;
      document.getElementById('detailTitle').textContent = roomId;
      document.getElementById('detailBody').innerHTML = '<div class="empty">本机没有这个工作台的负责人令牌，无法进入。</div>';
      showDetail();
    }
    async function copyText(text){
      if(navigator.clipboard && navigator.clipboard.writeText && window.isSecureContext){
        try{
          await navigator.clipboard.writeText(text);
          return true;
        }catch(_err){}
      }
      return fallbackCopyText(text);
    }
    function fallbackCopyText(text){
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.left = '-9999px';
      textarea.style.top = '0';
      document.body.appendChild(textarea);
      try{
        return copyTextarea(textarea);
      }finally{
        document.body.removeChild(textarea);
      }
    }
    function copyTextarea(textarea){
      textarea.focus();
      textarea.select();
      textarea.setSelectionRange(0, textarea.value.length);
      let copied = false;
      try{
        copied = document.execCommand('copy');
      }catch(_err){
        copied = false;
      }
      return copied;
    }
    function showCopyFallback(text){
      state.copyFallback = { roomId: state.room && state.room.id, text, copied:false };
      renderCopyFallback();
    }
    function renderCopyFallback(){
      const detail = document.getElementById('detailBody');
      if(!detail) return;
      const existing = document.getElementById('copyFallback');
      if(existing) existing.remove();
      if(!state.copyFallback || !state.room || state.copyFallback.roomId !== state.room.id) return;
      const wrapper = document.createElement('div');
      wrapper.id = 'copyFallback';
      wrapper.className = 'message owner';
      wrapper.style.marginBottom = '12px';
      const copyStatus = state.copyFallback.copied ? '已复制' : '待复制';
      const buttonText = state.copyFallback.copied ? '已复制' : '复制';
      wrapper.innerHTML = `
        <div class="message-head"><h3>MCP 接入话术</h3><span class="tag waiting">${copyStatus}</span></div>
        <p>浏览器没有放行自动复制，请点下面按钮复制，或直接选中文本。</p>
        <textarea id="copyFallbackText" readonly></textarea>
        <div class="actions" style="margin-top:8px"><button class="primary" id="copyFallbackButton">${buttonText}</button></div>`;
      detail.prepend(wrapper);
      const textarea = document.getElementById('copyFallbackText');
      const button = document.getElementById('copyFallbackButton');
      textarea.value = state.copyFallback.text;
      textarea.focus();
      textarea.select();
      button.addEventListener('click', () => {
        const copied = copyTextarea(textarea);
        if(copied){
          state.copyFallback.copied = true;
          button.textContent = '已复制';
          wrapper.querySelector('.tag').textContent = '已复制';
        }else{
          button.textContent = '已选中';
          wrapper.querySelector('.tag').textContent = '已选中';
          textarea.focus();
          textarea.select();
        }
      });
    }
    function inviteText(invite, agentName, role){
      const mcpUrl = `${location.origin}/mcp`;
      return [
        `添加远程 MCP 服务：`,
        `name: lighthouse-agent-board`,
        `url: ${mcpUrl}`,
        `auth: Bearer ${invite.token}`,
        ``,
        `身份：${agentName} · ${agentRoleLabel(role)}`,
        `添加后先调用 join_room，roomId=${state.room.id}。`,
        `然后调用 get_agent_briefing 读取本房间规则、信任边界、当前状态和下一步工具。`,
        `完成参与时调用 leave_room，然后停止 wait_room_events；如需彻底禁止再次接入，由负责人撤销访问。`
      ].join('\\n');
    }
    function openInviteModal(role='reviewer'){
      const modal = document.getElementById('inviteModal');
      document.getElementById('inviteAgentRole').value = role;
      document.getElementById('inviteAgentName').value = defaultAgentName();
      document.getElementById('inviteOutput').classList.add('hidden');
      document.getElementById('inviteCopyStatus').classList.add('hidden');
      document.getElementById('inviteCopyText').value = '';
      modal.classList.remove('hidden');
      document.getElementById('inviteAgentName').focus();
      document.getElementById('inviteAgentName').select();
    }
    function closeInviteModal(){
      document.getElementById('inviteModal').classList.add('hidden');
    }
    async function createMcpInvite(agentName, role){
      if(!state.room) return;
      const invite = await api(`/api/rooms/${encodeURIComponent(state.room.id)}/mcp-invites`, {
        method:'POST',
        headers: authHeaders(state.room.id),
        body: JSON.stringify({ agentName, agentRole: role, ttlMs: 24 * 60 * 60 * 1000 })
      });
      rememberPendingInvite(invite);
      const text = inviteText(invite, agentName, role);
      const output = document.getElementById('inviteOutput');
      const textarea = document.getElementById('inviteCopyText');
      const status = document.getElementById('inviteCopyStatus');
      textarea.value = text;
      output.classList.remove('hidden');
      status.classList.remove('hidden');
      const copied = await copyText(text);
      status.textContent = copied ? '已复制' : '请手动复制';
      status.className = copied ? 'tag online' : 'tag waiting';
      if(!copied){
        textarea.focus();
        textarea.select();
      }
      renderDetail();
    }
    async function submitInviteForm(event){
      event.preventDefault();
      const role = document.getElementById('inviteAgentRole').value || 'reviewer';
      const agentName = document.getElementById('inviteAgentName').value.trim() || defaultAgentName();
      document.getElementById('inviteAgentName').value = agentName;
      await createMcpInvite(agentName, role);
    }
    async function copyInviteText(){
      const textarea = document.getElementById('inviteCopyText');
      if(!textarea.value) return;
      const copied = await copyText(textarea.value);
      const status = document.getElementById('inviteCopyStatus');
      status.classList.remove('hidden');
      status.textContent = copied ? '已复制' : '请手动复制';
      status.className = copied ? 'tag online' : 'tag waiting';
      if(!copied){
        textarea.focus();
        textarea.select();
      }
    }
    function openSupervisorInviteModal(){
      const modal = document.getElementById('supervisorInviteModal');
      document.getElementById('supervisorInviteName').value = defaultSupervisorName();
      document.getElementById('supervisorInviteOutput').classList.add('hidden');
      document.getElementById('supervisorInviteCopyStatus').classList.add('hidden');
      document.getElementById('supervisorInviteUrl').value = '';
      modal.classList.remove('hidden');
      document.getElementById('supervisorInviteName').focus();
      document.getElementById('supervisorInviteName').select();
    }
    function closeSupervisorInviteModal(){
      document.getElementById('supervisorInviteModal').classList.add('hidden');
    }
    async function createSupervisorInvite(name){
      if(!state.room) return;
      const invite = await api(`/api/rooms/${encodeURIComponent(state.room.id)}/supervisor-invites`, {
        method:'POST',
        headers: authHeaders(state.room.id),
        body: JSON.stringify({ name, ttlMs: 24 * 60 * 60 * 1000 })
      });
      const url = invite.url || `${location.origin}/?roomId=${encodeURIComponent(state.room.id)}&supervisorInvite=${encodeURIComponent(invite.token)}`;
      const output = document.getElementById('supervisorInviteOutput');
      const textarea = document.getElementById('supervisorInviteUrl');
      const status = document.getElementById('supervisorInviteCopyStatus');
      textarea.value = url;
      output.classList.remove('hidden');
      status.classList.remove('hidden');
      const copied = await copyText(url);
      status.textContent = copied ? '已复制' : '请手动复制';
      status.className = copied ? 'tag online' : 'tag waiting';
      if(!copied){
        textarea.focus();
        textarea.select();
      }
    }
    async function submitSupervisorInviteForm(event){
      event.preventDefault();
      const name = document.getElementById('supervisorInviteName').value.trim() || defaultSupervisorName();
      document.getElementById('supervisorInviteName').value = name;
      await createSupervisorInvite(name);
    }
    async function copySupervisorInviteUrl(){
      const textarea = document.getElementById('supervisorInviteUrl');
      if(!textarea.value) return;
      const copied = await copyText(textarea.value);
      const status = document.getElementById('supervisorInviteCopyStatus');
      status.classList.remove('hidden');
      status.textContent = copied ? '已复制' : '请手动复制';
      status.className = copied ? 'tag online' : 'tag waiting';
      if(!copied){
        textarea.focus();
        textarea.select();
      }
    }
    async function consumeSupervisorInviteFromUrl(){
      const params = new URLSearchParams(location.search);
      const roomId = params.get('roomId');
      const inviteToken = params.get('supervisorInvite');
      if(!roomId || !inviteToken) return false;
      const result = await api(`/api/rooms/${encodeURIComponent(roomId)}/supervisor-invites/consume`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ token: inviteToken })
      });
      state.supervisorTokens[roomId] = result.accessToken;
      saveSupervisorTokens();
      if(history.replaceState) history.replaceState({}, document.title, location.pathname);
      await loadRooms();
      state.room = result.room || await api(`/api/workbenches/${encodeURIComponent(roomId)}`, { headers:{ Authorization:`Bearer ${accessTokenForRoom(roomId)}` } });
      renderRooms();
      renderDetail();
      connectSocket();
      showDetail();
      return true;
    }
    function connectSocket(){
      if(!state.room) return;
      if(state.ws) state.ws.close();
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      state.ws = new WebSocket(`${proto}//${location.host}/ws/rooms/${encodeURIComponent(state.room.id)}?token=${encodeURIComponent(accessTokenForRoom(state.room.id))}`);
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
    async function createTaskFromDetail(){
      if(!state.room) return;
      const task = await api(`/api/rooms/${encodeURIComponent(state.room.id)}/tasks`, {
        method:'POST',
        headers: authHeaders(state.room.id),
        body: JSON.stringify({ title:'评审 MR 风险', body:'输出结构化发现和关键证据。', assignedTo:'评审智能体' })
      });
      state.room.tasks = [...(state.room.tasks || []), task];
      renderDetail();
    }
    function inviteDefaultAgent(){ openInviteModal('reviewer'); }
    function openSupervisorLeaveModal(){
      document.getElementById('supervisorLeaveModal').classList.remove('hidden');
    }
    function closeSupervisorLeaveModal(){
      document.getElementById('supervisorLeaveModal').classList.add('hidden');
    }
    async function leaveSupervisorSession(){
      if(!state.room) return;
      const roomId = state.room.id;
      await api(`/api/rooms/${encodeURIComponent(roomId)}/supervisor-session/leave`, {
        method:'POST',
        headers: authHeaders(roomId),
        body: JSON.stringify({ reason:'supervisor left from workbench UI' })
      });
      closeSupervisorLeaveModal();
      if(state.ws) state.ws.close();
      delete state.supervisorTokens[roomId];
      saveSupervisorTokens();
      state.room = null;
      state.hallNotice = '已退出监督者会话，本设备已清除该看板访问令牌。';
      await loadRooms();
      showHall();
    }
    function openAgentRevokeModal(connectorId, name){
      state.pendingRevokeConnector = { id: connectorId, name };
      document.getElementById('agentRevokeName').textContent = name || 'Agent';
      document.getElementById('agentRevokeModal').classList.remove('hidden');
    }
    function closeAgentRevokeModal(){
      document.getElementById('agentRevokeModal').classList.add('hidden');
      state.pendingRevokeConnector = null;
    }
    async function revokeAgentAccess(){
      if(!state.room || !state.pendingRevokeConnector) return;
      const roomId = state.room.id;
      await api(`/api/rooms/${encodeURIComponent(roomId)}/connectors/${encodeURIComponent(state.pendingRevokeConnector.id)}/revoke`, {
        method:'POST',
        headers: authHeaders(roomId),
        body: JSON.stringify({ reason:'owner revoked Agent access from workbench UI' })
      });
      closeAgentRevokeModal();
      await reloadCurrentRoom(roomId);
    }
    function renderDetail(){
      const room = state.room;
      if(!room) return;
      document.getElementById('detailTitle').textContent = room.title;
      document.getElementById('detailMeta').textContent = `状态：${statusText[room.status] || room.status || '进行中'} · MCP 接入和任务运行以工作台状态为准`;
      const messages = room.messages || [];
      const findings = room.findings || [];
      const tasks = room.tasks || [];
      const events = room.events || [];
      const runs = room.agentRuns || [];
      const decisions = room.decisions || [];
      const connectors = room.connectors || [];
      const latestCursor = events.length ? events[events.length - 1].cursor : 0;
      const pendingMentions = events.filter(event => {
        if(event.type !== 'mention.requires_reply') return false;
        const message = (event.payload && event.payload.message) || {};
        return message.senderName !== (event.payload && event.payload.targetAgentName);
      }).length;
      const pendingTasks = tasks.filter(task => ['assigned','running'].includes(task.status)).length;
      const canManage = canManageCurrentRoom();
      const canEditWorkbench = canManage && room.status !== 'archived' && room.status !== 'deleted';
      const canArchiveWorkbench = canManage && !['archived','deleted'].includes(room.status);
      const canRestoreWorkbench = canManage && room.status === 'archived';
      const canPostMessage = canPostMessagesCurrentRoom();
      const isSupervisor = isSupervisorCurrentRoom();
      const detailLeaveSupervisor = document.getElementById('detailLeaveSupervisor');
      const detailCreateTask = document.getElementById('detailCreateTask');
      const detailInviteSupervisor = document.getElementById('detailInviteSupervisor');
      const detailInviteAgent = document.getElementById('detailInviteAgent');
      const detailArchiveWorkbench = document.getElementById('detailArchiveWorkbench');
      const detailRestoreWorkbench = document.getElementById('detailRestoreWorkbench');
      const detailDeleteWorkbench = document.getElementById('detailDeleteWorkbench');
      detailLeaveSupervisor.hidden = !isSupervisor || room.status === 'deleted';
      detailCreateTask.hidden = !canEditWorkbench;
      detailInviteSupervisor.hidden = !canEditWorkbench;
      detailInviteAgent.hidden = !canEditWorkbench;
      detailArchiveWorkbench.hidden = !canArchiveWorkbench;
      detailRestoreWorkbench.hidden = !canRestoreWorkbench;
      detailDeleteWorkbench.hidden = !canRestoreWorkbench;
      applyCommandPermission(detailCreateTask, canEditWorkbench, 'task:create');
      applyCommandPermission(detailInviteSupervisor, canEditWorkbench, 'member:invite_human');
      applyCommandPermission(detailInviteAgent, canEditWorkbench, 'member:invite_agent');
      applyCommandPermission(detailArchiveWorkbench, canArchiveWorkbench, 'room:archive');
      applyCommandPermission(detailRestoreWorkbench, canRestoreWorkbench, 'room:restore');
      applyCommandPermission(detailDeleteWorkbench, canRestoreWorkbench, 'room:delete');
      const topicLabel = isSupervisorCurrentRoom() ? '监督者发起话题' : '负责人发起话题';
      const topicDraft = isSupervisorCurrentRoom() ? '@Reviewer Agent ' : '请评审这个 MR 的鉴权风险，并给出可执行修复建议。';
      const composerHtml = canPostMessage
        ? `<div class="field" style="margin-top:12px"><label>${topicLabel}</label><div class="composer-box"><textarea id="topicInput">${topicDraft}</textarea><button class="primary" id="sendTopic">发送</button></div></div>${renderMentionBar(room)}`
        : room.status === 'archived'
          ? '<div class="empty">已归档工作台为只读状态，可恢复后继续协作。</div>'
        : '<div class="empty">监督者会话为只读模式，可查看工作台状态与审计日志。</div>';
      document.getElementById('detailBody').innerHTML = `
        <div class="detail-grid">
          <section class="panel">
            <div class="panel-head"><h2>成员与状态</h2><span class="tag">身份状态栏</span></div>
            <div class="panel-body">
              ${renderMembers(room, pendingMentions, pendingTasks, latestCursor)}
            </div>
          </section>
          <aside class="panel">
            <div class="panel-head"><h2>检查器 / 操作栏</h2><span class="tag info">任务 ${esc(tasks.length)} · 运行 ${esc(runs.length)}</span></div>
            <div class="panel-body">
              <div class="object-list">
                ${tasks.length ? tasks.map(renderTask).join('') : '<div class="empty">暂无目标</div>'}
                ${runs.length ? runs.map(renderRun).join('') : ''}
                ${decisions.length ? decisions.map(renderDecision).join('') : ''}
              </div>
              <p class="notice">普通工作台消息不是执行权限；智能体执行仍然需要任务、认领和运行记录。</p>
            </div>
          </aside>
        </div>
        <div class="stream-layout">
          <section class="panel">
            <div class="panel-head"><h2>上下文流</h2><span class="tag">消息输入</span></div>
            <div class="panel-body">
              <div class="timeline">${messages.length ? messages.map(renderMessage).join('') : '<div class="empty">暂无消息</div>'}</div>
              ${composerHtml}
            </div>
          </section>
        </div>
        ${renderAuditPanel(events)}`;
      document.querySelectorAll('[data-mention]').forEach(btn => btn.addEventListener('click', () => insertMention(btn.dataset.mention)));
      document.querySelectorAll('[data-revoke-connector]').forEach(btn => {
        btn.addEventListener('click', () => openAgentRevokeModal(btn.dataset.revokeConnector, btn.dataset.revokeName));
      });
      const sendTopic = document.getElementById('sendTopic');
      if(sendTopic) sendTopic.addEventListener('click', () => sendTopicMessage());
      document.querySelectorAll('[data-confirm]').forEach(btn => btn.addEventListener('click', () => sendSocket({ type:'finding.confirm', findingId:btn.dataset.confirm, decision:'accepted', body:'确认该修复方向。' })));
      document.querySelectorAll('[data-reject]').forEach(btn => btn.addEventListener('click', () => sendSocket({ type:'finding.reject', findingId:btn.dataset.reject, decision:'rejected', body:'驳回该结论，请继续讨论。' })));
      bindAuditControls();
      renderCopyFallback();
    }
    function renderTask(task){ return `<article class="object-row"><div class="message-head"><h3>${esc(task.title)}</h3><span class="tag waiting">${esc(statusText[task.status] || task.status)}</span></div><p>${esc(task.assignedTo || '待认领')}</p><p class="mono">${esc(task.id)}</p></article>`; }
    function renderRun(run){ return `<article class="object-row"><div class="message-head"><h3>${esc(run.agentName)}</h3><span class="tag online">${esc(statusText[run.status] || run.status)}</span></div><p>${esc(run.promptSummary || run.finalMessage || run.error)}</p><p class="mono">${esc(run.id)}</p></article>`; }
    function renderDecision(decision){ return `<article class="object-row"><div class="message-head"><h3>${esc(decision.action || decision.kind)}</h3><span class="tag waiting">${esc(statusText[decision.status] || decision.status)}</span></div><p>${esc(decision.reason)}</p><p class="mono">${esc(decision.id)}</p></article>`; }
    function renderEvent(event){ return `<article class="event-row"><div class="event-head"><span class="event-type">${esc(event.type)}</span><span class="tag">${esc(event.cursor)}</span></div><p>${esc(event.actorName)} · ${new Date(event.createdAt).toLocaleString()}</p></article>`; }
    function renderMessage(message){
      const cls = message.senderType === 'human' ? 'owner' : 'agent';
      return `<article class="message ${cls}"><div class="message-head"><h3>${esc(message.senderName)}</h3><span class="tag">${esc(message.kind)}</span></div><div class="body">${esc(message.body)}</div></article>`;
    }
    function renderFinding(finding){
      const canConfirm = finding.status === 'developer_responded';
      return `<article class="finding"><div class="finding-head"><span class="tag p1">${esc(finding.severity)}</span><span class="tag waiting">${esc(statusText[finding.status] || finding.status)}</span></div><div class="finding-title">${esc(finding.claim)}</div><p>${esc(finding.evidence)}</p><p><strong>建议：</strong>${esc(finding.suggestedFix)}</p><div class="finding-actions"><button class="success" data-confirm="${esc(finding.id)}" ${canConfirm ? '' : 'disabled'}>人工确认并同步</button><button class="danger" data-reject="${esc(finding.id)}" ${canConfirm ? '' : 'disabled'}>驳回并继续讨论</button><button disabled>开发智能体回复</button></div></article>`;
    }
    document.getElementById('createRoom').addEventListener('click', () => createRoom().catch(alert));
    document.getElementById('refreshRooms').addEventListener('click', () => loadRooms().catch(alert));
    document.getElementById('showArchivedRooms').addEventListener('click', () => showArchivedRooms());
    document.getElementById('showHall').addEventListener('click', () => showHall());
    document.getElementById('backToHall').addEventListener('click', () => showHall());
    document.getElementById('detailArchiveWorkbench').addEventListener('click', () => archiveCurrentRoom().catch(alert));
    document.getElementById('detailRestoreWorkbench').addEventListener('click', () => restoreCurrentRoom().catch(alert));
    document.getElementById('detailDeleteWorkbench').addEventListener('click', () => deleteCurrentRoom().catch(alert));
    document.getElementById('detailCreateTask').addEventListener('click', () => createTaskFromDetail().catch(alert));
    document.getElementById('detailInviteSupervisor').addEventListener('click', () => openSupervisorInviteModal());
    document.getElementById('detailInviteAgent').addEventListener('click', () => inviteDefaultAgent());
    document.getElementById('detailLeaveSupervisor').addEventListener('click', () => openSupervisorLeaveModal());
    document.getElementById('inviteForm').addEventListener('submit', event => submitInviteForm(event).catch(alert));
    document.getElementById('inviteClose').addEventListener('click', () => closeInviteModal());
    document.getElementById('inviteCancel').addEventListener('click', () => closeInviteModal());
    document.getElementById('inviteCopyButton').addEventListener('click', () => copyInviteText().catch(alert));
    document.getElementById('supervisorInviteForm').addEventListener('submit', event => submitSupervisorInviteForm(event).catch(alert));
    document.getElementById('supervisorInviteClose').addEventListener('click', () => closeSupervisorInviteModal());
    document.getElementById('supervisorInviteCancel').addEventListener('click', () => closeSupervisorInviteModal());
    document.getElementById('supervisorInviteCopyButton').addEventListener('click', () => copySupervisorInviteUrl().catch(alert));
    document.getElementById('supervisorLeaveForm').addEventListener('submit', event => {
      event.preventDefault();
      leaveSupervisorSession().catch(alert);
    });
    document.getElementById('supervisorLeaveClose').addEventListener('click', () => closeSupervisorLeaveModal());
    document.getElementById('supervisorLeaveCancel').addEventListener('click', () => closeSupervisorLeaveModal());
    document.getElementById('agentRevokeForm').addEventListener('submit', event => {
      event.preventDefault();
      revokeAgentAccess().catch(alert);
    });
    document.getElementById('agentRevokeClose').addEventListener('click', () => closeAgentRevokeModal());
    document.getElementById('agentRevokeCancel').addEventListener('click', () => closeAgentRevokeModal());
    document.getElementById('inviteAgentRole').addEventListener('change', event => {
      const input = document.getElementById('inviteAgentName');
      if(!input.value || /^Agent-[A-Z0-9]{4}$/.test(input.value)) input.value = defaultAgentName();
    });
    consumeSupervisorInviteFromUrl()
      .then(consumed => { if(!consumed) return loadRooms(); })
      .catch(error => { alert(error); return loadRooms(); })
      .catch(alert);
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
        "Lighthouse Agent Board listening on http://{}:{} db={} websocket=/ws/rooms/<room_id>".format(
            host,
            port,
            db_path,
        ),
        flush=True,
    )
    web.run_app(build_app(store), host=host, port=port, print=None)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lighthouse Agent Board connector service")
    parser.add_argument("--host", default=os.environ.get("REVIEW_ROOM_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("REVIEW_ROOM_PORT", DEFAULT_PORT)))
    parser.add_argument("--db", default=os.environ.get("REVIEW_ROOM_DB", DEFAULT_DB_PATH))
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    run_server(args.host, args.port, args.db)


if __name__ == "__main__":
    main()
