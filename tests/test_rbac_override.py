from types import SimpleNamespace

import pytest

from app.services.rbac import SessionActor, evaluate_override_eligibility, require_override_permission


def test_dev_cannot_override():
    actor = SessionActor(username="alice", role="dev", can_override=False)
    ev = evaluate_override_eligibility(actor, gate="BLOCK")
    assert ev["allowed"] is False
    assert ev["reason"] == "insufficient_role"


def test_qa_self_submit_blocked():
    job = SimpleNamespace(
        job_metadata={"commit_author_username": "bob", "commit_author_email": "bob@corp.com"},
        gate_result={"gate": "BLOCK", "allow_override": True},
    )
    actor = SessionActor(username="bob", role="qa", email="bob@corp.com", can_override=True)
    ev = evaluate_override_eligibility(actor, job=job, repo=None, gate="BLOCK")
    assert ev["allowed"] is False
    assert ev["reason"] == "self_submit"
    with pytest.raises(PermissionError, match="互斥"):
        require_override_permission(actor, job=job, repo=None)


def test_qa_self_submit_allowed_when_repo_flag():
    job = SimpleNamespace(
        job_metadata={"commit_author_username": "bob"},
        gate_result={"gate": "BLOCK"},
    )
    repo = SimpleNamespace(allow_self_override=True)
    actor = SessionActor(username="bob", role="qa", can_override=True)
    ev = evaluate_override_eligibility(actor, job=job, repo=repo, gate="BLOCK")
    assert ev["allowed"] is True