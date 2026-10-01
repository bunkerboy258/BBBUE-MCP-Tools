import argparse
import json
import os
from pathlib import Path
import re
import sys


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts/MCP"))
from mcp_call import McpSession, URL


def text_payload(result):
    """
    /**
     * @param result	协议结果
     * @return 首个文本响应
     */
    """
    return result["result"]["content"][0]["text"]


def value_payload(result):
    """
    /**
     * @param result	协议结果
     * @return 已检查的项目返回值
     */
    """
    value = json.loads(text_payload(result))["returnValue"]
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, dict):
        assert value.get("success") is not False, value
        assert not value.get("error"), value
    return value


def main():
    """/** @return 验证成功时无返回值 */"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args()
    project = Path(args.project_root).resolve()
    baseline = json.loads((ROOT / "Tests/tool_schema_baseline.json").read_text(encoding="utf-8"))
    with McpSession(URL, timeout_seconds=30) as session:
        listing = text_payload(session.call_tool("list_toolsets", {}))
        names = re.findall(r"^- ([^:\r\n ]+)", listing, re.MULTILINE)
        matches = [name for name in names if re.search(r"(?:^|\.)BBBMcpRuntimeToolset(?:_0x[0-9A-Fa-f]{8})?$", name)]
        assert len(matches) == 1, matches
        runtime = matches[0]
        session.call_tool("describe_toolset", {"toolset_name": runtime})

        def call(name, tool, arguments=None):
            """
            /**
             * @param name	工具集名称
             * @param tool	工具名称
             * @param arguments	参数对象
             * @return 检查后的结果
             */
            """
            return value_payload(session.call_tool("call_tool", {"toolset_name": name, "tool_name": tool, "arguments": arguments or {}}))

        guide = call(runtime, "get_mcp_usage_guide")
        dependencies = call(runtime, "inspect_mcp_dependencies")
        assert os.path.samefile(guide["dependency_document_path"], ROOT / "Docs/ProjectDependencies.md")
        assert os.path.samefile(guide["document_path"], ROOT / "Docs/UnrealMcpCanonical.md")
        assert os.path.samefile(guide["project_root"], project)
        assert os.path.samefile(dependencies["repository_root"], ROOT)
        assert os.path.samefile(dependencies["project_root"], project)
        assert guide["performance_toolset"] == runtime
        assert guide["profiles"]["GamingBackground"]["max_fps"] == 15
        assert all(name in names for name in guide["routes"].values())
        count = 0
        for module, expected in baseline.items():
            status = dependencies["modules"][module]
            matches = [name for name in names if re.search(r"(?:^|\.)" + re.escape(module) + r"(?:_0x[0-9A-Fa-f]{8})?$", name)]
            assert matches == [status["toolset_name"]], (module, matches)
            assert status["registered"], module
            assert status["native_dependencies_ready"], (module, status["missing_native_classes"])
            assert os.path.samefile(status["source_path"], ROOT / "Scripts" / (module + ".py")), module
            descriptor = json.loads(text_payload(session.call_tool("describe_toolset", {"toolset_name": status["toolset_name"]})))
            tools = {tool["name"].rsplit(".", 1)[-1]: tool for tool in descriptor["tools"]}
            for name, schema in expected.items():
                assert name in tools, (module, name)
                assert tools[name]["inputSchema"] == schema["inputSchema"], (module, name, "inputSchema")
                assert tools[name]["outputSchema"] == schema["outputSchema"], (module, name, "outputSchema")
            count += len(tools)
        external = dependencies["modules"]["BBBExternalToolset"]["toolset_name"]
        actions = call(external, "list_available_actions")
        assert sum(len(values) for values in actions["domains"].values()) == 94
        call(external, "util", {"action": "get_project_info"})
        animation = dependencies["modules"]["BBBAnimationMigrationToolset"]["toolset_name"]
        api = call(animation, "probe_python_api", {"type_names": ["SystemLibrary"]})
        assert "get_engine_version" in api["SystemLibrary"]
        for invalid in (ROOT / "README.md", ROOT / "ScriptsElsewhere/rejected.py"):
            try:
                call(animation, "run_editor_script", {"script_path": str(invalid)})
            except RuntimeError as error:
                assert "Scripts" in str(error), error
                continue
            raise AssertionError("越界路径未拒绝 " + str(invalid))
        performance = call(runtime, "inspect_mcp_performance")
        assert performance["process_id"] == dependencies["process_id"]
        assert performance["matches_configured_settings"], performance
        assert performance["available_profiles"] == guide["profiles"]
        generic = dependencies["modules"]["BBBGenericEditorToolset"]["toolset_name"]
        dirty = call(generic, "inspect_dirty_packages")
        print(json.dumps({"status": "PASS", "project_root": str(project), "runtime_toolset": runtime, "tools": count, "process_id": dependencies["process_id"], "profile": performance["profile"], "dirty_packages": dirty}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
