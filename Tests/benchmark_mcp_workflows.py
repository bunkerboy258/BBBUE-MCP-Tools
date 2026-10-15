import argparse
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from MCP.mcp_call import McpSession
from BBBMcpCapabilities import ToolCatalog
from test_mcp_discovery import fixture_catalog
from benchmark_mcp_cases import FULL_DISCOVERY_CASES, NATURAL_CASES, VALIDATION_CASES


def main():
    """/** @return 同一目标语料的发现 轮次与上下文基线 */"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url")
    parser.add_argument("--catalog")
    parser.add_argument("--implementation")
    parser.add_argument("--suite", choices=("fixed", "natural", "validation"), default="fixed")
    parser.add_argument("--report", required=True)
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 10:
        raise ValueError("BENCHMARK_REPEAT_RANGE")
    catalog_type = ToolCatalog
    if args.implementation:
        import importlib.util
        spec = importlib.util.spec_from_file_location("benchmark_capabilities", args.implementation)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        catalog_type = module.ToolCatalog
    catalog = fixture_catalog()
    if args.catalog:
        data = json.loads(Path(args.catalog).read_text(encoding="utf-8"))

        class Backend:
            """/** 固定实际注册描述 */"""

            def descriptors(self):
                """/** @return 注册工具 */"""
                return data["descriptors"]

            def external_contracts(self):
                """/** @return 外部领域动作 */"""
                return data["external"]

        if "tools" in data:
            catalog = object.__new__(catalog_type)
            catalog.tools = data["tools"]
            if not args.implementation:
                from MCP.mcp_discovery import SUMMARIES
                for identity, item in catalog.tools.items():
                    if item["summary"] == item["name"] and identity in SUMMARIES:
                        item["summary"] = SUMMARIES[identity]
        if "tools" not in data:
            catalog = catalog_type(Backend())
    session = McpSession(args.url, 30) if args.url else None
    rows = []
    try:
        for query, expected in {"fixed": FULL_DISCOVERY_CASES, "natural": NATURAL_CASES, "validation": VALIDATION_CASES}[args.suite]:
            samples = []
            for repetition in range(args.repeat):
                started = time.perf_counter()
                result = session.find_tools(query) if session else catalog.find(query)
                samples.append(1000 * (time.perf_counter() - started))
            ids = [value["id"] for value in result]
            rows.append({"query": query, "expected": expected, "selected": ids, "top3": bool(set(expected) & set(ids)),
                "top1": bool(ids and ids[0] in expected), "ready_contract": bool(result and "parameters" in result[0]),
                "median_ms": statistics.median(samples), "context_bytes": len(json.dumps(result, ensure_ascii=False).encode())})
    finally:
        if session is not None:
            session.close()
    report = {"method": "fixed_target_discovery", "cases": rows, "top3_success": sum(row["top3"] for row in rows),
        "top1_success": sum(row["top1"] for row in rows), "ready_contracts": sum(row["ready_contract"] for row in rows),
        "median_ms": statistics.median(row["median_ms"] for row in rows), "repeat": args.repeat, "suite": args.suite,
        "p95_ms": sorted(row["median_ms"] for row in rows)[int((len(rows) - 1) * .95)],
        "median_context_bytes": statistics.median(row["context_bytes"] for row in rows),
        "scope": "discovery_and_required_contract_roundtrips"}
    destination = Path(args.report).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=True))


if __name__ == "__main__":
    main()
