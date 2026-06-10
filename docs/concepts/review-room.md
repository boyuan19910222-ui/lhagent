# Lighthouse Review Room

## Core conclusion

Review Room should be a Lighthouse-hosted Agent collaboration control plane, not only a chat room and not only a small service inside one user instance.

Recommended split:

| Layer | Deployment | Responsibility |
| --- | --- | --- |
| Review Room Control Plane | Lighthouse platform | Room, message, finding, artifact, identity, permission, audit, console UI, MR comment synchronization |
| Review Room Connector | User Lighthouse instance or local CLI | Private Git/IM access, local Agent bridge, remote Reviewer Agent adapter, A2A/MCP conversion |

This keeps private source code, enterprise Git tokens, IM tokens, and local Agent execution inside the user's trusted environment while still giving Lighthouse a durable collaboration state source.

## Product model

Review Room turns code review into a structured Agent collaboration room:

- MR is the context entry.
- Room is the collaboration state source.
- Finding is the structured review output.
- Developer Agent responses are tracked in the Room.
- Human confirmation is the external sync boundary.
- Connector syncs confirmed results back to MR comments, IM, or later pipeline status.

Lighthouse does not need to be the smartest review Agent. Its role is to host the coordination layer where local and remote Agents can participate safely, leave auditable traces, and hand control back to a human before external changes are published.

## Agent split

Remote Reviewer Agents are better suited for read-only, review, verification, and design judgment work:

- Read the current MR or branch diff and produce structured findings.
- Review a Developer Agent fix plan and call out missing tests or unresolved risk.
- Evaluate the Review Room console interaction model.
- Audit connector security boundaries such as token scope, webhook secret handling, public exposure, and MR comment permissions.
- Re-check completed fixes and return pass/fail plus remaining findings.

Local Developer Agents are better suited for source edits, tests, running services, UI verification, and preparing commits. This keeps write conflicts inside the local workspace and keeps remote Agents focused on review output.

## Local product slice

This repository includes a dependency-free product slice at:

```text
experiments/review-room/service
```

The service uses Python standard library `http.server` and `sqlite3` to model:

- Review Room storage.
- Room messages.
- Structured findings.
- Local and remote Agent connectors.
- Token-authenticated connector events.
- Developer Agent responses.
- Human confirmation and MR sync preview.
- GitLab/GitHub-style merge request webhook ingestion.

It is intentionally small enough to run on a fresh Lighthouse instance and concrete enough to validate the full Room -> Connector -> Finding -> Developer response -> human confirmation loop.

## API surface

- `GET /health`
- `POST /api/demo/session`
- `POST /api/rooms`
- `GET /api/rooms`
- `GET /api/rooms/{id}`
- `POST /api/rooms/{id}/connectors`
- `POST /api/connectors/{id}/events`
- `POST /api/rooms/{id}/messages`
- `POST /api/rooms/{id}/findings`
- `PATCH /api/findings/{id}`
- `POST /api/findings/{id}/developer-response`
- `POST /api/findings/{id}/confirm`
- `POST /api/webhooks/merge-request`

## Productization path

P0: Local research loop

- Run the included connector service.
- Exercise MR webhook -> Room -> Finding -> Developer Agent response -> human confirmation.
- Add room token and webhook secret validation before public exposure.
- Use SSH tunnel or HTTPS reverse proxy for controlled access.

P1: Lighthouse control plane

- Move Room state into Lighthouse backend.
- Show real Room list, Room detail, Finding state, and connector status in Lighthouse Console.
- Keep the user-side Connector responsible for private network and Agent adapter access.

P2: Agent protocol ecosystem

- Add A2A adapter by mapping Room/Finding/Artifact to A2A Task/Message/Artifact.
- Add MCP server tools such as `list_rooms`, `post_message`, `post_finding`, and `update_finding`.
- Add IM and Git adapters for WeCom, Feishu, QQ, GitHub, GitLab, and Gongfeng MR comments.
