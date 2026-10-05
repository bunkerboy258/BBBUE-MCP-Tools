import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))
sys.path.insert(0, str(ROOT / "Scripts/MCP"))
from mcp_call import McpSession, McpBatchError
from MCP.mcp_result import decode_tool_result, McpBusinessError, require_business_success
import BBBMcpCapabilities as capabilities


def response(value):
    """
    /**
     * @param value	业务返回值
     * @return 官方文本包装
     */
    """
    return {"result": {"content": [{"type": "text", "text": json.dumps({"returnValue": json.dumps(value)})}]}}


class McpContractTests(unittest.TestCase):
    """/** 公共失败边界与能力发现回归 */"""

    def test_failure_wrappings_and_diagnostic_data(self):
        """/** @return 文本和结构化失败均拒绝 嵌套诊断和布尔查询保留 */"""
        for value in [{"success": False}, {"error": "失败"}]:
            for result in [response(value), {"result": {"structuredContent": {"returnValue": value}}}]:
                with self.assertRaises(McpBusinessError) as raised:
                    decode_tool_result(result)
                self.assertEqual(raised.exception.value, value)
        self.assertEqual(decode_tool_result(response({"items": [{"error": "资产诊断"}]})), {"items": [{"error": "资产诊断"}]})
        self.assertIs(decode_tool_result(response(False)), False)
        self.assertEqual(require_business_success("普通文本"), "普通文本")

    def test_batch_stops_at_business_failure_and_retains_completed_results(self):
        """/** @return 第一项保留 第二项失败 第三项不执行 */"""
        session = object.__new__(McpSession)
        seen = []
        first = response({"success": True, "saved": ["/Game/A"]})

        def call(name, arguments):
            """/** @param name 工具 @param arguments 参数 @return 协议结果 */"""
            seen.append(name)
            if len(seen) == 1:
                return first
            return response({"success": False, "message": "拒绝"})

        session.call_tool = call
        with self.assertRaises(McpBatchError) as raised:
            session.call_many([{"name": name} for name in ["first", "second", "third"]])
        self.assertEqual(seen, ["first", "second"])
        self.assertEqual(raised.exception.failed_index, 1)
        self.assertEqual(raised.exception.completed_results, [first])
        self.assertIsInstance(raised.exception.__cause__, McpBusinessError)

    def test_batch_validates_all_requests_before_execution(self):
        """/** @return 无效后续参数不会留下首项副作用 */"""
        session = object.__new__(McpSession)
        session.call_tool = lambda *args: self.fail("禁止执行")
        with self.assertRaises(ValueError):
            session.call_many([{"name": "write"}, {"name": "next", "arguments": []}])

    def test_routes_exclude_unregistered_entries(self):
        """/** @return 可用路由只包含实际注册项 缺失项仍可诊断 */"""
        registry = types.SimpleNamespace(is_toolset_registered=lambda name: name.startswith("project."))
        report = capabilities.usage_routes(lambda module: "project." + module, registry)
        self.assertEqual(len(report["routes"]), len(capabilities.TOOLSET_ROUTES))
        self.assertEqual(set(report["unavailable_routes"]), set(capabilities.OFFICIAL_ROUTES))

    def test_native_function_presence_is_checked(self):
        """/** @return 类存在而函数缺失仍不可用 */"""
        unreal = types.SimpleNamespace(BBBTestLibrary=types.SimpleNamespace(present=lambda: None))
        status = capabilities.dependency_status({"BBBTestLibrary": {"present", "missing"}}, unreal)
        self.assertFalse(status["native_dependencies_ready"])
        self.assertEqual(status["missing_native_functions"], ["BBBTestLibrary.missing"])

    def test_source_dependencies_follow_helpers_and_dynamic_library_aliases(self):
        """/** @return 排版测量 群体库 刚性部件与旧辅助依赖均被发现 */"""
        graph = capabilities.native_requirements("BBBBlueprintGraphToolset", "optimize_blueprint_node_layout")
        self.assertIn("measure_blueprint_graph_visual_geometry", graph["BBBBlueprintEditorLibrary"])
        preview = capabilities.native_requirements("BBBAnimationPreviewToolset", "spawn_mass_inspection_population")
        self.assertIn("spawn_population", preview["BBBMassValidationLibrary"])
        transition = capabilities.native_requirements("BBBAnimationPreviewToolset", "capture_monster_animation_transition")
        self.assertEqual(transition["BBBMonsterBehavior"], set())
        rig = capabilities.native_requirements("BBBRigidPartToolset", "validate_rigid_part_selection")
        self.assertIn("BBBBlueprintEditorLibrary", rig)
        old = capabilities.native_requirements("editor_actions", "ue_get_open_assets")
        self.assertEqual(old["MCPythonHelper"], {"get_all_edited_assets"})

    def test_server_boundary_rejects_business_failure_without_client(self):
        """/** @return 官方编排直接调用时同样进入错误边界 */"""
        fake_registry = types.SimpleNamespace(tool_call=lambda method: method.__func__)
        fake_unreal = types.SimpleNamespace()
        with patch.dict(sys.modules, {"unreal": fake_unreal, "toolset_registry": fake_registry}), patch.object(capabilities, "native_requirements", return_value={}):
            def function(target: str = "") -> str:
                """/** @param target 目标 @return 失败结果 */"""
                return json.dumps({"success": False, "target": target})

            tool = capabilities.mcp_tool(staticmethod(function))
            with self.assertRaises(McpBusinessError):
                tool("asset")


if __name__ == "__main__":
    unittest.main()
