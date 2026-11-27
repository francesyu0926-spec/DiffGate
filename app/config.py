from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "DiffGate"
    debug: bool = False
    webhook_secret_github: str = ""
    webhook_secret_gitlab: str = ""
    # 公网回调根地址（如 https://xxx.ngrok-free.app），供界面展示；无则仅用相对路径
    webhook_public_base_url: str = ""

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # 本地无 Docker 可用 sqlite:///./data/diffgate.db
    mysql_dsn: str = "mysql+pymysql://diffgate:diffgate@localhost:3306/diffgate"

    use_redis: bool = True
    local_data_dir: str = "./data"

    use_neo4j: bool = True
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "diffgate123"

    repo_clone_root: str = "./data/repos"

    # 精准回归调度中心（第四步联动）；为空则跳过
    # 本地测试可设 http://127.0.0.1:8000/api/v1/dispatch/regression
    dispatch_center_url: str = ""

    # DiffGate API 根地址，供调度 payload / coverage.py 回传门禁
    api_public_base_url: str = "http://127.0.0.1:8000"

    # 本地单进程：FastAPI BackgroundTasks 执行分析，仅需 uvicorn（默认）
    use_background_tasks: bool = True
    # 为 True 时 Celery 在 API 进程内同步跑任务（仍依赖 celery 包，不需 Worker）
    celery_always_eager: bool = False

    # Webhook 同分支防抖窗口（秒）；0 表示关闭
    webhook_debounce_seconds: int = 20
    # 分析完成后仍未收到 gate-report 的探针回传超时（分钟）
    probe_return_timeout_minutes: int = 30
    # 分析使用 git worktree 沙箱（多分支并发）
    use_job_worktree: bool = True
    # Vue/TS tree-sitter 全栈追溯 + 跨仓 HTTP Client 扫描
    use_fullstack_trace: bool = True

    # 可选：企业级 Java 静态分析 CLI（diffgate-java-analyzer.jar）
    java_analyzer_jar: str = ""

    # 可选：Go 静态分析 CLI（diffgate-go-ast）
    go_analyzer_bin: str = ""

    # 平台状态回写 / IM
    github_token: str = ""
    github_pr_comments: bool = True
    gitlab_token: str = ""
    # 内网 / 非标准端口 GitLab 默认放宽 SSL（可被仓库/用例集 skip_ssl_verify 覆盖）
    git_skip_ssl_verify_internal: bool = True
    feishu_webhook_url: str = ""
    dingtalk_webhook_url: str = ""
    wecom_webhook_url: str = ""

    # RBAC：可信 Header X-DiffGate-User / X-DiffGate-Role（由反向代理注入）
    default_actor_name: str = "developer"
    default_actor_role: str = "dev"
    override_roles: str = "qa,pm,admin,owner"
    # 前端精准回归页根地址（IM 卡片「人工豁免」链接）
    web_app_public_base_url: str = "http://127.0.0.1:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()