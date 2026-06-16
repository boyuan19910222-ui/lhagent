# Lighthouse Review Room Productization Implementation Plan

> 2026-06-16 update: this plan is kept as historical implementation context. The product direction has changed from a realtime Agent room to an MCP-only shared blackboard model. Do not treat non-MCP onboarding, non-MCP runners, or remote wake-up behavior as the product path. Preserve the useful parts: scoped identity, durable Room state, Message/Task/Finding/Decision records, audit trail, and human confirmation.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the Review Room prototype into a usable local product slice where Lighthouse is the Room Board control plane and activated agents read/write shared state through scoped MCP tools.

**Architecture:** Keep the dependency-free Python service as the local Lighthouse Review Room backend for this slice. Add durable board records, scoped MCP identities, task/finding status, and event ingestion so activated agents can leave evidence, tasks, findings, decisions, and audit events on the same Room Board. The HTML page becomes a control-plane UI for creating a Room Board, provisioning MCP access, viewing inbox/task/finding state, and watching audited state changes.

**Tech Stack:** Python standard library `http.server` + `sqlite3`, built-in HTML/CSS/JS, `unittest`.

### Task 1: Connector Data Model

**Files:**
- Modify: `services/review-room-service/review_room_service.py`
- Test: `services/review-room-service/tests/test_review_room_service.py`

**Steps:**
1. Write failing tests for registering scoped agent identities on a Room Board.
2. Implement connector/session records as identity and audit metadata, not as a promise that a live local Agent exists.
3. Verify identity list is returned from `get_room` without exposing secrets.

### Task 2: Connector Event Ingestion

**Files:**
- Modify: `services/review-room-service/review_room_service.py`
- Test: `services/review-room-service/tests/test_review_room_service.py`

**Steps:**
1. Write failing tests for scoped agents creating messages, tasks, and findings.
2. Implement event ingestion / MCP tool handlers with token validation.
3. Verify invalid token is rejected and valid token writes auditable Room Board events.

### Task 3: Control Plane UI

**Files:**
- Modify: `services/review-room-service/review_room_service.py`
- Test: `services/review-room-service/tests/test_review_room_service.py`

**Steps:**
1. Write failing HTML smoke test for real product actions: create Room Board, create MCP invite, view Agent Inbox, view Tasks, view Findings / Decisions.
2. Replace demo-first page with a Room Board UI that still keeps demo seed as optional sample data.
3. Verify browser flow with local Chrome.

### Task 4: Documentation

**Files:**
- Modify: `services/review-room-service/README.md`
- Modify: `docs/plans/2026-06-10-lighthouse-review-room-delivery.md`

**Steps:**
1. Document the shared blackboard usage path.
2. Document Remote MCP tools and legacy connector curl examples separately.
3. Verify commands against the running service.
