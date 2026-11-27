from app.services.git_credential_chain import (
    gitlab_instances_match,
    normalize_git_netloc,
    resolve_git_clone_credentials,
)
from app.services.repo_detect_parse import CloneUrlMeta, parse_clone_url_meta


def test_normalize_git_netloc_private_port():
    assert normalize_git_netloc("http://gitlab.corp.local:8080") == "gitlab.corp.local:8080"


def test_gitlab_instances_match_private():
    meta = parse_clone_url_meta("http://gitlab.corp.local:8080/qa/tests.git")
    assert meta is not None
    assert gitlab_instances_match(meta, "http://gitlab.corp.local:8080")


def test_resolve_explicit_token_first():
    class _Db:
        def get(self, *_a, **_k):
            return None

    creds = resolve_git_clone_credentials(
        _Db(),  # type: ignore[arg-type]
        "https://gitlab.corp.local/qa/tests.git",
        explicit_auth_method="token",
        explicit_token="deploy-token-secret",
    )
    assert creds.credential_source == "explicit"
    assert creds.access_token == "deploy-token-secret"


def test_resolve_anonymous_when_no_creds():
    class _Db:
        def get(self, *_a, **_k):
            return None

    creds = resolve_git_clone_credentials(
        _Db(),  # type: ignore[arg-type]
        "https://gitlab.corp.local/qa/tests.git",
    )
    assert creds.credential_source == "anonymous"
    assert creds.auth_method == "none"


def test_session_match_github():
    from types import SimpleNamespace

    from app.services.git_credential_chain import session_matches_clone_url

    meta = CloneUrlMeta("github", "org", "repo", "org/repo", transport="http", host="github.com")
    user = SimpleNamespace(provider="github", username="dev")
    sess = SimpleNamespace(
        platform_provider="github",
        platform_access_token="ghp_xxx",
        gitlab_base_url=None,
    )
    assert session_matches_clone_url(sess, user, meta)  # type: ignore[arg-type]