# Ideas Inbox

This file catches useful ideas before they become committed roadmap work.
Promote an idea into a track when it has clear user value, acceptance criteria,
and a next action.

## Product positioning

- Position Lighthouse Agent Board as the first milestone toward a Human-Agent Workspace.
- Keep "Agent Collaboration Room" as an alternate product phrase when the
  discussion is specifically about room-based multi-Agent coordination.
- Explain that MR review is the proving ground, not the product limit.
- Build demos around visible control, not around magical Agent chat.

## Room types beyond MR review

- Incident response room.
- Legal review room.
- Security triage room.
- Release readiness room.
- Product decision room.
- Documentation review room.
- Customer escalation room.

## Agent onboarding

- Give every Agent a compact onboarding package:
  - room id,
  - short-lived token,
  - protocol version,
  - event schema,
  - tool URLs,
  - event stream URL,
  - capability declaration,
  - room snapshot,
  - assigned tasks,
  - acceptance criteria,
  - trust labels.
- Add a first-connect UTF-8 or locale probe before the Agent posts user-visible
  text.
- Show "ready", "streaming", "working", "stale", and "revoked" as separate
  states.

## Connector and adapter ecosystem

- Maintain an adapter matrix for Codex, Claude Code, CodeBuddy, OpenClaw,
  HermesAgent, local CLI Agents, vendor APIs, and future A2A-compatible Agents.
- Explore a generic CLI adapter that maps room tasks to shell commands and
  parses structured output.
- Explore HTTP webhook adapters for enterprise systems.
- Explore A2A mapping from Room, Task, Message, Finding, and Artifact.
- Keep MCP Remote as the lowest-install path where Agent support exists.
- Keep sidecars for local unattended work and private workspace access.

## Observability

- Add transcript/log pointers to every adapter that can expose them.
- Add stale-run detection.
- Add owner-visible cancel and retry actions.
- Add run comparison for Reviewer verification after Developer fixes.
- Add a compact "why this Agent is allowed to act" explanation on each task.

## Safety

- Build a context packer that separates trusted task data from untrusted room,
  MR, code, comment, attachment, and link content.
- Add prompt-injection checks for requests to ignore instructions, reveal
  secrets, auto-approve, push, merge, deploy, or sync externally.
- Add owner-facing sync previews before external adapters publish.
- Add decision records for all external side effects.
- Add per-adapter forbidden action defaults.

## Lifecycle and cleanup

- Add owner-facing cleanup checklists for MCP Remote and sidecar adapters.
- Warn users not to paste bearer tokens into long-lived shell history unless
  they accept that risk.
- Distinguish rotate token, disconnect, kick, revoke, cancel task, and cleanup.
- Record which remote residue remains after each owner action.

## UX

- Split the composer into message, assign task, ask for review, ask for fix,
  ask for verification, and start deliberation modes.
- Add a right-side work panel with tasks, runs, handoffs, decisions, and
  threads.
- Add room-level status that reflects pending owner decision, running Agents,
  stale runs, and unresolved findings.
- Add an invite flow that starts with MCP Remote and lets the owner switch to
  sidecar or CLI.

## Real scenario testing

- Test with real remote Agent behavior, not scripted demo replies.
- Record what the Agent could and could not do.
- Keep limitations explicit in the room timeline or test report.
- Use a repeatable smoke scenario:
  - create room,
  - register or invite Reviewer Agent,
  - create review task,
  - start run,
  - create finding,
  - propose handoff,
  - owner accepts,
  - Developer fixes,
  - Reviewer verifies,
  - owner confirms external action.
