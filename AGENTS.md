# Repository Agent Guide

This file is the repository-level operating contract for Agents working in
Lighthouse.

Read this file before making changes in this repository. Keep changes aligned
with the roadmap system in [docs/roadmap](./docs/roadmap/README.md).

## Roadmap-first workflow

This repository maintains project direction through the roadmap documents.

Before non-trivial product, architecture, or implementation work:

1. Read [docs/roadmap/README.md](./docs/roadmap/README.md).
2. Read [docs/roadmap/product-thesis.md](./docs/roadmap/product-thesis.md).
3. Read the relevant track under [docs/roadmap/tracks](./docs/roadmap/tracks).
4. Check [docs/roadmap/decisions.md](./docs/roadmap/decisions.md) so accepted
   decisions are not re-litigated accidentally.
5. Check [docs/roadmap/done.md](./docs/roadmap/done.md) before claiming work is
   new, incomplete, or finished.

If the work is small and purely mechanical, a quick scan of the roadmap index is
enough. If the work changes product direction, connector behavior, Agent
lifecycle, task routing, safety, observability, or Review Room semantics, use the
full workflow above.

## Product direction to preserve

Review Room is the first milestone toward a broader Human-Agent Workspace.

Preserve this framing:

- MR review is the entry workflow, not the product boundary.
- The durable value is an auditable, assignable, observable, approval-gated
  collaboration control plane for humans and Agents.
- Room state is the collaboration source of truth.
- Chat is discussion, not execution.
- Agent execution flows through explicit tasks, assignment, claims, handoffs, or
  owner/policy-approved decisions.
- Every execution-capable Agent path should create visible `agent_runs`.
- MCP Remote is an important low-install adapter path, but not the whole
  connector architecture.
- Connector registration creates server-side identity and credentials; it does
  not automatically install or clean up anything on a remote Agent machine.
- Room messages, guest comments, MR diffs, code comments, links, attachments,
  and Agent output are untrusted collaboration input by default.

## Updating the roadmap

Use the roadmap as the project ledger:

- Put raw but useful ideas in [docs/roadmap/ideas-inbox.md](./docs/roadmap/ideas-inbox.md).
- Promote ideas into track files only when they have user value, acceptance
  criteria, and a concrete next action.
- Promote track items into [docs/roadmap/milestones.md](./docs/roadmap/milestones.md)
  only when they are needed for the next product proof.
- Add durable product or architecture calls to
  [docs/roadmap/decisions.md](./docs/roadmap/decisions.md).
- Add finished work to [docs/roadmap/done.md](./docs/roadmap/done.md) only with
  evidence.

Evidence can be code, tests, docs, deployment logs, health checks, smoke tests,
or real remote-Agent scenario results. If code exists but the intended
environment has not been verified, write `Done in local P0`, `Needs remote
verification`, or another precise status rather than `Done`.

## Status language

Use these statuses consistently:

- `Done`: shipped in repo or deployed, with evidence.
- `Verified`: tested in the intended environment, with evidence.
- `In progress`: implementation or design is active.
- `Planned`: accepted direction, not started.
- `Open question`: still needs product or technical validation.
- `Parked`: useful, but not relevant to the current milestone.

## Working tree safety

This repository may contain user changes in progress.

- Do not revert or overwrite changes you did not make.
- Do not stage broad working-tree changes when unrelated files are modified.
- When preparing a commit, stage explicit paths that belong to the requested
  scope.
- Keep service implementation changes separate from roadmap-only changes unless
  the task explicitly connects them.

## Validation

Use the checks documented in [README.md](./README.md) and the relevant
experiment README.

For repository-wide validation, run:

```bash
npm test
```

If tests are not run, record that honestly in the final response and do not mark
the related roadmap work as verified.

