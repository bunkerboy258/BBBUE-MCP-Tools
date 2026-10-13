import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

from BBBMcpCapabilities import TOOL_DOMAINS, TOOLSET_ROUTES, source_index, tool_contract
from MCP.mcp_call import McpSession
from MCP.mcp_task_gateway import public_tools


def schema_shape(value):
    """/** @param value 参数契约 @return 参数结构与约束 */"""
    if isinstance(value, dict):
        return {key: schema_shape(item) for key, item in value.items() if key != "description"}
    if isinstance(value, list):
        return [schema_shape(item) for item in value]
    return value


def main():
    """/** @return 公开契约及当前宿主只读验证 */"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args()
    baseline = json.loads((ROOT / "Tests/tool_schema_baseline.json").read_text(encoding="utf-8"))
    assert set(baseline) == set(TOOLSET_ROUTES)
    for module, expected in baseline.items():
        assert set(expected) == set(source_index(module)["public_tools"]), module
    with McpSession(args.url, 60) as session:
        actual = session._post("tools/list", {})["result"]["tools"]
        assert actual == public_tools(), "PUBLIC_CONTRACT_CHANGED"
        count = 0
        for module, tools in baseline.items():
            if TOOL_DOMAINS[module] in {None, "external"}:
                continue
            for name, schema in tools.items():
                expected = tool_contract(module, name, schema["inputSchema"])
                if expected is None:
                    continue
                identity = expected["id"]
                found = session.find_tools(identity)
                assert identity in {item["id"] for item in found}, identity
                actual = session.describe_tool(identity)
                assert schema_shape(actual["parameters"]) == schema_shape(expected["parameters"]), (identity, actual["parameters"], expected["parameters"])
                assert (actual["access"], actual["world"]) == (expected["access"], expected["world"]), identity
                count += 1
        operations = [
            {"tool": "runtime.inspect_mcp_dependencies", "arguments": {"tool": "blueprint.inspect_blueprint_graph"}},
            {"tool": "runtime.inspect_mcp_resources", "arguments": {}},
            {"tool": "editor.inspect_dirty_packages", "arguments": {}},
        ]
        identity = session.submit_batch(operations, "公开契约只读验收")["batch"]
        value = session.wait_batch(identity, 120)
        assert value["status"] == "completed", value
        dependencies, performance, dirty = value["results"]
        assert Path(dependencies["project_root"]).resolve() == Path(args.project_root).resolve(), dependencies
        assert dependencies["native_dependencies_ready"], dependencies
        assert dependencies["process_id"] == performance["process_id"]
        assert performance["matches_configured_settings"], performance
        session.control_task("close", identity)
        state = session.inspect_tasks()
        assert state["host"]["process_id"] == dependencies["process_id"], state
        print(json.dumps({"status": "PASS", "public_tools": 5, "schemas_compared": count, "process_id": dependencies["process_id"], "profile": performance["profile"], "dirty_packages": dirty}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
