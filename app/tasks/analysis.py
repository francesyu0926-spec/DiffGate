from app.celery_app import celery
from app.services.analysis_runner import run_analyze_merge


@celery.task(bind=True, name="diffgate.analyze_merge")
def analyze_merge_task(
    self,
    job_id: str,
    provider: str,
    repo_full_name: str,
    clone_url: str,
    base_sha: str,
    head_sha: str,
    ref: str,
) -> dict:
    return run_analyze_merge(
        job_id,
        provider,
        repo_full_name,
        clone_url,
        base_sha,
        head_sha,
        ref,
    )