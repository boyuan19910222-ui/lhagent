import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from review_room_service import ReviewRoomStore, build_handler, index_html  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402
from threading import Barrier, Thread  # noqa: E402


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

    def test_create_topic_room_without_repository_or_mr(self):
        room = self.store.create_room(
            {
                "title": "开放话题房间",
                "objective": "围绕一个设计问题协作。",
                "tags": ["review", "agent"],
                "contextAttachments": [{"type": "link", "url": "https://example.com/spec"}],
            }
        )

        loaded = self.store.get_room(room["id"])

        self.assertEqual(loaded["provider"], "topic")
        self.assertEqual(loaded["mrUrl"], "")
        self.assertEqual(loaded["objective"], "围绕一个设计问题协作。")
        self.assertEqual(loaded["tags"], ["review", "agent"])
        self.assertEqual(loaded["contextAttachments"][0]["type"], "link")
        self.assertEqual(loaded["participants"][0]["role"], "owner")

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
                    "title": "Draft: Review Room",
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
        self.assertEqual(room["status"], "agent_working")
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

        self.assertIn("创建话题房间", html)
        self.assertIn("分享给外部成员", html)
        self.assertIn("邀请 Agent", html)
        self.assertIn("房间状态", html)
        self.assertIn("房间角色", html)
        self.assertIn("任务与运行", html)
        self.assertIn("分配结构化任务", html)
        self.assertIn("轮换 token", html)
        self.assertIn("Threads", html)
        self.assertIn("Handoffs", html)
        self.assertIn("/api/rooms/${encodeURIComponent(state.room.id)}/invites", html)
        self.assertIn("/api/rooms/${encodeURIComponent(state.room.id)}/tasks", html)
        self.assertIn("/api/handoffs/", html)
        self.assertIn("/rotate-token", html)
        self.assertIn("async function submitMessage()", html)
        self.assertIn("function postMessageOverHttp", html)
        self.assertIn("/api/rooms/${encodeURIComponent(state.room.id)}/messages", html)
        self.assertIn("function appendMessage", html)
        self.assertIn("function createTask()", html)
        self.assertIn("function renderThreads()", html)
        self.assertIn("function decideHandoff", html)
        self.assertIn("function rotateConnectorToken", html)
        self.assertIn("function copyText", html)
        self.assertIn("function fallbackCopyText", html)
        self.assertIn("生成 Agent 接入信息", html)
        self.assertIn("MCP Remote Agent 接入包", html)
        self.assertIn("function agentInviteAccessText", html)
        self.assertIn("function agentInvitePromptText", html)
        self.assertIn("copyAgentAccess", html)
        self.assertIn("copyAgentPrompt", html)
        self.assertIn("eventStreamUrl", html)
        self.assertIn("Last-Event-ID", html)
        self.assertIn("mentionMenu", html)
        self.assertIn("function mentionTargets()", html)
        self.assertIn("function isSelfMentionTarget", html)
        self.assertIn("function suppressMentionMenu", html)
        self.assertIn("mentionSuppressUntil", html)
        self.assertIn("if(!query.query)", html)
        self.assertIn("event.inputType.startsWith('delete')", html)
        self.assertIn("function mentionsForBody", html)
        self.assertIn("const payload = {mentions:mentionsForBody(body)}", html)
        self.assertIn("sendSocket({type:'message.create', body, payload})", html)
        self.assertIn("agentRuns", html)
        self.assertIn("event.key !== 'Enter'", html)
        self.assertIn("event.isComposing", html)
        self.assertIn("compositioncancel", html)
        self.assertIn("state.composing = false", html)
        self.assertIn("创建体验房间", html)
        self.assertIn("/api/demo/session", html)
        self.assertNotIn("/api/connectors/{connectorId}/events", html)

    def test_guest_invite_join_adds_read_write_participant_without_leaking_token(self):
        room = self.store.create_room({"title": "开放话题"})
        invite = self.store.create_invite(room["id"], {"type": "guest"}, "https://review.example.com")

        joined = self.store.join_room(room["id"], {"inviteCode": invite["code"], "nickname": "外部用户"})
        loaded = self.store.get_room(room["id"])
        identity = self.store.authenticate_room_token(room["id"], joined["guestToken"])

        self.assertEqual(invite["inviteUrl"], "https://review.example.com/r/{}".format(invite["code"]))
        self.assertEqual(joined["identity"]["permissions"], ["read", "message"])
        self.assertEqual(identity["type"], "guest")
        self.assertEqual(identity["name"], "外部用户")
        self.assertEqual(loaded["participants"][-1]["name"], "外部用户")
        self.assertNotIn("token", loaded["participants"][-1])

    def test_disconnect_guest_revokes_token_and_hides_participant(self):
        room = self.store.create_room({"title": "topic"})
        invite = self.store.create_invite(room["id"], {"type": "guest"}, "https://review.example.com")
        joined = self.store.join_room(room["id"], {"inviteCode": invite["code"], "nickname": "Guest User"})
        participant_id = joined["identity"]["participantId"]

        result = self.store.disconnect_member(
            room["id"],
            {"targetType": "guest", "participantId": participant_id},
        )
        loaded = self.store.get_room(room["id"])

        self.assertTrue(result["ok"])
        self.assertEqual(result["participant"]["status"], "removed")
        self.assertEqual(len(loaded["participants"]), 1)
        self.assertEqual(loaded["participants"][0]["role"], "owner")
        self.assertEqual(loaded["messages"][-1]["kind"], "member_disconnected")
        with self.assertRaises(PermissionError):
            self.store.authenticate_room_token(room["id"], joined["guestToken"])

    def test_agent_invite_creates_invited_agent_member(self):
        room = self.store.create_room({"title": "开放话题"})

        invite = self.store.create_invite(
            room["id"],
            {"type": "agent", "role": "reviewer", "name": "Reviewer Agent"},
            "https://review.example.com",
        )
        loaded = self.store.get_room(room["id"])

        self.assertEqual(invite["type"], "agent")
        self.assertEqual(invite["role"], "reviewer")
        self.assertIn("advanced", invite)
        self.assertEqual(loaded["status"], "waiting_for_agent")
        self.assertEqual(loaded["connectors"][0]["status"], "invited")
        self.assertEqual(loaded["connectors"][0]["name"], "Reviewer Agent")
        self.assertEqual(loaded["connectors"][0]["adapterType"], "mcp-remote")
        self.assertEqual(invite["advanced"]["adapterType"], "mcp-remote")
        self.assertEqual(invite["advanced"]["mcp"]["toolsUrl"], "https://review.example.com/api/mcp/tools")
        self.assertEqual(invite["advanced"]["mcp"]["eventStreamUrl"], "https://review.example.com/api/mcp/events?roomId={}".format(room["id"]))
        self.assertEqual(invite["advanced"]["bootstrap"]["realtime"]["eventStreamUrl"], invite["advanced"]["mcp"]["eventStreamUrl"])
        self.assertEqual(invite["advanced"]["bootstrap"]["realtime"]["authorization"], "Bearer {}".format(invite["advanced"]["connectorToken"]))
        self.assertEqual(invite["advanced"]["bootstrap"]["realtime"]["websocketUrl"], "wss://review.example.com/ws/rooms/{}?token={}".format(room["id"], invite["advanced"]["connectorToken"]))
        self.assertIn("get_snapshot", invite["advanced"]["mcp"]["tools"])
        self.assertIn("poll_events", invite["advanced"]["mcp"]["tools"])
        self.assertEqual(invite["advanced"]["mcp"]["bearerToken"], invite["advanced"]["connectorToken"])
        self.assertIn("payload", invite["advanced"]["bootstrap"]["agentContract"]["eventEnvelope"]["required"])
        self.assertEqual(invite["advanced"]["bootstrap"]["agentContract"]["cursorReconnect"]["fallbackTool"], "poll_events")
        self.assertEqual(invite["advanced"]["bootstrap"]["agentContract"]["replyPolicy"]["shouldRespond"][0]["priority"], "P0")

    def test_streaming_connector_opens_waiting_room_without_overriding_workflow_status(self):
        room = self.store.create_room({"title": "topic"})
        connector = self.store.register_connector(
            room["id"],
            {"role": "developer", "name": "Developer Agent", "adapterType": "mcp-remote"},
        )

        self.store.mark_connector_seen(connector["id"], "mcp_streaming", "")
        opened = self.store.get_room(room["id"])

        self.assertEqual(opened["status"], "open")
        self.assertEqual(opened["connectors"][0]["status"], "mcp_streaming")

        with self.store.connect() as conn:
            conn.execute("UPDATE rooms SET status = ? WHERE id = ?", ("needs_owner_decision", room["id"]))
        self.store.mark_connector_seen(connector["id"], "mcp_streaming", "")
        preserved = self.store.get_room(room["id"])

        self.assertEqual(preserved["status"], "needs_owner_decision")

    def test_legacy_provisioned_connector_status_remains_active(self):
        room = self.store.create_room({"title": "topic"})
        connector = self.store.register_connector(
            room["id"],
            {"role": "developer", "name": "Developer Agent", "adapterType": "codex-sidecar", "status": "provisioned"},
        )

        self.assertEqual(connector["status"], "invited")

        with self.store.connect() as conn:
            conn.execute("UPDATE connectors SET status = ? WHERE id = ?", ("provisioned", connector["id"]))
        loaded = self.store.get_room(room["id"])

        self.assertEqual(loaded["connectors"][0]["status"], "provisioned")
        self.assertEqual(loaded["statusSummary"]["activeAgentCount"], 1)
        self.assertEqual(loaded["statusSummary"]["agentStatusCounts"]["provisioned"], 1)

    def test_message_mentions_are_resolved_from_room_roles(self):
        room = self.store.create_room({"title": "topic"})
        reviewer = self.store.register_connector(room["id"], {"name": "Reviewer Agent", "role": "reviewer"})
        developer = self.store.register_connector(room["id"], {"name": "Developer Agent", "role": "developer"})

        message = self.store.add_message(
            room["id"],
            {
                "senderType": "human",
                "senderName": "review room owner",
                "kind": "owner_topic",
                "body": "@Reviewer-Agent 请看风险，@developer 跟进修复，@owner 稍后确认。",
            },
        )
        mentions_by_role = {mention["role"]: mention for mention in message["payload"]["mentions"]}

        self.assertEqual(mentions_by_role["reviewer"]["connectorId"], reviewer["id"])
        self.assertEqual(mentions_by_role["developer"]["connectorId"], developer["id"])
        self.assertNotIn("owner", mentions_by_role)
        self.assertNotIn("connectorToken", json.dumps(message["payload"], ensure_ascii=False))

        reviewer_message = self.store.add_message(
            room["id"],
            {
                "senderType": "agent",
                "senderName": "Reviewer Agent",
                "kind": "connector_message",
                "body": "@reviewer 自己不应该出现，@developer 应该出现。",
                "senderIdentity": {
                    "type": "connector",
                    "connectorId": reviewer["id"],
                    "name": "Reviewer Agent",
                    "role": "reviewer",
                },
            },
        )
        reviewer_mentions_by_role = {mention["role"]: mention for mention in reviewer_message["payload"]["mentions"]}

        self.assertNotIn("reviewer", reviewer_mentions_by_role)
        self.assertEqual(reviewer_mentions_by_role["developer"]["connectorId"], developer["id"])

    def test_agent_invite_can_request_codex_sidecar_adapter(self):
        room = self.store.create_room({"title": "topic"})

        invite = self.store.create_invite(
            room["id"],
            {"type": "agent", "role": "reviewer", "name": "Reviewer Agent", "adapterType": "codex-sidecar"},
            "https://review.example.com",
        )
        loaded = self.store.get_room(room["id"])

        self.assertEqual(loaded["connectors"][0]["adapterType"], "codex-sidecar")
        self.assertEqual(invite["advanced"]["adapterType"], "codex-sidecar")
        self.assertIn("codex_connector.py", invite["advanced"]["bootstrap"]["command"])
        self.assertNotIn("mcp", invite["advanced"])

    def test_disconnect_connector_revokes_token(self):
        room = self.store.create_room({"title": "topic"})
        connector = self.store.register_connector(room["id"], {"name": "Reviewer Agent", "role": "reviewer"})

        result = self.store.disconnect_member(
            room["id"],
            {"targetType": "connector", "connectorId": connector["id"]},
        )
        loaded = self.store.get_room(room["id"])

        self.assertTrue(result["ok"])
        self.assertEqual(loaded["connectors"][0]["status"], "revoked")
        self.assertEqual(loaded["connectors"][0]["connectorToken"], "")
        self.assertEqual(loaded["messages"][-1]["kind"], "member_disconnected")
        with self.assertRaises(PermissionError):
            self.store.authenticate_room_token(room["id"], connector["connectorToken"])

        owner_message = self.store.add_message(
            room["id"],
            {
                "senderType": "human",
                "senderName": "review room owner",
                "kind": "owner_topic",
                "body": "revoked connector should stay disconnected",
            },
        )
        with patch.dict(os.environ, {"REVIEW_ROOM_ENABLE_HOSTED_AGENT": "true"}):
            reply = self.store.create_hosted_agent_reply(room["id"], owner_message)
        reloaded = self.store.get_room(room["id"])

        self.assertIsNone(reply)
        self.assertEqual(reloaded["connectors"][0]["status"], "revoked")

    def test_rotate_connector_token_invalidates_old_token_without_leaking_audit_secret(self):
        room = self.store.create_room({"title": "topic"})
        connector = self.store.register_connector(room["id"], {"name": "Reviewer Agent", "role": "reviewer"})

        rotated = self.store.rotate_connector_token(room["id"], connector["id"], {}, "https://review.example.com")
        loaded = self.store.get_room(room["id"])

        self.assertTrue(rotated["ok"])
        self.assertNotEqual(rotated["connectorToken"], connector["connectorToken"])
        self.assertIn(rotated["connectorToken"], rotated["bootstrap"]["command"])
        self.assertEqual(loaded["connectors"][0]["status"], "invited")
        self.assertEqual(loaded["messages"][-1]["kind"], "connector_token_rotated")
        self.assertNotIn(rotated["connectorToken"], json.dumps(loaded["messages"][-1], ensure_ascii=False))
        with self.assertRaises(PermissionError):
            self.store.authenticate_room_token(room["id"], connector["connectorToken"])
        identity = self.store.authenticate_room_token(room["id"], rotated["connectorToken"])
        self.assertEqual(identity["connectorId"], connector["id"])

    def test_connector_status_event_updates_lifecycle_state(self):
        room = self.store.create_room({"title": "topic"})
        connector = self.store.register_connector(room["id"], {"name": "Reviewer Agent", "role": "reviewer"})

        updated = self.store.ingest_connector_event(
            connector["id"],
            connector["connectorToken"],
            {"type": "status", "status": "thinking", "detail": "reading the assigned task"},
        )
        loaded = self.store.get_room(room["id"])

        self.assertEqual(updated["status"], "thinking")
        self.assertEqual(loaded["connectors"][0]["status"], "thinking")
        self.assertEqual(loaded["connectors"][0]["eventCount"], 1)
        self.assertIsNotNone(loaded["connectors"][0]["lastSeenAt"])
        self.assertIsNotNone(loaded["connectors"][0]["heartbeatAt"])
        self.assertEqual(loaded["status"], "agent_working")
        self.assertEqual(loaded["statusSummary"]["busyAgentCount"], 1)
        self.assertEqual(loaded["statusSummary"]["onlineAgentCount"], 1)
        with self.assertRaisesRegex(ValueError, "connector status"):
            self.store.ingest_connector_event(
                connector["id"],
                connector["connectorToken"],
                {"type": "status", "status": "teleporting"},
            )
        with self.assertRaisesRegex(PermissionError, "cannot revoke itself"):
            self.store.ingest_connector_event(
                connector["id"],
                connector["connectorToken"],
                {"type": "status", "status": "revoked"},
            )

    def test_hosted_agent_does_not_reply_without_explicit_experience_mode(self):
        room = self.store.create_room({"title": "开放话题"})
        self.store.create_invite(
            room["id"],
            {"type": "agent", "role": "reviewer", "name": "Reviewer Agent"},
            "https://review.example.com",
        )
        owner_message = self.store.add_message(
            room["id"],
            {
                "senderType": "human",
                "senderName": "review room owner",
                "kind": "owner_topic",
                "body": "我作为 owner 怎么和你对话？",
            },
        )

        reply = self.store.create_hosted_agent_reply(room["id"], owner_message)

        self.assertIsNone(reply)

    def test_hosted_agent_replies_when_experience_mode_is_enabled(self):
        room = self.store.create_room({"title": "开放话题"})
        self.store.create_invite(
            room["id"],
            {"type": "agent", "role": "reviewer", "name": "Reviewer Agent"},
            "https://review.example.com",
        )
        owner_message = self.store.add_message(
            room["id"],
            {
                "senderType": "human",
                "senderName": "review room owner",
                "kind": "owner_topic",
                "body": "我作为 owner 怎么和你对话？",
            },
        )

        with patch.dict(os.environ, {"REVIEW_ROOM_ENABLE_HOSTED_AGENT": "true"}):
            reply = self.store.create_hosted_agent_reply(room["id"], owner_message)
        loaded = self.store.get_room(room["id"])

        self.assertIsNotNone(reply)
        self.assertEqual(reply["senderName"], "Reviewer Agent")
        self.assertEqual(reply["kind"], "connector_message")
        self.assertTrue(reply["payload"]["hostedAgent"])
        self.assertIn("我作为 owner 怎么和你对话", reply["body"])
        self.assertEqual(loaded["connectors"][0]["status"], "online")
        self.assertEqual(loaded["connectors"][0]["eventCount"], 1)
        self.assertEqual(loaded["status"], "agent_working")

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
        self.assertEqual(remote["adapterType"], "codex-sidecar")
        self.assertIn("finding:create", remote["capabilities"])
        self.assertIn("repo:write", remote["forbidden"])
        self.assertEqual(remote["bootstrap"]["adapterType"], "codex-sidecar")
        self.assertIn("codex_connector.py", remote["bootstrap"]["command"])
        self.assertIn(remote["connectorToken"], remote["bootstrap"]["command"])

    def test_task_assignment_and_agent_run_are_visible_in_room_snapshot(self):
        room = self.store.create_room({"title": "Task room"})
        connector = self.store.register_connector(
            room["id"],
            {"name": "Reviewer Agent", "role": "reviewer", "adapterType": "codex-sidecar"},
        )

        task = self.store.create_task(
            room["id"],
            {
                "kind": "review",
                "instruction": "Review the permission boundary.",
                "target": {"mode": "connector", "connectorId": connector["id"]},
            },
        )
        run = self.store.start_agent_run(
            task["id"],
            connector["id"],
            {"workspace": "G:/Codex/Lighthouse", "model": "gpt-test", "sandbox": "read-only"},
        )
        completed = self.store.complete_task(
            task["id"],
            connector["id"],
            {"finalMessage": "Finding created."},
        )
        loaded = self.store.get_room(room["id"])

        self.assertEqual(task["status"], "assigned")
        self.assertEqual(run["status"], "running")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(loaded["tasks"][0]["id"], task["id"])
        self.assertEqual(loaded["agentRuns"][0]["taskId"], task["id"])
        self.assertEqual(loaded["agentRuns"][0]["status"], "completed")
        self.assertEqual(loaded["statusSummary"]["activeTaskCount"], 0)

    def test_scoped_thread_records_messages_and_summary(self):
        room = self.store.create_room({"title": "Thread room"})
        reviewer = self.store.register_connector(room["id"], {"name": "Reviewer Agent", "role": "reviewer"})
        developer = self.store.register_connector(room["id"], {"name": "Developer Agent", "role": "developer"})
        observer = self.store.register_connector(room["id"], {"name": "Observer Agent", "role": "observer"})
        owner_identity = self.store.authenticate_room_token(room["id"], room["ownerToken"])
        reviewer_identity = self.store.authenticate_room_token(room["id"], reviewer["connectorToken"])
        developer_identity = self.store.authenticate_room_token(room["id"], developer["connectorToken"])
        observer_identity = self.store.authenticate_room_token(room["id"], observer["connectorToken"])
        invite = self.store.create_invite(room["id"], {"type": "guest"})
        guest = self.store.join_room(room["id"], {"inviteCode": invite["code"], "nickname": "Guest"})
        guest_identity = self.store.authenticate_room_token(room["id"], guest["guestToken"])

        with self.assertRaises(PermissionError):
            self.store.create_thread(
                room["id"],
                {"question": "Can the reviewer and developer agree?", "participants": [reviewer["id"]]},
                guest_identity,
            )
        thread = self.store.create_thread(
            room["id"],
            {
                "question": "Can the reviewer and developer agree?",
                "participants": [{"connectorId": reviewer["id"]}, developer["id"]],
                "maxTurns": 2,
                "sourceFindingId": "finding_1",
            },
            owner_identity,
        )
        with self.assertRaises(PermissionError):
            self.store.post_thread_message(thread["id"], {"body": "Observer should not join."}, observer_identity)
        first = self.store.post_thread_message(thread["id"], {"body": "Reviewer proposes a fix."}, reviewer_identity)
        second = self.store.post_thread_message(thread["id"], {"body": "Developer agrees with constraints."}, developer_identity)
        with self.assertRaises(ValueError):
            self.store.post_thread_message(thread["id"], {"body": "One turn too many."}, developer_identity)
        summarized = self.store.summarize_thread(
            thread["id"],
            {
                "status": "needs_owner_decision",
                "proposal": "Ship after owner approves the external sync.",
                "objections": ["External sync needs owner approval."],
                "recommendedNextTask": {"kind": "sync", "instruction": "Publish the decision summary."},
            },
            reviewer_identity,
        )
        loaded = self.store.get_room(room["id"])
        message_kinds = [message["kind"] for message in loaded["messages"]]

        self.assertEqual(thread["status"], "open")
        self.assertEqual(thread["source"]["sourceFindingId"], "finding_1")
        self.assertEqual([item["connectorId"] for item in thread["participants"]], [reviewer["id"], developer["id"]])
        self.assertEqual(first["turnCount"], 1)
        self.assertEqual(second["turnCount"], 2)
        self.assertEqual(second["status"], "needs_summary")
        self.assertEqual(summarized["status"], "needs_owner_decision")
        self.assertEqual(summarized["summary"]["createdBy"], "Reviewer Agent")
        self.assertEqual(loaded["status"], "needs_owner_decision")
        self.assertEqual(loaded["statusSummary"]["openThreadCount"], 0)
        self.assertEqual(len(loaded["threads"][0]["messages"]), 2)
        self.assertEqual(loaded["tasks"], [])
        self.assertIn("thread_created", message_kinds)
        self.assertIn("thread_message", message_kinds)
        self.assertIn("thread_summary", message_kinds)

    def test_thread_consensus_summary_does_not_force_agent_working_status(self):
        room = self.store.create_room({"title": "Consensus thread room"})
        reviewer = self.store.register_connector(room["id"], {"name": "Reviewer Agent", "role": "reviewer"})
        owner_identity = self.store.authenticate_room_token(room["id"], room["ownerToken"])
        reviewer_identity = self.store.authenticate_room_token(room["id"], reviewer["connectorToken"])
        thread = self.store.create_thread(
            room["id"],
            {"question": "Can this close without owner action?", "participants": [reviewer["id"]]},
            owner_identity,
        )

        self.store.post_thread_message(thread["id"], {"body": "Reviewer has no objections."}, reviewer_identity)
        before_summary = self.store.get_room(room["id"])
        summarized = self.store.summarize_thread(
            thread["id"],
            {"status": "consensus", "proposal": "Close without owner action."},
            reviewer_identity,
        )
        loaded = self.store.get_room(room["id"])

        self.assertEqual(summarized["status"], "consensus")
        self.assertEqual(loaded["status"], before_summary["status"])
        self.assertNotEqual(loaded["status"], "agent_working")
        self.assertEqual(loaded["statusSummary"]["openThreadCount"], 0)

    def test_claimable_task_requires_matching_connector_claim_before_run(self):
        room = self.store.create_room({"title": "Claim room"})
        reviewer = self.store.register_connector(room["id"], {"name": "Reviewer Agent", "role": "reviewer"})
        developer = self.store.register_connector(room["id"], {"name": "Developer Agent", "role": "developer"})
        observer = self.store.register_connector(room["id"], {"name": "Observer Agent", "role": "observer"})
        task = self.store.create_task(
            room["id"],
            {
                "kind": "review",
                "instruction": "Claim this review task.",
                "target": {"mode": "claim", "role": "reviewer", "capability": "finding:create"},
            },
        )

        with self.assertRaises(PermissionError):
            self.store.start_agent_run(task["id"], reviewer["id"], {})
        with self.assertRaises(PermissionError):
            self.store.claim_task(task["id"], developer["id"], {})
        broad_task = self.store.create_task(
            room["id"],
            {"kind": "research", "instruction": "Only executable agents can claim this.", "target": {"mode": "claim"}},
        )
        with self.assertRaises(PermissionError):
            self.store.claim_task(broad_task["id"], observer["id"], {})

        claimed = self.store.claim_task(task["id"], reviewer["id"], {})
        run = self.store.start_agent_run(task["id"], reviewer["id"], {"workspace": "G:/Codex/Lighthouse"})
        loaded = self.store.get_room(room["id"])

        self.assertEqual(task["status"], "open")
        self.assertEqual(claimed["status"], "claimed")
        self.assertEqual(claimed["assignedConnectorId"], reviewer["id"])
        self.assertGreater(claimed["leaseExpiresAt"], claimed["updatedAt"])
        self.assertEqual(run["status"], "running")
        self.assertIn("task_claimed", [message["kind"] for message in loaded["messages"]])

    def test_concurrent_claim_only_assigns_one_connector(self):
        room = self.store.create_room({"title": "Claim race"})
        reviewer_a = self.store.register_connector(room["id"], {"name": "Reviewer A", "role": "reviewer"})
        reviewer_b = self.store.register_connector(room["id"], {"name": "Reviewer B", "role": "reviewer"})
        race_task = self.store.create_task(
            room["id"],
            {"kind": "review", "instruction": "Only one reviewer may claim this.", "target": {"mode": "claim", "role": "reviewer"}},
        )
        barrier = Barrier(2)
        claimed = []
        errors = []

        def claim(connector):
            try:
                barrier.wait()
                claimed.append(self.store.claim_task(race_task["id"], connector["id"], {}))
            except Exception as exc:  # noqa: BLE001 - test records the loser path.
                errors.append(exc)

        threads = [Thread(target=claim, args=(reviewer_a,)), Thread(target=claim, args=(reviewer_b,))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        loaded = self.store.get_room(room["id"])
        assigned = [item for item in loaded["tasks"] if item["id"] == race_task["id"]][0]
        claim_messages = [message for message in loaded["messages"] if message["kind"] == "task_claimed"]

        self.assertEqual(len(claimed), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], PermissionError)
        self.assertEqual(assigned["assignedConnectorId"], claimed[0]["assignedConnectorId"])
        self.assertEqual(len(claim_messages), 1)

    def test_handoff_acceptance_converts_finding_to_developer_task(self):
        room = self.store.create_room({"title": "Handoff room"})
        reviewer = self.store.register_connector(room["id"], {"name": "Reviewer Agent", "role": "reviewer"})
        developer = self.store.register_connector(room["id"], {"name": "Developer Agent", "role": "developer"})
        finding = self.store.add_finding(room["id"], {"claim": "权限校验缺失", "createdBy": "Reviewer Agent"})
        reviewer_identity = self.store.authenticate_room_token(room["id"], reviewer["connectorToken"])

        handoff = self.store.propose_handoff(
            finding["id"],
            {
                "reason": "需要 Developer Agent 修改代码并补测试。",
                "suggestedTask": "修复权限校验并回传验证结果。",
            },
            reviewer_identity,
        )
        result = self.store.decide_handoff(handoff["id"], {"decision": "accepted"}, "review room owner")
        loaded = self.store.get_room(room["id"])

        self.assertEqual(handoff["status"], "proposed")
        self.assertEqual(result["handoff"]["status"], "converted_to_task")
        self.assertEqual(result["task"]["kind"], "fix")
        self.assertEqual(result["task"]["source"]["handoffId"], handoff["id"])
        self.assertEqual(result["task"]["source"]["findingId"], finding["id"])
        self.assertEqual(result["task"]["assignedConnectorId"], developer["id"])
        self.assertEqual(loaded["handoffs"][0]["convertedTaskId"], result["task"]["id"])
        self.assertEqual(loaded["tasks"][0]["target"]["role"], "developer")
        self.assertEqual(loaded["statusSummary"]["pendingHandoffCount"], 0)
        self.assertIn("handoff_proposed", [message["kind"] for message in loaded["messages"]])
        self.assertIn("handoff_converted", [message["kind"] for message in loaded["messages"]])

    def test_fix_completion_creates_reviewer_verification_task(self):
        room = self.store.create_room({"title": "Verify handoff room"})
        reviewer = self.store.register_connector(room["id"], {"name": "Reviewer Agent", "role": "reviewer"})
        developer = self.store.register_connector(room["id"], {"name": "Developer Agent", "role": "developer"})
        finding = self.store.add_finding(room["id"], {"claim": "Missing auth test", "createdBy": "Reviewer Agent"})
        reviewer_identity = self.store.authenticate_room_token(room["id"], reviewer["connectorToken"])
        handoff = self.store.propose_handoff(
            finding["id"],
            {"reason": "Needs a fix.", "suggestedTask": "Patch the auth path and report tests."},
            reviewer_identity,
        )
        accepted = self.store.decide_handoff(handoff["id"], {"decision": "accepted"}, "review room owner")

        completion = self.store.complete_task_result(
            accepted["task"]["id"],
            developer["id"],
            {"finalMessage": "Fix applied and regression test passed."},
        )
        loaded = self.store.get_room(room["id"])
        verify_tasks = [task for task in loaded["tasks"] if task["kind"] == "verify"]

        self.assertEqual(completion["task"]["status"], "completed")
        self.assertEqual(completion["verificationTask"]["kind"], "verify")
        self.assertEqual(completion["verificationTask"]["assignedConnectorId"], reviewer["id"])
        self.assertEqual(completion["verificationTask"]["source"]["fixTaskId"], accepted["task"]["id"])
        self.assertEqual(completion["verificationTask"]["source"]["findingId"], finding["id"])
        self.assertEqual(completion["verificationTask"]["source"]["handoffId"], handoff["id"])
        self.assertEqual(len(verify_tasks), 1)
        self.assertEqual(verify_tasks[0]["target"]["capability"], "verify:run")

    def test_handoff_proposal_requires_reviewer_connector(self):
        room = self.store.create_room({"title": "Handoff permissions"})
        developer = self.store.register_connector(room["id"], {"name": "Developer Agent", "role": "developer"})
        finding = self.store.add_finding(room["id"], {"claim": "Missing auth test", "createdBy": "Reviewer Agent"})
        developer_identity = self.store.authenticate_room_token(room["id"], developer["connectorToken"])

        with self.assertRaises(PermissionError):
            self.store.propose_handoff(
                finding["id"],
                {"reason": "Developer should not directly propose review handoffs."},
                developer_identity,
            )

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

    def get_json(self, path, headers=None):
        request = urllib.request.Request(
            self.base_url + path,
            headers=headers or {},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
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
            {"Authorization": "Bearer {}".format(room["ownerToken"])},
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
        loaded = self.get_json(
            "/api/rooms/{}".format(room["id"]),
            {"Authorization": "Bearer {}".format(room["ownerToken"])},
        )

        self.assertEqual(event["status"], "needs_developer_response")
        self.assertEqual(loaded["connectors"][0]["status"], "online")
        self.assertEqual(loaded["connectors"][0]["eventCount"], 1)
        self.assertNotIn("connectorToken", loaded["connectors"][0])
        self.assertEqual(loaded["findings"][0]["claim"], "真实 connector 写入 finding")

    def test_http_rejects_connector_event_without_valid_token(self):
        room = self.post_json("/api/rooms", {"title": "MR"})
        connector = self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"name": "本地 Codex"},
            {"Authorization": "Bearer {}".format(room["ownerToken"])},
        )

        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.post_json(
                "/api/connectors/{}/events".format(connector["id"]),
                {"type": "message", "body": "should fail"},
                {"Authorization": "Bearer wrong-token"},
            )

        self.assertEqual(raised.exception.code, 403)

    def test_http_claim_task_before_run(self):
        room = self.post_json("/api/rooms", {"title": "Claim HTTP"})
        reviewer = self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"name": "Reviewer Agent", "role": "reviewer"},
            {"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        task = self.post_json(
            "/api/rooms/{}/tasks".format(room["id"]),
            {
                "kind": "review",
                "instruction": "Claim over HTTP.",
                "target": {"mode": "claim", "role": "reviewer", "capability": "finding:create"},
            },
            {"Authorization": "Bearer {}".format(room["ownerToken"])},
        )

        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.post_json(
                "/api/tasks/{}/runs".format(task["id"]),
                {},
                {"Authorization": "Bearer {}".format(reviewer["connectorToken"])},
            )
        claimed = self.post_json(
            "/api/tasks/{}/claim".format(task["id"]),
            {},
            {"Authorization": "Bearer {}".format(reviewer["connectorToken"])},
        )
        run = self.post_json(
            "/api/tasks/{}/runs".format(task["id"]),
            {},
            {"Authorization": "Bearer {}".format(reviewer["connectorToken"])},
        )

        self.assertEqual(raised.exception.code, 403)
        self.assertEqual(claimed["assignedConnectorId"], reviewer["id"])
        self.assertEqual(claimed["status"], "claimed")
        self.assertEqual(run["status"], "running")

    def test_http_scoped_thread_endpoints_follow_participants(self):
        room = self.post_json("/api/rooms", {"title": "Thread HTTP"})
        reviewer = self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"name": "Reviewer Agent", "role": "reviewer"},
            {"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        developer = self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"name": "Developer Agent", "role": "developer"},
            {"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        observer = self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"name": "Observer Agent", "role": "observer"},
            {"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        thread = self.post_json(
            "/api/rooms/{}/threads".format(room["id"]),
            {"question": "Can HTTP agents agree?", "participants": [reviewer["id"], developer["id"]], "maxTurns": 2},
            {"Authorization": "Bearer {}".format(room["ownerToken"])},
        )

        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.post_json(
                "/api/threads/{}/messages".format(thread["id"]),
                {"body": "Observer should not join."},
                {"Authorization": "Bearer {}".format(observer["connectorToken"])},
            )
        first = self.post_json(
            "/api/threads/{}/messages".format(thread["id"]),
            {"body": "Reviewer proposes the guarded path."},
            {"Authorization": "Bearer {}".format(reviewer["connectorToken"])},
        )
        second = self.post_json(
            "/api/threads/{}/messages".format(thread["id"]),
            {"body": "Developer agrees."},
            {"Authorization": "Bearer {}".format(developer["connectorToken"])},
        )
        summary = self.post_json(
            "/api/threads/{}/summary".format(thread["id"]),
            {"status": "needs_owner_decision", "proposal": "Owner should approve the guarded path."},
            {"Authorization": "Bearer {}".format(reviewer["connectorToken"])},
        )
        loaded = self.get_json(
            "/api/rooms/{}".format(room["id"]),
            {"Authorization": "Bearer {}".format(room["ownerToken"])},
        )

        self.assertEqual(raised.exception.code, 403)
        self.assertEqual(first["turnCount"], 1)
        self.assertEqual(second["status"], "needs_summary")
        self.assertEqual(summary["status"], "needs_owner_decision")
        self.assertEqual(loaded["threads"][0]["summary"]["proposal"], "Owner should approve the guarded path.")

    def test_http_owner_can_rotate_connector_token(self):
        room = self.post_json("/api/rooms", {"title": "MR"})
        connector = self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"name": "本地 Codex", "role": "reviewer"},
            {"Authorization": "Bearer {}".format(room["ownerToken"])},
        )

        rotated = self.post_json(
            "/api/rooms/{}/connectors/{}/rotate-token".format(room["id"], connector["id"]),
            {},
            {"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.post_json(
                "/api/connectors/{}/events".format(connector["id"]),
                {"type": "message", "body": "old token should fail"},
                {"Authorization": "Bearer {}".format(connector["connectorToken"])},
            )
        event = self.post_json(
            "/api/connectors/{}/events".format(connector["id"]),
            {"type": "message", "body": "new token works"},
            {"Authorization": "Bearer {}".format(rotated["connectorToken"])},
        )

        self.assertEqual(raised.exception.code, 403)
        self.assertTrue(rotated["ok"])
        self.assertNotEqual(rotated["connectorToken"], connector["connectorToken"])
        self.assertIn(rotated["connectorToken"], rotated["bootstrap"]["command"])
        self.assertEqual(event["body"], "new token works")

    def test_http_handoff_acceptance_creates_developer_task(self):
        room = self.post_json("/api/rooms", {"title": "Handoff"})
        reviewer = self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"name": "Reviewer Agent", "role": "reviewer"},
            {"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        developer = self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"name": "Developer Agent", "role": "developer"},
            {"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        finding = self.post_json(
            "/api/rooms/{}/findings".format(room["id"]),
            {"claim": "缺少鉴权测试"},
            {"Authorization": "Bearer {}".format(reviewer["connectorToken"])},
        )

        handoff = self.post_json(
            "/api/findings/{}/handoffs".format(finding["id"]),
            {"reason": "需要修复并补测试", "suggestedTask": "补上鉴权测试"},
            {"Authorization": "Bearer {}".format(reviewer["connectorToken"])},
        )
        result = self.post_json(
            "/api/handoffs/{}/accept".format(handoff["id"]),
            {},
            {"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        completed = self.post_json(
            "/api/tasks/{}/complete".format(result["task"]["id"]),
            {"finalMessage": "Fix landed."},
            {"Authorization": "Bearer {}".format(developer["connectorToken"])},
        )
        loaded = self.get_json(
            "/api/rooms/{}".format(room["id"]),
            {"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        verify_tasks = [task for task in loaded["tasks"] if task["kind"] == "verify"]

        self.assertEqual(result["handoff"]["status"], "converted_to_task")
        self.assertEqual(result["task"]["assignedConnectorId"], developer["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(loaded["handoffs"][0]["convertedTaskId"], result["task"]["id"])
        self.assertEqual(loaded["tasks"][0]["kind"], "fix")
        self.assertEqual(len(verify_tasks), 1)
        self.assertEqual(verify_tasks[0]["assignedConnectorId"], reviewer["id"])
        self.assertEqual(verify_tasks[0]["source"]["fixTaskId"], result["task"]["id"])


if __name__ == "__main__":
    unittest.main()
