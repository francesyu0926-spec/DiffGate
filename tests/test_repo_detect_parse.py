from app.services.repo_detect_parse import classify_clone_url, parse_clone_url_meta


def test_local_unix_path():
    meta = parse_clone_url_meta("/opt/tests/api-cases")
    assert meta is not None
    assert meta.provider == "local"
    assert meta.transport == "local"


def test_local_windows_path():
    meta = parse_clone_url_meta(r"D:\repos\cases")
    assert meta is not None
    assert meta.transport == "local"


def test_ssh_gitlab_nested_group():
    raw = "git@gitlab.company.internal:qa/team/api-tests.git"
    meta = parse_clone_url_meta(raw)
    assert meta is not None
    assert meta.transport == "ssh"
    assert meta.provider == "gitlab"
    assert meta.full_name == "qa/team/api-tests"
    assert meta.host == "gitlab.company.internal"


def test_https_private_gitlab_with_port():
    raw = "http://10.20.30.40:8080/group/project.git"
    meta = parse_clone_url_meta(raw)
    assert meta is not None
    assert meta.transport == "http"
    assert meta.provider == "gitlab"
    assert meta.base_url == "http://10.20.30.40:8080"
    assert meta.full_name == "group/project"


def test_github_com():
    meta = parse_clone_url_meta("https://github.com/org/repo.git")
    assert meta is not None
    assert meta.provider == "github"


def test_github_enterprise_host():
    meta = parse_clone_url_meta("https://github.mycompany.com/team/service.git")
    assert meta is not None
    assert meta.provider == "github"


def test_classify_suggested_auth_ssh():
    data = classify_clone_url("git@gitlab.com:a/b.git")
    assert data["ok"] is True
    assert data["suggested_auth"] == "ssh"