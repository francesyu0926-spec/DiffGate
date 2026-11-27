from app.services.clone_url_normalize import (
    clone_url_match_key,
    clone_url_repo_slug,
    collect_incoming_clone_keys,
    record_matches_platform_repo,
)


def test_clone_url_http_ssh_same_key() -> None:
    http = "https://github.com/acme/foo.git"
    ssh = "git@github.com:acme/foo.git"
    assert clone_url_match_key(http) == clone_url_match_key(ssh)
    assert clone_url_repo_slug(http) == "acme/foo"


def test_gitlab_http_ssh_slug() -> None:
    http = "https://gitlab.com/team/app.git"
    ssh = "git@gitlab.com:team/app.git"
    keys, slugs, fps = collect_incoming_clone_keys(http, ssh)
    assert "team/app" in slugs
    assert len(slugs) == 1
    assert len(fps) >= 1


def test_record_matches_platform_with_suffix() -> None:
    assert record_matches_platform_repo("acme/foo (backend)", "acme/foo")
    assert not record_matches_platform_repo("other/bar", "acme/foo")