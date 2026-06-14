import asyncio
import base64
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    from aiohttp import WSMsgType
    from aiohttp.test_utils import TestClient, TestServer
except ModuleNotFoundError:
    WSMsgType = None
    TestClient = None
    TestServer = None


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from codex_connector import build_agent_response, is_assigned_task_event, parse_room_url, summarize_connector_response  # noqa: E402
from review_room_service import MCP_ENCODING_PROBE, ReviewRoomStore, build_app  # noqa: E402


class ReviewRoomP0StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ReviewRoomStore(os.path.join(self.tmp.name, "test.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_room_creation_returns_owner_token_and_topic_room_owner(self):
        room = self.store.create_room(
            {
                "title": "开放评审讨论",
                "objective": "让 owner、外部成员和 Agent 围绕一个话题协作。",
            }
        )

        self.assertEqual(room["roomId"], room["id"])
        self.assertTrue(room["ownerToken"].startswith("rro_"))
        self.assertEqual(room["provider"], "topic")
        self.assertEqual(room["mrUrl"], "")
        self.assertEqual(room["objective"], "让 owner、外部成员和 Agent 围绕一个话题协作。")
        self.assertEqual(
            [(item["type"], item["role"]) for item in room["participants"]],
            [("human", "owner")],
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
            {"decision": "accepted", "senderName": "review room owner"},
        )

        self.assertEqual(responded["status"], "developer_responded")
        self.assertEqual(confirmed["status"], "accepted")
        self.assertEqual(self.store.get_room(room["id"])["status"], "completed")

    def test_owner_confirmation_rejects_invalid_decision_value(self):
        room = self.store.create_room({"title": "MR"})
        connector = self.store.register_connector(room["id"], {"role": "reviewer"})
        identity = self.store.authenticate_room_token(room["id"], connector["connectorToken"])
        decision = self.store.create_owner_confirmation_request(room["id"], {"question": "Approve external sync?"}, identity)

        with self.assertRaisesRegex(ValueError, "decision must be accepted or rejected"):
            self.store.decide_owner_confirmation(decision["id"], {"decision": "maybe"})


@unittest.skipIf(TestClient is None, "aiohttp is not installed")
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

        await owner_ws.send_json({"type": "message.create", "body": "@owner 记录一下，@reviewer 请评审这个 MR 的鉴权风险。"})
        owner_message = await self._read_event(owner_ws, "message.created")
        self.assertEqual(owner_message["message"]["senderName"], "review room owner")
        self.assertEqual(len(owner_message["message"]["payload"]["mentions"]), 1)
        self.assertEqual(owner_message["message"]["payload"]["mentions"][0]["connectorId"], reviewer["id"])
        self.assertEqual(owner_message["message"]["payload"]["mentions"][0]["role"], "reviewer")

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

    async def test_websocket_handoff_acceptance_assigns_developer_task(self):
        _, room = await self.post_json("/api/rooms", {"title": "Handoff realtime"})
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

        await reviewer_ws.send_json({"type": "finding.create", "claim": "缺少鉴权测试"})
        finding_created = await self._read_event(owner_ws, "finding.created")
        await reviewer_ws.send_json(
            {
                "type": "handoff.propose",
                "findingId": finding_created["finding"]["id"],
                "reason": "需要 Developer Agent 修复并补测试。",
                "suggestedTask": "补上鉴权测试并回传结果。",
            }
        )
        handoff_event = await self._read_event(owner_ws, "handoff.proposed")
        await owner_ws.send_json({"type": "handoff.accept", "handoffId": handoff_event["handoff"]["id"]})
        converted = await self._read_event(owner_ws, "handoff.converted_to_task")
        assigned = await self._read_event(developer_ws, "task.assigned")
        snapshot = await self._read_event(owner_ws, "room.snapshot")

        self.assertEqual(converted["handoff"]["status"], "converted_to_task")
        self.assertEqual(converted["task"]["assignedConnectorId"], developer["id"])
        self.assertEqual(assigned["task"]["id"], converted["task"]["id"])
        self.assertEqual(snapshot["room"]["handoffs"][0]["convertedTaskId"], converted["task"]["id"])

        await developer_ws.send_json(
            {
                "type": "task.complete",
                "taskId": converted["task"]["id"],
                "finalMessage": "Fix applied and tests passed.",
            }
        )
        completed = await self._read_event(owner_ws, "task.completed")
        verify_assigned = await self._read_assigned_task_kind(reviewer_ws, "verify")
        verify_snapshot = await self._read_event(owner_ws, "room.snapshot")

        self.assertEqual(completed["task"]["status"], "completed")
        self.assertEqual(verify_assigned["task"]["assignedConnectorId"], reviewer["id"])
        self.assertEqual(verify_assigned["task"]["source"]["fixTaskId"], converted["task"]["id"])
        self.assertEqual(verify_snapshot["room"]["tasks"][-1]["kind"], "verify")

        await owner_ws.close()
        await reviewer_ws.close()
        await developer_ws.close()

    async def test_guest_invite_can_chat_but_cannot_confirm(self):
        _, room = await self.post_json("/api/rooms", {"title": "开放话题", "objective": "验证访客分享链接"})
        _, invite = await self.post_json(
            "/api/rooms/{}/invites".format(room["id"]),
            {"type": "guest"},
            room["ownerToken"],
        )
        _, joined = await self.post_json(
            "/api/rooms/{}/join".format(room["id"]),
            {"inviteCode": invite["code"], "nickname": "外部用户"},
        )

        owner_ws = await self.client.ws_connect("/ws/rooms/{}?token={}".format(room["id"], room["ownerToken"]))
        guest_ws = await self.client.ws_connect("/ws/rooms/{}?token={}".format(room["id"], joined["guestToken"]))
        await self._drain_initial_events(owner_ws, guest_ws)

        await guest_ws.send_json({"type": "message.create", "body": "我从分享链接进来了。"})
        guest_message = await self._read_event(owner_ws, "message.created")
        self.assertEqual(guest_message["message"]["senderName"], "外部用户")
        self.assertEqual(guest_message["message"]["kind"], "guest_message")

        await guest_ws.send_json({"type": "finding.confirm", "findingId": "finding_missing"})
        error = await self._read_event(guest_ws, "error")
        self.assertEqual(error["error"], "owner token required")

        await owner_ws.close()
        await guest_ws.close()

    async def test_owner_can_disconnect_guest_and_connector(self):
        _, room = await self.post_json("/api/rooms", {"title": "Room control"})
        _, connector = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"role": "reviewer", "name": "Reviewer Agent"},
            room["ownerToken"],
        )
        _, invite = await self.post_json(
            "/api/rooms/{}/invites".format(room["id"]),
            {"type": "guest"},
            room["ownerToken"],
        )
        _, joined = await self.post_json(
            "/api/rooms/{}/join".format(room["id"]),
            {"inviteCode": invite["code"], "nickname": "Guest User"},
        )

        guest_ws = await self.client.ws_connect("/ws/rooms/{}?token={}".format(room["id"], joined["guestToken"]))
        connector_ws = await self.client.ws_connect("/ws/rooms/{}?token={}".format(room["id"], connector["connectorToken"]))
        await self._drain_initial_events(guest_ws, connector_ws)

        guest_disconnect, guest_result = await self.post_json(
            "/api/rooms/{}/disconnect".format(room["id"]),
            {"targetType": "guest", "participantId": joined["identity"]["participantId"]},
            room["ownerToken"],
        )
        guest_event = await self._read_event(guest_ws, "room.disconnected")
        denied_guest_message, _ = await self.post_json(
            "/api/rooms/{}/messages".format(room["id"]),
            {"body": "still here"},
            joined["guestToken"],
        )

        connector_disconnect, connector_result = await self.post_json(
            "/api/rooms/{}/disconnect".format(room["id"]),
            {"targetType": "connector", "connectorId": connector["id"]},
            room["ownerToken"],
        )
        connector_event = await self._read_event(connector_ws, "room.disconnected")
        denied_connector_snapshot = await self.client.get(
            "/api/rooms/{}".format(room["id"]),
            headers={"Authorization": "Bearer {}".format(connector["connectorToken"])},
        )

        self.assertEqual(guest_disconnect.status, 201)
        self.assertEqual(guest_result["closedConnections"], 1)
        self.assertEqual(guest_event["target"]["targetType"], "guest")
        self.assertEqual(denied_guest_message.status, 403)
        self.assertEqual(connector_disconnect.status, 201)
        self.assertEqual(connector_result["closedConnections"], 1)
        self.assertEqual(connector_event["target"]["targetType"], "connector")
        self.assertEqual(denied_connector_snapshot.status, 403)

        await guest_ws.close()
        await connector_ws.close()

    async def test_owner_can_rotate_connector_token_and_disconnect_old_socket(self):
        _, room = await self.post_json("/api/rooms", {"title": "Token rotation"})
        _, connector = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"role": "reviewer", "name": "Reviewer Agent"},
            room["ownerToken"],
        )
        connector_ws = await self.client.ws_connect("/ws/rooms/{}?token={}".format(room["id"], connector["connectorToken"]))
        await self._drain_initial_events(connector_ws)

        rotate_response, rotated = await self.post_json(
            "/api/rooms/{}/connectors/{}/rotate-token".format(room["id"], connector["id"]),
            {},
            room["ownerToken"],
        )
        disconnect_event = await self._read_event(connector_ws, "room.disconnected")
        denied_old_snapshot = await self.client.get(
            "/api/rooms/{}".format(room["id"]),
            headers={"Authorization": "Bearer {}".format(connector["connectorToken"])},
        )
        allowed_new_snapshot = await self.client.get(
            "/api/rooms/{}".format(room["id"]),
            headers={"Authorization": "Bearer {}".format(rotated["connectorToken"])},
        )
        allowed_new_snapshot_json = await allowed_new_snapshot.json()
        new_event_response, new_event = await self.post_json(
            "/api/connectors/{}/events".format(connector["id"]),
            {"type": "message", "body": "new token works"},
            rotated["connectorToken"],
        )

        self.assertEqual(rotate_response.status, 201)
        self.assertEqual(rotated["closedConnections"], 1)
        self.assertNotEqual(rotated["connectorToken"], connector["connectorToken"])
        self.assertIn(rotated["connectorToken"], rotated["bootstrap"]["command"])
        self.assertEqual(disconnect_event["target"]["targetType"], "connector")
        self.assertEqual(denied_old_snapshot.status, 403)
        self.assertEqual(allowed_new_snapshot.status, 200)
        self.assertNotIn("connectorToken", allowed_new_snapshot_json["connectors"][0])
        self.assertEqual(new_event_response.status, 201)
        self.assertEqual(new_event["body"], "new token works")

        await connector_ws.close()

    async def test_owner_task_assignment_tracks_agent_run_lifecycle(self):
        _, room = await self.post_json("/api/rooms", {"title": "Task control"})
        _, connector = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"role": "reviewer", "name": "Reviewer Agent"},
            room["ownerToken"],
        )

        owner_ws = await self.client.ws_connect("/ws/rooms/{}?token={}".format(room["id"], room["ownerToken"]))
        connector_ws = await self.client.ws_connect("/ws/rooms/{}?token={}".format(room["id"], connector["connectorToken"]))
        await self._drain_initial_events(owner_ws, connector_ws)

        task_response, task = await self.post_json(
            "/api/rooms/{}/tasks".format(room["id"]),
            {
                "kind": "review",
                "instruction": "Review the task routing boundary.",
                "target": {"mode": "connector", "connectorId": connector["id"]},
            },
            room["ownerToken"],
        )
        assigned = await self._read_event(connector_ws, "task.assigned")
        run_response, run = await self.post_json(
            "/api/tasks/{}/runs".format(task["id"]),
            {"workspace": "G:/Codex/Lighthouse", "model": "gpt-test", "sandbox": "read-only"},
            connector["connectorToken"],
        )
        completed_response, completed = await self.post_json(
            "/api/tasks/{}/complete".format(task["id"]),
            {"finalMessage": "Task completed."},
            connector["connectorToken"],
        )
        snapshot_response = await self.client.get(
            "/api/rooms/{}".format(room["id"]),
            headers={"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        snapshot = await snapshot_response.json()

        self.assertEqual(task_response.status, 201)
        self.assertEqual(assigned["task"]["id"], task["id"])
        self.assertEqual(run_response.status, 201)
        self.assertEqual(run["status"], "running")
        self.assertEqual(completed_response.status, 201)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(snapshot["tasks"][0]["status"], "completed")
        self.assertEqual(snapshot["agentRuns"][0]["status"], "completed")

        await owner_ws.close()
        await connector_ws.close()

    async def test_claimable_task_requires_claim_before_agent_run(self):
        _, room = await self.post_json("/api/rooms", {"title": "Claim realtime"})
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

        _, task = await self.post_json(
            "/api/rooms/{}/tasks".format(room["id"]),
            {
                "kind": "review",
                "instruction": "Claimable review work.",
                "target": {"mode": "claim", "role": "reviewer", "capability": "finding:create"},
            },
            room["ownerToken"],
        )
        await reviewer_ws.send_json({"type": "agent_run.start", "taskId": task["id"]})
        run_error = await self._read_event(reviewer_ws, "error")
        await developer_ws.send_json({"type": "task.claim", "taskId": task["id"]})
        claim_error = await self._read_event(developer_ws, "error")
        await reviewer_ws.send_json({"type": "task.claim", "taskId": task["id"]})
        claimed = await self._read_event(owner_ws, "task.claimed")
        assigned = await self._read_assigned_task_kind(reviewer_ws, "review")
        await reviewer_ws.send_json({"type": "agent_run.start", "taskId": task["id"], "workspace": "G:/Codex/Lighthouse"})
        started = await self._read_event(owner_ws, "agent_run.started")

        self.assertEqual(run_error["error"], "task must be claimed before running")
        self.assertEqual(claim_error["error"], "connector does not match task target")
        self.assertEqual(claimed["task"]["assignedConnectorId"], reviewer["id"])
        self.assertEqual(assigned["task"]["id"], task["id"])
        self.assertEqual(started["agentRun"]["taskId"], task["id"])

        await owner_ws.close()
        await reviewer_ws.close()
        await developer_ws.close()

    async def test_mcp_gateway_snapshot_and_finding_use_connector_identity(self):
        _, room = await self.post_json("/api/rooms", {"title": "MCP Gateway"})
        _, reviewer = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"role": "reviewer", "name": "Reviewer Agent", "adapterType": "mcp-remote"},
            room["ownerToken"],
        )

        tools_response = await self.client.get("/api/mcp/tools")
        tools = await tools_response.json()
        snapshot_response, snapshot = await self.post_json(
            "/api/mcp/tools/get_snapshot",
            {"roomId": room["id"]},
            reviewer["connectorToken"],
        )
        denied_owner_message_response, denied_owner_message = await self.post_json(
            "/api/mcp/tools/post_message",
            {"roomId": room["id"], "body": "owner cannot use connector chat"},
            room["ownerToken"],
        )
        invalid_message_payload_response, invalid_message_payload = await self.post_json(
            "/api/mcp/tools/post_message",
            {"roomId": room["id"], "body": "bad payload", "payload": []},
            reviewer["connectorToken"],
        )
        mojibake_message_response, mojibake_message = await self.post_json(
            "/api/mcp/tools/post_message",
            {"roomId": room["id"], "body": "?? @reviewer????????"},
            reviewer["connectorToken"],
        )
        utf8_body = "\u6536\u5230 @reviewer\uff0c\u4e2d\u6587\u56de\u590d\u6b63\u5e38\u3002"
        base64_message_response, base64_message = await self.post_json(
            "/api/mcp/tools/post_message",
            {"roomId": room["id"], "bodyUtf8Base64": base64.b64encode(utf8_body.encode("utf-8")).decode("ascii")},
            reviewer["connectorToken"],
        )
        with patch.dict(os.environ, {"REVIEW_ROOM_ENABLE_HOSTED_AGENT": "true"}):
            message_response, message_result = await self.post_json(
                "/api/mcp/tools/post_message",
                {"roomId": room["id"], "body": "MCP connector says hello.", "kind": "review_finding"},
                reviewer["connectorToken"],
            )
        snapshot_after_message = self.store.get_room(room["id"])
        connector_messages = [message for message in snapshot_after_message["messages"] if message["kind"] == "connector_message"]
        denied_owner_response, denied_owner = await self.post_json(
            "/api/mcp/tools/create_finding",
            {"roomId": room["id"], "claim": "owner cannot use connector tool"},
            room["ownerToken"],
        )
        mojibake_finding_response, mojibake_finding = await self.post_json(
            "/api/mcp/tools/create_finding",
            {
                "roomId": room["id"],
                "severity": "P2",
                "claim": "????????",
                "evidence": "Gateway used connector token.",
                "suggestedFix": "Use UTF-8.",
            },
            reviewer["connectorToken"],
        )
        finding_response, finding_result = await self.post_json(
            "/api/mcp/tools/create_finding",
            {
                "roomId": room["id"],
                "severity": "P1",
                "claim": "MCP submitted finding",
                "evidence": "Gateway used connector token.",
                "suggestedFix": "Keep connector-scoped capability checks.",
            },
            reviewer["connectorToken"],
        )
        _, task = await self.post_json(
            "/api/rooms/{}/tasks".format(room["id"]),
            {
                "kind": "review",
                "instruction": "Claim from MCP.",
                "target": {"mode": "claim", "role": "reviewer", "capability": "finding:create"},
            },
            room["ownerToken"],
        )
        list_response, listed = await self.post_json(
            "/api/mcp/tools/list_tasks",
            {"roomId": room["id"]},
            reviewer["connectorToken"],
        )
        claim_response, claimed = await self.post_json(
            "/api/mcp/tools/claim_task",
            {"taskId": task["id"]},
            reviewer["connectorToken"],
        )
        denied_owner_start_response, denied_owner_start = await self.post_json(
            "/api/mcp/tools/start_run",
            {"taskId": task["id"]},
            room["ownerToken"],
        )
        start_response, started = await self.post_json(
            "/api/mcp/tools/start_run",
            {
                "taskId": task["id"],
                "promptSummary": "MCP run lifecycle",
                "workspace": "G:/Codex/Lighthouse",
                "model": "gpt-test",
                "sandbox": "read-only",
            },
            reviewer["connectorToken"],
        )
        complete_response, completed = await self.post_json(
            "/api/mcp/tools/complete_task",
            {"taskId": task["id"], "finalMessage": "MCP task completed."},
            reviewer["connectorToken"],
        )
        snapshot_after_response = await self.client.get(
            "/api/rooms/{}".format(room["id"]),
            headers={"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        snapshot_after = await snapshot_after_response.json()

        self.assertEqual(tools_response.status, 200)
        self.assertEqual(tools["gateway"], "review-room.mcp-remote")
        self.assertIn("payload", tools["eventEnvelope"]["required"])
        self.assertEqual(tools["cursorReconnect"]["resumeHeader"], "Last-Event-ID")
        self.assertEqual(tools["replyPolicy"]["shouldRespond"][1]["reason"], "direct mention")
        self.assertEqual(tools["streams"][0]["name"], "room.events")
        self.assertEqual(tools["streams"][0]["transport"], "sse")
        self.assertIn("connect", [tool["name"] for tool in tools["tools"]])
        self.assertIn("get_snapshot", [tool["name"] for tool in tools["tools"]])
        self.assertIn("poll_events", [tool["name"] for tool in tools["tools"]])
        self.assertIn("set_status", [tool["name"] for tool in tools["tools"]])
        self.assertIn("list_tasks", [tool["name"] for tool in tools["tools"]])
        self.assertIn("claim_task", [tool["name"] for tool in tools["tools"]])
        self.assertIn("start_run", [tool["name"] for tool in tools["tools"]])
        self.assertIn("complete_task", [tool["name"] for tool in tools["tools"]])
        self.assertIn("post_message", [tool["name"] for tool in tools["tools"]])
        self.assertIn("propose_handoff", [tool["name"] for tool in tools["tools"]])
        self.assertEqual(snapshot_response.status, 200)
        self.assertEqual(snapshot["room"]["id"], room["id"])
        self.assertEqual(snapshot["agentContract"]["replyPolicy"]["shouldRespond"][0]["priority"], "P0")
        self.assertEqual(snapshot["room"]["connectors"][0]["status"], "mcp_ready")
        self.assertEqual(snapshot["room"]["statusSummary"]["onlineAgentCount"], 0)
        self.assertIn("trust", snapshot)
        self.assertEqual(denied_owner_message_response.status, 403)
        self.assertEqual(denied_owner_message["error"], "message:reply connector capability required")
        self.assertEqual(invalid_message_payload_response.status, 400)
        self.assertEqual(invalid_message_payload["error"], "payload must be an object")
        self.assertEqual(mojibake_message_response.status, 400)
        self.assertIn("mojibake", mojibake_message["error"])
        self.assertEqual(base64_message_response.status, 201)
        self.assertEqual(base64_message["message"]["body"], utf8_body)
        self.assertEqual(message_response.status, 201)
        self.assertEqual(message_result["message"]["kind"], "connector_message")
        self.assertEqual(message_result["message"]["senderName"], "Reviewer Agent")
        self.assertIn("not executable work", message_result["trust"])
        self.assertEqual(len(connector_messages), 2)
        self.assertIn(utf8_body, [message["body"] for message in connector_messages])
        self.assertFalse(any(message["payload"].get("hostedAgent") for message in connector_messages))
        self.assertEqual(denied_owner_response.status, 403)
        self.assertEqual(denied_owner["error"], "finding:create connector capability required")
        self.assertEqual(mojibake_finding_response.status, 400)
        self.assertIn("mojibake", mojibake_finding["error"])
        self.assertEqual(finding_response.status, 201)
        self.assertEqual(finding_result["finding"]["createdBy"], "Reviewer Agent")
        self.assertEqual(list_response.status, 200)
        self.assertTrue([item for item in listed["tasks"] if item["id"] == task["id"] and item["claimable"]])
        self.assertEqual(claim_response.status, 201)
        self.assertEqual(claimed["task"]["assignedConnectorId"], reviewer["id"])
        self.assertEqual(denied_owner_start_response.status, 403)
        self.assertEqual(denied_owner_start["error"], "connector token required")
        self.assertEqual(start_response.status, 201)
        self.assertEqual(started["agentRun"]["taskId"], task["id"])
        self.assertEqual(started["agentRun"]["adapterType"], "mcp-remote")
        self.assertEqual(started["agentRun"]["status"], "running")
        self.assertEqual(complete_response.status, 201)
        self.assertEqual(completed["task"]["status"], "completed")
        self.assertIsNone(completed["verificationTask"])
        self.assertEqual(snapshot_after_response.status, 200)
        self.assertEqual(snapshot_after["connectors"][0]["status"], "mcp_ready")
        self.assertEqual(snapshot_after["connectors"][0]["eventCount"], 8)
        self.assertEqual(snapshot_after["statusSummary"]["onlineAgentCount"], 0)
        self.assertEqual(snapshot_after["tasks"][-1]["status"], "completed")
        self.assertEqual(snapshot_after["agentRuns"][-1]["adapterType"], "mcp-remote")
        self.assertEqual(snapshot_after["agentRuns"][-1]["status"], "completed")

    async def test_mcp_connect_marks_remote_agent_connected_once(self):
        _, room = await self.post_json("/api/rooms", {"title": "MCP Connect"})
        _, reviewer = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"role": "reviewer", "name": "Reviewer Agent", "adapterType": "mcp-remote"},
            room["ownerToken"],
        )
        _, guest_invite = await self.post_json(
            "/api/rooms/{}/invites".format(room["id"]),
            {"type": "guest"},
            room["ownerToken"],
        )
        _, guest = await self.post_json(
            "/api/rooms/{}/join".format(room["id"]),
            {"inviteCode": guest_invite["code"], "nickname": "Guest"},
        )

        denied_owner_response, denied_owner = await self.post_json(
            "/api/mcp/tools/connect",
            {"roomId": room["id"]},
            room["ownerToken"],
        )
        denied_guest_response, denied_guest = await self.post_json(
            "/api/mcp/tools/connect",
            {"roomId": room["id"]},
            guest["guestToken"],
        )
        missing_probe_response, missing_probe = await self.post_json(
            "/api/mcp/tools/connect",
            {"roomId": room["id"], "clientName": "Fast MCP Agent"},
            reviewer["connectorToken"],
        )
        bad_probe_response, bad_probe = await self.post_json(
            "/api/mcp/tools/connect",
            {"roomId": room["id"], "clientName": "Fast MCP Agent", "encodingProbe": "????"},
            reviewer["connectorToken"],
        )
        connect_response, connected = await self.post_json(
            "/api/mcp/tools/connect",
            {"roomId": room["id"], "clientName": "Fast MCP Agent", "clientVersion": "0.1.0", "encodingProbe": MCP_ENCODING_PROBE},
            reviewer["connectorToken"],
        )
        first_seen = connected["connector"]["firstSeenAt"]
        first_latency = connected["connector"]["connectLatencyMs"]
        await asyncio.sleep(0.01)
        repeat_response, repeated = await self.post_json(
            "/api/mcp/tools/connect",
            {"roomId": room["id"], "clientName": "Fast MCP Agent", "clientVersion": "0.1.1", "encodingProbe": MCP_ENCODING_PROBE},
            reviewer["connectorToken"],
        )
        snapshot = self.store.get_room(room["id"])

        self.assertEqual(denied_owner_response.status, 403)
        self.assertEqual(denied_owner["error"], "connector token required")
        self.assertEqual(denied_guest_response.status, 403)
        self.assertEqual(denied_guest["error"], "connector token required")
        self.assertEqual(missing_probe_response.status, 400)
        self.assertEqual(missing_probe["encoding"]["requiredProbe"], MCP_ENCODING_PROBE)
        self.assertEqual(bad_probe_response.status, 400)
        self.assertTrue(bad_probe["encoding"]["looksLikeMojibake"])
        self.assertEqual(connect_response.status, 201)
        self.assertTrue(connected["connected"])
        self.assertEqual(connected["connector"]["status"], "connected")
        self.assertEqual(connected["connector"]["version"], "0.1.0")
        self.assertNotIn("token", connected["connector"])
        self.assertNotIn("connectorToken", connected["connector"])
        self.assertIsNotNone(first_seen)
        self.assertGreaterEqual(first_latency, 0)
        self.assertLessEqual(first_latency, 30000)
        self.assertEqual(connected["next"]["listen"]["transport"], "sse")
        self.assertIn("/api/mcp/events?roomId={}".format(room["id"]), connected["next"]["listen"]["eventStreamUrl"])
        self.assertEqual(connected["next"]["fallbackTool"], "poll_events")
        self.assertEqual(connected["encoding"]["status"], "verified")
        self.assertEqual(repeat_response.status, 201)
        self.assertEqual(repeated["connector"]["firstSeenAt"], first_seen)
        self.assertEqual(repeated["connector"]["version"], "0.1.1")
        self.assertEqual(snapshot["connectors"][0]["status"], "connected")
        self.assertEqual(snapshot["connectors"][0]["firstSeenAt"], first_seen)
        self.assertEqual(snapshot["connectors"][0]["connectLatencyMs"], first_latency)

    async def test_mcp_set_status_updates_remote_agent_lifecycle(self):
        _, room = await self.post_json("/api/rooms", {"title": "MCP Status"})
        _, reviewer = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"role": "reviewer", "name": "Reviewer Agent", "adapterType": "mcp-remote"},
            room["ownerToken"],
        )

        denied_response, denied = await self.post_json(
            "/api/mcp/tools/set_status",
            {"roomId": room["id"], "status": "thinking"},
            room["ownerToken"],
        )
        invalid_response, invalid = await self.post_json(
            "/api/mcp/tools/set_status",
            {"roomId": room["id"], "status": "teleporting"},
            reviewer["connectorToken"],
        )
        status_response, status = await self.post_json(
            "/api/mcp/tools/set_status",
            {"roomId": room["id"], "status": "thinking", "detail": "reviewing task context"},
            reviewer["connectorToken"],
        )
        await self.post_json(
            "/api/mcp/tools/get_snapshot",
            {"roomId": room["id"]},
            reviewer["connectorToken"],
        )
        snapshot = self.store.get_room(room["id"])

        self.assertEqual(denied_response.status, 403)
        self.assertEqual(denied["error"], "connector token required")
        self.assertEqual(invalid_response.status, 400)
        self.assertIn("connector status", invalid["error"])
        self.assertEqual(status_response.status, 201)
        self.assertEqual(status["connector"]["status"], "thinking")
        self.assertNotIn("connectorToken", status["connector"])
        self.assertEqual(snapshot["connectors"][0]["status"], "thinking")
        self.assertEqual(snapshot["statusSummary"]["busyAgentCount"], 1)
        self.assertEqual(snapshot["statusSummary"]["onlineAgentCount"], 1)

    async def test_mcp_poll_events_returns_room_content_by_cursor(self):
        _, room = await self.post_json("/api/rooms", {"title": "MCP Poll Events"})
        _, reviewer = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"role": "reviewer", "name": "Reviewer Agent", "adapterType": "mcp-remote"},
            room["ownerToken"],
        )
        _, owner_message = await self.post_json(
            "/api/rooms/{}/messages".format(room["id"]),
            {"body": "Owner message for remote Agent.", "senderName": "review room owner"},
            room["ownerToken"],
        )
        _, task = await self.post_json(
            "/api/rooms/{}/tasks".format(room["id"]),
            {
                "kind": "review",
                "instruction": "Decide whether to answer the owner.",
                "target": {"mode": "connector", "connectorId": reviewer["id"]},
            },
            room["ownerToken"],
        )

        denied_response, denied = await self.post_json(
            "/api/mcp/tools/poll_events",
            {"roomId": room["id"]},
            room["ownerToken"],
        )
        first_response, first = await self.post_json(
            "/api/mcp/tools/poll_events",
            {"roomId": room["id"], "limit": 3},
            reviewer["connectorToken"],
        )
        first_event_ids = [event["id"] for event in first["events"]]
        first_types = [event["type"] for event in first["events"]]
        next_response, next_page = await self.post_json(
            "/api/mcp/tools/poll_events",
            {"roomId": room["id"], "cursor": first["nextCursor"]},
            reviewer["connectorToken"],
        )
        all_first_page_events = first["events"] + next_page["events"]
        all_first_page_types = [event["type"] for event in all_first_page_events]
        all_first_page_messages = [
            event["message"]["body"]
            for event in all_first_page_events
            if event["type"] == "message.created"
        ]
        _, followup_message = await self.post_json(
            "/api/rooms/{}/messages".format(room["id"]),
            {"body": "Follow-up only after cursor.", "senderName": "review room owner"},
            room["ownerToken"],
        )
        followup_response, followup = await self.post_json(
            "/api/mcp/tools/poll_events",
            {"roomId": room["id"], "cursor": next_page["nextCursor"]},
            reviewer["connectorToken"],
        )
        followup_message_events = [
            event for event in followup["events"] if event["type"] == "message.created"
        ]
        invalid_response, invalid = await self.post_json(
            "/api/mcp/tools/poll_events",
            {"roomId": room["id"], "cursor": "bad-cursor"},
            reviewer["connectorToken"],
        )
        snapshot = self.store.get_room(room["id"])

        self.assertEqual(denied_response.status, 403)
        self.assertEqual(denied["error"], "connector token required")
        self.assertEqual(first_response.status, 200)
        self.assertEqual(first["poller"]["connectorId"], reviewer["id"])
        self.assertEqual(first["agentContract"]["cursorReconnect"]["fallbackTool"], "poll_events")
        self.assertEqual(first["events"][0]["cursor"], "1")
        self.assertIn("payload", first["events"][0])
        self.assertTrue(first["hasMore"])
        self.assertEqual(next_response.status, 200)
        self.assertGreaterEqual(int(next_page["nextCursor"]), int(first["nextCursor"]))
        self.assertIn("message.created", first_types)
        self.assertIn("message:{}:created".format(owner_message["id"]), first_event_ids + [event["id"] for event in next_page["events"]])
        self.assertIn("Owner message for remote Agent.", all_first_page_messages)
        self.assertIn("task.created", all_first_page_types)
        task_events = [event for event in all_first_page_events if event.get("task", {}).get("id") == task["id"]]
        self.assertEqual(task_events[-1]["resource"], "room.tasks")
        self.assertEqual(task_events[-1]["trust"], "review-room-policy")
        self.assertEqual(task_events[-1]["payload"]["task"]["id"], task["id"])
        self.assertIn("assigned or claimed tasks", first["trust"])
        self.assertEqual(followup_response.status, 200)
        self.assertEqual(followup_message_events[-1]["message"]["id"], followup_message["id"])
        self.assertEqual(followup_message_events[-1]["message"]["body"], "Follow-up only after cursor.")
        self.assertEqual(invalid_response.status, 400)
        self.assertEqual(invalid["error"], "cursor must be a numeric event cursor")
        self.assertEqual(snapshot["connectors"][0]["status"], "mcp_ready")
        self.assertEqual(snapshot["statusSummary"]["onlineAgentCount"], 0)

    async def test_mcp_event_stream_pushes_room_content_realtime(self):
        _, room = await self.post_json("/api/rooms", {"title": "MCP Realtime Events"})
        _, reviewer = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"role": "reviewer", "name": "Reviewer Agent", "adapterType": "mcp-remote"},
            room["ownerToken"],
        )
        connect_response, connected_agent = await self.post_json(
            "/api/mcp/tools/connect",
            {"roomId": room["id"], "clientName": "Realtime MCP Agent", "encodingProbe": MCP_ENCODING_PROBE},
            reviewer["connectorToken"],
        )
        first_seen = connected_agent["connector"]["firstSeenAt"]
        first_latency = connected_agent["connector"]["connectLatencyMs"]
        await asyncio.sleep(0.01)

        denied_response = await self.client.get(
            "/api/mcp/events?roomId={}".format(room["id"]),
            headers={"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        invalid_cursor_response = await self.client.get(
            "/api/mcp/events?roomId={}&cursor=bad-cursor".format(room["id"]),
            headers={"Authorization": "Bearer {}".format(reviewer["connectorToken"])},
        )
        stream_response = await self.client.get(
            "/api/mcp/events?roomId={}".format(room["id"]),
            headers={"Authorization": "Bearer {}".format(reviewer["connectorToken"])},
        )
        connected = await self._read_sse_event(stream_response, "review_room.connected")
        _, owner_message = await self.post_json(
            "/api/rooms/{}/messages".format(room["id"]),
            {"body": "Realtime push for remote Agent.", "senderName": "review room owner"},
            room["ownerToken"],
        )
        pushed = await self._read_sse_event(
            stream_response,
            "message.created",
            lambda data: data.get("message", {}).get("id") == owner_message["id"],
        )
        snapshot = self.store.get_room(room["id"])

        denied_body = await denied_response.json()
        invalid_body = await invalid_cursor_response.json()
        denied_response.close()
        invalid_cursor_response.close()
        stream_response.close()
        await asyncio.sleep(0.05)
        snapshot_after_close = self.store.get_room(room["id"])

        self.assertEqual(connect_response.status, 201)
        self.assertEqual(denied_response.status, 403)
        self.assertEqual(denied_body["error"], "connector token required")
        self.assertEqual(invalid_cursor_response.status, 400)
        self.assertEqual(invalid_body["error"], "Last-Event-ID must be a numeric event cursor")
        self.assertEqual(stream_response.status, 200)
        self.assertIn("text/event-stream", stream_response.headers.get("Content-Type", ""))
        self.assertEqual(connected["data"]["identity"]["connectorId"], reviewer["id"])
        self.assertEqual(pushed["data"]["type"], "message.created")
        self.assertEqual(pushed["data"]["message"]["body"], "Realtime push for remote Agent.")
        self.assertEqual(pushed["data"]["resource"], "room.timeline")
        self.assertEqual(pushed["data"]["trust"], "mixed-untrusted")
        self.assertEqual(pushed["data"]["payload"]["message"]["id"], owner_message["id"])
        self.assertTrue(pushed["id"].isdigit())
        self.assertEqual(snapshot["connectors"][0]["status"], "mcp_streaming")
        self.assertEqual(snapshot["connectors"][0]["firstSeenAt"], first_seen)
        self.assertEqual(snapshot["connectors"][0]["connectLatencyMs"], first_latency)
        self.assertEqual(snapshot["statusSummary"]["onlineAgentCount"], 1)
        self.assertEqual(snapshot_after_close["connectors"][0]["status"], "mcp_ready")
        self.assertEqual(snapshot_after_close["statusSummary"]["onlineAgentCount"], 0)

    async def test_rest_scoped_threads_limit_participants_and_summarize_to_owner_decision(self):
        _, room = await self.post_json("/api/rooms", {"title": "Thread REST"})
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
        _, observer = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"role": "observer", "name": "Observer Agent"},
            room["ownerToken"],
        )
        _, invite = await self.post_json(
            "/api/rooms/{}/invites".format(room["id"]),
            {"type": "guest"},
            room["ownerToken"],
        )
        _, joined = await self.post_json(
            "/api/rooms/{}/join".format(room["id"]),
            {"inviteCode": invite["code"], "nickname": "Guest"},
        )
        denied_guest_response, denied_guest = await self.post_json(
            "/api/rooms/{}/threads".format(room["id"]),
            {"question": "Guest should not create this.", "participants": [reviewer["id"]]},
            joined["guestToken"],
        )
        create_response, thread = await self.post_json(
            "/api/rooms/{}/threads".format(room["id"]),
            {
                "question": "Can reviewer and developer agree on the fix?",
                "participants": [reviewer["id"], developer["id"]],
                "maxTurns": 2,
                "sourceFindingId": "finding_1",
            },
            room["ownerToken"],
        )
        denied_observer_response, denied_observer = await self.post_json(
            "/api/threads/{}/messages".format(thread["id"]),
            {"body": "Observer should not join the scoped thread."},
            observer["connectorToken"],
        )
        reviewer_message_response, reviewer_thread = await self.post_json(
            "/api/threads/{}/messages".format(thread["id"]),
            {"body": "Reviewer proposes the safer fix."},
            reviewer["connectorToken"],
        )
        developer_message_response, developer_thread = await self.post_json(
            "/api/threads/{}/messages".format(thread["id"]),
            {"body": "Developer accepts with an owner sync gate."},
            developer["connectorToken"],
        )
        extra_message_response, extra_message = await self.post_json(
            "/api/threads/{}/messages".format(thread["id"]),
            {"body": "This turn should exceed the thread budget."},
            developer["connectorToken"],
        )
        summary_response, summarized = await self.post_json(
            "/api/threads/{}/summary".format(thread["id"]),
            {
                "status": "needs_owner_decision",
                "proposal": "Apply the fix after owner approves external sync.",
                "objections": ["External sync is an owner decision."],
                "recommendedNextTask": {"kind": "sync", "instruction": "Publish the thread summary."},
            },
            reviewer["connectorToken"],
        )
        snapshot_response = await self.client.get(
            "/api/rooms/{}".format(room["id"]),
            headers={"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        snapshot = await snapshot_response.json()
        message_kinds = [message["kind"] for message in snapshot["messages"]]

        self.assertEqual(denied_guest_response.status, 403)
        self.assertEqual(denied_guest["error"], "owner or connector token required")
        self.assertEqual(create_response.status, 201)
        self.assertEqual(thread["status"], "open")
        self.assertEqual(thread["source"]["sourceFindingId"], "finding_1")
        self.assertEqual(denied_observer_response.status, 403)
        self.assertEqual(denied_observer["error"], "thread participant or owner required")
        self.assertEqual(reviewer_message_response.status, 201)
        self.assertEqual(reviewer_thread["turnCount"], 1)
        self.assertEqual(developer_message_response.status, 201)
        self.assertEqual(developer_thread["turnCount"], 2)
        self.assertEqual(developer_thread["status"], "needs_summary")
        self.assertEqual(extra_message_response.status, 400)
        self.assertEqual(extra_message["error"], "thread is not open")
        self.assertEqual(summary_response.status, 201)
        self.assertEqual(summarized["status"], "needs_owner_decision")
        self.assertEqual(summarized["summary"]["createdBy"], "Reviewer Agent")
        self.assertEqual(snapshot_response.status, 200)
        self.assertEqual(snapshot["status"], "needs_owner_decision")
        self.assertEqual(snapshot["statusSummary"]["openThreadCount"], 0)
        self.assertEqual(len(snapshot["threads"]), 1)
        self.assertEqual(len(snapshot["threads"][0]["messages"]), 2)
        self.assertEqual(snapshot["tasks"], [])
        self.assertIn("thread_created", message_kinds)
        self.assertIn("thread_message", message_kinds)
        self.assertIn("thread_summary", message_kinds)

    async def test_mcp_complete_task_creates_verification_after_handoff_fix(self):
        _, room = await self.post_json("/api/rooms", {"title": "MCP verify follow-up"})
        _, reviewer = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"role": "reviewer", "name": "Reviewer Agent", "adapterType": "mcp-remote"},
            room["ownerToken"],
        )
        _, developer = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"role": "developer", "name": "Developer Agent", "adapterType": "mcp-remote"},
            room["ownerToken"],
        )
        _, finding_result = await self.post_json(
            "/api/mcp/tools/create_finding",
            {
                "roomId": room["id"],
                "severity": "P1",
                "claim": "MCP follow-up finding",
                "evidence": "Developer completion should create a verify task.",
                "suggestedFix": "Complete the handoff fix through MCP.",
            },
            reviewer["connectorToken"],
        )
        denied_handoff_response, denied_handoff = await self.post_json(
            "/api/mcp/tools/propose_handoff",
            {
                "findingId": finding_result["finding"]["id"],
                "reason": "Developer should not propose reviewer handoffs.",
            },
            developer["connectorToken"],
        )
        handoff_response, handoff_result = await self.post_json(
            "/api/mcp/tools/propose_handoff",
            {
                "findingId": finding_result["finding"]["id"],
                "reason": "Needs developer fix.",
                "suggestedTask": "Patch and report through MCP.",
                "target": {"mode": "role", "role": "developer", "capability": "finding:respond"},
            },
            reviewer["connectorToken"],
        )
        handoff = handoff_result["handoff"]
        _, accepted = await self.post_json(
            "/api/handoffs/{}/accept".format(handoff["id"]),
            {},
            room["ownerToken"],
        )
        fix_task = accepted["task"]
        start_response, started = await self.post_json(
            "/api/mcp/tools/start_run",
            {"taskId": fix_task["id"], "promptSummary": "MCP developer fix", "sandbox": "workspace-write"},
            developer["connectorToken"],
        )
        complete_response, completed = await self.post_json(
            "/api/mcp/tools/complete_task",
            {
                "taskId": fix_task["id"],
                "finalMessage": "MCP developer fix completed.",
                "verificationInstruction": "Verify the MCP-completed fix.",
            },
            developer["connectorToken"],
        )
        snapshot_response = await self.client.get(
            "/api/rooms/{}".format(room["id"]),
            headers={"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        snapshot = await snapshot_response.json()
        verify_tasks = [task for task in snapshot["tasks"] if task["kind"] == "verify"]

        self.assertEqual(fix_task["assignedConnectorId"], developer["id"])
        self.assertEqual(denied_handoff_response.status, 403)
        self.assertEqual(denied_handoff["error"], "reviewer connector required")
        self.assertEqual(handoff_response.status, 201)
        self.assertEqual(handoff["status"], "proposed")
        self.assertEqual(handoff["sourceFindingId"], finding_result["finding"]["id"])
        self.assertEqual(start_response.status, 201)
        self.assertEqual(started["agentRun"]["taskId"], fix_task["id"])
        self.assertEqual(complete_response.status, 201)
        self.assertEqual(completed["task"]["status"], "completed")
        self.assertEqual(completed["verificationTask"]["kind"], "verify")
        self.assertEqual(completed["verificationTask"]["assignedConnectorId"], reviewer["id"])
        self.assertEqual(snapshot_response.status, 200)
        self.assertEqual(len(verify_tasks), 1)
        self.assertEqual(verify_tasks[0]["source"]["fixTaskId"], fix_task["id"])
        self.assertEqual(verify_tasks[0]["source"]["handoffId"], handoff["id"])

    async def test_mcp_request_owner_confirmation_creates_decision_record(self):
        _, room = await self.post_json("/api/rooms", {"title": "MCP owner decision"})
        _, reviewer = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"role": "reviewer", "name": "Reviewer Agent", "adapterType": "mcp-remote"},
            room["ownerToken"],
        )
        owner_denied_response, owner_denied = await self.post_json(
            "/api/mcp/tools/request_owner_confirmation",
            {
                "roomId": room["id"],
                "question": "Should this external sync be published?",
                "proposal": "Publish the approved review result.",
            },
            room["ownerToken"],
        )
        invalid_source_response, invalid_source = await self.post_json(
            "/api/mcp/tools/request_owner_confirmation",
            {
                "roomId": room["id"],
                "question": "Should this malformed source be accepted?",
                "source": "finding_smoke",
            },
            reviewer["connectorToken"],
        )
        request_response, requested = await self.post_json(
            "/api/mcp/tools/request_owner_confirmation",
            {
                "roomId": room["id"],
                "question": "Should this external sync be published?",
                "proposal": "Publish the approved review result.",
                "risk": "This would leave Review Room and affect an external MR.",
                "syncTarget": "GitHub MR comment",
                "source": {"findingId": "finding_smoke"},
            },
            reviewer["connectorToken"],
        )
        decision = requested["decision"]
        snapshot_response = await self.client.get(
            "/api/rooms/{}".format(room["id"]),
            headers={"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        snapshot = await snapshot_response.json()
        connector_decide_response, connector_decide = await self.post_json(
            "/api/decisions/{}/accept".format(decision["id"]),
            {},
            reviewer["connectorToken"],
        )
        accept_response, accepted = await self.post_json(
            "/api/decisions/{}/accept".format(decision["id"]),
            {"note": "Approved after checking the requested target."},
            room["ownerToken"],
        )
        repeat_response, repeat = await self.post_json(
            "/api/decisions/{}/reject".format(decision["id"]),
            {},
            room["ownerToken"],
        )
        final_snapshot_response = await self.client.get(
            "/api/rooms/{}".format(room["id"]),
            headers={"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        final_snapshot = await final_snapshot_response.json()
        message_kinds = [message["kind"] for message in final_snapshot["messages"]]

        self.assertEqual(owner_denied_response.status, 403)
        self.assertEqual(owner_denied["error"], "connector token required")
        self.assertEqual(invalid_source_response.status, 400)
        self.assertEqual(invalid_source["error"], "source must be an object")
        self.assertEqual(request_response.status, 201)
        self.assertEqual(decision["status"], "requested")
        self.assertEqual(decision["requestedByConnectorId"], reviewer["id"])
        self.assertEqual(decision["syncTarget"], "GitHub MR comment")
        self.assertEqual(snapshot_response.status, 200)
        self.assertEqual(snapshot["status"], "needs_owner_decision")
        self.assertEqual(snapshot["decisions"][0]["id"], decision["id"])
        self.assertEqual(snapshot["statusSummary"]["pendingDecisionCount"], 1)
        self.assertEqual(connector_decide_response.status, 403)
        self.assertEqual(connector_decide["error"], "owner token required")
        self.assertEqual(accept_response.status, 201)
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(accepted["decidedBy"], "review room owner")
        self.assertEqual(repeat_response.status, 400)
        self.assertEqual(repeat["error"], "decision is not pending")
        self.assertEqual(final_snapshot_response.status, 200)
        self.assertEqual(final_snapshot["statusSummary"]["pendingDecisionCount"], 0)
        self.assertIn("owner_confirmation_requested", message_kinds)
        self.assertIn("owner_confirmation_decided", message_kinds)

    async def test_rest_finding_mutations_require_matching_roles(self):
        _, room = await self.post_json("/api/rooms", {"title": "开放话题", "objective": "验证 REST 权限边界"})
        _, reviewer = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"type": "agent", "role": "reviewer", "name": "Reviewer Agent"},
            room["ownerToken"],
        )
        _, developer = await self.post_json(
            "/api/rooms/{}/connectors".format(room["id"]),
            {"type": "agent", "role": "developer", "name": "Developer Agent"},
            room["ownerToken"],
        )
        _, invite = await self.post_json(
            "/api/rooms/{}/invites".format(room["id"]),
            {"type": "guest"},
            room["ownerToken"],
        )
        _, joined = await self.post_json(
            "/api/rooms/{}/join".format(room["id"]),
            {"inviteCode": invite["code"], "nickname": "外部用户"},
        )

        denied_finding, denied_finding_body = await self.post_json(
            "/api/rooms/{}/findings".format(room["id"]),
            {"claim": "访客伪造 finding"},
            joined["guestToken"],
        )
        finding_response, finding = await self.post_json(
            "/api/rooms/{}/findings".format(room["id"]),
            {"claim": "Reviewer 发现风险", "createdBy": "spoofed"},
            reviewer["connectorToken"],
        )
        denied_response, denied_response_body = await self.post_json(
            "/api/findings/{}/developer-response".format(finding["id"]),
            {"body": "Reviewer 不能冒充 Developer"},
            reviewer["connectorToken"],
        )
        developer_response, _ = await self.post_json(
            "/api/findings/{}/developer-response".format(finding["id"]),
            {"senderName": "spoofed", "body": "Developer 已给出修复计划。"},
            developer["connectorToken"],
        )
        denied_confirm, denied_confirm_body = await self.post_json(
            "/api/findings/{}/confirm".format(finding["id"]),
            {"decision": "accepted"},
            joined["guestToken"],
        )
        confirm_response, confirmed = await self.post_json(
            "/api/findings/{}/confirm".format(finding["id"]),
            {"decision": "accepted", "senderName": "spoofed"},
            room["ownerToken"],
        )
        loaded = self.store.get_room(room["id"])

        self.assertEqual(denied_finding.status, 403)
        self.assertEqual(denied_finding_body["error"], "reviewer connector required")
        self.assertEqual(finding_response.status, 201)
        self.assertEqual(finding["createdBy"], "Reviewer Agent")
        self.assertEqual(denied_response.status, 403)
        self.assertEqual(denied_response_body["error"], "developer connector required")
        self.assertEqual(developer_response.status, 201)
        self.assertEqual(denied_confirm.status, 403)
        self.assertEqual(denied_confirm_body["error"], "owner token required")
        self.assertEqual(confirm_response.status, 201)
        self.assertEqual(confirmed["status"], "accepted")
        messages_by_kind = {message["kind"]: message for message in loaded["messages"]}
        self.assertEqual(messages_by_kind["review_finding"]["senderName"], "Reviewer Agent")
        self.assertEqual(messages_by_kind["developer_response"]["senderName"], "Developer Agent")
        self.assertEqual(messages_by_kind["human_confirmation"]["senderName"], "review room owner")

    async def test_owner_message_receives_hosted_agent_reply_only_in_experience_mode(self):
        _, room = await self.post_json("/api/rooms", {"title": "开放话题", "objective": "验证 owner 和 Agent 对话"})
        await self.post_json(
            "/api/rooms/{}/invites".format(room["id"]),
            {"type": "agent", "role": "reviewer", "name": "Reviewer Agent"},
            room["ownerToken"],
        )

        owner_ws = await self.client.ws_connect("/ws/rooms/{}?token={}".format(room["id"], room["ownerToken"]))
        await self._drain_initial_events(owner_ws)

        with patch.dict(os.environ, {"REVIEW_ROOM_ENABLE_HOSTED_AGENT": "true"}):
            await owner_ws.send_json({"type": "message.create", "body": "我作为 owner 怎么和你对话？"})
            owner_message = await self._read_event(owner_ws, "message.created")
            agent_reply = await self._read_event(owner_ws, "message.created")
            snapshot = await self._read_event(owner_ws, "room.snapshot")

        self.assertEqual(owner_message["message"]["senderName"], "review room owner")
        self.assertEqual(agent_reply["message"]["senderName"], "Reviewer Agent")
        self.assertEqual(agent_reply["message"]["kind"], "connector_message")
        self.assertTrue(agent_reply["message"]["payload"]["hostedAgent"])
        self.assertIn("怎么和你对话", agent_reply["message"]["body"])
        self.assertEqual(snapshot["room"]["connectors"][0]["status"], "online")

        await owner_ws.close()

    async def _drain_initial_events(self, *websockets):
        for ws in websockets:
            await self._read_event(ws, "room.snapshot")

    async def _read_event(self, ws, expected_type):
        for _ in range(20):
            message = await ws.receive(timeout=5)
            self.assertEqual(message.type, WSMsgType.TEXT)
            data = json.loads(message.data)
            if data.get("type") == expected_type:
                return data
        self.fail("did not receive {}".format(expected_type))

    async def _read_sse_event(self, response, expected_type, predicate=None):
        predicate = predicate or (lambda data: True)
        event_type = ""
        event_id = ""
        data_lines = []
        for _ in range(200):
            line = await asyncio.wait_for(response.content.readline(), timeout=5)
            if not line:
                self.fail("SSE stream closed before {}".format(expected_type))
            text = line.decode("utf-8").rstrip("\r\n")
            if text.startswith(":"):
                continue
            if not text:
                if not event_type and not data_lines:
                    continue
                data = json.loads("\n".join(data_lines)) if data_lines else {}
                if event_type == expected_type and predicate(data):
                    return {"event": event_type, "id": event_id, "data": data}
                event_type = ""
                event_id = ""
                data_lines = []
                continue
            if text.startswith("event:"):
                event_type = text.split(":", 1)[1].strip()
            elif text.startswith("id:"):
                event_id = text.split(":", 1)[1].strip()
            elif text.startswith("data:"):
                data_lines.append(text.split(":", 1)[1].strip())
        self.fail("did not receive SSE {}".format(expected_type))

    async def _read_finding_status(self, ws, expected_status):
        for _ in range(20):
            event = await self._read_event(ws, "finding.updated")
            if event["finding"]["status"] == expected_status:
                return event
        self.fail("did not receive finding status {}".format(expected_status))

    async def _read_assigned_task_kind(self, ws, expected_kind):
        for _ in range(20):
            event = await self._read_event(ws, "task.assigned")
            if event["task"]["kind"] == expected_kind:
                return event
        self.fail("did not receive assigned {} task".format(expected_kind))


class CodexConnectorClientTest(unittest.TestCase):
    def test_home_page_exposes_realtime_room_experience(self):
        from review_room_service import index_html

        html = index_html()

        self.assertIn("/ws/rooms/", html)
        self.assertIn("new WebSocket", html)
        self.assertIn("review room owner", html)
        self.assertIn("Reviewer Agent", html)
        self.assertIn("Developer Agent", html)
        self.assertIn("创建话题房间", html)
        self.assertIn("房间角色", html)
        self.assertIn("任务与运行", html)
        self.assertIn("分配任务", html)
        self.assertIn("Threads", html)
        self.assertIn("Handoffs", html)
        self.assertIn("轮换 token", html)
        self.assertIn("function createTask()", html)
        self.assertIn("function renderThreads()", html)
        self.assertIn("function decideHandoff", html)
        self.assertIn("function rotateConnectorToken", html)
        self.assertIn("agentAdapter", html)
        self.assertIn("MCP Remote", html)
        self.assertIn("/tasks", html)
        self.assertIn("/api/handoffs/", html)
        self.assertIn("/rotate-token", html)

    def test_parse_room_url_converts_http_to_websocket_path(self):
        ws_url = parse_room_url("http://127.0.0.1:8707", "room_123", "token_abc")

        self.assertEqual(ws_url, "ws://127.0.0.1:8707/ws/rooms/room_123?token=token_abc")

    def test_mock_reviewer_and_developer_responses_match_room_events(self):
        reviewer_event = build_agent_response("reviewer", "请评审鉴权风险", mock=True)
        developer_event = build_agent_response("developer", "鉴权可能被绕过", mock=True, finding_id="finding_1")

        self.assertEqual(reviewer_event["type"], "finding.create")
        self.assertEqual(developer_event["type"], "finding.respond")
        self.assertEqual(developer_event["findingId"], "finding_1")

    def test_connector_matches_direct_task_assignment(self):
        args = type("Args", (), {"role": "reviewer", "identity": {"connectorId": "connector_1", "capabilities": ["finding:create"]}})()
        event = {
            "type": "task.assigned",
            "task": {
                "assignedConnectorId": "connector_1",
                "target": {"mode": "connector", "connectorId": "connector_1"},
            },
        }

        self.assertTrue(is_assigned_task_event(args, event))
        self.assertEqual(summarize_connector_response({"type": "finding.create", "claim": "风险"}), "风险")


if __name__ == "__main__":
    unittest.main()
