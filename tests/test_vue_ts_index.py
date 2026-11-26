from pathlib import Path

from app.parsers.vue_ts_index import extract_vue_scripts, scan_frontend_repo, trace_frontend_impact


def test_extract_vue_script():
    src = '<template><div/></template>\n<script setup lang="ts">\nimport x from "./api"\n</script>\n'
    script = extract_vue_scripts(src)
    assert 'import x from "./api"' in script


def test_trace_api_and_route(tmp_path: Path):
    web = tmp_path / "web" / "src"
    web.mkdir(parents=True)
    (web / "api.ts").write_text(
        'import axios from "axios"\nexport function load() { return axios.get("/api/v1/users") }\n',
        encoding="utf-8",
    )
    (web / "router.ts").write_text(
        """
        import Home from './views/Home.vue'
        export default createRouter({
          routes: [{ path: '/users', component: () => import('./views/Home.vue') }]
        })
        """,
        encoding="utf-8",
    )
    (web / "views").mkdir()
    (web / "views" / "Home.vue").write_text(
        '<script setup lang="ts">\nimport { load } from "../api"\nload()\n</script>',
        encoding="utf-8",
    )
    idx = scan_frontend_repo(tmp_path, scan_roots=("web",))
    impact = trace_frontend_impact(idx, {"web/src/api.ts"}, tmp_path)
    assert impact["stats"]["api_call_count"] >= 1
    paths = {c["path"] for c in impact.get("frontend_api_calls") or []}
    assert "/api/v1/users" in paths