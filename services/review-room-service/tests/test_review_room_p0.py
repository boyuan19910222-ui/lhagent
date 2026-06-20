import asyncio
import json
import os
import sys
import tempfile
import unittest

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from codex_connector import build_agent_response, parse_room_url  # noqa: E402
from review_room_service import ReviewRoomStore, build_app  # noqa: E402


class ReviewRoomP0StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ReviewRoomStore(os.path.join(self.tmp.name, "test.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_room_creation_returns_owner_token_and_default_roles(self):
        room = self.store.create_room(
            {
                "title": "MR: websocket review room",
                "context": {"repository": "lighthouse/review-room"},
            }
        )

        self.assertEqual(room["roomId"], room["id"])
        self.assertTrue(room["ownerToken"].startswith("rro_"))
        self.assertEqual(
            [(item["type"], item["role"]) for item in room["participants"]],
            [("human", "owner"), ("agent", "reviewer"), ("agent", "developer")],
        )

    def test_room_token_authenticates_owner_or_connector_only(self):
        room = self.store.create_room({"title": "MR"})
        connector = self.store.register_connector(room["id"], {"role": "reviewer"})

        owner_identity = self.store.authenticate_room_token(room["id"], room["ownerToken"])
        connector_identity = self.store.authenticate_room_token(room["id"], connector["connectorToken"])

        self.assertEqual(owner_identity["type"], "owner")
        self.assertEqual(connector_identity["type"], "connector")
        self.assertEqual(connector_identity["role"], "reviewer")
        with self.assertRaises(PermissionError):
            self.store.authenticate_room_token(room["id"], "bad-token")

    def test_developer_response_and_owner_confirmation_status_flow(self):
        room = self.store.create_room({"title": "MR"})
        finding = self.store.add_finding(room["id"], {"claim": "缺少权限校验"})

        responded = self.store.respond_to_finding(
            finding["id"],
            {"body": "我会补权限校验。", "senderName": "Developer Agent"},
        )
        confirmed = self.store.confirm_finding(
            finding["id"],
            {"decision": "accepted", "senderName": "Agent Board owner"},
        )

        self.assertEqual(responded["status"], "developer_responded")
        self.assertEqual(confirmed["status"], "accepted")
        self.assertEqual(self.store.get_room(room["id"])["status"], "completed")


class ReviewRoomP0AioHttpTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ReviewRoomStore(os.path.join(self.tmp.name, "test.sqlite3"))
        self.server = TestServer(build_app(self.store))
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def post_json(self, path, payload, token=None):
        headers = {}
        if token:
            headers["Authorization"] = "Bearer {}".format(token)
        response = await self.client.post(path, json=payload, headers=headers)
        data = await response.json()
        return response, data

    async def patch_json(self, path, payload, token=None):
        headers = {}
        if token:
            headers["Authorization"] = "Bearer {}".format(token)
        response = await self.client.patch(path, json=payload, headers=headers)
        data = await response.json()
        return response, data

    async def delete_json(self, path, payload, token=None):
        headers = {}
        if token:
            headers["Authorization"] = "Bearer {}".format(token)
        response = await self.client.delete(path, json=payload, headers=headers)
        data = await response.json()
        return response, data

    async def test_rest_requires_owner_token_for_room_snapshot_and_connector_registration(self):
        create_response, room = await self.post_json("/api/rooms", {"title": "MR"})
        self.assertEqual(create_response.status, 201)

        denied_snapshot = await self.client.get("/api/rooms/{}".format(room["id"]))
        denied_connector, _ = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"role": "reviewer"},
        )
        allowed_snapshot = await self.client.get(
            "/api/rooms/{}".format(room["id"]),
            headers={"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        allowed_connector, connector = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"role": "reviewer", "name": "Reviewer Agent"},
            room["ownerToken"],
        )

        self.assertEqual(denied_snapshot.status, 403)
        self.assertEqual(denied_connector.status, 403)
        self.assertEqual(allowed_snapshot.status, 200)
        self.assertEqual(allowed_connector.status, 201)
        self.assertTrue(connector["connectorToken"].startswith("rrc_"))

    async def test_workbench_api_create_list_read_and_lifecycle(self):
        create_response, workbench = await self.post_json(
            "/api/workbenches",
            {
                "title": "MR: terminal workbench",
                "repository": "lighthouse/console",
                "mrUrl": "https://git.example.com/lighthouse/console/-/merge_requests/12",
            },
        )
        list_response = await self.client.get("/api/workbenches")
        list_data = await list_response.json()
        connector = self.store.register_connector(
            workbench["id"],
            {"name": "Reviewer Agent", "role": "reviewer"},
        )
        denied_read = await self.client.get("/api/workbenches/{}".format(workbench["id"]))
        denied_connector_read = await self.client.get(
            "/api/workbenches/{}".format(workbench["id"]),
            headers={"Authorization": "Bearer {}".format(connector["connectorToken"])},
        )
        allowed_read = await self.client.get(
            "/api/workbenches/{}".format(workbench["id"]),
            headers={"Authorization": "Bearer {}".format(workbench["ownerToken"])},
        )
        allowed_detail = await allowed_read.json()
        rename_response, renamed = await self.patch_json(
            "/api/workbenches/{}".format(workbench["id"]),
            {"title": "MR: renamed terminal workbench"},
            workbench["ownerToken"],
        )
        archive_response, archived = await self.post_json(
            "/api/workbenches/{}/archive".format(workbench["id"]),
            {},
            workbench["ownerToken"],
        )
        restore_response, restored = await self.post_json(
            "/api/workbenches/{}/restore".format(workbench["id"]),
            {},
            workbench["ownerToken"],
        )
        delete_response, deleted = await self.delete_json(
            "/api/workbenches/{}".format(workbench["id"]),
            {"confirm": True, "reason": "owner cleanup"},
            workbench["ownerToken"],
        )

        self.assertEqual(create_response.status, 201)
        self.assertEqual(list_response.status, 200)
        self.assertEqual(denied_read.status, 403)
        self.assertEqual(denied_connector_read.status, 403)
        self.assertEqual(allowed_read.status, 200)
        self.assertNotIn("ownerToken", list_data["workbenches"][0])
        self.assertEqual(list_data["workbenches"][0]["template"], "mr-review")
        self.assertIn("counts", list_data["workbenches"][0])
        self.assertEqual(allowed_detail["title"], "MR: terminal workbench")
        self.assertEqual(rename_response.status, 200)
        self.assertEqual(renamed["title"], "MR: renamed terminal workbench")
        self.assertEqual(archive_response.status, 200)
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(restore_response.status, 200)
        self.assertEqual(restored["status"], "open")
        self.assertEqual(delete_response.status, 200)
        self.assertEqual(deleted["status"], "deleted")
        self.assertIn("does not clean remote Agent machines", deleted["cleanupBoundary"])

    async def test_supervisor_invite_consumes_once_and_reads_workbench_without_owner_rights(self):
        _, workbench = await self.post_json("/api/workbenches", {"title": "MR: supervised"})
        _, connector = await self.post_json(
            "/api/rooms/{}/connectors".format(workbench["id"]),
            {"role": "reviewer", "name": "Reviewer Agent"},
            workbench["ownerToken"],
        )

        invite_response, invite = await self.post_json(
            "/api/rooms/{}/supervisor-invites".format(workbench["id"]),
            {"name": "Alice"},
            workbench["ownerToken"],
        )
        consume_response, consumed = await self.post_json(
            "/api/rooms/{}/supervisor-invites/consume".format(workbench["id"]),
            {"token": invite["token"]},
        )
        supervisor_read = await self.client.get(
            "/api/workbenches/{}".format(workbench["id"]),
            headers={"Authorization": "Bearer {}".format(consumed["accessToken"])},
        )
        supervisor_detail = await supervisor_read.json()
        second_consume_response, _ = await self.post_json(
            "/api/rooms/{}/supervisor-invites/consume".format(workbench["id"]),
            {"token": invite["token"]},
        )
        archive_response, _ = await self.post_json(
            "/api/workbenches/{}/archive".format(workbench["id"]),
            {},
            consumed["accessToken"],
        )

        self.assertEqual(invite_response.status, 201)
        self.assertIn("supervisorInvite=", invite["url"])
        self.assertEqual(consume_response.status, 201)
        self.assertTrue(consumed["accessToken"].startswith("rrs_"))
        self.assertEqual(supervisor_read.status, 200)
        self.assertIn({"type": "human", "name": "Alice", "role": "supervisor"}, supervisor_detail["participants"])
        self.assertNotIn("ownerToken", supervisor_detail)
        self.assertNotIn("connectorToken", supervisor_detail["connectors"][0])
        self.assertNotIn("token", supervisor_detail["connectors"][0])
        self.assertEqual(second_consume_response.status, 403)
        self.assertEqual(archive_response.status, 403)
        self.assertTrue(connector["connectorToken"].startswith("rrc_"))

    async def test_supervisor_session_can_write_messages_but_not_manage_room_content(self):
        _, workbench = await self.post_json("/api/workbenches", {"title": "MR: supervised message only"})
        _, connector = await self.post_json(
            "/api/rooms/{}/connectors".format(workbench["id"]),
            {"role": "reviewer", "name": "Reviewer Agent"},
            workbench["ownerToken"],
        )
        _, invite = await self.post_json(
            "/api/rooms/{}/supervisor-invites".format(workbench["id"]),
            {"name": "Alice"},
            workbench["ownerToken"],
        )
        _, consumed = await self.post_json(
            "/api/rooms/{}/supervisor-invites/consume".format(workbench["id"]),
            {"token": invite["token"]},
        )
        token = consumed["accessToken"]

        message_response, _ = await self.post_json(
            "/api/rooms/{}/messages".format(workbench["id"]),
            {"body": "@Reviewer Agent please review this context.", "payload": {"mentions": ["Reviewer Agent"]}},
            token,
        )
        finding_response, _ = await self.post_json(
            "/api/rooms/{}/findings".format(workbench["id"]),
            {"claim": "should not write"},
            token,
        )
        task_response, _ = await self.post_json(
            "/api/rooms/{}/tasks".format(workbench["id"]),
            {"title": "should not write"},
            token,
        )
        ws = await self.client.ws_connect("/ws/rooms/{}?token={}".format(workbench["id"], token))
        await ws.receive_json()
        await ws.receive_json()
        await ws.send_json(
            {
                "type": "message.create",
                "body": "@Reviewer Agent supervisor follow-up",
                "mentions": ["Reviewer Agent"],
            }
        )
        ws_message = await ws.receive_json()
        await ws.send_json({"type": "finding.create", "claim": "should not write"})
        ws_error = await ws.receive_json()
        await ws.close()

        self.assertEqual(message_response.status, 201)
        self.assertEqual(finding_response.status, 403)
        self.assertEqual(task_response.status, 403)
        self.assertEqual(ws_message["type"], "message.created")
        self.assertEqual(ws_message["message"]["senderName"], "Alice")
        self.assertEqual(ws_message["message"]["kind"], "supervisor_message")
        self.assertEqual(ws_error["type"], "error")
        self.assertIn("supervisor", ws_error["error"])
        self.assertTrue(connector["connectorToken"].startswith("rrc_"))

    async def test_supervisor_session_leave_invalidates_token_and_broadcasts_snapshot(self):
        _, workbench = await self.post_json("/api/workbenches", {"title": "MR: supervisor leave"})
        _, invite = await self.post_json(
            "/api/rooms/{}/supervisor-invites".format(workbench["id"]),
            {"name": "Alice"},
            workbench["ownerToken"],
        )
        _, consumed = await self.post_json(
            "/api/rooms/{}/supervisor-invites/consume".format(workbench["id"]),
            {"token": invite["token"]},
        )
        owner_ws = await self.client.ws_connect("/ws/rooms/{}?token={}".format(workbench["id"], workbench["ownerToken"]))
        await owner_ws.receive_json()
        await owner_ws.receive_json()

        leave_response, left = await self.post_json(
            "/api/rooms/{}/supervisor-session/leave".format(workbench["id"]),
            {"reason": "done observing"},
            consumed["accessToken"],
        )
        snapshot = await asyncio.wait_for(owner_ws.receive_json(), timeout=1)
        denied_read = await self.client.get(
            "/api/workbenches/{}".format(workbench["id"]),
            headers={"Authorization": "Bearer {}".format(consumed["accessToken"])},
        )
        await owner_ws.close()

        self.assertEqual(leave_response.status, 200)
        self.assertEqual(left["status"], "left")
        self.assertEqual(snapshot["type"], "room.snapshot")
        self.assertNotIn({"type": "human", "name": "Alice", "role": "supervisor"}, snapshot["room"]["participants"])
        self.assertIn("supervisor.left", [event["type"] for event in snapshot["room"]["events"]])
        self.assertEqual(denied_read.status, 403)

    async def test_owner_revoke_connector_invalidates_agent_token_and_broadcasts_snapshot(self):
        _, workbench = await self.post_json("/api/workbenches", {"title": "MR: revoke agent"})
        _, connector = await self.post_json(
            "/api/rooms/{}/connectors".format(workbench["id"]),
            {"role": "reviewer", "name": "Reviewer Agent"},
            workbench["ownerToken"],
        )
        owner_ws = await self.client.ws_connect("/ws/rooms/{}?token={}".format(workbench["id"], workbench["ownerToken"]))
        await owner_ws.receive_json()
        await owner_ws.receive_json()

        revoke_response, revoked = await self.post_json(
            "/api/rooms/{}/connectors/{}/revoke".format(workbench["id"], connector["id"]),
            {"reason": "owner removed agent"},
            workbench["ownerToken"],
        )
        snapshot = await asyncio.wait_for(owner_ws.receive_json(), timeout=1)
        denied_message, _ = await self.post_json(
            "/api/rooms/{}/messages".format(workbench["id"]),
            {"body": "should fail"},
            connector["connectorToken"],
        )
        denied_revoke, _ = await self.post_json(
            "/api/rooms/{}/connectors/{}/revoke".format(workbench["id"], connector["id"]),
            {"reason": "agent cannot revoke itself"},
            connector["connectorToken"],
        )
        await owner_ws.close()

        self.assertEqual(revoke_response.status, 200)
        self.assertEqual(revoked["status"], "revoked")
        self.assertIn("does not clean remote Agent machines", revoked["cleanupBoundary"])
        self.assertEqual(snapshot["type"], "room.snapshot")
        self.assertEqual(snapshot["room"]["connectors"][0]["status"], "revoked")
        self.assertIn("mcp.agent_revoked", [event["type"] for event in snapshot["room"]["events"]])
        self.assertEqual(denied_message.status, 403)
        self.assertEqual(denied_revoke.status, 403)

    async def test_finding_mutation_routes_require_matching_role(self):
        _, workbench = await self.post_json("/api/workbenches", {"title": "MR: guarded findings"})
        _, reviewer = await self.post_json(
            "/api/rooms/{}/connectors".format(workbench["id"]),
            {"role": "reviewer", "name": "Reviewer Agent"},
            workbench["ownerToken"],
        )
        _, developer = await self.post_json(
            "/api/rooms/{}/connectors".format(workbench["id"]),
            {"role": "developer", "name": "Developer Agent"},
            workbench["ownerToken"],
        )
        _, invite = await self.post_json(
            "/api/rooms/{}/supervisor-invites".format(workbench["id"]),
            {"name": "Read Only"},
            workbench["ownerToken"],
        )
        _, consumed = await self.post_json(
            "/api/rooms/{}/supervisor-invites/consume".format(workbench["id"]),
            {"token": invite["token"]},
        )
        _, finding = await self.post_json(
            "/api/rooms/{}/findings".format(workbench["id"]),
            {"claim": "review finding"},
            reviewer["connectorToken"],
        )

        anonymous_patch, _ = await self.patch_json("/api/findings/{}".format(finding["id"]), {"status": "accepted"})
        supervisor_patch, _ = await self.patch_json(
            "/api/findings/{}".format(finding["id"]),
            {"status": "accepted"},
            consumed["accessToken"],
        )
        reviewer_confirm, _ = await self.post_json(
            "/api/findings/{}/confirm".format(finding["id"]),
            {"decision": "accepted"},
            reviewer["connectorToken"],
        )
        supervisor_confirm, _ = await self.post_json(
            "/api/findings/{}/confirm".format(finding["id"]),
            {"decision": "accepted"},
            consumed["accessToken"],
        )
        supervisor_response, _ = await self.post_json(
            "/api/findings/{}/developer-response".format(finding["id"]),
            {"body": "not allowed"},
            consumed["accessToken"],
        )
        reviewer_response, _ = await self.post_json(
            "/api/findings/{}/developer-response".format(finding["id"]),
            {"body": "not allowed"},
            reviewer["connectorToken"],
        )
        developer_response, _ = await self.post_json(
            "/api/findings/{}/developer-response".format(finding["id"]),
            {"body": "fix prepared"},
            developer["connectorToken"],
        )
        owner_confirm, _ = await self.post_json(
            "/api/findings/{}/confirm".format(finding["id"]),
            {"decision": "accepted"},
            workbench["ownerToken"],
        )

        self.assertEqual(anonymous_patch.status, 403)
        self.assertEqual(supervisor_patch.status, 403)
        self.assertEqual(reviewer_confirm.status, 403)
        self.assertEqual(supervisor_confirm.status, 403)
        self.assertEqual(supervisor_response.status, 403)
        self.assertEqual(reviewer_response.status, 403)
        self.assertEqual(developer_response.status, 201)
        self.assertEqual(owner_confirm.status, 201)

    async def test_websocket_finding_mutations_are_scoped_to_socket_room(self):
        _, room_a = await self.post_json("/api/workbenches", {"title": "MR: room A"})
        _, room_b = await self.post_json("/api/workbenches", {"title": "MR: room B"})
        _, developer_a = await self.post_json(
            "/api/rooms/{}/connectors".format(room_a["id"]),
            {"role": "developer", "name": "Developer A"},
            room_a["ownerToken"],
        )
        _, reviewer_b = await self.post_json(
            "/api/rooms/{}/connectors".format(room_b["id"]),
            {"role": "reviewer", "name": "Reviewer B"},
            room_b["ownerToken"],
        )
        _, finding_b = await self.post_json(
            "/api/rooms/{}/findings".format(room_b["id"]),
            {"claim": "room B finding"},
            reviewer_b["connectorToken"],
        )

        developer_ws = await self.client.ws_connect("/ws/rooms/{}?token={}".format(room_a["id"], developer_a["connectorToken"]))
        await developer_ws.receive_json()
        await developer_ws.receive_json()
        await developer_ws.send_json({"type": "finding.respond", "findingId": finding_b["id"], "body": "wrong room"})
        developer_error = await developer_ws.receive_json()
        await developer_ws.close()

        owner_ws = await self.client.ws_connect("/ws/rooms/{}?token={}".format(room_a["id"], room_a["ownerToken"]))
        await owner_ws.receive_json()
        await owner_ws.receive_json()
        await owner_ws.send_json({"type": "finding.confirm", "findingId": finding_b["id"], "decision": "accepted"})
        owner_error = await owner_ws.receive_json()
        await owner_ws.close()

        loaded_b = self.store.get_finding(finding_b["id"])

        self.assertEqual(developer_error["type"], "error")
        self.assertIn("same room", developer_error["error"])
        self.assertEqual(owner_error["type"], "error")
        self.assertIn("same room", owner_error["error"])
        self.assertEqual(loaded_b["status"], "needs_developer_response")

    async def test_workbench_lifecycle_api_requires_owner_token_and_confirmation(self):
        _, workbench = await self.post_json("/api/workbenches", {"title": "MR: guarded"})

        denied_rename, _ = await self.patch_json(
            "/api/workbenches/{}".format(workbench["id"]),
            {"title": "bad"},
            "wrong-token",
        )
        denied_archive, _ = await self.post_json(
            "/api/workbenches/{}/archive".format(workbench["id"]),
            {},
            "wrong-token",
        )
        denied_delete, _ = await self.delete_json(
            "/api/workbenches/{}".format(workbench["id"]),
            {"confirm": True},
            "wrong-token",
        )
        unconfirmed_delete, _ = await self.delete_json(
            "/api/workbenches/{}".format(workbench["id"]),
            {"confirm": False},
            workbench["ownerToken"],
        )

        self.assertEqual(denied_rename.status, 403)
        self.assertEqual(denied_archive.status, 403)
        self.assertEqual(denied_delete.status, 403)
        self.assertEqual(unconfirmed_delete.status, 400)

    async def test_websocket_room_broadcasts_topic_finding_response_and_confirmation(self):
        _, room = await self.post_json(
            "/api/rooms",
            {"title": "MR: realtime", "context": {"repository": "lighthouse/review-room"}},
        )
        _, reviewer = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"role": "reviewer", "name": "Reviewer Agent"},
            room["ownerToken"],
        )
        _, developer = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"role": "developer", "name": "Developer Agent"},
            room["ownerToken"],
        )

        owner_ws = await self.client.ws_connect("/ws/rooms/{}?token={}".format(room["id"], room["ownerToken"]))
        reviewer_ws = await self.client.ws_connect("/ws/rooms/{}?token={}".format(room["id"], reviewer["connectorToken"]))
        developer_ws = await self.client.ws_connect("/ws/rooms/{}?token={}".format(room["id"], developer["connectorToken"]))
        await self._drain_initial_events(owner_ws, reviewer_ws, developer_ws)

        await owner_ws.send_json({"type": "message.create", "body": "请评审这个 MR 的鉴权风险。"})
        owner_message = await self._read_event(owner_ws, "message.created")
        self.assertEqual(owner_message["message"]["senderName"], "Agent Board owner")

        await reviewer_ws.send_json(
            {
                "type": "finding.create",
                "severity": "P1",
                "claim": "鉴权可能被绕过",
                "evidence": "新增路径没有校验 owner token",
                "suggestedFix": "补充 token 校验和测试",
            }
        )
        finding_created = await self._read_event(developer_ws, "finding.created")
        finding_id = finding_created["finding"]["id"]

        await developer_ws.send_json(
            {
                "type": "finding.respond",
                "findingId": finding_id,
                "body": "我会补充 owner token 校验。",
            }
        )
        responded = await self._read_event(owner_ws, "finding.updated")
        self.assertEqual(responded["finding"]["status"], "developer_responded")

        await owner_ws.send_json(
            {
                "type": "finding.confirm",
                "findingId": finding_id,
                "decision": "accepted",
                "body": "确认该修复方向。",
            }
        )
        confirmed = await self._read_finding_status(reviewer_ws, "accepted")
        self.assertEqual(confirmed["finding"]["status"], "accepted")

        await owner_ws.close()
        await reviewer_ws.close()
        await developer_ws.close()

    async def _drain_initial_events(self, *websockets):
        for ws in websockets:
            await self._read_event(ws, "room.snapshot")

    async def _read_event(self, ws, expected_type):
        try:
            return await asyncio.wait_for(self._read_event_loop(ws, expected_type), timeout=2)
        except asyncio.TimeoutError:
            self.fail("did not receive {}".format(expected_type))

    async def _read_finding_status(self, ws, expected_status):
        async def wait_for_status():
            while True:
                event = await self._read_event_loop(ws, "finding.updated")
                if event["finding"]["status"] == expected_status:
                    return event

        try:
            return await asyncio.wait_for(wait_for_status(), timeout=2)
        except asyncio.TimeoutError:
            self.fail("did not receive finding status {}".format(expected_status))

    async def _read_event_loop(self, ws, expected_type):
        while True:
            message = await ws.receive()
            self.assertEqual(message.type, WSMsgType.TEXT)
            data = json.loads(message.data)
            if data.get("type") == expected_type:
                return data


class CodexConnectorClientTest(unittest.TestCase):
    def test_home_page_exposes_realtime_room_experience(self):
        from review_room_service import index_html

        html = index_html()

        self.assertIn("/ws/rooms/", html)
        self.assertIn("new WebSocket", html)
        self.assertIn("工作台负责人", html)
        self.assertIn("评审智能体", html)
        self.assertIn("开发智能体", html)
        self.assertNotIn("发现 / 负责人决策", html)
        self.assertNotIn("暂无发现 / 负责人决策", html)

    def test_parse_room_url_converts_http_to_websocket_path(self):
        ws_url = parse_room_url("http://127.0.0.1:8707", "room_123", "token_abc")

        self.assertEqual(ws_url, "ws://127.0.0.1:8707/ws/rooms/room_123?token=token_abc")

    def test_mock_reviewer_and_developer_responses_match_room_events(self):
        reviewer_event = build_agent_response("reviewer", "请评审鉴权风险", mock=True)
        developer_event = build_agent_response("developer", "鉴权可能被绕过", mock=True, finding_id="finding_1")

        self.assertEqual(reviewer_event["type"], "finding.create")
        self.assertEqual(developer_event["type"], "finding.respond")
        self.assertEqual(developer_event["findingId"], "finding_1")


if __name__ == "__main__":
    unittest.main()
