from pathlib import Path

from app.adapters.java_adapter import index_java


def test_index_java_spring_routes(tmp_path: Path):
    root = tmp_path / "src/main/java/com/example"
    root.mkdir(parents=True)
    java = root / "OrderController.java"
    java.write_text(
        """
package com.example;

@RestController
@RequestMapping("/api/v1/orders")
public class OrderController {
    @GetMapping("/{id}")
    public String get() { return orderService.find(1); }
}
""".strip(),
        encoding="utf-8",
    )
    ir = index_java(
        repo_id="rid",
        repo_full_name="acme/order",
        repo_dir=tmp_path,
        scan_root="src/main/java",
    )
    assert ir.language == "java"
    assert len(ir.endpoints) >= 1
    ep = ir.endpoints[0]
    assert ep.method == "GET"
    assert "/api/v1/orders" in ep.path or ep.path.endswith("/{id}")
    assert ir.meta.get("index_mode") == "regex_spring"