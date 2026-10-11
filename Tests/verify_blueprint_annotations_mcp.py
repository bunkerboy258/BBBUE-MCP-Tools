import argparse
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))
from MCP.mcp_call import McpSession


def main():
    """/** @return 只读接口契约和可选真实图表预览验证 */"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--graph")
    parser.add_argument("--automation", action="store_true")
    args = parser.parse_args()
    with McpSession(args.url, timeout_seconds=120) as session:
        def call(tool, arguments=None):
            """/** @param tool 稳定 ID @param arguments 参数 @return 完成后的单项结果 */"""
            session.describe_tool(tool)
            identity = session.submit_batch([{"tool": tool, "arguments": arguments or {}}], "蓝图注释验收")["batch"]
            value = session.wait_batch(identity, 180)
            assert value["status"] == "completed", value
            session.control_task("close", identity)
            return value["results"][0]
        dependencies = call("runtime.inspect_mcp_dependencies", {"tool": "blueprint.inspect_blueprint_graph"})
        assert Path(dependencies["project_root"]).resolve() == Path(args.project_root).resolve()
        assert dependencies["native_dependencies_ready"], dependencies
        for name in ("inspect_blueprint_graph", "inspect_blueprint_graph_logic", "annotate_blueprint_graph"):
            descriptor = session.describe_tool("blueprint." + name)
            assert "graph_path" in descriptor["parameters"]["properties"]
        print(json.dumps({"schemas": 3, "process_id": dependencies["process_id"]}, ensure_ascii=False))
        if args.graph:
            dirty = call("editor.inspect_dirty_packages")
            snapshot = call("blueprint.inspect_blueprint_graph", {"graph_path": args.graph})
            logic = call("blueprint.inspect_blueprint_graph_logic", {"graph_path": args.graph})
            assert "geometry" not in logic, "逻辑读取触发显示测量"
            assert logic["snapshot"] == snapshot["snapshot"] and logic["nodes"] == snapshot["nodes"], "两种读取的逻辑身份不一致"
            assert snapshot["layoutSupported"], snapshot["warnings"]
            candidates = [item for item in snapshot["nodes"] if not item["isComment"] and not item["nodeComment"]]
            assert candidates, "图表没有空注释节点"
            claimed = {key for item in snapshot["nodes"] if item["isComment"] for key in item["members"]}
            members = sorted(item["guid"] for item in snapshot["nodes"] if not item["isComment"] and item["guid"] not in claimed)
            blocks = [{"title": "图表逻辑区块", "description": "根据本图的连接组织逻辑节点", "members": members}] if members else []
            request = {
                "expectedSnapshot": snapshot["snapshot"], "blocks": blocks,
                "nodeComments": [{"nodeGuid": candidates[0]["guid"], "text": "读取此节点的输入并计算输出"}],
            }
            preview = call("blueprint.annotate_blueprint_graph", {"graph_path": args.graph, "annotations_json": json.dumps(request, ensure_ascii=False), "dry_run": True})
            after = call("blueprint.inspect_blueprint_graph", {"graph_path": args.graph})
            assert snapshot == after, "只读预览改变了图表"
            assert dirty == call("editor.inspect_dirty_packages"), "预览改变脏资产列表"
            print(json.dumps({"graph": args.graph, "nodes": len(snapshot["nodes"]), "blocks": len(preview["blocks"]), "warnings": snapshot["warnings"], "before": preview["before"], "after": preview["after"], "canApply": preview["canApply"], "unchanged": True}, ensure_ascii=False))

        if args.automation:
            result = call("editor.run_automation_tests", {"test_filter": "BBB.BlueprintAnnotations.Transaction"})
            with Path(result["log_file"]).open("rb") as handle:
                handle.seek(result["log_offset"])
                output = handle.read().decode("utf-8", errors="replace")
            assert "Automation Test Queue Empty" in output, output[-2000:]
            assert re.search(r"Result=\{Success\}.*BBB.BlueprintAnnotations.Transaction", output), output[-2000:]
            assert not re.search(r"Result=\{Fail\}|Automation Test Failed", output), output[-2000:]
            print(json.dumps({"automation": "PASS"}))


if __name__ == "__main__":
    main()
