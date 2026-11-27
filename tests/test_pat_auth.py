"""PAT 登录 RBAC 与会话解析（轻量单测）。"""

from app.services.rbac import actor_can_override, actor_from_headers


def test_admin_can_override():
    assert actor_can_override("admin") is True


def test_dev_cannot_override_by_default():
    assert actor_can_override("dev") is False


def test_qa_can_override():
    assert actor_can_override("qa") is True


def test_header_fallback_actor():
    actor = actor_from_headers("alice", "qa", "alice@example.com")
    assert actor.username == "alice"
    assert actor.can_override is True