from types import SimpleNamespace

from app.services.job_execution_state import (
    finalize_after_analysis,
    mark_cancelled,
    mark_completed_after_probe,
    mark_env_mismatch,
)


def test_finalize_awaiting_probe_when_needs_coverage():
    job = SimpleNamespace(
        status="running",
        gate_result={"executable_changed_lines": 5, "diff_lines_total": 8},
        job_metadata={},
    )
    finalize_after_analysis(job)
    assert job.status == "awaiting_probe"


def test_finalize_completed_when_not_required():
    job = SimpleNamespace(
        status="running",
        gate_result={"coverage_not_required": True, "diff_lines_total": 3},
        job_metadata={},
    )
    finalize_after_analysis(job)
    assert job.status == "completed"


def test_mark_cancelled_writes_metadata():
    job = SimpleNamespace(status="running", job_metadata={}, error_message=None)
    mark_cancelled(job)
    assert job.status == "cancelled"
    assert job.job_metadata.get("execution_phase") == "cancelled"


def test_probe_success_moves_to_completed():
    job = SimpleNamespace(status="awaiting_probe", gate_result={"probe_status": "TIMEOUT"}, job_metadata={})
    mark_completed_after_probe(job)
    assert job.status == "completed"
    assert "probe_status" not in job.gate_result


def test_env_mismatch_state():
    job = SimpleNamespace(status="awaiting_probe", gate_result={}, job_metadata={})
    mark_env_mismatch(job, running="a" * 40, target="b" * 40)
    assert job.status == "env_mismatch"
    assert job.gate_result.get("probe_status") == "ENV_MISMATCH"