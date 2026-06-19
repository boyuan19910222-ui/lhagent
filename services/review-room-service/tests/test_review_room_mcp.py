import json
import asyncio
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing

from aiohttp.test_utils import TestClient, TestServer


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from review_room_service import ReviewRoomStore, build_app  # noqa: E402


class ReviewRoomMcpStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ReviewRoomStore(os.path.join(self.tmp.name, "test.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_message_events_include_explicit_agent_mentions(self):
        room = self.store.create_room(
            {
                "title": "MR",
                "participants": [
                    {"type": "human", "name": "owner", "role": "owner"},
                    {"type": "agent", "name": "Reviewer Agent", "role": "reviewer"},
                ],
            }
        )
        initial_events = self.store.list_room_events(room["id"])
        self.assertGreater(len(initial_events), 0, "Room creation should generate at least one event")
        cursor = initial_events[-1]["cursor"]

        self.store.add_message(
            room["id"],
            {
                "senderType": "human",
                "senderName": "owner",
                "kind": "owner_topic",
                "body": "@Reviewer Agent 请评审鉴权风险，其他内容只作为上下文。",
            },
        )

        events = self.store.list_room_events(room["id"], after_cursor=cursor)
        self.assertEqual([event["type"] for event in events], ["message.created", "mention.requires_reply"])
        self.assertEqual(events[1]["payload"]["targetAgentName"], "Reviewer Agent")
        self.assertEqual(events[1]["payload"]["message"]["body"], "@Reviewer Agent 请评审鉴权风险，其他内容只作为上下文。")

    def test_message_events_include_role_alias_mentions(self):
        room = self.store.create_room({"title": "MR"})
        initial_events = self.store.list_room_events(room["id"])
        self.assertGreater(len(initial_events), 0, "Room creation should generate at least one event")
        cursor = initial_events[-1]["cursor"]

        self.store.add_message(
            room["id"],
            {
                "senderType": "human",
                "senderName": "owner",
                "kind": "owner_topic",
                "body": "@developer 请处理接入状态展示问题。",
            },
        )

        events = self.store.list_room_events(room["id"], after_cursor=cursor)
        self.assertEqual([event["type"] for event in events], ["message.created", "mention.requires_reply"])
        self.assertEqual(events[1]["payload"]["targetAgentName"], "Developer Agent")

    def test_agent_self_mentions_do_not_require_reply(self):
        room = self.store.create_room({"title": "MR"})
        initial_events = self.store.list_room_events(room["id"])
        self.assertGreater(len(initial_events), 0, "Room creation should generate at least one event")
        cursor = initial_events[-1]["cursor"]

        self.store.add_message(
            room["id"],
            {
                "senderType": "agent",
                "senderName": "Developer Agent",
                "kind": "mcp_message",
                "body": "Developer Agent 已接入，等待任务。",
            },
        )

        events = self.store.list_room_events(room["id"], after_cursor=cursor)
        self.assertEqual([event["type"] for event in events], ["message.created"])

    def test_supervision_messages_enter_every_agent_inbox_without_starting_runs(self):
        room = self.store.create_room({"title": "MR"})

        self.store.add_message(
            room["id"],
            {
                "senderType": "human",
                "senderName": "owner",
                "kind": "owner_topic",
                "body": "请所有 Agent 注意这条监督说明，但不要开始执行。",
            },
        )
        self.store.add_message(
            room["id"],
            {
                "senderType": "human",
                "senderName": "owner",
                "kind": "owner_topic",
                "body": "@Developer Agent 请优先看这个上下文，执行仍然等 task。",
            },
        )
        loaded = self.store.get_room(room["id"])

        reviewer_items = self.store.list_inbox(room["id"], "Reviewer Agent")
        developer_items = self.store.list_inbox(room["id"], "Developer Agent")
        developer_mention = developer_items[-1]
        reviewer_second = reviewer_items[-1]

        self.assertEqual(len(reviewer_items), 2)
        self.assertEqual(len(developer_items), 2)
        self.assertEqual(developer_mention["priority"], "high")
        self.assertTrue(developer_mention["requiresReply"])
        self.assertEqual(developer_mention["status"], "unread")
        self.assertEqual(reviewer_second["priority"], "normal")
        self.assertFalse(reviewer_second["requiresReply"])
        self.assertEqual(loaded["agentRuns"], [])

    def test_ack_event_updates_agent_inbox_lifecycle(self):
        room = self.store.create_room({"title": "MR"})
        self.store.add_message(
            room["id"],
            {
                "senderType": "human",
                "senderName": "owner",
                "kind": "owner_topic",
                "body": "这条消息需要进入 Agent Inbox。",
            },
        )
        item = self.store.list_inbox(room["id"], "Reviewer Agent")[0]

        acked = self.store.ack_event(
            room["id"],
            {
                "agentName": "Reviewer Agent",
                "inboxItemId": item["id"],
                "status": "handled",
            },
        )

        self.assertEqual(acked["status"], "handled")
        self.assertEqual(
            self.store.list_inbox(room["id"], "Reviewer Agent", include_handled=True)[0]["status"],
            "handled",
        )

    def test_tasks_can_be_assigned_claimed_and_completed(self):
        room = self.store.create_room({"title": "MR"})
        task = self.store.create_task(
            room["id"],
            {
                "title": "复核修复计划",
                "body": "确认 Developer Agent 是否覆盖 finding。",
                "assignedTo": "Reviewer Agent",
                "createdBy": "Agent Board owner",
            },
        )

        claimed = self.store.claim_task(task["id"], {"agentName": "Reviewer Agent"})
        completed = self.store.update_task(
            task["id"],
            {"status": "completed", "result": "修复计划覆盖 finding。", "agentName": "Reviewer Agent"},
        )

        self.assertEqual(task["status"], "assigned")
        self.assertEqual(claimed["status"], "running")
        self.assertEqual(claimed["claimedBy"], "Reviewer Agent")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"], "修复计划覆盖 finding。")
        self.assertEqual([item["id"] for item in self.store.list_tasks(room["id"])], [task["id"]])

    def test_agent_run_decision_and_handoff_are_canonical_board_objects(self):
        room = self.store.create_room({"title": "MR"})
        task = self.store.create_task(
            room["id"],
            {"title": "修复 finding", "body": "补 owner token 校验。", "assignedTo": "Developer Agent"},
        )
        run = self.store.start_run(task["id"], {"agentName": "Developer Agent", "promptSummary": "Fix auth"})
        completed = self.store.complete_task(
            task["id"],
            {"agentName": "Developer Agent", "finalMessage": "已修复并通过测试。"},
        )
        finding = self.store.add_finding(
            room["id"],
            {
                "severity": "P1",
                "claim": "鉴权可能被绕过",
                "evidence": "缺少 owner token 校验",
                "suggestedFix": "补校验",
                "createdBy": "Reviewer Agent",
            },
        )
        handoff = self.store.propose_handoff(
            finding["id"],
            {
                "fromAgent": "Reviewer Agent",
                "targetAgent": "Developer Agent",
                "reason": "需要代码修复。",
                "suggestedTask": "修复鉴权并回传测试。",
            },
        )
        decision = self.store.request_owner_confirmation(
            room["id"],
            {
                "requester": "Developer Agent",
                "action": "sync MR comment",
                "reason": "修复已完成，需要 owner 确认外部同步。",
                "targetType": "task",
                "targetId": task["id"],
            },
        )
        loaded = self.store.get_room(room["id"])

        self.assertEqual(run["status"], "running")
        self.assertEqual(completed["task"]["status"], "completed")
        self.assertEqual(completed["run"]["status"], "completed")
        self.assertEqual(handoff["status"], "proposed")
        self.assertEqual(decision["status"], "pending")
        self.assertEqual(loaded["agentRuns"][0]["finalMessage"], "已修复并通过测试。")
        self.assertEqual(loaded["handoffs"][0]["sourceFindingId"], finding["id"])
        self.assertEqual(loaded["decisions"][0]["targetId"], task["id"])

    def test_existing_experimental_task_schema_is_migrated(self):
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        db_path = os.path.join(self.tmp.name, "test.sqlite3")
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE tasks (
                  id TEXT PRIMARY KEY,
                  room_id TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  status TEXT NOT NULL,
                  instruction TEXT NOT NULL,
                  target_json TEXT NOT NULL,
                  source_json TEXT NOT NULL,
                  created_by TEXT NOT NULL,
                  assigned_connector_id TEXT NOT NULL,
                  lease_expires_at INTEGER,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()

        self.store = ReviewRoomStore(db_path)
        room = self.store.create_room({"title": "MR"})
        task = self.store.create_task(
            room["id"],
            {"title": "修复 finding", "body": "补 owner token 校验。", "assignedTo": "Developer Agent"},
        )

        self.assertEqual(task["title"], "修复 finding")
        self.assertEqual(self.store.list_tasks(room["id"], assigned_to="Developer Agent")[0]["id"], task["id"])

    def test_mcp_invite_joins_room_as_agent_session(self):
        room = self.store.create_room({"title": "MR"})
        invite = self.store.create_mcp_invite(
            room["id"],
            {"agentName": "Remote Reviewer", "agentRole": "reviewer", "ttlMs": 60_000},
        )

        session = self.store.join_mcp_room(invite["token"], {"roomId": room["id"]})
        loaded = self.store.get_room(room["id"])

        self.assertEqual(session["roomId"], room["id"])
        self.assertEqual(session["name"], "Remote Reviewer")
        self.assertEqual(session["role"], "reviewer")
        self.assertEqual(session["sessionToken"], invite["token"])
        self.assertEqual(loaded["connectors"][0]["kind"], "mcp-agent")

    def test_expired_mcp_invite_is_rejected(self):
        room = self.store.create_room({"title": "MR"})
        invite = self.store.create_mcp_invite(
            room["id"],
            {"agentName": "Remote Reviewer", "agentRole": "reviewer", "ttlMs": -1},
        )

        with self.assertRaises(PermissionError):
            self.store.join_mcp_room(invite["token"], {"roomId": room["id"]})


class ReviewRoomMcpAioHttpTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ReviewRoomStore(os.path.join(self.tmp.name, "test.sqlite3"))
        self.server = TestServer(build_app(self.store))
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def rpc(self, token, method, params=None, rpc_id=1):
        response = await self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params or {}},
            headers={"Authorization": "Bearer {}".format(token)} if token else {},
        )
        data = await response.json()
        return response, data

    async def call_tool(self, token, name, arguments=None, rpc_id=1):
        return await self.rpc(
            token,
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            rpc_id=rpc_id,
        )

    async def test_mcp_lists_tools_resources_and_prompt(self):
        room = self.store.create_room({"title": "MR"})
        invite = self.store.create_mcp_invite(room["id"], {"agentName": "Reviewer Agent", "agentRole": "reviewer"})

        _, tools = await self.rpc(invite["token"], "tools/list", rpc_id=1)
        _, resources = await self.rpc(invite["token"], "resources/list", rpc_id=2)
        _, prompts = await self.rpc(invite["token"], "prompts/list", rpc_id=3)

        tool_names = [tool["name"] for tool in tools["result"]["tools"]]
        resource_uris = [resource["uri"] for resource in resources["result"]["resources"]]
        prompt_names = [prompt["name"] for prompt in prompts["result"]["prompts"]]
        self.assertIn("join_room", tool_names)
        self.assertIn("list_inbox", tool_names)
        self.assertIn("ack_event", tool_names)
        self.assertIn("create_task", tool_names)
        self.assertIn("start_run", tool_names)
        self.assertIn("complete_task", tool_names)
        self.assertIn("request_owner_confirmation", tool_names)
        self.assertIn("review_room.list_inbox", tool_names)
        self.assertIn("post_finding", tool_names)
        self.assertIn("review-room://current/snapshot", resource_uris)
        self.assertIn("review-room-onboarding", prompt_names)

    async def test_mcp_listing_requires_bearer_token(self):
        _, tools = await self.rpc(None, "tools/list", rpc_id=1)

        self.assertEqual(tools["error"]["code"], -32001)
        self.assertIn("missing bearer token", tools["error"]["message"])

    async def test_mcp_agent_can_join_read_context_reply_and_create_finding(self):
        room = self.store.create_room({"title": "MR", "context": {"repository": "lighthouse/review-room"}})
        invite = self.store.create_mcp_invite(room["id"], {"agentName": "Reviewer Agent", "agentRole": "reviewer"})
        self.store.add_message(
            room["id"],
            {
                "senderType": "human",
                "senderName": "Agent Board owner",
                "kind": "owner_topic",
                "body": "@Reviewer Agent 请评审这个 MR。",
            },
        )

        join_response, join = await self.call_tool(invite["token"], "join_room", {"roomId": room["id"]}, rpc_id=1)
        snapshot_response, snapshot = await self.call_tool(invite["token"], "get_room_snapshot", {}, rpc_id=2)
        reply_response, reply = await self.call_tool(
            invite["token"],
            "post_message",
            {"body": "Reviewer Agent 已接入，开始评审。"},
            rpc_id=3,
        )
        finding_response, finding = await self.call_tool(
            invite["token"],
            "post_finding",
            {
                "severity": "P1",
                "claim": "鉴权可能被绕过",
                "evidence": "新增路径没有 owner token 校验",
                "suggestedFix": "补充 token 校验和测试",
            },
            rpc_id=4,
        )
        _, events = await self.call_tool(invite["token"], "wait_room_events", {"afterCursor": 0}, rpc_id=5)

        self.assertEqual(join_response.status, 200)
        self.assertEqual(snapshot_response.status, 200)
        self.assertEqual(reply_response.status, 200)
        self.assertEqual(finding_response.status, 200)
        self.assertEqual(join["result"]["structuredContent"]["name"], "Reviewer Agent")
        self.assertEqual(snapshot["result"]["structuredContent"]["context"]["repository"], "lighthouse/review-room")
        self.assertEqual(reply["result"]["structuredContent"]["senderName"], "Reviewer Agent")
        self.assertEqual(finding["result"]["structuredContent"]["createdBy"], "Reviewer Agent")
        self.assertIn("mention.requires_reply", [event["type"] for event in events["result"]["structuredContent"]["events"]])

    async def test_mcp_agent_consumes_inbox_and_ack_without_starting_run(self):
        room = self.store.create_room({"title": "MR"})
        invite = self.store.create_mcp_invite(room["id"], {"agentName": "Reviewer Agent", "agentRole": "reviewer"})
        self.store.add_message(
            room["id"],
            {
                "senderType": "human",
                "senderName": "Agent Board owner",
                "kind": "owner_topic",
                "body": "普通监督消息，进入 inbox 但不执行。",
            },
        )
        await self.call_tool(invite["token"], "join_room", {"roomId": room["id"]}, rpc_id=1)

        _, listed = await self.call_tool(invite["token"], "list_inbox", {}, rpc_id=2)
        inbox_item = listed["result"]["structuredContent"]["items"][0]
        _, acked = await self.call_tool(
            invite["token"],
            "ack_event",
            {"inboxItemId": inbox_item["id"], "status": "read"},
            rpc_id=3,
        )
        snapshot = self.store.get_room(room["id"])

        self.assertEqual(inbox_item["type"], "message")
        self.assertEqual(acked["result"]["structuredContent"]["status"], "read")
        self.assertEqual(snapshot["agentRuns"], [])

    async def test_mcp_task_lifecycle_and_resources(self):
        room = self.store.create_room({"title": "MR"})
        invite = self.store.create_mcp_invite(room["id"], {"agentName": "Developer Agent", "agentRole": "developer"})
        task_response = await self.client.post(
            "/api/rooms/{}/tasks".format(room["id"]),
            json={"title": "修复 finding", "body": "补 owner token 校验。", "assignedTo": "Developer Agent"},
            headers={"Authorization": "Bearer {}".format(room["ownerToken"])},
        )
        task = await task_response.json()
        await self.call_tool(invite["token"], "join_room", {"roomId": room["id"]}, rpc_id=1)

        _, listed = await self.call_tool(invite["token"], "list_tasks", {}, rpc_id=2)
        _, claimed = await self.call_tool(invite["token"], "claim_task", {"taskId": task["id"]}, rpc_id=3)
        _, started = await self.call_tool(invite["token"], "start_run", {"taskId": task["id"]}, rpc_id=4)
        _, completed = await self.call_tool(
            invite["token"],
            "complete_task",
            {"taskId": task["id"], "finalMessage": "已补校验并通过测试。"},
            rpc_id=5,
        )
        resource_response = await self.client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 6,
                "method": "resources/read",
                "params": {"uri": "review-room://current/tasks"},
            },
            headers={"Authorization": "Bearer {}".format(invite["token"])},
        )
        resource = await resource_response.json()

        self.assertEqual(task_response.status, 201)
        self.assertEqual(listed["result"]["structuredContent"]["tasks"][0]["id"], task["id"])
        self.assertEqual(claimed["result"]["structuredContent"]["status"], "running")
        self.assertEqual(started["result"]["structuredContent"]["status"], "running")
        self.assertEqual(completed["result"]["structuredContent"]["task"]["status"], "completed")
        self.assertEqual(completed["result"]["structuredContent"]["run"]["status"], "completed")
        self.assertIn("已补校验", resource["result"]["contents"][0]["text"])

    async def test_mcp_legacy_update_task_alias_still_completes_run(self):
        room = self.store.create_room({"title": "MR"})
        invite = self.store.create_mcp_invite(room["id"], {"agentName": "Developer Agent", "agentRole": "developer"})
        task = self.store.create_task(
            room["id"],
            {"title": "修复 finding", "body": "补 owner token 校验。", "assignedTo": "Developer Agent"},
        )
        await self.call_tool(invite["token"], "join_room", {"roomId": room["id"]}, rpc_id=1)
        await self.call_tool(invite["token"], "review_room.start_run", {"taskId": task["id"]}, rpc_id=2)

        _, completed = await self.call_tool(
            invite["token"],
            "update_task",
            {"taskId": task["id"], "status": "completed", "result": "兼容路径完成。"},
            rpc_id=3,
        )

        self.assertEqual(completed["result"]["structuredContent"]["task"]["status"], "completed")
        self.assertEqual(completed["result"]["structuredContent"]["run"]["status"], "completed")

    async def test_task_tools_validate_required_arguments(self):
        room = self.store.create_room({"title": "MR"})
        invite = self.store.create_mcp_invite(room["id"], {"agentName": "Developer Agent", "agentRole": "developer"})
        task = self.store.create_task(
            room["id"],
            {"title": "修复 finding", "body": "补 owner token 校验。", "assignedTo": "Developer Agent"},
        )
        await self.call_tool(invite["token"], "join_room", {"roomId": room["id"]}, rpc_id=1)

        _, missing_claim_id = await self.call_tool(invite["token"], "claim_task", {}, rpc_id=2)
        _, missing_update_status = await self.call_tool(
            invite["token"],
            "update_task",
            {"taskId": task["id"]},
            rpc_id=3,
        )
        _, missing_confirmation_action = await self.call_tool(
            invite["token"],
            "request_owner_confirmation",
            {},
            rpc_id=4,
        )

        self.assertEqual(missing_claim_id["error"]["code"], -32602)
        self.assertIn("taskId is required", missing_claim_id["error"]["message"])
        self.assertEqual(missing_update_status["error"]["code"], -32602)
        self.assertIn("status is required", missing_update_status["error"]["message"])
        self.assertEqual(missing_confirmation_action["error"]["code"], -32602)
        self.assertIn("action is required", missing_confirmation_action["error"]["message"])

    async def test_mcp_join_broadcasts_room_snapshot_to_web_owner(self):
        room = self.store.create_room({"title": "MR"})
        invite = self.store.create_mcp_invite(room["id"], {"agentName": "Developer Agent", "agentRole": "developer"})
        websocket = await self.client.ws_connect(
            "/ws/rooms/{}?token={}".format(room["id"], room["ownerToken"])
        )
        await websocket.receive_json()
        await websocket.receive_json()

        await self.call_tool(invite["token"], "join_room", {"roomId": room["id"]}, rpc_id=1)

        event = await asyncio.wait_for(websocket.receive_json(), timeout=1)
        self.assertEqual(event["type"], "room.snapshot")
        self.assertEqual(event["room"]["connectors"][0]["name"], "Developer Agent")
        await websocket.close()


if __name__ == "__main__":
    unittest.main()
