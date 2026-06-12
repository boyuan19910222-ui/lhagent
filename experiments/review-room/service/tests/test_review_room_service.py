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
        self.assertIn("/api/rooms/${encodeURIComponent(state.room.id)}/invites", html)
        self.assertIn("function submitMessage()", html)
        self.assertIn("event.key !== 'Enter'", html)
        self.assertIn("event.isComposing", html)
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


if __name__ == "__main__":
    unittest.main()
