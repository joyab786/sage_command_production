# SageCommand V3 — Event-Driven Architecture (Prompt 17)

## Overview

The **Event-Driven Architecture Foundation** establishes an internal publish-subscribe mechanism for SageCommand V3, bridging the gap between canonical event generation and domain-specific execution safely, deterministically, and idempotently.

This implementation satisfies the requirements of **Prompt 17**, ensuring complete tenant isolation and adhering strictly to the constraint of keeping execution logic out of the event bus itself.

## Core Capabilities

1. **Deterministic Fingerprinting & Idempotency**: 
   The Event Bus leverages the canonical event fingerprint and subscription ID to generate a deterministic delivery identity via SHA-256 (`compute_delivery_id`). This ensures that duplicate events are not re-processed across system crashes.
2. **Strict Tenant Isolation**:
   Subscriptions are scoped to a tenant. The `EventBus` verifies tenant boundary constraints before invoking subscriber callbacks, preventing cross-tenant data leakage.
3. **Bounded & Resilient Queueing**:
   Built on `asyncio.Queue` with a bounded configuration (`SAGE_EVENT_BUS_QUEUE_SIZE`), background workers continuously process pending events safely without blocking incoming HTTP threads.
4. **Reliable Retries & Dead Lettering**:
   Failed deliveries are retried using a bounded exponential backoff. Upon exhausting max retries (`SAGE_EVENT_BUS_MAX_RETRIES`), the payload is moved into a dead-letter queue for operator inspection.
5. **Separation of Execution**:
   The `EventBus` makes zero assumptions about what a subscriber does. It intentionally does **not** import or execute `ExecutionGateway`. It merely delivers the Canonical Event to in-memory callbacks.

## Data Persistence

Delivery metadata and dead letters are persisted using a lightweight SQLite repository (`EventDeliveryRepository`) with Write-Ahead Logging (WAL) and foreign-key enforcement. The database schema clearly splits operational delivery states from the canonical event store.

* `Subscription`: Defines subscriber matching criteria.
* `EventDelivery`: Tracks delivery attempts, status, and backoff states.
* `DeadLetter`: Captures terminally failed event dispatches.

## API Endpoints

The architecture exposes read-only endpoints strictly meant for operational inspection.

* `GET /api/v3/event-bus/status`
* `GET /api/v3/event-bus/subscriptions`
* `GET /api/v3/event-bus/deliveries`
* `GET /api/v3/event-bus/dead-letters`

## Internal Workflow

1. A client invokes `POST /api/v3/events` to record an event.
2. The endpoint calls `repo.record_event()` for deduplication and persistence.
3. The endpoint delegates the saved Canonical Event to `bus.publish(saved_event)`.
4. `publish` identifies matching subscriptions, generates unique delivery IDs, persists pending statuses, and enqueues.
5. Background worker tasks drain the queue, invoke in-memory callbacks, update statuses to `SUCCESS` or increment retry counts, ultimately resolving or dead-lettering.
