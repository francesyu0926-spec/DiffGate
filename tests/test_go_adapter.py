from pathlib import Path

from app.adapters.go_adapter import index_go


def test_index_go_gin_routes(tmp_path: Path):
    pkg = tmp_path / "handlers"
    pkg.mkdir()
    (pkg / "orders.go").write_text(
        """
package handlers

import "github.com/gin-gonic/gin"

func Register(r *gin.Engine) {
    v1 := r.Group("/api/v1")
    v1.GET("/orders", listOrders)
}

func listOrders(c *gin.Context) {}
""".strip(),
        encoding="utf-8",
    )
    ir = index_go(repo_id="rid", repo_full_name="acme/go-api", repo_dir=tmp_path, scan_root=".")
    assert ir.language == "go"
    assert len(ir.endpoints) >= 1
    ep = ir.endpoints[0]
    assert ep.method == "GET"
    assert "orders" in ep.path