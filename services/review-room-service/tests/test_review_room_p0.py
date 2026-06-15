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
        self.assertIn("Agent Board owner", html)
        self.assertIn("Reviewer Agent", html)
        self.assertIn("Developer Agent", html)
        self.assertIn("Finding / Decision", html)

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
