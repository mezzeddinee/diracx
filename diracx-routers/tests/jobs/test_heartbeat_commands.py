from __future__ import annotations

from datetime import datetime, timezone
from time import sleep

import pytest
from fastapi.testclient import TestClient

from diracx.core.models.job import JobStatus


pytestmark = pytest.mark.enabled_dependencies(
    [
        "AuthSettings",
        "JobDB",
        "JobLoggingDB",
        "ConfigSource",
        "TaskQueueDB",
        "SandboxMetadataDB",
        "WMSAccessPolicy",
        "DevelopmentSettings",
        "JobParametersDB",
    ]
)


def test_kill_command_created_and_delivered_once(
    normal_user_client: TestClient,
    valid_job_id: int,
):
    """
    Verify lifecycle of a Kill command:

    1. Job initially has no commands.
    2. Setting Status=KILLED creates a Kill command.
    3. Command is delivered on next heartbeat.
    4. Command is not re-delivered.
    """

    # ------------------------------------------------------------------
    # 1️⃣ Initial heartbeat → no commands
    # ------------------------------------------------------------------
    r = normal_user_client.patch(
        "/api/jobs/heartbeat",
        json={valid_job_id: {"Vsize": 1000}},
    )
    r.raise_for_status()
    assert r.json() == []

    # ------------------------------------------------------------------
    # 2️⃣ Set job to KILLED (creates Kill command internally)
    # ------------------------------------------------------------------
    r = normal_user_client.patch(
        "/api/jobs/status",
        json={
            valid_job_id: {
                datetime.now(timezone.utc).isoformat(): {
                    "Status": JobStatus.KILLED,
                    "MinorStatus": "Marked for termination",
                }
            }
        },
    )
    r.raise_for_status()

    # Avoid heartbeat timestamp collision
    sleep(1)

    # ------------------------------------------------------------------
    # 3️⃣ First heartbeat → command delivered
    # ------------------------------------------------------------------
    r = normal_user_client.patch(
        "/api/jobs/heartbeat",
        json={valid_job_id: {"Vsize": 1001}},
    )
    r.raise_for_status()

    commands = r.json()

    assert len(commands) == 1
    assert commands[0]["job_id"] == valid_job_id
    assert commands[0]["command"] == "Kill"

    sleep(1)

    # ------------------------------------------------------------------
    # 4️⃣ Second heartbeat → command NOT delivered again
    # ------------------------------------------------------------------
    r = normal_user_client.patch(
        "/api/jobs/heartbeat",
        json={valid_job_id: {"Vsize": 1002}},
    )
    r.raise_for_status()

    assert r.json() == []


def test_multiple_jobs_receive_independent_kill_commands(
    normal_user_client: TestClient,
    valid_job_ids: list[int],
):
    """
    Verify that multiple jobs each receive their own Kill command
    and there is no cross-contamination.
    """

    job_ids = valid_job_ids

    # ------------------------------------------------------------------
    # Kill all jobs
    # ------------------------------------------------------------------
    r = normal_user_client.patch(
        "/api/jobs/status",
        json={
            job_id: {
                datetime.now(timezone.utc).isoformat(): {
                    "Status": JobStatus.KILLED,
                    "MinorStatus": "Marked for termination",
                }
            }
            for job_id in job_ids
        },
    )
    r.raise_for_status()

    sleep(1)

    # ------------------------------------------------------------------
    # Heartbeat all jobs at once
    # ------------------------------------------------------------------
    r = normal_user_client.patch(
        "/api/jobs/heartbeat",
        json={job_id: {"Vsize": 2000} for job_id in job_ids},
    )
    r.raise_for_status()

    commands = r.json()

    assert len(commands) == len(job_ids)

    returned_ids = {cmd["job_id"] for cmd in commands}
    assert returned_ids == set(job_ids)

    for cmd in commands:
        assert cmd["command"] == "Kill"

    sleep(1)

    # ------------------------------------------------------------------
    # Second heartbeat → no commands anymore
    # ------------------------------------------------------------------
    r = normal_user_client.patch(
        "/api/jobs/heartbeat",
        json={job_id: {"Vsize": 2001} for job_id in job_ids},
    )
    r.raise_for_status()

    assert r.json() == []




def test_non_killed_status_does_not_create_command(
    normal_user_client: TestClient,
    valid_job_id: int,
):
    """
    Verify that updating a job to a non-KILLED status
    does not create any JobCommand.
    """

    # Set job to RUNNING
    r = normal_user_client.patch(
        "/api/jobs/status",
        json={
            valid_job_id: {
                datetime.now(timezone.utc).isoformat(): {
                    "Status": "Running",
                    "MinorStatus": "Normal transition",
                }
            }
        },
    )
    r.raise_for_status()

    sleep(1)

    # Heartbeat → should return no commands
    r = normal_user_client.patch(
        "/api/jobs/heartbeat",
        json={valid_job_id: {"Vsize": 500}},
    )
    r.raise_for_status()

    assert r.json() == []


def test_command_delivered_exactly_once(
    normal_user_client: TestClient,
    valid_job_id: int,
):
    """
    Explicitly verify that a Kill command is delivered
    exactly once and removed after delivery.
    """

    # Kill job
    normal_user_client.patch(
        "/api/jobs/status",
        json={
            valid_job_id: {
                datetime.now(timezone.utc).isoformat(): {
                    "Status": "Killed",
                    "MinorStatus": "Termination requested",
                }
            }
        },
    ).raise_for_status()

    sleep(1)

    # First heartbeat → get Kill
    r = normal_user_client.patch(
        "/api/jobs/heartbeat",
        json={valid_job_id: {"Vsize": 111}},
    )
    r.raise_for_status()

    assert len(r.json()) == 1

    sleep(1)

    # Second heartbeat → no more commands
    r = normal_user_client.patch(
        "/api/jobs/heartbeat",
        json={valid_job_id: {"Vsize": 112}},
    )
    r.raise_for_status()

    assert r.json() == []

def test_deleted_creates_kill_command(
    normal_user_client: TestClient,
    valid_job_id: int,
):
    """
    Verify that transitioning a job to DELETED
    creates a Kill JobCommand (same behavior as KILLED).
    """

    # Transition to DELETED
    r = normal_user_client.patch(
        "/api/jobs/status",
        json={
            valid_job_id: {
                datetime.now(timezone.utc).isoformat(): {
                    "Status": "Deleted",
                    "MinorStatus": "User removed job",
                }
            }
        },
    )
    r.raise_for_status()

    sleep(1)

    # Heartbeat should deliver Kill command
    r = normal_user_client.patch(
        "/api/jobs/heartbeat",
        json={valid_job_id: {"Vsize": 123}},
    )
    r.raise_for_status()

    commands = r.json()

    assert len(commands) == 1
    assert commands[0]["job_id"] == valid_job_id
    assert commands[0]["command"] == "Kill"

    # Second heartbeat → no command anymore
    sleep(1)
    r = normal_user_client.patch(
        "/api/jobs/heartbeat",
        json={valid_job_id: {"Vsize": 124}},
    )
    r.raise_for_status()

    assert r.json() == []


