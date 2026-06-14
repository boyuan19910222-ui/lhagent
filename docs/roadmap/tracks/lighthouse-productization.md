# Track: Lighthouse Productization

Status: `Planned`

## Purpose

Move Review Room from local experiment into Lighthouse as a durable product
surface.

## Target shape

Lighthouse should provide:

- room list,
- room detail,
- timeline,
- task panel,
- Agent run panel,
- finding panel,
- handoff and decision panel,
- connector status and lifecycle controls,
- invite and bootstrap UX,
- audit and sync preview,
- integration settings.

The user-side connector should keep private repo, IM, and Agent execution access
inside the user's trusted environment.

## Current next actions

- Define the Lighthouse backend data model for rooms, tasks, findings, runs,
  handoffs, decisions, threads, and connectors.
- Decide which parts of the P0 service become product backend and which remain
  prototype-only.
- Sketch the Lighthouse Console room view from the existing built-in HTML
  workflow.
- Define GitHub, GitLab, Gongfeng, Feishu, WeCom, and QQ sync boundaries.
- Decide how room events, audit logs, and transcript links are retained.

## Acceptance criteria

- Product UI makes Agent state visible without relying on terminal output.
- External sync uses preview plus owner decision records.
- Private credentials stay in the correct trust boundary.
- The architecture can support other room types after MR review.

## Open questions

- Should Review Room state live in the main Lighthouse backend from P1, or stay
  in a service boundary first?
- What is the minimum Console UI needed before remote users can evaluate the
  product?
- Which sync adapter should ship first after MR comments?
- How much room history should be retained by default?

