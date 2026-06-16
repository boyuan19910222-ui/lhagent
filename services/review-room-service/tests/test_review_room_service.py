import json
import os
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
import urllib.request


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from review_room_service import ReviewRoomStore, build_handler, index_html  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402
from threading import Thread  # noqa: E402


class ReviewRoomStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ReviewRoomStore(os.path.join(self.tmp.name, "test.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_room_adds_system_message(self):
        room = self.store.create_room(
            {
                "title": "MR: add review room",
                "provider": "gitlab",
                "mrUrl": "https://git.example.com/a/b/-/merge_requests/1",
                "participants": [{"type": "agent", "name": "Reviewer Agent"}],
            }
        )

        loaded = self.store.get_room(room["id"])

        self.assertEqual(loaded["title"], "MR: add review room")
        self.assertEqual(loaded["provider"], "gitlab")
        self.assertEqual(loaded["messages"][0]["kind"], "room_created")

    def test_add_finding_emits_review_finding_message(self):
        room = self.store.create_room({"title": "MR"})

        finding = self.store.add_finding(
            room["id"],
            {
                "severity": "P1",
                "filePath": "src/auth/session.ts",
                "line": 87,
                "claim": "权限校验可能被绕过",
                "evidence": "新增 early return 没有检查 role",
                "suggestedFix": "补充 role 校验并增加测试",
                "createdBy": "Reviewer Agent",
            },
        )
        loaded = self.store.get_room(room["id"])

        self.assertEqual(finding["status"], "needs_developer_response")
        self.assertEqual(loaded["findings"][0]["severity"], "P1")
        self.assertEqual(loaded["messages"][-1]["kind"], "review_finding")

    def test_update_finding_status(self):
        room = self.store.create_room({"title": "MR"})
        finding = self.store.add_finding(room["id"], {"claim": "缺少测试"})

        updated = self.store.update_finding(finding["id"], {"status": "accepted"})

        self.assertEqual(updated["status"], "accepted")

    def test_ingest_gitlab_merge_request_webhook(self):
        room = self.store.ingest_merge_request_webhook(
            {
                "object_attributes": {
                    "title": "Draft: Lighthouse Agent Board",
                    "url": "https://git.example.com/a/b/-/merge_requests/2",
                    "action": "open",
                },
                "project": {"path_with_namespace": "a/b"},
            }
        )

        self.assertEqual(room["provider"], "gitlab")
        self.assertEqual(room["context"]["repository"], "a/b")
        self.assertEqual(room["messages"][-1]["kind"], "mr_webhook")

    def test_demo_session_creates_actionable_review_room(self):
        room = self.store.create_demo_session()

        self.assertEqual(room["provider"], "demo")
        self.assertEqual(room["status"], "open")
        self.assertEqual(room["context"]["repository"], "lighthouse/review-room-demo")
        self.assertEqual(len(room["findings"]), 1)
        self.assertEqual(room["findings"][0]["status"], "needs_developer_response")
        self.assertEqual(room["messages"][-1]["kind"], "review_finding")

    def test_developer_response_and_human_confirmation_close_loop(self):
        room = self.store.create_demo_session()
        finding = room["findings"][0]

        responded = self.store.respond_to_finding(
            finding["id"],
            {
                "body": "我接受这个问题，会把 webhook secret 校验补到入口。",
                "senderName": "Developer Agent",
            },
        )
        confirmed = self.store.confirm_finding(
            finding["id"],
            {
                "decision": "accepted",
                "body": "同意该修复方向，同步为 MR 评论。",
                "syncTarget": "MR 评论",
            },
        )
        loaded = self.store.get_room(room["id"])

        self.assertEqual(responded["status"], "developer_responded")
        self.assertEqual(confirmed["status"], "accepted")
        self.assertEqual(loaded["status"], "completed")
        self.assertEqual(loaded["messages"][-3]["kind"], "developer_response")
        self.assertEqual(loaded["messages"][-2]["kind"], "human_confirmation")
        self.assertEqual(loaded["messages"][-1]["kind"], "mr_sync_preview")

    def test_home_page_exposes_product_workflow_actions(self):
        html = index_html()

        self.assertIn("工作台大厅", html)
        self.assertIn("MR 评审工作台", html)
        self.assertIn("终端作战台", html)
        self.assertIn("流程轨道", html)
        self.assertIn("接入", html)
        self.assertIn("评审", html)
        self.assertIn("修复", html)
        self.assertIn("验证", html)
        self.assertIn("决策", html)
        self.assertIn("活动 / 审计日志", html)
        self.assertIn("创建任务", html)
        self.assertIn("邀请智能体", html)
        self.assertIn("/api/workbenches", html)
        self.assertIn("/mcp", html)
        self.assertIn("复制 MCP 接入话术", html)
        self.assertIn("/api/rooms/{roomId}/mcp-invites", html)
        self.assertNotIn("注册本地智能体连接器", html)
        self.assertNotIn("注册远端智能体连接器", html)
        self.assertNotIn("/api/rooms/{roomId}/connectors", html)
        self.assertNotIn("/api/connectors/{connectorId}/events", html)
        self.assertNotIn("registerConnector", html)
        self.assertNotIn("data-role=", html)
        self.assertNotIn("local-agent", html)
        self.assertNotIn("remote-agent", html)
        self.assertNotIn("codex-sidecar", html)
        self.assertIn("创建体验看板", html)
        self.assertIn("开发智能体回复", html)
        self.assertIn("人工确认并同步", html)
        self.assertIn("/api/demo/session", html)
        self.assertNotIn("Terminal Operations Console", html)
        self.assertNotIn("Workbench Hall", html)
        self.assertNotIn("MR Review Workbench", html)
        self.assertNotIn("Launch MR Review Workbench", html)
        self.assertNotIn("Activity / Audit Log", html)
        self.assertNotIn("Create Task", html)
        self.assertNotIn("Invite Agent", html)
        self.assertNotIn("Finding / Owner Decision", html)
        self.assertNotIn("Agent Operations", html)
        self.assertNotIn("Inspector / Action Rail", html)

    def test_workbench_summary_has_counts_without_owner_token(self):
        room = self.store.create_room(
            {
                "title": "MR: Workbench summary",
                "provider": "gitlab",
                "mrUrl": "https://git.example.com/lighthouse/console/-/merge_requests/42",
                "context": {"repository": "lighthouse/console"},
            }
        )
        self.store.register_connector(room["id"], {"role": "reviewer", "name": "Reviewer Agent"})
        self.store.add_finding(room["id"], {"claim": "需要 owner 决策", "createdBy": "Reviewer Agent"})
        self.store.create_task(room["id"], {"title": "修复 finding", "assignedTo": "Developer Agent"})

        summary = self.store.workbench_summary(self.store.get_room(room["id"]))

        self.assertNotIn("ownerToken", summary)
        self.assertEqual(summary["template"], "mr-review")
        self.assertEqual(summary["counts"]["findings"], 1)
        self.assertEqual(summary["counts"]["tasks"], 1)
        self.assertEqual(summary["counts"]["connectors"], 1)
        self.assertEqual(summary["pendingOwnerActions"], 0)
        self.assertEqual(summary["activeRunCount"], 0)
        self.assertEqual(summary["connectorStatus"]["total"], 1)

    def test_init_schema_migrates_legacy_agent_runs_without_agent_name(self):
        room = self.store.create_room({"title": "MR: legacy runs"})
        connector = self.store.register_connector(room["id"], {"role": "reviewer", "name": "Reviewer Agent"})
        task = self.store.create_task(room["id"], {"title": "legacy task", "assignedTo": "Reviewer Agent"})
        timestamp = 1700000000000
        with sqlite3.connect(self.store.db_path) as conn:
            conn.execute("DROP TABLE agent_runs")
            conn.execute(
                """
                CREATE TABLE agent_runs (
                  id TEXT PRIMARY KEY,
                  room_id TEXT NOT NULL,
                  task_id TEXT NOT NULL,
                  connector_id TEXT NOT NULL,
                  adapter_type TEXT NOT NULL,
                  external_session_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  prompt_summary TEXT NOT NULL,
                  workspace TEXT NOT NULL,
                  model TEXT NOT NULL,
                  sandbox TEXT NOT NULL,
                  final_message TEXT NOT NULL,
                  error TEXT NOT NULL,
                  log_path TEXT NOT NULL,
                  transcript_url TEXT NOT NULL,
                  started_at INTEGER,
                  finished_at INTEGER,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO agent_runs
                  (id, room_id, task_id, connector_id, adapter_type, external_session_id, status,
                   prompt_summary, workspace, model, sandbox, final_message, error, log_path,
                   transcript_url, started_at, finished_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "run_legacy",
                    room["id"],
                    task["id"],
                    connector["id"],
                    "codex-sidecar",
                    "",
                    "running",
                    "legacy run",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    timestamp,
                    None,
                    timestamp,
                    timestamp,
                ),
            )

        migrated = ReviewRoomStore(self.store.db_path)
        loaded = migrated.get_room(room["id"])
        summary = migrated.list_workbenches()[0]

        self.assertEqual(loaded["agentRuns"][0]["agentName"], "Reviewer Agent")
        self.assertEqual(summary["activeRunCount"], 1)

    def test_init_schema_migrates_legacy_collaboration_object_columns(self):
        room = self.store.create_room({"title": "MR: legacy objects"})
        connector = self.store.register_connector(room["id"], {"role": "reviewer", "name": "Reviewer Agent"})
        timestamp = 1700000000000
        with sqlite3.connect(self.store.db_path) as conn:
            conn.execute("DROP TABLE decisions")
            conn.execute(
                """
                CREATE TABLE decisions (
                  id TEXT PRIMARY KEY,
                  room_id TEXT NOT NULL,
                  requested_by_connector_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  question TEXT NOT NULL,
                  proposal TEXT NOT NULL,
                  risk TEXT NOT NULL,
                  sync_target TEXT NOT NULL,
                  source_json TEXT NOT NULL,
                  created_by TEXT NOT NULL,
                  decided_by TEXT NOT NULL,
                  decision_note TEXT NOT NULL,
                  decided_at INTEGER,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO decisions
                  (id, room_id, requested_by_connector_id, status, question, proposal, risk,
                   sync_target, source_json, created_by, decided_by, decision_note, decided_at,
                   created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "decision_legacy",
                    room["id"],
                    connector["id"],
                    "pending",
                    "Should sync this finding?",
                    "Post MR comment",
                    "Owner approval required",
                    "MR comment",
                    "{}",
                    "Reviewer Agent",
                    "",
                    "",
                    None,
                    timestamp,
                    timestamp,
                ),
            )
            conn.execute("DROP TABLE handoffs")
            conn.execute(
                """
                CREATE TABLE handoffs (
                  id TEXT PRIMARY KEY,
                  room_id TEXT NOT NULL,
                  from_connector_id TEXT NOT NULL,
                  source_finding_id TEXT NOT NULL,
                  target_json TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  suggested_task TEXT NOT NULL,
                  status TEXT NOT NULL,
                  converted_task_id TEXT NOT NULL,
                  created_by TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO handoffs
                  (id, room_id, from_connector_id, source_finding_id, target_json, reason,
                   suggested_task, status, converted_task_id, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "handoff_legacy",
                    room["id"],
                    connector["id"],
                    "finding_legacy",
                    '{"agentName":"Developer Agent"}',
                    "Needs a code fix",
                    "Patch the failing path",
                    "proposed",
                    "",
                    "Reviewer Agent",
                    timestamp,
                    timestamp,
                ),
            )
            conn.execute("DROP TABLE threads")
            conn.execute(
                """
                CREATE TABLE threads (
                  id TEXT PRIMARY KEY,
                  room_id TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  status TEXT NOT NULL,
                  source_json TEXT NOT NULL,
                  participants_json TEXT NOT NULL,
                  question TEXT NOT NULL,
                  max_turns INTEGER NOT NULL,
                  turn_count INTEGER NOT NULL,
                  end_condition TEXT NOT NULL,
                  summary_json TEXT NOT NULL,
                  created_by TEXT NOT NULL,
                  closed_by TEXT NOT NULL,
                  closed_at INTEGER,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO threads
                  (id, room_id, kind, status, source_json, participants_json, question,
                   max_turns, turn_count, end_condition, summary_json, created_by, closed_by,
                   closed_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "thread_legacy",
                    room["id"],
                    "deliberation",
                    "open",
                    "{}",
                    "[]",
                    "Review the auth risk",
                    3,
                    0,
                    "owner decision",
                    "{}",
                    "Reviewer Agent",
                    "",
                    None,
                    timestamp,
                    timestamp,
                ),
            )

        migrated = ReviewRoomStore(self.store.db_path)
        loaded = migrated.get_room(room["id"])
        summary = migrated.list_workbenches()[0]

        self.assertEqual(loaded["decisions"][0]["kind"], "owner_decision")
        self.assertEqual(loaded["decisions"][0]["requester"], "Reviewer Agent")
        self.assertEqual(loaded["handoffs"][0]["fromAgent"], "Reviewer Agent")
        self.assertEqual(loaded["handoffs"][0]["targetAgent"], "Developer Agent")
        self.assertEqual(loaded["threads"][0]["title"], "Review the auth risk")
        self.assertEqual(summary["pendingOwnerActions"], 2)

    def test_workbench_lifecycle_records_audit_events(self):
        room = self.store.create_workbench(
            {
                "title": "MR: old title",
                "repository": "lighthouse/console",
                "mrUrl": "https://git.example.com/lighthouse/console/-/merge_requests/7",
            }
        )

        renamed = self.store.update_workbench(room["id"], {"title": "MR: renamed"}, room["ownerToken"])
        archived = self.store.archive_workbench(room["id"], room["ownerToken"])
        restored = self.store.restore_workbench(room["id"], room["ownerToken"])
        deleted = self.store.delete_workbench(
            room["id"],
            {"confirm": True, "reason": "cleanup local planning workbench"},
            room["ownerToken"],
        )
        loaded = self.store.get_room(room["id"])
        event_types = [event["type"] for event in loaded["events"]]

        self.assertEqual(renamed["title"], "MR: renamed")
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(restored["status"], "open")
        self.assertEqual(deleted["status"], "deleted")
        self.assertIn("workbench.renamed", event_types)
        self.assertIn("workbench.archived", event_types)
        self.assertIn("workbench.restored", event_types)
        self.assertIn("workbench.deleted", event_types)
        self.assertIn("does not clean remote Agent machines", deleted["cleanupBoundary"])

    def test_workbench_lifecycle_requires_owner_token(self):
        room = self.store.create_workbench({"title": "MR: protected"})

        with self.assertRaises(PermissionError):
            self.store.update_workbench(room["id"], {"title": "bad"}, "wrong-token")
        with self.assertRaises(PermissionError):
            self.store.archive_workbench(room["id"], "wrong-token")
        with self.assertRaises(PermissionError):
            self.store.restore_workbench(room["id"], "wrong-token")
        with self.assertRaises(PermissionError):
            self.store.delete_workbench(room["id"], {"confirm": True}, "wrong-token")

    def test_mcp_invite_copy_has_http_fallback(self):
        html = index_html()

        self.assertIn("copyText(text)", html)
        self.assertIn("document.createElement('textarea')", html)
        self.assertIn("document.execCommand('copy')", html)
        self.assertIn("showCopyFallback(text)", html)
        self.assertIn("copyFallback: null", html)
        self.assertIn("renderCopyFallback();", html)
        self.assertIn("copyFallbackButton", html)
        self.assertIn("已选中", html)
        self.assertIn("浏览器没有放行自动复制", html)

    def test_home_page_exposes_agent_mention_controls(self):
        html = index_html()

        self.assertIn('data-mention="评审智能体"', html)
        self.assertIn('data-mention="开发智能体"', html)
        self.assertIn("extractMentionNames", html)
        self.assertIn("sendTopicMessage", html)

    def test_registers_local_and_remote_agent_connectors_for_room(self):
        room = self.store.create_room(
            {
                "title": "MR: productize review room",
                "provider": "gitlab",
                "mrUrl": "https://git.example.com/lighthouse/review-room/-/merge_requests/9",
            }
        )

        local = self.store.register_connector(
            room["id"],
            {
                "name": "本地 Codex",
                "kind": "local-agent",
                "agentRole": "developer",
                "endpoint": "http://127.0.0.1:8877/review-room",
            },
        )
        remote = self.store.register_connector(
            room["id"],
            {
                "name": "远端 Reviewer Agent",
                "kind": "remote-agent",
                "agentRole": "reviewer",
                "endpoint": "https://agent.example.com/review-room",
            },
        )
        loaded = self.store.get_room(room["id"])

        self.assertEqual(local["roomId"], room["id"])
        self.assertEqual(local["kind"], "local-agent")
        self.assertTrue(local["token"].startswith("rrc_"))
        self.assertEqual(remote["agentRole"], "reviewer")
        self.assertEqual([item["name"] for item in loaded["connectors"]], ["本地 Codex", "远端 Reviewer Agent"])

    def test_connector_event_writes_message_and_finding_to_room(self):
        room = self.store.create_room({"title": "MR"})
        local = self.store.register_connector(room["id"], {"name": "本地 Codex", "kind": "local-agent"})
        remote = self.store.register_connector(room["id"], {"name": "远端 Reviewer Agent", "kind": "remote-agent"})

        self.store.ingest_connector_event(
            local["id"],
            local["token"],
            {
                "type": "message",
                "senderName": "Developer Agent",
                "body": "我已拉取 MR diff，等待 review finding。",
            },
        )
        finding = self.store.ingest_connector_event(
            remote["id"],
            remote["token"],
            {
                "type": "finding",
                "severity": "P1",
                "filePath": "src/auth/session.ts",
                "line": 87,
                "claim": "权限校验可能被绕过",
                "evidence": "新增 early return 没有检查 role",
                "suggestedFix": "补充 role 校验并增加测试",
            },
        )
        loaded = self.store.get_room(room["id"])

        self.assertEqual(finding["status"], "needs_developer_response")
        self.assertEqual(loaded["messages"][-2]["kind"], "connector_message")
        self.assertEqual(loaded["messages"][-1]["kind"], "review_finding")
        self.assertEqual(loaded["findings"][0]["createdBy"], "远端 Reviewer Agent")

    def test_connector_event_rejects_invalid_token(self):
        room = self.store.create_room({"title": "MR"})
        connector = self.store.register_connector(room["id"], {"name": "本地 Codex", "kind": "local-agent"})

        with self.assertRaises(PermissionError):
            self.store.ingest_connector_event(
                connector["id"],
                "wrong-token",
                {"type": "message", "body": "should fail"},
            )


class ReviewRoomHttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ReviewRoomStore(os.path.join(self.tmp.name, "test.sqlite3"))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(self.store))
        self.thread = Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = "http://127.0.0.1:{}".format(self.httpd.server_address[1])

    def tearDown(self):
        self.httpd.shutdown()
        self.thread.join(timeout=2)
        self.httpd.server_close()
        self.tmp.cleanup()

    def post_json(self, path, payload, headers=None):
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_json(self, path):
        with urllib.request.urlopen(self.base_url + path, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_http_registers_connector_and_accepts_tokened_events(self):
        room = self.post_json(
            "/api/rooms",
            {
                "title": "MR: real connector",
                "provider": "gitlab",
                "mrUrl": "https://git.example.com/a/b/-/merge_requests/10",
            },
        )
        connector = self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"name": "远端 Reviewer Agent", "kind": "remote-agent", "agentRole": "reviewer"},
        )
        event = self.post_json(
            "/api/connectors/{}/events".format(connector["id"]),
            {
                "type": "finding",
                "severity": "P1",
                "claim": "真实 connector 写入 finding",
                "evidence": "通过 token 认证的 connector event API 写入",
                "suggestedFix": "保留该事件作为 Room 时间线的一部分",
            },
            {"Authorization": "Bearer {}".format(connector["token"])},
        )
        loaded = self.get_json("/api/rooms/{}".format(room["id"]))

        self.assertEqual(event["status"], "needs_developer_response")
        self.assertEqual(loaded["connectors"][0]["status"], "connected")
        self.assertEqual(loaded["connectors"][0]["eventCount"], 1)
        self.assertEqual(loaded["findings"][0]["claim"], "真实 connector 写入 finding")

    def test_http_rejects_connector_event_without_valid_token(self):
        room = self.post_json("/api/rooms", {"title": "MR"})
        connector = self.post_json("/api/rooms/{}/connectors".format(room["id"]), {"name": "本地 Codex"})

        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.post_json(
                "/api/connectors/{}/events".format(connector["id"]),
                {"type": "message", "body": "should fail"},
                {"Authorization": "Bearer wrong-token"},
            )

        self.assertEqual(raised.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
