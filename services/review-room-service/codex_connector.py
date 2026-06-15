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
import logging
import os
import shlex
import subprocess
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse

try:
    from aiohttp import ClientSession, WSMsgType
except ModuleNotFoundError:  # pragma: no cover - exercised only in minimal helper environments.
    ClientSession = None
    WSMsgType = None


SANDBOX_CHOICES = ("read-only", "workspace-write", "danger-full-access")
LOGGER = logging.getLogger(__name__)


def parse_room_url(base_url: str, room_id: str, token: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    host = parsed.netloc or parsed.path
    return "{}://{}/ws/rooms/{}?token={}".format(scheme, host, quote(room_id), quote(token))


def default_sandbox_for_role(role: str) -> str:
    return "read-only" if role == "reviewer" else "workspace-write"


def build_codex_exec_args(
    command: str,
    prompt: str,
    role: str,
    workspace: str = "",
    sandbox: str = "",
    model: str = "",
) -> list[str]:
    args = shlex.split(command) + ["exec", "--json"]
    if workspace:
        args.extend(["--cd", workspace])
    args.extend(["--sandbox", sandbox or default_sandbox_for_role(role)])
    if model:
        args.extend(["-m", model])
    args.append(prompt)
    return args


def parse_codex_last_message(stdout: str) -> str:
    lines = [line for line in stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        text = extract_text(event)
        if text:
            return text
    return lines[-1].strip() if lines else ""


def extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(part for part in (extract_text(item) for item in value) if part).strip()
    if not isinstance(value, dict):
        return ""
    for key in ("text", "message", "content", "output_text", "final", "result", "item", "delta", "response"):
        if key not in value:
            continue
        text = extract_text(value[key])
        if text:
            return text
    return ""


def build_reviewer_finding_event(agent_output: str) -> Dict[str, Any]:
    data = parse_json_object(agent_output)
    if data:
        return {
            "type": "finding.create",
            "severity": data.get("severity") or "P1",
            "filePath": data.get("filePath") or data.get("file_path") or "",
            "line": optional_int(data.get("line")),
            "claim": data.get("claim") or first_line(agent_output) or "Reviewer Agent 发现风险",
            "evidence": data.get("evidence") or agent_output,
            "suggestedFix": data.get("suggestedFix") or data.get("suggested_fix") or "请根据 Reviewer Agent 输出确认修复方案。",
        }
    return {
        "type": "finding.create",
        "severity": "P1",
        "filePath": "",
        "line": None,
        "claim": first_line(agent_output) or "Reviewer Agent 发现风险",
        "evidence": agent_output,
        "suggestedFix": "请根据 Reviewer Agent 输出确认修复方案。",
    }


def parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    candidate = strip_json_fence(text.strip())
    for value in (candidate, slice_json_object(candidate)):
        if not value:
            continue
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def strip_json_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def slice_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start : end + 1]


def optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


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


def run_codex_command(
    command: str,
    prompt: str,
    timeout: int,
    role: str,
    workspace: str = "",
    sandbox: str = "",
    model: str = "",
) -> str:
    try:
        completed = subprocess.run(
            build_codex_exec_args(command, prompt, role=role, workspace=workspace, sandbox=sandbox, model=model),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "Codex command timed out after {} seconds".format(timeout)
    if completed.returncode != 0:
        return "Codex command failed: {}".format((completed.stderr or completed.stdout).strip())
    return parse_codex_last_message(completed.stdout)


async def run_connector(args: argparse.Namespace) -> None:
    if ClientSession is None or WSMsgType is None:
        raise RuntimeError("aiohttp is required to run the connector; install services/review-room-service/requirements.txt")
    ws_url = parse_room_url(args.room_url, args.room_id, args.token)
    backoff = 1.0
    async with ClientSession() as session:
        while True:
            try:
                async with session.ws_connect(ws_url) as ws:
                    backoff = 1.0
                    await ws.send_json(
                        {
                            "type": "message.create",
                            "body": "{} connector online.".format(args.role),
                        }
                    )
                    async for message in ws:
                        if message.type != WSMsgType.TEXT:
                            continue
                        try:
                            event = json.loads(message.data)
                        except json.JSONDecodeError:
                            LOGGER.warning("Ignoring malformed Review Room event: %r", message.data)
                            continue
                        try:
                            response = await await_response_with_keepalive(maybe_build_response(args, event), ws)
                        except Exception:
                            LOGGER.exception("Review Room connector failed to process event")
                            continue
                        if response:
                            try:
                                await ws.send_json(response)
                            except Exception:
                                LOGGER.exception("Review Room connector failed to send response")
                                break
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Review Room connector websocket disconnected")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def await_response_with_keepalive(response_coro: Any, websocket: Any, interval: float = 10.0) -> Optional[Dict[str, Any]]:
    task = asyncio.create_task(response_coro)
    try:
        while True:
            done, _pending = await asyncio.wait({task}, timeout=interval)
            if done:
                return task.result()
            await websocket.ping()
    finally:
        if not task.done():
            task.cancel()


async def maybe_build_response(args: argparse.Namespace, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    event_type = event.get("type")
    if args.role == "reviewer" and event_type == "message.created":
        body = (event.get("message") or {}).get("body", "")
        if not body or (event.get("message") or {}).get("senderName") != "review room owner":
            return None
        if args.mock:
            return build_agent_response("reviewer", body, mock=True)
        codex_text = await asyncio.to_thread(
            run_codex_command,
            args.codex_command,
            reviewer_prompt(body, args),
            args.timeout,
            args.role,
            args.workspace,
            args.sandbox,
            args.model,
        )
        return build_reviewer_finding_event(codex_text)
    if args.role == "developer" and event_type == "finding.created":
        finding = event.get("finding") or {}
        finding_id = finding.get("id")
        if not finding_id:
            return None
        if args.mock:
            return build_agent_response("developer", finding.get("claim", ""), mock=True, finding_id=finding_id)
        codex_text = await asyncio.to_thread(
            run_codex_command,
            args.codex_command,
            developer_prompt(finding, args),
            args.timeout,
            args.role,
            args.workspace,
            args.sandbox,
            args.model,
        )
        return {"type": "finding.respond", "findingId": finding_id, "body": codex_text}
    return None


def reviewer_prompt(topic: str, args: Optional[argparse.Namespace] = None) -> str:
    return (
        "你是 Lighthouse Review Room 的 Reviewer Agent。\n"
        "{}\n"
        "请在当前工作区做真实代码评审，只读分析 MR/分支差异，不要修改文件。\n"
        "请只输出一个 JSON object，不要 Markdown，不要额外解释。字段必须包含："
        "severity, filePath, line, claim, evidence, suggestedFix。\n"
        "话题：\n{}".format(prompt_context(args), topic)
    )


def developer_prompt(finding: Dict[str, Any], args: Optional[argparse.Namespace] = None) -> str:
    return (
        "你是 Lighthouse Review Room 的 Developer Agent。\n"
        "{}\n"
        "请在当前可写工作区针对下面 finding 进行真实修复；如无法安全修改，请说明阻塞原因。"
        "完成后输出修复摘要、验证命令和结果。\n"
        "{}".format(prompt_context(args), json.dumps(finding, ensure_ascii=False))
    )


def prompt_context(args: Optional[argparse.Namespace]) -> str:
    if not args:
        return ""
    rows = [
        ("repository", getattr(args, "repo", "")),
        ("mrUrl", getattr(args, "mr_url", "")),
        ("baseRef", getattr(args, "base_ref", "")),
        ("headRef", getattr(args, "head_ref", "")),
        ("workspace", getattr(args, "workspace", "")),
        ("task", getattr(args, "task", "")),
    ]
    rendered = ["{}: {}".format(key, value) for key, value in rows if value]
    return "上下文：\n{}".format("\n".join(rendered)) if rendered else ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Connect a local Agent/Codex process to Lighthouse Review Room")
    parser.add_argument("--role", choices=["reviewer", "developer"], required=True)
    parser.add_argument("--room-url", default=os.environ.get("REVIEW_ROOM_URL", "http://127.0.0.1:8707"))
    parser.add_argument("--room-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--codex-command", default=os.environ.get("CODEX_COMMAND", "codex"))
    parser.add_argument("--workspace", default=os.environ.get("REVIEW_ROOM_WORKSPACE", ""))
    parser.add_argument("--sandbox", choices=SANDBOX_CHOICES, default="")
    parser.add_argument("--model", default=os.environ.get("CODEX_MODEL", ""))
    parser.add_argument("--repo", default=os.environ.get("REVIEW_ROOM_REPO", ""))
    parser.add_argument("--mr-url", default=os.environ.get("REVIEW_ROOM_MR_URL", ""))
    parser.add_argument("--base-ref", default=os.environ.get("REVIEW_ROOM_BASE_REF", ""))
    parser.add_argument("--head-ref", default=os.environ.get("REVIEW_ROOM_HEAD_REF", ""))
    parser.add_argument("--task", default=os.environ.get("REVIEW_ROOM_TASK", ""))
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--mock", action="store_true")
    return parser.parse_args()


def main() -> None:
    asyncio.run(run_connector(parse_args()))


if __name__ == "__main__":
    main()
