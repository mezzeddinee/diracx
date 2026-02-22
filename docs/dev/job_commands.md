## Job Heartbeat & Commands – Documentation and Tests

This addresses issue #445 by:

- Adding router-level tests for heartbeat and job commands.
- Documenting the purpose and lifecycle of job commands.
- Providing diagrams for clarity.

---

## What Are Job Commands?

Job commands implement a **per-job control queue** between the WMS and the pilot (JobAgent).

They allow the WMS to send control instructions to running jobs via the heartbeat mechanism.

Currently used for:

- Remote job termination (`Kill` command)

The mechanism is generic and could support additional commands in the future (e.g. debug actions, core dump requests, etc.).

---

## Behaviour Summary

### Command Creation

When a job transitions to a terminal state (`KILLED` or `DELETED`),  
`set_job_statuses()` enqueues a `Kill` command in the JobDB.

### Command Delivery

Commands are delivered during:

```text
PATCH /api/jobs/heartbeat
```

Flow:

1. Heartbeat updates job state.
2. `get_job_commands()` retrieves pending commands.
3. Commands are marked as sent.
4. Commands are returned to the pilot.

This guarantees **one-shot delivery semantics**:

- A command is delivered exactly once.
- It is not re-delivered on subsequent heartbeats.

---

## Sequence Diagram (Kill Command Lifecycle)

```mermaid
sequenceDiagram
    autonumber
    participant User
    participant Router
    participant BL
    participant JobDB
    participant Pilot

    User->>Router: PATCH /api/jobs/status (Killed)
    Router->>BL: set_job_statuses()
    BL->>JobDB: update status → KILLED
    BL->>JobDB: enqueue "Kill"
    Router-->>User: 200 OK

    Pilot->>Router: PATCH /api/jobs/heartbeat
    Router->>BL: add_heartbeat()
    Router->>BL: get_job_commands()
    BL->>JobDB: fetch + mark sent
    Router-->>Pilot: [Kill]

    Pilot->>Router: PATCH /api/jobs/heartbeat
    Router->>BL: get_job_commands()
    Router-->>Pilot: []
```

---

## Activity View

```mermaid
flowchart TD
    A[Status change → KILLED] --> B[Enqueue Kill command]
    B --> C[Stored in JobDB]

    D[Heartbeat] --> E[Fetch commands]
    E --> F[Mark as sent]
    F --> G[Return to pilot]
    G --> D
```

---

## Tests Added

Router-level tests verify:

- Heartbeat returns `list[JobCommand]`.
- Kill command is created when status → `KILLED`.
- Kill command is delivered exactly once.
- Subsequent heartbeats return no duplicate commands.
- Non-terminal status transitions do not create commands.

This confirms correct queue semantics and router wiring.****