import argparse
import json
from pathlib import Path
import re
import sys


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts/MCP"))
from mcp_call import McpSession, URL


def _payload(response):
    """
    /**
     * @param response	协议结果
     * @return 已解码的工具文本对象
     */
    """
    return json.loads(response["result"]["content"][0]["text"])


def main():
    """/** @return 只读接口契约和可选真实图表预览验证 */"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--graph")
    parser.add_argument("--automation", action="store_true")
    args = parser.parse_args()
    with McpSession(URL, timeout_seconds=120) as session:
        listing = session.call_tool("list_toolsets", {})["result"]["content"][0]["text"]
        names = re.findall(r"^- ([^:\r\n ]+)", listing, re.MULTILINE)

        def resolve(module):
            """
            /**
             * @param module	目标类名
             * @return 唯一实际注册名称
             */
            """
            matches = [name for name in names if re.search(r"(?:^|\.)" + module + r"(?:_0x[0-9A-Fa-f]{8})?$", name)]
            assert len(matches) == 1, matches
            return matches[0]

        def call(module, tool, arguments=None):
            """
            /**
             * @param module	目标工具类
             * @param tool	接口名称
             * @param arguments	参数
             * @return 已检查的接口返回值
             */
            """
            result = _payload(session.call_tool("call_tool", {"toolset_name": resolve(module), "tool_name": tool, "arguments": arguments or {}}))["returnValue"]
            if isinstance(result, str):
                result = json.loads(result)
            assert not isinstance(result, dict) or not result.get("error"), result
            return result

        dependencies = call("BBBMcpRuntimeToolset", "inspect_mcp_dependencies")
        assert Path(dependencies["project_root"]).resolve() == Path(args.project_root).resolve()
        assert dependencies["modules"]["BBBBlueprintGraphToolset"]["native_dependencies_ready"]
        call("BBBMcpRuntimeToolset", "get_mcp_usage_guide")
        descriptor = _payload(session.call_tool("describe_toolset", {"toolset_name": resolve("BBBBlueprintGraphToolset")}))
        tools = {item["name"].rsplit(".", 1)[-1]: item for item in descriptor["tools"]}
        baseline = json.loads((ROOT / "Tests/tool_schema_baseline.json").read_text(encoding="utf-8"))["BBBBlueprintGraphToolset"]
        for name in ("inspect_blueprint_graph", "annotate_blueprint_graph"):
            assert tools[name]["inputSchema"] == baseline[name]["inputSchema"], tools[name]
            assert tools[name]["outputSchema"] == baseline[name]["outputSchema"], tools[name]

        print(json.dumps({"schemas": 2, "processId": dependencies["process_id"]}, ensure_ascii=False))
        if args.graph:
            dirty = call("BBBGenericEditorToolset", "inspect_dirty_packages")
            snapshot = call("BBBBlueprintGraphToolset", "inspect_blueprint_graph", {"graph_path": args.graph})
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
            preview = call("BBBBlueprintGraphToolset", "annotate_blueprint_graph", {"graph_path": args.graph, "annotations_json": json.dumps(request, ensure_ascii=False), "dry_run": True})
            after = call("BBBBlueprintGraphToolset", "inspect_blueprint_graph", {"graph_path": args.graph})
            assert snapshot == after, "只读预览改变了图表"
            assert dirty == call("BBBGenericEditorToolset", "inspect_dirty_packages"), "预览改变脏资产列表"
            print(json.dumps({"graph": args.graph, "nodes": len(snapshot["nodes"]), "blocks": len(preview["blocks"]), "warnings": snapshot["warnings"], "before": preview["before"], "after": preview["after"], "canApply": preview["canApply"], "unchanged": True}, ensure_ascii=False))

        if args.automation:
            call("BBBExternalToolset", "util", {"action": "execute_console_command", "params_json": json.dumps({"command": "Automation RunTests BBB.BlueprintAnnotations.Transaction"})})
            print("已派发瞬态图原生测试 必须从编辑器日志核对最终结果")


if __name__ == "__main__":
    main()
