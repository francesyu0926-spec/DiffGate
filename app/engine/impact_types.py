from dataclasses import dataclass, field


@dataclass
class SuspectFunction:
    qualified_name: str
    file_path: str
    start_line: int
    end_line: int
    changed_lines: list[int] = field(default_factory=list)