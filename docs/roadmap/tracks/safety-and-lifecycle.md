# Track: Safety And Lifecycle

Status: `In progress`

## Purpose

Keep the room useful without treating room content as trusted instructions or
pretending server-side revocation can clean another machine.

Core concept doc:

- [Lighthouse Agent Board Security](../../concepts/review-room-security.md)

## Safety rule

Room content is collaboration input, not trusted instruction.

Untrusted by default:

- guest messages,
- MR diffs,
- code comments,
- external comments,
- links,
- attachments,
- Agent output.

## Capability boundary

Connector registration should declare:

- role,
- adapter type,
- protocol version,
- capabilities,
- forbidden actions,
- sandbox expectations,
- version,
- heartbeat or last seen status.

The service should enforce policy, and the connector runtime should check again
before invoking an Agent.

## Owner approval boundary

External side effects require owner confirmation or a trusted policy adapter.

External side effects include:

- MR comment sync,
- IM messages,
- commit creation,
- push,
- merge,
- deploy,
- pipeline status changes,
- secret or credential access.

## Lifecycle boundary

Owner actions such as rotate token, disconnect, kick, or revoke invalidate server
access. They do not automatically clean residue on an Agent machine unless the
adapter explicitly implements remote cleanup.

Possible residue includes:

- room id,
- bearer token,
- MCP config,
- connector scripts,
- virtualenvs or dependencies,
- repo checkouts,
- shell history,
- stdout/stderr logs,
- Agent session transcripts,
- workspace changes,
- test artifacts,
- local caches.

## Current next actions

- Add an owner-facing cleanup checklist by adapter type.
- Label token rotation and disconnect as server-side invalidation, not remote
  cleanup.
- Make bearer-token handling guidance visible in bootstrap output.
- Add context-pack rules that separate trusted task data from untrusted room and
  code content.
- Add guardrails for obvious prompt injection and external side-effect requests.

## Recent evidence

- [review-room-remote-mcp-debugging-2026-06-13-14.md](../review-room-remote-mcp-debugging-2026-06-13-14.md)
  records repeated stale-token failures from local scratch loops and preserves
  the rule that bearer tokens must not be committed to docs, scripts, or logs.
- The MCP `encodingProbe` and `bodyUtf8Base64` path are now part of the remote
  Agent safety boundary for shell-sensitive non-ASCII text.

## Acceptance criteria

- Owner can understand what is revoked server-side.
- Owner can understand what may remain on the remote Agent machine.
- Agents receive context with trust labels.
- Connectors enforce local assignment and capability checks.
- Decision records exist before sync adapters publish external effects.
