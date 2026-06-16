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
from urllib.parse import parse_qs, urlparse

from aiohttp import web

from review_room_mcp import AFTER_TOOL_APP_KEY as MCP_AFTER_TOOL_KEY
from review_room_mcp import STORE_APP_KEY as MCP_STORE_KEY
from review_room_mcp import handle_mcp_get, handle_mcp_post


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
            rows = conn.execute("SELECT * FROM rooms ORDER BY updated_at DESC").fetchall()
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
        cleanup_boundary = (
            "Server-side Workbench tombstone only; this does not clean remote Agent machines, "
            "shell history, MCP config, transcripts, logs, caches, or workspace files."
        )
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
        invite = {
            "id": make_id("mcpi"),
            "roomId": room_id,
            "agentName": payload.get("agentName") or payload.get("agent_name") or "Remote Agent",
            "agentRole": payload.get("agentRole") or payload.get("agent_role") or payload.get("role") or "reviewer",
            "token": payload.get("token") or make_id("mcp"),
            "permissions": payload.get("permissions") or ["room:read", "message:write", "finding:write", "task:update"],
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
            if parsed.path == "/api/workbenches":
                self.send_json({"workbenches": self.store.list_workbenches()})
                return
            match = re.match(r"^/api/workbenches/([^/]+)$", parsed.path)
            if match:
                token = self.read_bearer_token({})
                self.store.require_owner_token(match.group(1), token)
                room = self.store.get_room(match.group(1))
                if not room:
                    self.send_error_json(HTTPStatus.NOT_FOUND, "workbench not found")
                    return
                self.send_json(room)
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
            match = re.match(r"^/api/workbenches/([^/]+)$", parsed.path)
            if match:
                self.send_json(self.store.update_workbench(match.group(1), body, self.read_bearer_token(body)))
                return
            match = re.match(r"^/api/findings/([^/]+)$", parsed.path)
            if match:
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
        mentions = payload.get("mentions") or payload.get("mentionedAgents") or []
        message = store.add_message(
            room_id,
            {
                "senderType": "human" if identity["type"] == "owner" else "agent",
                "senderName": identity["name"],
                "kind": payload.get("kind") or ("owner_topic" if identity["type"] == "owner" else "connector_message"),
                "body": payload.get("body") or "",
                "payload": {"eventType": event_type, "role": identity["role"], "mentions": mentions},
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
            await app[HUB_KEY].broadcast(room_id, {"type": "room.snapshot", "room": app[STORE_KEY].get_room(room_id)})

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
        ensure_owner(identity)
        room = app[STORE_KEY].get_room(room_id)
        if not room:
            raise web.HTTPNotFound(text=json_dumps({"ok": False, "error": "workbench not found"}), content_type="application/json")
        return json_response(room)

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
        return json_response(room)

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
    :root{--bg:#05070b;--surface:#0b1118;--panel:#0f1720;--panel2:#131d27;--line:#263544;--line2:#334657;--text:#d7e2ea;--muted:#7f91a2;--cyan:#35d6ff;--lime:#8df26f;--amber:#ffbf45;--red:#ff5f63;--blue:#6aa8ff;--shadow:rgba(0,0,0,.45)}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:"Source Sans 3","Geist",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;letter-spacing:0}
    body:before{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(53,214,255,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(53,214,255,.035) 1px,transparent 1px);background-size:32px 32px}
    button,input,textarea{font:inherit}button{min-height:34px;border:1px solid var(--line2);border-radius:6px;background:#111b25;color:var(--text);padding:0 12px;cursor:pointer}
    button.primary{border-color:var(--cyan);background:#062633;color:#dff8ff}button.success{border-color:var(--lime);background:#122a19;color:#eaffdf}button.danger{border-color:var(--red);background:#301318;color:#ffe5e5}
    button:disabled{opacity:.48;cursor:not-allowed}input,textarea{width:100%;border:1px solid var(--line);border-radius:6px;background:#071018;color:var(--text);padding:9px 10px}textarea{min-height:88px;resize:vertical}
    .mono,code,.tag,.metric,.event-type{font-family:"JetBrains Mono","IBM Plex Mono","SFMono-Regular",Consolas,monospace}code{border:1px solid var(--line);border-radius:4px;background:#08121a;padding:2px 6px;color:var(--cyan)}
    header{position:sticky;top:0;z-index:4;border-bottom:1px solid var(--line);background:rgba(5,7,11,.94);backdrop-filter:blur(16px)}.shell{max-width:1440px;margin:0 auto;padding:16px}.topbar{display:flex;gap:16px;align-items:center;justify-content:space-between}
    h1{margin:0;font-size:22px;line-height:1.15}h2{margin:0;font-size:15px}h3{margin:0;font-size:13px}p{margin:5px 0 0;color:var(--muted);line-height:1.45}.eyebrow{color:var(--cyan);font-size:12px;text-transform:uppercase}
    .actions{display:flex;flex-wrap:wrap;gap:8px}.tabs{display:flex;gap:6px}.tab{border-color:var(--line);background:#071018;color:var(--muted)}.tab.active{border-color:var(--cyan);color:var(--cyan)}
    .panel{border:1px solid var(--line);border-radius:8px;background:rgba(15,23,32,.96);box-shadow:0 18px 44px var(--shadow);min-width:0}.panel-head{display:flex;align-items:center;justify-content:space-between;gap:10px;border-bottom:1px solid var(--line);padding:12px 14px}.panel-body{padding:14px}
    .hall-grid{display:grid;grid-template-columns:minmax(340px,420px) minmax(0,1fr);gap:14px}.form-grid{display:grid;grid-template-columns:1fr;gap:10px}.field{display:grid;gap:6px}.field label{font-size:12px;color:var(--muted);text-transform:uppercase}.template-line{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;border:1px solid var(--line);border-radius:8px;background:#071018;padding:12px}
    .workbench-table{display:grid;gap:8px}.workbench-row{display:grid;grid-template-columns:minmax(220px,1.6fr) 120px repeat(4,minmax(74px,.5fr)) 120px;gap:8px;align-items:center;width:100%;min-height:58px;text-align:left;border:1px solid var(--line);border-radius:8px;background:#08121a;padding:10px}.workbench-row:hover,.workbench-row.active{border-color:var(--cyan)}
    .tag{display:inline-flex;align-items:center;gap:6px;min-height:22px;border:1px solid var(--line);border-radius:999px;background:#071018;padding:0 8px;color:var(--muted);font-size:11px}.tag.online{border-color:#315f38;color:var(--lime)}.tag.waiting{border-color:#6a5120;color:var(--amber)}.tag.p1,.tag.danger{border-color:#713039;color:var(--red)}.tag.info{border-color:#2e4f78;color:var(--blue)}
    .dot{width:7px;height:7px;border-radius:50%;background:var(--muted);display:inline-block}.dot.online{background:var(--lime)}.dot.waiting{background:var(--amber)}.dot.danger{background:var(--red)}.dot.info{background:var(--cyan)}
    .detail-grid{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:14px}.command-bar{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:center;margin-bottom:14px}.workflow{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}.step{border:1px solid var(--line);border-radius:8px;background:#071018;padding:10px;min-height:72px}.step.active{border-color:var(--cyan)}.step.done{border-color:#315f38}.step.waiting{border-color:#6a5120}
    .stream-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,420px);gap:14px;margin-top:14px}.timeline,.finding-list,.audit-list,.object-list{display:grid;gap:8px}.message,.finding,.object-row,.event-row{border:1px solid var(--line);border-radius:8px;background:#08121a;padding:10px}.message.owner{border-color:#244568}.message.agent{border-color:#315f38}.message-head,.finding-head,.event-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px}.body{white-space:pre-wrap;line-height:1.5;overflow-wrap:anywhere}.finding-title{font-weight:700}.finding-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
    .metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:10px}.metric{border:1px solid var(--line);border-radius:8px;background:#071018;padding:10px}.metric strong{display:block;color:var(--text);font-size:18px}.empty{border:1px dashed var(--line);border-radius:8px;padding:24px 14px;text-align:center;color:var(--muted)}.notice{margin-top:10px;color:var(--muted);font-size:12px}.hidden{display:none}
    @media(max-width:1100px){.hall-grid,.detail-grid,.stream-layout,.command-bar{grid-template-columns:1fr}.workbench-row{grid-template-columns:1fr 1fr}.workflow,.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
    @media(max-width:640px){.topbar{display:grid}.workflow,.metric-grid,.workbench-row{grid-template-columns:1fr}.shell{padding:12px}}
  </style>
</head>
<body>
  <header>
    <div class="shell topbar">
      <div>
        <div class="eyebrow mono">终端作战台</div>
        <h1>Lighthouse 工作台 / 智能体看板</h1>
        <p>MR 评审工作台控制台。消息进入上下文流；执行必须通过任务、认领、运行和负责人决策。</p>
      </div>
      <div class="actions">
        <button id="refreshRooms">刷新工作台</button>
        <button class="primary" id="showHall">工作台大厅</button>
        <button id="createDemo">创建体验看板</button>
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
              <div class="field"><label>仓库</label><input id="roomRepo" value="lighthouse/review-room"></div>
              <div class="field"><label>MR URL</label><input id="roomMr" value="https://git.example.com/lighthouse/review-room/-/merge_requests/1"></div>
              <div class="field"><label>负责人</label><input id="roomOwner" value="工作台负责人"></div>
            </div>
            <div class="actions" style="margin-top:12px"><button class="primary" id="createRoom">启动 MR 评审工作台</button></div>
            <p class="notice">生命周期操作会写入审计事件。删除只会生成服务端工作台墓碑，不会清理远端智能体机器。</p>
            <p class="notice mono">API: <code>/api/workbenches</code> · <code>/api/rooms/{roomId}/mcp-invites</code> · <code>/api/demo/session</code> · <code>/mcp</code></p>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head"><h2>最近工作台</h2><span class="tag" id="roomCount">0</span></div>
          <div class="panel-body">
            <div class="workbench-row mono" style="min-height:34px;color:var(--muted)">
              <span>工作台</span><span>状态</span><span>发现</span><span>任务</span><span>运行</span><span>负责人</span><span>MCP</span>
            </div>
            <div class="workbench-table" id="roomList"></div>
          </div>
        </section>
      </div>
    </section>
    <section id="detailView" class="hidden">
      <div class="command-bar">
        <div>
          <div class="eyebrow mono">工作台详情 · 流程轨道</div>
          <h1 id="detailTitle">选择或创建工作台</h1>
          <p id="detailMeta">负责人令牌会保存在本机浏览器 localStorage。</p>
        </div>
        <div class="actions"><span class="tag" id="socketState">未连接</span><button id="backToHall">返回大厅</button><button class="primary" id="detailCreateTask">创建任务</button><button id="detailInviteAgent">邀请智能体</button></div>
      </div>
      <div id="detailBody"><div class="empty">还没有可展示的工作台。</div></div>
    </section>
  </main>
  <script>
    const state = { rooms: [], room: null, ws: null, copyFallback: null, tokens: JSON.parse(localStorage.getItem('reviewRoomOwnerTokens') || '{}') };
    const statusText = { open: '进行中', archived: '已归档', deleted: '已删除', completed: '已完成', assigned:'已分配', running:'运行中', started:'已开始', pending:'待处理', proposed:'已提议', failed:'失败', needs_developer_response: '等待开发智能体', developer_responded: '等待负责人确认', accepted: '已确认', rejected: '已驳回' };
    const connectorStatusText = { connected:'已连接', disconnected:'已断开', invited:'已邀请', revoked:'已撤销', mcp_ready:'MCP 就绪', mcp_streaming:'MCP 在线' };
    const connectorKindText = { connector:'MCP', 'mcp-agent':'MCP', 'mcp-remote':'远程 MCP' };
    const workflowStages = ['接入','评审','修复','验证','决策'];
    function saveTokens(){ localStorage.setItem('reviewRoomOwnerTokens', JSON.stringify(state.tokens)); }
    function esc(v){ return String(v ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;'); }
    async function api(path, options={}){
      const res = await fetch(path, options);
      const data = await res.json();
      if(!res.ok) throw new Error(data.error || res.statusText);
      return data;
    }
    function authHeaders(roomId){ return { 'Content-Type':'application/json', Authorization:`Bearer ${state.tokens[roomId] || ''}` }; }
    function showHall(){
      document.getElementById('hallView').classList.remove('hidden');
      document.getElementById('detailView').classList.add('hidden');
      renderRooms();
    }
    function showDetail(){
      document.getElementById('hallView').classList.add('hidden');
      document.getElementById('detailView').classList.remove('hidden');
    }
    function roleStatus(role){
      const found = ((state.room && state.room.connectors) || []).find(c => c.agentRole === role);
      return found ? `${found.name} · ${connectorStatusText[found.status] || found.status || '已连接'} · ${connectorKindText[found.kind] || 'MCP 连接'}` : '未接入 MCP';
    }
    function extractMentionNames(body){
      const normalized = (body || '').toLowerCase();
      const options = [
        ['评审智能体', ['@评审智能体', '@评审', '@reviewer agent', '@reviewer', '@review']],
        ['开发智能体', ['@开发智能体', '@开发', '@developer agent', '@developer', '@dev']]
      ];
      return options
        .filter(([, aliases]) => aliases.some(alias => normalized.includes(alias)))
        .map(([name]) => name);
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
      sendSocket({ type:'message.create', body, mentions:extractMentionNames(body) });
    }
    async function loadRooms(){
      const data = await api('/api/workbenches');
      state.rooms = data.workbenches || [];
      document.getElementById('roomCount').textContent = `${state.rooms.length} 个`;
      renderRooms();
    }
    function renderRooms(){
      const list = document.getElementById('roomList');
      if(!state.rooms.length){ list.innerHTML = '<div class="empty">暂无工作台</div>'; return; }
      list.innerHTML = state.rooms.map(room => `
        <button class="workbench-row ${state.room && state.room.id === room.id ? 'active' : ''}" data-room="${esc(room.id)}">
          <span><strong>${esc(room.title)}</strong><p class="mono">${esc(room.repository || room.mrUrl || room.provider)}</p></span>
          <span class="tag ${room.status === 'open' ? 'online' : room.status === 'deleted' ? 'danger' : 'waiting'}">${esc(statusText[room.status] || room.status)}</span>
          <span class="metric">${esc((room.counts && room.counts.findings) || 0)}</span>
          <span class="metric">${esc((room.counts && room.counts.tasks) || 0)}</span>
          <span class="metric">${esc(room.activeRunCount || 0)}</span>
          <span class="metric">${esc(room.pendingOwnerActions || 0)}</span>
          <span class="metric">${esc((room.connectorStatus && room.connectorStatus.active) || 0)}/${esc((room.connectorStatus && room.connectorStatus.total) || 0)}</span>
        </button>`).join('');
      list.querySelectorAll('[data-room]').forEach(btn => btn.addEventListener('click', () => selectRoom(btn.dataset.room)));
    }
    async function createRoom(){
      const room = await api('/api/workbenches', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
        title: document.getElementById('roomTitle').value || 'MR：Lighthouse 智能体看板',
        provider: 'lighthouse',
        mrUrl: document.getElementById('roomMr').value,
        repository: document.getElementById('roomRepo').value,
        owner: document.getElementById('roomOwner').value || '工作台负责人',
        template: 'mr-review',
        context: { repository: document.getElementById('roomRepo').value, goal: 'MR 评审工作台' }
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
      state.room = await api(`/api/workbenches/${encodeURIComponent(roomId)}`, { headers:{ Authorization:`Bearer ${token}` } });
      renderRooms();
      renderDetail();
      connectSocket();
      showDetail();
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
    async function createMcpInvite(role){
      if(!state.room) return;
      const agentName = role === 'reviewer' ? '评审智能体' : '开发智能体';
      const invite = await api(`/api/rooms/${encodeURIComponent(state.room.id)}/mcp-invites`, {
        method:'POST',
        headers: authHeaders(state.room.id),
        body: JSON.stringify({ agentName, agentRole: role, ttlMs: 24 * 60 * 60 * 1000 })
      });
      const mcpUrl = `${location.origin}/mcp`;
      const text = [
        `请添加远程 MCP 服务：`,
        `name: lighthouse-agent-board`,
        `url: ${mcpUrl}`,
        `auth: Bearer ${invite.token}`,
        ``,
        `添加后请调用 join_room，roomId=${state.room.id}。`,
        `所有工作台消息都会进入你的收件箱；明确 @${agentName} 的消息是高优先级并需要回复。`,
        `消息不是执行权限；分配给你的任务必须 claim_task、start_run，然后 complete_task。`,
        `普通回复用 post_message，评审结论用 post_finding，外部动作先 request_owner_confirmation。`
      ].join('\\n');
      const copied = await copyText(text);
      await selectRoom(state.room.id);
      if(copied){
        state.copyFallback = null;
        alert('已复制 MCP 接入话术');
      }else{
        showCopyFallback(text);
      }
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
    function currentWorkflowStage(room){
      const findings = room.findings || [];
      const tasks = room.tasks || [];
      const decisions = room.decisions || [];
      if(decisions.some(decision => decision.status === 'pending') || findings.some(finding => finding.status === 'developer_responded')) return '决策';
      if(tasks.some(task => task.status === 'completed')) return '验证';
      if(tasks.some(task => ['assigned','running'].includes(task.status))) return '修复';
      if(findings.length) return '修复';
      if((room.messages || []).length > 1) return '评审';
      return '接入';
    }
    function renderWorkflow(room){
      const active = currentWorkflowStage(room);
      const activeIndex = workflowStages.indexOf(active);
      return `<div class="workflow">${workflowStages.map((stage, index) => {
        const cls = index < activeIndex ? 'done' : stage === active ? 'active' : index === activeIndex + 1 ? 'waiting' : '';
        return `<div class="step ${cls}"><span class="tag">${index + 1}</span><h3>${stage}</h3><p>${stage === active ? '负责人下一步' : '状态检查点'}</p></div>`;
      }).join('')}</div>`;
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
    function inviteDefaultAgent(){ createMcpInvite('reviewer').catch(alert); }
    function renderDetail(){
      const room = state.room;
      if(!room) return;
      document.getElementById('detailTitle').textContent = room.title;
      document.getElementById('detailMeta').textContent = `${(room.context && room.context.repository) || '未绑定仓库'} · ${room.mrUrl || '无 MR 地址'}`;
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
      document.getElementById('detailBody').innerHTML = `
        <section class="panel"><div class="panel-body">${renderWorkflow(room)}
          <div class="metric-grid">
            <div class="metric"><span>发现</span><strong>${esc(findings.length)}</strong></div>
            <div class="metric"><span>任务</span><strong>${esc(tasks.length)}</strong></div>
            <div class="metric"><span>运行</span><strong>${esc(runs.length)}</strong></div>
            <div class="metric"><span>负责人</span><strong>${esc(pendingMentions + decisions.filter(d => d.status === 'pending').length)}</strong></div>
          </div>
        </div></section>
        <div class="detail-grid" style="margin-top:14px">
          <section class="panel">
            <div class="panel-head"><h2>智能体作业</h2><span class="tag">MCP 游标 ${esc(latestCursor)}</span></div>
            <div class="panel-body">
              <div class="object-list">
                <div class="object-row"><h3>工作台负责人</h3><p>Web 端监督者 · 负责人令牌</p><span class="tag online"><span class="dot online"></span>在线</span></div>
                <div class="object-row"><h3>评审智能体</h3><p>${esc(roleStatus('reviewer'))}</p><div class="actions"><button data-mcp-role="reviewer">复制 MCP 接入话术</button></div></div>
                <div class="object-row"><h3>开发智能体</h3><p>${esc(roleStatus('developer'))}</p><div class="actions"><button data-mcp-role="developer">复制 MCP 接入话术</button></div></div>
              </div>
              <div class="actions" style="margin-top:12px"><span class="tag waiting">待回复 @ ${esc(pendingMentions)}</span><span class="tag waiting">待执行任务 ${esc(pendingTasks)}</span><span class="tag info">MCP ${esc(connectors.length)}</span></div>
            </div>
          </section>
          <aside class="panel">
            <div class="panel-head"><h2>检查器 / 操作栏</h2><span class="tag info">显式执行</span></div>
            <div class="panel-body">
              <div class="object-list">
                ${tasks.length ? tasks.map(renderTask).join('') : '<div class="empty">暂无任务</div>'}
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
              <div class="field" style="margin-top:12px"><label>负责人发起话题</label><textarea id="topicInput">请评审这个 MR 的鉴权风险，并给出可执行修复建议。</textarea></div>
              <div class="actions" style="margin-top:8px"><button type="button" data-mention="评审智能体">@评审</button><button type="button" data-mention="开发智能体">@开发</button><button class="primary" id="sendTopic">发送话题</button></div>
            </div>
          </section>
          <section class="panel">
          <div class="panel-head"><h2>发现 / 负责人决策</h2><span class="tag">${esc(findings.length)} 项</span></div>
          <div class="panel-body"><div class="finding-list">${findings.length ? findings.map(renderFinding).join('') : '<div class="empty">暂无发现 / 负责人决策</div>'}</div></div>
          </section>
        </div>
        <section class="panel" style="margin-top:14px">
          <div class="panel-head"><h2>活动 / 审计日志</h2><span class="tag">${esc(events.length)} 条事件</span></div>
          <div class="panel-body"><div class="audit-list">${events.length ? events.slice(-18).reverse().map(renderEvent).join('') : '<div class="empty">暂无审计事件</div>'}</div></div>
        </section>`;
      document.querySelectorAll('[data-mcp-role]').forEach(btn => btn.addEventListener('click', () => createMcpInvite(btn.dataset.mcpRole).catch(alert)));
      document.querySelectorAll('[data-mention]').forEach(btn => btn.addEventListener('click', () => insertMention(btn.dataset.mention)));
      document.getElementById('sendTopic').addEventListener('click', () => sendTopicMessage());
      document.querySelectorAll('[data-confirm]').forEach(btn => btn.addEventListener('click', () => sendSocket({ type:'finding.confirm', findingId:btn.dataset.confirm, decision:'accepted', body:'确认该修复方向。' })));
      document.querySelectorAll('[data-reject]').forEach(btn => btn.addEventListener('click', () => sendSocket({ type:'finding.reject', findingId:btn.dataset.reject, decision:'rejected', body:'驳回该结论，请继续讨论。' })));
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
    document.getElementById('createDemo').addEventListener('click', () => createDemo().catch(alert));
    document.getElementById('refreshRooms').addEventListener('click', () => loadRooms().catch(alert));
    document.getElementById('showHall').addEventListener('click', () => showHall());
    document.getElementById('backToHall').addEventListener('click', () => showHall());
    document.getElementById('detailCreateTask').addEventListener('click', () => createTaskFromDetail().catch(alert));
    document.getElementById('detailInviteAgent').addEventListener('click', () => inviteDefaultAgent());
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
