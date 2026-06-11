#!/usr/bin/env python3
"""Agent-side connector client for Lighthouse Review Room.

The Review Room service owns state and realtime transport. This client runs
beside an Agent/Codex environment, watches room messages, invokes local agent
logic, and posts structured events back over WebSocket.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse

from aiohttp import ClientSession, WSMsgType


def parse_room_url(base_url: str, room_id: str, token: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    host = parsed.netloc or parsed.path
    return "{}://{}/ws/rooms/{}?token={}".format(scheme, host, quote(room_id), quote(token))


def build_agent_response(role: str, topic: str, mock: bool = False, finding_id: Optional[str] = None) -> Dict[str, Any]:
    if role == "reviewer":
        return {
            "type": "finding.create",
            "severity": "P1",
            "filePath": "services/review-room-service/review_room_service.py",
            "line": 1,
            "claim": "鉴权或状态边界需要人工确认。",
            "evidence": topic or "Reviewer Agent 收到 owner 发起的代码评审话题。",
            "suggestedFix": "补充 owner/connector token 校验，并为 WebSocket 房间事件增加回归测试。",
        }
    if role == "developer":
        return {
            "type": "finding.respond",
            "findingId": finding_id or "",
            "body": "我会按 finding 补充修复计划、实现和验证记录。",
        }
    return {
        "type": "message.create",
        "body": "Agent connector 已收到话题：{}".format(topic),
    }


def run_codex_command(command: str, prompt: str, timeout: int) -> str:
    completed = subprocess.run(
        [command, "exec", "--json", prompt],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        return "Codex command failed: {}".format((completed.stderr or completed.stdout).strip())
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    return lines[-1] if lines else completed.stdout.strip()


async def run_connector(args: argparse.Namespace) -> None:
    ws_url = parse_room_url(args.room_url, args.room_id, args.token)
    async with ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            await ws.send_json(
                {
                    "type": "message.create",
                    "body": "{} connector online.".format(args.role),
                }
            )
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    continue
                event = json.loads(message.data)
                response = maybe_build_response(args, event)
                if response:
                    await ws.send_json(response)


def maybe_build_response(args: argparse.Namespace, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    event_type = event.get("type")
    if args.role == "reviewer" and event_type == "message.created":
        body = (event.get("message") or {}).get("body", "")
        if not body or (event.get("message") or {}).get("senderName") != "review room owner":
            return None
        if args.mock:
            return build_agent_response("reviewer", body, mock=True)
        codex_text = run_codex_command(args.codex_command, reviewer_prompt(body), args.timeout)
        return build_agent_response("reviewer", codex_text)
    if args.role == "developer" and event_type == "finding.created":
        finding = event.get("finding") or {}
        finding_id = finding.get("id")
        if not finding_id:
            return None
        if args.mock:
            return build_agent_response("developer", finding.get("claim", ""), mock=True, finding_id=finding_id)
        codex_text = run_codex_command(args.codex_command, developer_prompt(finding), args.timeout)
        return {"type": "finding.respond", "findingId": finding_id, "body": codex_text}
    return None


def reviewer_prompt(topic: str) -> str:
    return (
        "你是 Review Room 的 Reviewer Agent。请围绕下面代码评审话题输出一个风险 finding，"
        "包含 claim/evidence/suggestedFix。话题：\n{}".format(topic)
    )


def developer_prompt(finding: Dict[str, Any]) -> str:
    return (
        "你是 Review Room 的 Developer Agent。请针对下面 finding 输出修复计划和验证计划。\n"
        "{}".format(json.dumps(finding, ensure_ascii=False))
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Connect a local Agent/Codex process to Lighthouse Review Room")
    parser.add_argument("--role", choices=["reviewer", "developer"], required=True)
    parser.add_argument("--room-url", default=os.environ.get("REVIEW_ROOM_URL", "http://127.0.0.1:8707"))
    parser.add_argument("--room-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--codex-command", default=os.environ.get("CODEX_COMMAND", "codex"))
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--mock", action="store_true")
    return parser.parse_args()


def main() -> None:
    asyncio.run(run_connector(parse_args()))


if __name__ == "__main__":
    main()
