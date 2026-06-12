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
import shlex
import shutil
import subprocess
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse

try:
    from aiohttp import ClientSession, WSMsgType
except ModuleNotFoundError:  # pragma: no cover - exercised only in minimal helper environments.
    ClientSession = None
    WSMsgType = None


SANDBOX_CHOICES = ("read-only", "workspace-write", "danger-full-access")
RESPONSE_MODE_CHOICES = ("chat", "finding", "auto")


def split_command(command: str) -> list[str]:
    return shlex.split(command, posix=os.name != "nt")


def default_codex_command() -> str:
    if os.environ.get("CODEX_COMMAND"):
        return os.environ["CODEX_COMMAND"]
    return shutil.which("codex.cmd") or shutil.which("codex") or "codex"


def parse_room_url(base_url: str, room_id: str, token: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    host = parsed.netloc or parsed.path
    return "{}://{}/ws/rooms/{}?token={}".format(scheme, host, quote(room_id), quote(token))


def parse_room_api_url(base_url: str, room_id: str) -> str:
    normalized = base_url if "://" in base_url else "http://{}".format(base_url)
    parsed = urlparse(normalized)
    host = parsed.netloc or parsed.path
    scheme = parsed.scheme or "http"
    return "{}://{}/api/rooms/{}".format(scheme, host, quote(room_id))


def default_sandbox_for_role(role: str) -> str:
    return "read-only" if role == "reviewer" else "workspace-write"


def build_codex_exec_args(
    command: str,
    prompt: str,
    role: str,
    workspace: str = "",
    sandbox: str = "",
    model: str = "",
    reasoning_effort: str = "",
    ignore_user_config: bool = False,
    ignore_rules: bool = False,
    ephemeral: bool = False,
    skip_git_repo_check: bool = False,
    prompt_via_stdin: bool = False,
) -> list[str]:
    args = split_command(command) + ["exec", "--json"]
    if ignore_user_config:
        args.append("--ignore-user-config")
    if ignore_rules:
        args.append("--ignore-rules")
    if ephemeral:
        args.append("--ephemeral")
    if skip_git_repo_check:
        args.append("--skip-git-repo-check")
    if workspace:
        args.extend(["--cd", workspace])
    args.extend(["--sandbox", sandbox or default_sandbox_for_role(role)])
    if model:
        args.extend(["-m", model])
    if reasoning_effort:
        args.extend(["-c", 'model_reasoning_effort="{}"'.format(reasoning_effort)])
    args.append("-" if prompt_via_stdin else prompt)
    return args


def parse_codex_last_message(stdout: str) -> str:
    if not stdout:
        return ""
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
            "filePath": "experiments/review-room/service/review_room_service.py",
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


def build_chat_event(agent_output: str) -> Dict[str, Any]:
    return {
        "type": "message.create",
        "body": agent_output.strip() or "我已收到，会继续跟进这个话题。",
    }


def should_return_finding(topic: str) -> bool:
    lowered = topic.lower()
    keywords = ("finding", "review", "mr", "pr", "风险", "评审", "代码", "漏洞", "修复", "鉴权")
    return any(keyword in lowered for keyword in keywords)


def run_codex_command(
    command: str,
    prompt: str,
    timeout: int,
    role: str,
    workspace: str = "",
    sandbox: str = "",
    model: str = "",
    reasoning_effort: str = "",
    ignore_user_config: bool = False,
    ignore_rules: bool = False,
    ephemeral: bool = False,
    skip_git_repo_check: bool = False,
) -> str:
    completed = subprocess.run(
        build_codex_exec_args(
            command,
            prompt,
            role=role,
            workspace=workspace,
            sandbox=sandbox,
            model=model,
            reasoning_effort=reasoning_effort,
            ignore_user_config=ignore_user_config,
            ignore_rules=ignore_rules,
            ephemeral=ephemeral,
            skip_git_repo_check=skip_git_repo_check,
            prompt_via_stdin=True,
        ),
        check=False,
        capture_output=True,
        input=prompt,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    parsed = parse_codex_last_message(completed.stdout)
    if parsed:
        return parsed
    if completed.returncode != 0:
        return "Codex command failed: {}".format((completed.stderr or completed.stdout).strip())
    return ""


async def run_connector(args: argparse.Namespace) -> None:
    if ClientSession is None or WSMsgType is None:
        raise RuntimeError("aiohttp is required to run the connector; install experiments/review-room/service/requirements.txt")
    while True:
        try:
            await run_connector_once(args)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not getattr(args, "reconnect", True):
                raise
            print("connector disconnected: {}; reconnecting in {}s".format(exc, args.reconnect_delay), flush=True)
        else:
            if not getattr(args, "reconnect", True):
                return
            print("connector websocket closed; reconnecting in {}s".format(args.reconnect_delay), flush=True)
        await asyncio.sleep(args.reconnect_delay)


async def run_connector_once(args: argparse.Namespace) -> None:
    ws_url = parse_room_url(args.room_url, args.room_id, args.token)
    async with ClientSession() as session:
        args.room_history = await load_room_history(session, args)
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
                remember_room_event(args, event)
                if is_assigned_task_event(args, event):
                    task = event.get("task") or {}
                    await ws.send_json(
                        {
                            "type": "agent_run.start",
                            "taskId": task.get("id"),
                            "workspace": args.workspace,
                            "model": args.model,
                            "sandbox": args.sandbox or default_sandbox_for_role(args.role),
                            "promptSummary": task.get("instruction", "")[:500],
                        }
                    )
                    response = await await_response_with_keepalive(build_task_response(args, event), ws)
                    if response:
                        await ws.send_json(response)
                    await ws.send_json(
                        {
                            "type": "task.complete",
                            "taskId": task.get("id"),
                            "finalMessage": summarize_connector_response(response),
                        }
                    )
                    continue
                if should_send_working_notice(args, event):
                    await ws.send_json(
                        {
                            "type": "message.create",
                            "kind": "agent_working",
                            "body": "{} 正在调用本机 Codex 处理这条消息，可能需要几十秒到两分钟。".format(agent_display_name(args.role)),
                        }
                    )
                response = await await_response_with_keepalive(maybe_build_response(args, event), ws)
                if response:
                    await ws.send_json(response)


async def load_room_history(session: Any, args: argparse.Namespace) -> list[Dict[str, Any]]:
    if not getattr(args, "room_history_enabled", True):
        return []
    try:
        async with session.get(
            parse_room_api_url(args.room_url, args.room_id),
            headers={"Authorization": "Bearer {}".format(args.token)},
        ) as response:
            if response.status != 200:
                return []
            room = await response.json()
    except Exception:
        return []
    history = [compact_room_message(message) for message in room.get("messages", [])]
    return trim_room_history([message for message in history if message], getattr(args, "history_limit", 12))


def remember_room_event(args: argparse.Namespace, event: Dict[str, Any]) -> None:
    if event.get("type") == "room.snapshot":
        args.identity = event.get("identity") or {}
        return
    if not getattr(args, "room_history_enabled", True):
        return
    if event.get("type") != "message.created":
        return
    message = compact_room_message(event.get("message") or {})
    if not message:
        return
    history = getattr(args, "room_history", None)
    if history is None:
        history = []
        args.room_history = history
    history.append(message)
    args.room_history = trim_room_history(history, getattr(args, "history_limit", 12))


def compact_room_message(message: Dict[str, Any]) -> Dict[str, str]:
    body = (message.get("body") or "").strip()
    if not body:
        return {}
    return {
        "sender": str(message.get("senderName") or message.get("senderType") or "unknown"),
        "kind": str(message.get("kind") or "message"),
        "body": body,
    }


def trim_room_history(history: list[Dict[str, str]], limit: int) -> list[Dict[str, str]]:
    if limit <= 0:
        return []
    return history[-limit:]


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
    if event_type == "message.created":
        message = event.get("message") or {}
        body = message.get("body", "")
        if not body or message.get("senderName") != "review room owner":
            return None
        response_mode = getattr(args, "response_mode", "finding")
        if args.mock:
            if response_mode == "chat":
                return build_chat_event("我已收到：{}。".format(body))
            return build_agent_response(args.role, body, mock=True)
        prompt = chat_prompt(body, args)
        if args.role == "reviewer" and (response_mode == "finding" or (response_mode == "auto" and should_return_finding(body))):
            prompt = reviewer_prompt(body, args)
        codex_text = await asyncio.to_thread(
            run_codex_command,
            args.codex_command,
            prompt,
            args.timeout,
            args.role,
            args.workspace,
            args.sandbox,
            args.model,
            getattr(args, "reasoning_effort", ""),
            getattr(args, "ignore_user_config", False),
            getattr(args, "ignore_rules", False),
            getattr(args, "ephemeral", False),
            getattr(args, "skip_git_repo_check", False),
        )
        if args.role != "reviewer" or response_mode == "chat" or (response_mode == "auto" and not should_return_finding(body)):
            return build_chat_event(codex_text)
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
            getattr(args, "reasoning_effort", ""),
            getattr(args, "ignore_user_config", False),
            getattr(args, "ignore_rules", False),
            getattr(args, "ephemeral", False),
            getattr(args, "skip_git_repo_check", False),
        )
        return {"type": "finding.respond", "findingId": finding_id, "body": codex_text}
    return None


def is_assigned_task_event(args: argparse.Namespace, event: Dict[str, Any]) -> bool:
    if event.get("type") != "task.assigned":
        return False
    task = event.get("task") or {}
    identity = getattr(args, "identity", {}) or {}
    assigned_connector_id = task.get("assignedConnectorId") or ""
    if assigned_connector_id:
        return identity.get("connectorId") == assigned_connector_id
    target = task.get("target") or {}
    if target.get("role") and target.get("role") != args.role:
        return False
    capability = target.get("capability") or ""
    capabilities = identity.get("capabilities") or []
    return not capability or capability in capabilities


async def build_task_response(args: argparse.Namespace, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    task = event.get("task") or {}
    instruction = task.get("instruction") or ""
    source = task.get("source") or {}
    if args.mock:
        if args.role == "reviewer":
            return build_agent_response("reviewer", instruction, mock=True)
        if args.role == "developer" and source.get("findingId"):
            return build_agent_response("developer", instruction, mock=True, finding_id=source.get("findingId"))
        return build_chat_event("我已完成任务：{}。".format(instruction))
    prompt = task_prompt(task, args)
    codex_text = await asyncio.to_thread(
        run_codex_command,
        args.codex_command,
        prompt,
        args.timeout,
        args.role,
        args.workspace,
        args.sandbox,
        args.model,
        getattr(args, "reasoning_effort", ""),
        getattr(args, "ignore_user_config", False),
        getattr(args, "ignore_rules", False),
        getattr(args, "ephemeral", False),
        getattr(args, "skip_git_repo_check", False),
    )
    if args.role == "reviewer":
        return build_reviewer_finding_event(codex_text)
    if args.role == "developer" and source.get("findingId"):
        return {"type": "finding.respond", "findingId": source["findingId"], "body": codex_text}
    return build_chat_event(codex_text)


def summarize_connector_response(response: Optional[Dict[str, Any]]) -> str:
    if not response:
        return "Connector completed without output."
    if response.get("type") == "finding.create":
        return response.get("claim") or "Reviewer Agent created a finding."
    if response.get("type") == "finding.respond":
        return response.get("body") or "Developer Agent responded to finding."
    return response.get("body") or response.get("type") or "Connector completed task."


def should_send_working_notice(args: argparse.Namespace, event: Dict[str, Any]) -> bool:
    if getattr(args, "mock", False) or not getattr(args, "working_notice", True):
        return False
    if event.get("type") != "message.created":
        return False
    message = event.get("message") or {}
    return bool(message.get("body")) and message.get("senderName") == "review room owner"


def agent_display_name(role: str) -> str:
    return "Developer Agent" if role == "developer" else "Reviewer Agent"


def reviewer_prompt(topic: str, args: Optional[argparse.Namespace] = None) -> str:
    return (
        "你是 Lighthouse Review Room 的 Reviewer Agent。\n"
        "{}\n"
        "请在当前工作区做真实代码评审，只读分析 MR/分支差异，不要修改文件。\n"
        "请只输出一个 JSON object，不要 Markdown，不要额外解释。字段必须包含："
        "severity, filePath, line, claim, evidence, suggestedFix。\n"
        "话题：\n{}".format(prompt_context(args), topic)
    )


def chat_prompt(topic: str, args: Optional[argparse.Namespace] = None) -> str:
    role = getattr(args, "role", "reviewer") if args else "reviewer"
    role_name = "Developer Agent" if role == "developer" else "Reviewer Agent"
    return (
        "你是 Lighthouse Review Room 中通过本机 Codex 真实接入的 {}。\n"
        "{}\n"
        "请用中文直接回复 owner 的消息。不要伪装成系统，不要说自己只是模板。"
        "如果信息不足，先提出一个清晰的问题；如果可以推进，给出简洁的判断和下一步。"
        "回复应适合聊天室，尽量短，不要展开无关实现细节。\n"
        "owner 消息：\n{}".format(role_name, prompt_context(args), topic)
    )


def developer_prompt(finding: Dict[str, Any], args: Optional[argparse.Namespace] = None) -> str:
    return (
        "你是 Lighthouse Review Room 的 Developer Agent。\n"
        "{}\n"
        "请在当前可写工作区针对下面 finding 进行真实修复；如无法安全修改，请说明阻塞原因。"
        "完成后输出修复摘要、验证命令和结果。\n"
        "{}".format(prompt_context(args), json.dumps(finding, ensure_ascii=False))
    )


def task_prompt(task: Dict[str, Any], args: Optional[argparse.Namespace] = None) -> str:
    role = getattr(args, "role", "reviewer") if args else "reviewer"
    if role == "reviewer":
        return (
            "你是 Lighthouse Review Room 的 Reviewer Agent。\n"
            "{}\n"
            "下面是 Review Room 分配给你的结构化任务。只读分析，不要修改文件。"
            "请只输出一个 JSON object，字段包含 severity, filePath, line, claim, evidence, suggestedFix。\n"
            "{}".format(prompt_context(args), json.dumps(task, ensure_ascii=False))
        )
    return (
        "你是 Lighthouse Review Room 的 Developer Agent。\n"
        "{}\n"
        "下面是 Review Room 分配给你的结构化任务。按本地工作区权限执行，完成后输出简洁的修复摘要和验证结果。\n"
        "{}".format(prompt_context(args), json.dumps(task, ensure_ascii=False))
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
    parts = []
    if rendered:
        parts.append("上下文：\n{}".format("\n".join(rendered)))
    history = format_room_history(getattr(args, "room_history", []), getattr(args, "history_limit", 12))
    if history:
        parts.append("最近房间消息：\n{}".format(history))
    return "\n".join(parts)


def format_room_history(history: list[Dict[str, str]], limit: int = 12) -> str:
    rows = []
    for message in trim_room_history(history or [], limit):
        body = " ".join((message.get("body") or "").split())
        if len(body) > 600:
            body = body[:597] + "..."
        rows.append("- {} [{}]: {}".format(message.get("sender", "unknown"), message.get("kind", "message"), body))
    return "\n".join(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Connect a local Agent/Codex process to Lighthouse Review Room")
    parser.add_argument("--role", choices=["reviewer", "developer"], required=True)
    parser.add_argument("--room-url", default=os.environ.get("REVIEW_ROOM_URL", "http://127.0.0.1:8707"))
    parser.add_argument("--room-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--codex-command", default=default_codex_command())
    parser.add_argument("--workspace", default=os.environ.get("REVIEW_ROOM_WORKSPACE", ""))
    parser.add_argument("--sandbox", choices=SANDBOX_CHOICES, default="")
    parser.add_argument("--model", default=os.environ.get("CODEX_MODEL", "gpt-5.3-codex-spark"))
    parser.add_argument("--reasoning-effort", default=os.environ.get("CODEX_REASONING_EFFORT", "low"))
    parser.add_argument("--repo", default=os.environ.get("REVIEW_ROOM_REPO", ""))
    parser.add_argument("--mr-url", default=os.environ.get("REVIEW_ROOM_MR_URL", ""))
    parser.add_argument("--base-ref", default=os.environ.get("REVIEW_ROOM_BASE_REF", ""))
    parser.add_argument("--head-ref", default=os.environ.get("REVIEW_ROOM_HEAD_REF", ""))
    parser.add_argument("--task", default=os.environ.get("REVIEW_ROOM_TASK", ""))
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--history-limit", type=int, default=int(os.environ.get("REVIEW_ROOM_HISTORY_LIMIT", "12")))
    parser.add_argument("--response-mode", choices=RESPONSE_MODE_CHOICES, default=os.environ.get("REVIEW_ROOM_RESPONSE_MODE", "chat"))
    parser.add_argument("--use-user-config", action="store_true", help="Allow the connector to inherit ~/.codex/config.toml.")
    parser.add_argument("--use-rules", action="store_true", help="Load Codex rules files for connector runs.")
    parser.add_argument("--persistent-session", action="store_true", help="Do not pass --ephemeral to codex exec.")
    parser.add_argument("--require-git-repo", action="store_true", help="Do not pass --skip-git-repo-check to codex exec.")
    parser.add_argument("--reconnect-delay", type=float, default=float(os.environ.get("REVIEW_ROOM_RECONNECT_DELAY", "5")))
    parser.add_argument("--no-reconnect", action="store_true")
    parser.add_argument("--no-room-history", action="store_true")
    parser.add_argument("--no-working-notice", action="store_true")
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args()
    args.ignore_user_config = not args.use_user_config
    args.ignore_rules = not args.use_rules
    args.ephemeral = not args.persistent_session
    args.skip_git_repo_check = not args.require_git_repo
    args.reconnect = not args.no_reconnect
    args.room_history_enabled = not args.no_room_history
    args.working_notice = not args.no_working_notice
    return args


def main() -> None:
    asyncio.run(run_connector(parse_args()))


if __name__ == "__main__":
    main()
