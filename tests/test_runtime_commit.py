from app.services.runtime_commit import sha_matches_target


def test_sha_matches_full_and_prefix():
    target = "abcdef1234567890" * 2 + "abcd"
    assert sha_matches_target(target, target)
    assert sha_matches_target(target[:12], target)