# LHAgent Experiments

This file is the registry for experiments in this repository. Each experiment should be self-contained and should be safe to move, archive, or productize independently.

| Experiment | Status | Type | Entry | Concept Doc | Notes |
| --- | --- | --- | --- | --- | --- |
| OpenClaw Billing Guardian | validated | runtime patch / UX guardrail | [experiments/openclaw-billing-guardian](./experiments/openclaw-billing-guardian) | [docs/concepts/openclaw-error-guardian.md](./docs/concepts/openclaw-error-guardian.md) | Converts structured provider billing errors into beginner-readable Chinese guidance. |
| Lighthouse Agent Board | productizing | Agent workbench / control plane | [services/review-room-service](./services/review-room-service) | [docs/concepts/review-room.md](./docs/concepts/review-room.md) | Canonical P0 service. Messages feed Agent Inbox; execution flows through Task, Claim, Run, Finding, Handoff, and Decision state. |
| Review Room legacy P0 | archived reference | protocol reference | [experiments/review-room](./experiments/review-room) | [docs/concepts/review-room.md](./docs/concepts/review-room.md) | Legacy implementation kept for historical task/run/handoff/decision evidence. Do not add new product work here. |

## Adding an Experiment

Create:

```text
experiments/<experiment-id>/
  README.md
```

The experiment README should cover:

- Purpose: what problem this experiment validates.
- Status: `idea`, `prototype`, `validated`, `productizing`, or `archived`.
- How to run: local commands, dependencies, and tests.
- Lighthouse relationship: control plane, instance-side connector, OpenClaw plugin, runtime helper, or research-only.
- Boundaries: what the experiment intentionally does not solve.
- Next steps: keep, productize, migrate, or archive.

## Shared Code Rule

Keep code inside an experiment until a second experiment genuinely reuses it. Only then promote the common piece into `shared/`.
