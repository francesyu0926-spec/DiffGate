from pathlib import Path

from app.engine.reverse_trace import ImpactReport, ReverseTraceEngine


def analyze_impact(
    repo_path: Path,
    base_sha: str,
    head_sha: str,
    repo_key: str,
    use_neo4j: bool,
    job_id: str | None = None,
    scan_root: str = ".",
) -> ImpactReport:
    return ReverseTraceEngine().run(
        repo_path=repo_path,
        base_sha=base_sha,
        head_sha=head_sha,
        repo_key=repo_key,
        use_neo4j=use_neo4j,
        job_id=job_id,
        scan_root=scan_root,
    )