from app.services.test_suite_webhook import _urls_match, push_touches_case_path


def test_urls_match_https_git():
    assert _urls_match(
        "https://github.com/acme/order-tests.git",
        "git@github.com:acme/order-tests.git",
    )


def test_push_touches_case_path_prefix():
    assert push_touches_case_path(["cases/order/new.yaml"], "cases/order")
    assert not push_touches_case_path(["README.md"], "cases/order")