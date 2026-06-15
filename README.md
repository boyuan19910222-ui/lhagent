# LHAgent

LHAgent is a Lighthouse Agent Lab: a research repository for experiments around Lighthouse, OpenClaw, Agent runtime usability, and Agent collaboration workflows.

The repository is intentionally experimental. Different experiments may look unrelated at first glance, but each one must stay self-contained, runnable, documented, and easy to archive or productize later.

## Current Experiments

See [EXPERIMENTS.md](./EXPERIMENTS.md) for the full index.

Agent guide: [AGENTS.md](./AGENTS.md) with [Agent.md](./Agent.md) as a
compatibility pointer.

Roadmap: [Lighthouse Roadmap](./docs/roadmap/README.md)

| Experiment | Status | Entry | Focus |
| --- | --- | --- | --- |
| OpenClaw Billing Guardian | validated | [experiments/openclaw-billing-guardian](./experiments/openclaw-billing-guardian) | Translate provider billing/runtime errors into beginner-readable Chinese recovery guidance. |
| Lighthouse Agent Board | productizing prototype | [services/review-room-service](./services/review-room-service) | Model MR review as an Agent workbench where messages feed Agent Inbox, executable work flows through tasks/runs, and findings/decisions stay auditable. |

## Repository Rules

- Put runnable prototypes under `experiments/<experiment-id>/`.
- Put product and architecture notes under `docs/concepts/`.
- Keep root files focused on repository navigation and shared commands.
- Do not add a shared library until at least two experiments actually reuse it.
- Every experiment should have its own `README.md` with purpose, status, commands, Lighthouse relationship, boundaries, and next steps.

## Quick Start

Run all available checks:

```bash
npm test
```

Run one experiment:

```bash
npm run test:openclaw-billing-guardian
npm run test:review-room
```

Run the Lighthouse Agent Board local service:

```bash
python3 services/review-room-service/review_room_service.py --host 127.0.0.1 --port 8707
```

Then open:

```text
http://127.0.0.1:8707
```

## Structure

```text
docs/
  concepts/                         # Product and architecture notes
services/
  review-room-service/              # Canonical Lighthouse Agent Board P0 service
experiments/
  openclaw-billing-guardian/        # OpenClaw provider-error readability experiment
  review-room/                      # Legacy Review Room P0 protocol reference
shared/                             # Reserved for proven cross-experiment reuse
EXPERIMENTS.md                      # Experiment index and lifecycle table
README.md                           # Repository orientation
```

## Experiment Lifecycle

- `idea`: concept only, no runnable artifact yet.
- `prototype`: runnable enough to validate the core loop.
- `validated`: tested and useful as a reference or operational helper.
- `productizing`: being migrated into a real Lighthouse/OpenClaw product surface.
- `archived`: kept for context, no longer maintained.
