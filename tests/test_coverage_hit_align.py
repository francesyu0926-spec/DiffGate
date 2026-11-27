from app.services.coverage_hit_align import propagate_multiline_hits

SRC = """def f():
    return some_call(
        1,
        2,
    )
"""

def test_propagate_multiline_hits_when_head_hit():
    effective = {("a.py", 2), ("a.py", 3), ("a.py", 4), ("a.py", 5)}
    executed = {("a.py", 2)}
    out = propagate_multiline_hits(effective, executed, {"a.py": SRC})
    assert ("a.py", 3) in out
    assert ("a.py", 4) in out
    assert ("a.py", 5) in out