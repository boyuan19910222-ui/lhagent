import json
import os
import sys
import unittest
from argparse import Namespace
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from codex_connector import (  # noqa: E402
    await_response_with_keepalive,
    build_codex_exec_args,
    build_reviewer_finding_event,
    format_room_history,
    maybe_build_response,
    parse_codex_last_message,
    parse_room_api_url,
)


class CodexConnectorRunnerTest(unittest.TestCase):
    def test_build_codex_exec_args_sets_workspace_and_role_sandbox(self):
        reviewer_args = build_codex_exec_args(
            "codex",
            "review prompt",
            role="reviewer",
            workspace="/tmp/reviewer-checkout",
            model="gpt-5-codex",
        )
        developer_args = build_codex_exec_args(
            "codex",
            "fix prompt",
            role="developer",
            workspace="/tmp/developer-checkout",
        )

        self.assertEqual(
            reviewer_args,
            [
                "codex",
                "exec",
                "--json",
                "--cd",
                "/tmp/reviewer-checkout",
                "--sandbox",
                "read-only",
                "-m",
                "gpt-5-codex",
                "review prompt",
            ],
        )
        self.assertEqual(
            developer_args,
            [
                "codex",
                "exec",
                "--json",
                "--cd",
                "/tmp/developer-checkout",
                "--sandbox",
                "workspace-write",
                "fix prompt",
            ],
        )

    def test_build_codex_exec_args_can_force_fast_local_worker_mode(self):
        args = build_codex_exec_args(
            "codex",
            "chat prompt",
            role="developer",
            model="gpt-5.3-codex-spark",
            reasoning_effort="low",
            ignore_user_config=True,
            ignore_rules=True,
            ephemeral=True,
            skip_git_repo_check=True,
        )

        self.assertEqual(
            args,
            [
                "codex",
                "exec",
                "--json",
                "--ignore-user-config",
                "--ignore-rules",
                "--ephemeral",
                "--skip-git-repo-check",
                "--sandbox",
                "workspace-write",
                "-m",
                "gpt-5.3-codex-spark",
                "-c",
                'model_reasoning_effort="low"',
                "chat prompt",
            ],
        )

    def test_parse_room_api_url_uses_http_room_snapshot_endpoint(self):
        self.assertEqual(
            parse_room_api_url("http://review-room.example", "room_123"),
            "http://review-room.example/api/rooms/room_123",
        )

    def test_format_room_history_keeps_recent_compact_messages(self):
        history = [
            {"sender": "Agent Board owner", "kind": "owner_topic", "body": "第一条"},
            {"sender": "Developer Agent", "kind": "connector_message", "body": "第二条"},
            {"sender": "Agent Board owner", "kind": "owner_topic", "body": "第三条"},
        ]

        self.assertEqual(
            format_room_history(history, limit=2),
            "- Developer Agent [connector_message]: 第二条\n- Agent Board owner [owner_topic]: 第三条",
        )

    def test_parse_codex_last_message_extracts_assistant_text_from_jsonl(self):
        stdout = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "thread_1"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": "最终 finding JSON"},
                            ],
                        },
                    }
                ),
                json.dumps({"type": "turn.completed"}),
            ]
        )

        self.assertEqual(parse_codex_last_message(stdout), "最终 finding JSON")

    def test_build_reviewer_finding_event_uses_structured_agent_output(self):
        event = build_reviewer_finding_event(
            json.dumps(
                {
                    "severity": "P0",
                    "filePath": "src/auth/session.ts",
                    "line": 42,
                    "claim": "owner token 未校验",
                    "evidence": "新增入口直接信任 header",
                    "suggestedFix": "补充 owner token 校验并加回归测试",
                },
                ensure_ascii=False,
            )
        )

        self.assertEqual(event["type"], "finding.create")
        self.assertEqual(event["severity"], "P0")
        self.assertEqual(event["filePath"], "src/auth/session.ts")
        self.assertEqual(event["line"], 42)
        self.assertEqual(event["claim"], "owner token 未校验")
        self.assertEqual(event["evidence"], "新增入口直接信任 header")
        self.assertEqual(event["suggestedFix"], "补充 owner token 校验并加回归测试")


class CodexConnectorAsyncResponseTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_reviewer_response_awaits_codex_runner_and_returns_finding(self):
        args = Namespace(
            role="reviewer",
            mock=False,
            codex_command="codex",
            timeout=600,
            workspace="/tmp/reviewer-checkout",
            sandbox="read-only",
            model="",
            repo="repo/name",
            mr_url="https://example.com/repo",
            base_ref="main",
            head_ref="feature",
            task="review this repository",
        )
        event = {
            "type": "message.created",
            "message": {
                "senderName": "Agent Board owner",
                "body": "先看看这个仓库里说的什么",
            },
        }
        output = json.dumps(
            {
                "severity": "P1",
                "filePath": "README.md",
                "line": 1,
                "claim": "仓库说明缺少安全边界",
                "evidence": "README 没有说明 token 处理方式",
                "suggestedFix": "补充 token 边界说明",
            },
            ensure_ascii=False,
        )

        with patch("codex_connector.run_codex_command", return_value=output) as run_codex:
            response = await maybe_build_response(args, event)

        run_codex.assert_called_once()
        self.assertEqual(response["type"], "finding.create")
        self.assertEqual(response["claim"], "仓库说明缺少安全边界")

    async def test_reviewer_chat_mode_returns_room_message(self):
        args = Namespace(
            role="reviewer",
            mock=False,
            response_mode="chat",
            codex_command="codex",
            timeout=600,
            workspace="/tmp/reviewer-checkout",
            sandbox="read-only",
            model="",
            repo="",
            mr_url="",
            base_ref="",
            head_ref="",
            task="open topic room",
            room_history=[
                {"sender": "Agent Board owner", "kind": "owner_topic", "body": "上一条：请先确认你能看到 Board。"},
                {"sender": "Reviewer Agent", "kind": "connector_message", "body": "我能看到。"},
            ],
            history_limit=12,
        )
        event = {
            "type": "message.created",
            "message": {
                "senderName": "Agent Board owner",
                "body": "你真的是 Agent 吗？",
            },
        }

        with patch("codex_connector.run_codex_command", return_value="我是通过 Codex connector 接入的真实回复。") as run_codex:
            response = await maybe_build_response(args, event)

        run_codex.assert_called_once()
        prompt = run_codex.call_args.args[1]
        self.assertIn("最近Board 消息", prompt)
        self.assertIn("上一条：请先确认你能看到 Board。", prompt)
        self.assertEqual(response["type"], "message.create")
        self.assertEqual(response["body"], "我是通过 Codex connector 接入的真实回复。")

    async def test_developer_chat_mode_returns_room_message_for_owner_chat(self):
        args = Namespace(
            role="developer",
            mock=False,
            response_mode="chat",
            codex_command="codex",
            timeout=600,
            workspace="/tmp/developer-checkout",
            sandbox="workspace-write",
            model="gpt-5.3-codex-spark",
            reasoning_effort="low",
            ignore_user_config=True,
            ignore_rules=True,
            ephemeral=True,
            skip_git_repo_check=True,
            repo="",
            mr_url="",
            base_ref="",
            head_ref="",
            task="open topic room",
        )
        event = {
            "type": "message.created",
            "message": {
                "senderName": "Agent Board owner",
                "body": "请你作为本地 Codex 接入并回复。",
            },
        }

        with patch("codex_connector.run_codex_command", return_value="本地 Codex 已接入，我会在这个 Board 里处理任务。") as run_codex:
            response = await maybe_build_response(args, event)

        run_codex.assert_called_once()
        self.assertEqual(response["type"], "message.create")
        self.assertEqual(response["body"], "本地 Codex 已接入，我会在这个 Board 里处理任务。")

    async def test_keepalive_pings_websocket_while_response_is_pending(self):
        class FakeWebSocket:
            def __init__(self):
                self.pings = 0

            async def ping(self):
                self.pings += 1

        async def slow_response():
            import asyncio

            await asyncio.sleep(0.03)
            return {"type": "finding.create"}

        websocket = FakeWebSocket()

        response = await await_response_with_keepalive(slow_response(), websocket, interval=0.01)

        self.assertEqual(response["type"], "finding.create")
        self.assertGreaterEqual(websocket.pings, 1)


if __name__ == "__main__":
    unittest.main()
