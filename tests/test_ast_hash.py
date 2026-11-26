import textwrap

from app.parsers.ast_hash import function_body_hash


def test_cosmetic_reformat_same_hash():
    a = textwrap.dedent(
        """
        def foo(x):
            return x + 1
        """
    )
    b = textwrap.dedent(
        """
        def foo(x):

            # comment only
            return x + 1
        """
    )
    assert function_body_hash(a, "mod.foo") == function_body_hash(b, "mod.foo")


def test_logic_change_different_hash():
    a = "def foo(x):\n    return x + 1\n"
    b = "def foo(x):\n    return x + 2\n"
    assert function_body_hash(a, "mod.foo") != function_body_hash(b, "mod.foo")