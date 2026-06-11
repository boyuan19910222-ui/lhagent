# Lighthouse Review Room Productization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the Review Room prototype into a usable local product slice where Lighthouse is the Room control plane and local/remote agents connect through named connectors.

**Architecture:** Keep the dependency-free Python service as the local Lighthouse Review Room backend for this slice. Add connector records, scoped connector tokens, and a generic event ingestion endpoint so local and remote agents can join the same Room without using demo-only buttons. The HTML page becomes a control-plane UI for creating a Room, provisioning connectors, viewing connector status, and watching real agent events flow into the Room.

**Tech Stack:** Python standard library `http.server` + `sqlite3`, built-in HTML/CSS/JS, `unittest`.

### Task 1: Connector Data Model

**Files:**
- Modify: `services/review-room-service/review_room_service.py`
- Test: `services/review-room-service/tests/test_review_room_service.py`

**Steps:**
1. Write failing tests for registering `local-agent` and `remote-agent` connectors on a Room.
2. Implement `connectors` table and store methods.
3. Verify connector list is returned from `get_room`.

### Task 2: Connector Event Ingestion

**Files:**
- Modify: `services/review-room-service/review_room_service.py`
- Test: `services/review-room-service/tests/test_review_room_service.py`

**Steps:**
1. Write failing tests for connector events creating messages and findings.
2. Implement `/api/connectors/{id}/events` with token validation.
3. Verify invalid token is rejected and valid token writes Room timeline.

### Task 3: Control Plane UI

**Files:**
- Modify: `services/review-room-service/review_room_service.py`
- Test: `services/review-room-service/tests/test_review_room_service.py`

**Steps:**
1. Write failing HTML smoke test for real product actions: create Room, add local connector, add remote connector, connector event endpoint.
2. Replace demo-first page with a Room control-plane UI that still keeps demo seed as optional sample data.
3. Verify browser flow with local Chrome.

### Task 4: Documentation

**Files:**
- Modify: `services/review-room-service/README.md`
- Modify: `docs/plans/2026-06-10-lighthouse-review-room-delivery.md`

**Steps:**
1. Document the real usage path.
2. Document local/remote connector curl examples.
3. Verify commands against the running service.
