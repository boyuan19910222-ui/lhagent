# Product Thesis

## North star

Lighthouse should become a Human-Agent Workspace: a control plane where humans
and Agents can collaborate through visible, structured, auditable state.

Review Room is the first milestone because MR review already contains the
hard coordination problems:

- a human owner,
- reviewer and developer roles,
- CI and security signals,
- external comments,
- code artifacts,
- task assignment,
- verification,
- final approval.

The goal is not just "humans and Agents can chat in a group." The goal is a
room where work is assignable, execution is observable, outputs are reviewable,
and external effects stay approval-gated.

## Product boundary

Review Room should own:

- room state,
- identity and capability policy,
- messages and timeline events,
- tasks and assignment,
- findings and handoffs,
- Agent run visibility,
- owner decisions,
- audit trail,
- sync previews and approval records.

Review Room should not pretend to own:

- remote Agent installation unless a connector adapter explicitly supports it,
- private repo or IM credentials unless they are inside a trusted user-side
  connector boundary,
- automatic cleanup of files, logs, sessions, or shell history on another
  machine,
- final approval for external side effects without owner or trusted-policy
  confirmation.

## Entry workflow

The entry workflow remains MR review:

1. A room is created from an MR, branch, topic, or webhook.
2. Owner invites or registers Agents.
3. Reviewer Agent produces findings.
4. Developer Agent fixes or responds.
5. Reviewer Agent verifies.
6. Owner confirms.
7. A sync adapter publishes approved results back to the external system.

The architecture should still generalize beyond MR review. Future room types can
reuse the same primitives:

- legal review rooms,
- incident response rooms,
- release readiness rooms,
- product decision rooms,
- security triage rooms,
- document review rooms.

## Design principles

- Room state is the source of collaboration truth.
- Chat is discussion, not execution.
- Execution flows through explicit tasks, assignment, claim, or policy.
- Handoffs are visible proposals before they become work.
- Every Agent execution produces an `agent_run`.
- Agent-to-Agent work stays inside room objects, scoped threads, summaries, and
  decisions.
- Untrusted content is labeled as untrusted before it reaches an Agent.
- External side effects require explicit owner confirmation or a trusted policy
  adapter.
- Connector architecture should support more than Codex.
- MCP Remote is an important low-install path, but not the only adapter path.

## Current product bet

The strongest near-term product proof is:

> A real remote Agent can join a Review Room, observe room state, receive or
> claim an explicit task, produce visible work, leave an auditable run trail, and
> ask the owner for approval before external effects.

This proof is stronger than a scripted demo. The room should expose real
limitations, encoding problems, lifecycle gaps, and connector friction so they
can become product work.

