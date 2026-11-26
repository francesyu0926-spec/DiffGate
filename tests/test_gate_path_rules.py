from app.services.gate_path_rules import effective_threshold, override_allowed_for_job


def test_payment_path_strict_threshold():
    th, rule = effective_threshold(
        ["app/payment/charge.py"],
        repo_rules=None,
        default_threshold=80,
    )
    assert th == 95
    assert rule is not None
    assert rule.allow_override is False


def test_scripts_relaxed_threshold():
    th, _ = effective_threshold(
        ["app/scripts/backup.py"],
        repo_rules=None,
        default_threshold=80,
    )
    assert th == 50


def test_override_blocked_on_payment():
    assert not override_allowed_for_job(["app/payment/x.py"], None)
    assert override_allowed_for_job(["app/utils/helper.py"], None)