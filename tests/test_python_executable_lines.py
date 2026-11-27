from app.services.python_executable_lines import filter_diff_changed_lines, get_effective_executable_lines

SAMPLE = '''"""module doc"""
import os

class M:
    """cls doc"""
    user_id: str

    def run(self):
        pass
        x = 1  # inline ok
        return x
'''


def test_get_effective_executable_lines():
    eff = get_effective_executable_lines(SAMPLE)
    assert 1 not in eff  # module docstring block
    assert 2 not in eff  # import os
    assert 5 not in eff  # class docstring
    assert 6 not in eff  # user_id: str
    assert 9 not in eff  # pass
    assert 8 in eff  # def run
    assert 10 in eff  # x = 1
    assert 11 in eff  # return x


def test_type_checking_block_excluded():
    src = """from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from foo import Bar

def run():
    return 1
"""
    eff = get_effective_executable_lines(src)
    assert 4 not in eff and 5 not in eff
    assert 6 in eff and 7 in eff


def test_multiline_import_and_docstring_spans():
    src = '''"""line one
line two
line three"""
from pkg import (
    a,
    b,
)
x = 1
'''
    eff = get_effective_executable_lines(src)
    assert 1 not in eff and 2 not in eff and 3 not in eff
    assert 4 not in eff and 5 not in eff and 6 not in eff and 7 not in eff
    assert 8 in eff


def test_filter_diff_changed_lines():
    diff = {1, 2, 6, 9, 10, 11}
    out = filter_diff_changed_lines("app/x.py", SAMPLE, diff)
    assert out["effective_lines"] == [10, 11]
    assert 2 in out["ignored_lines"]
    assert 6 in out["ignored_lines"]