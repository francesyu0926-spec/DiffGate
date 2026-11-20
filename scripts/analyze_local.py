"""Analyze a local git repo without webhooks."""

import argparse
from pathlib import Path

from git import Repo

from app.services.impact import analyze_impact


def main() -> None:
    parser = argparse.ArgumentParser(description="DiffGate AST reverse API tracing")
    parser.add_argument("--repo", required=True, help="Path to git repository")
    parser.add_argument("--base", required=True, help="Base ref or SHA")
    parser.add_argument("--head", default="HEAD", help="Head ref or SHA")
    parser.add_argument("--no-neo4j", action="store_true")
    args = parser.parse_args()

    repo_path = Path(args.repo).resolve()
    git = Repo(str(repo_path))
    base_sha = git.commit(args.base).hexsha
    head_sha = git.commit(args.head).hexsha
    repo_key = repo_path.name

    report = analyze_impact(
        repo_path=repo_path,
        base_sha=base_sha,
        head_sha=head_sha,
        repo_key=repo_key,
        use_neo4j=not args.no_neo4j,
    )

    print(f"[Step2] 变更行块: {len(report.line_ranges)}")
    print(f"[Step2] 嫌疑函数: {len(report.suspect_functions)}")
    for s in report.suspect_functions:
        print(f"  - {s.qualified_name} ({s.file_path}:{s.start_line}-{s.end_line})")
    print(f"[Step3/4] 影响 API: {len(report.affected_apis)}")
    for path in report.call_paths:
        chain = " -> ".join(path["chain_labels"])
        print(f"  {path['method']} {path['path']}")
        print(f"    链路: {chain}")


if __name__ == "__main__":
    main()