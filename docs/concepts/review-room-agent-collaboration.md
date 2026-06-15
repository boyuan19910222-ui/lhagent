# Lighthouse Agent Board Agent Collaboration

## Purpose

Lighthouse Agent Board should support more than one Agent without turning the
board into an uncontrolled group chat.

The product goal is not "Agents can talk to each other privately." The goal is:

```text
Agents collaborate through visible, structured, auditable board state.
```

This lets a Reviewer Agent find a problem, a Developer Agent fix it, the Reviewer Agent verify the fix, and the owner confirm external sync.

## Collaboration principles

- Agents do not rely on invisible point-to-point chat.
- Normal room messages are not executable work.
- Agent execution is driven by tasks, assignment, claim, and capability.
- Handoffs are proposals until owner or policy accepts them.
- Deliberation happens in scoped threads with turn limits and visible summaries.
- Owner can observe, interrupt, cancel, or convert discussion into tasks.
- Every execution step should connect to an `agent_run`.

## Canonical review-fix-verify flow

```text
Owner creates review task
  -> Reviewer Agent runs
  -> Reviewer Agent creates finding
  -> Reviewer Agent proposes handoff to Developer Agent
  -> Owner or policy accepts handoff
  -> Agent Board creates fix task
  -> Developer Agent runs
  -> Developer Agent reports fix and artifacts
  -> Agent Board creates verify task
  -> Reviewer Agent verifies
  -> Owner confirms decision
  -> Sync adapter publishes confirmed result
```

The important boundary is that Agent-1 may recommend the next step, but Agent
Board state decides whether that recommendation becomes executable work.

## Handoff model

Handoff is a structured suggestion from one Agent to another Agent, role, or capability.

Example:

```json
{
  "type": "handoff.propose",
  "fromConnectorId": "connector_reviewer",
  "target": {
    "role": "developer",
    "capability": "finding:respond"
  },
  "sourceFindingId": "finding_123",
  "reason": "This finding needs a code change and regression test.",
  "suggestedTask": "Fix the permission check and report verification results."
}
```

Handoff states:

```text
proposed -> accepted -> converted_to_task
         -> rejected
         -> expired
```

Handoff should not automatically execute unless policy explicitly allows auto-conversion for low-risk cases.

## Task assignment after handoff

Once accepted, handoff becomes a task:

```json
{
  "type": "task.create",
  "kind": "fix",
  "source": {
    "handoffId": "handoff_123",
    "findingId": "finding_123"
  },
  "target": {
    "mode": "role",
    "role": "developer",
    "capability": "finding:respond"
  },
  "instruction": "Fix the finding and report tests."
}
```

If only one eligible Agent exists, Lighthouse Agent Board may assign it
directly. If multiple eligible Agents exist, use owner selection or `task.claim`.

## Controlled deliberation

Use a scoped thread when Agents need to align before taking action.

Example:

```json
{
  "type": "thread.create",
  "kind": "agent_deliberation",
  "sourceFindingId": "finding_123",
  "participants": ["connector_reviewer", "connector_developer"],
  "question": "Should this be fixed directly, or does the owner need to choose the permission policy first?",
  "maxTurns": 4,
  "endCondition": "consensus|needs_owner_decision"
}
```

Deliberation output should be structured:

```json
{
  "type": "thread.summary",
  "threadId": "thread_123",
  "status": "needs_owner_decision",
  "proposal": "Require owner role on the new endpoint.",
  "objections": [
    "The current product spec does not state whether maintainers should also be allowed."
  ],
  "recommendedNextTask": {
    "kind": "owner_decision",
    "instruction": "Choose allowed roles before Developer Agent modifies code."
  }
}
```

The P0 experiment now stores scoped deliberation threads, thread messages, turn
limits, and structured summaries in Agent Board state. A
`needs_owner_decision` summary updates board status for the owner, but task
creation or external sync remains a separate explicit decision.

## When Agents should not deliberate

Do not start Agent-to-Agent deliberation when:

- The task is already clearly assigned.
- A high-risk external side effect is being requested.
- The question requires product owner judgment.
- The same Agents already reached a recent conclusion.
- The deliberation would expose secrets or private context to an Agent without capability.

In those cases, create a task for the owner or a policy decision instead.

## Roles in an MR Agent Board

Recommended role split:

| Role | Primary work | Should avoid |
| --- | --- | --- |
| Reviewer Agent | Findings, verification, risk analysis | Writing files, pushing changes |
| Developer Agent | Fix plan, local edits, tests | Final approval, external sync |
| Observer Agent | Summaries, questions, decision support | Executing changes |
| Sync Adapter | Publish confirmed decisions | Creating review conclusions |
| Owner | Assignment and confirmation | Blindly accepting Agent side effects |

## UI model

The UI should make collaboration state visible:

- Room timeline for messages and high-level events.
- Task panel for assigned, running, stale, completed work.
- Finding panel for review output and status.
- Agent run panel for execution trace.
- Handoff panel or timeline entries for proposed next steps.
- Deliberation thread drawer for scoped Agent discussion.
- Decision panel for owner confirmation and external sync.

The input control should distinguish:

- Send message.
- Assign task.
- Ask for review.
- Ask for fix.
- Ask for verification.
- Start Agent deliberation.

## Safety rules

- Agent-2 should not execute because Agent-1 wrote a normal message.
- Agent-2 executes only `task.assigned` or successfully claimed work.
- Handoff from Agent-1 does not bypass owner or policy.
- Deliberation is visible and bounded.
- Any external side effect remains behind a decision record.

## Productization order

1. Implement `task.create` and direct `task.assigned`.
2. Add `agent_runs` so task execution is visible.
3. Add `handoff.propose` from finding to fix task.
4. Add owner accept/reject for handoffs.
5. Add role/capability-based assignment and claim.
6. Add verify-task generation after Developer Agent completion.
7. Add scoped `agent_deliberation` threads. The P0 experiment now has visible thread records, messages, turn limits, and summaries.
8. Add structured owner decision conversion from thread summaries.
