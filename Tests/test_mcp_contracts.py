import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))
from MCP.mcp_call import McpSession
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

    def test_optional_graph_does_not_hide_blueprint_write_scope(self):
        """/** @return 成员变量以蓝图定界 局部变量追加图表 无实际目标时仍拒绝 */"""
        schema = {"type": "object", "properties": {"blueprint": {"type": "string"},
            "graph": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}}, "required": ["blueprint"]}
        contract = capabilities.tool_contract("BlueprintTools", "add_variable", schema)
        path = "/Game/Animation/Main.Main"
        for arguments in ({"blueprint": path}, {"blueprint": path, "graph": None}):
            targets, scoped = capabilities.write_scope(contract, arguments)
            self.assertTrue(scoped)
            self.assertEqual(targets, [path])
        graph = path + ":Update"
        self.assertEqual(capabilities.write_scope(contract, {"blueprint": path, "graph": graph}), ([path, graph], True))
        self.assertEqual(capabilities.write_scope(contract, {"graph": None}), ([], False))

    def test_character_locomotion_authoring_and_observation_boundaries(self):
        """/** @return 连续循环构图需要原生依赖和明确写入范围 运动状态查询保持只读 */"""
        requirements = capabilities.native_requirements("BBBAnimationGraphToolset", "restore_character_directional_cycle")
        self.assertEqual(requirements["BBBAnimationGraphEditorLibrary"], {
            "restore_character_directional_cycle"})
        authoring = capabilities.tool_contract("BBBAnimationGraphToolset", "restore_character_directional_cycle", {"type": "object"})
        self.assertEqual((authoring["access"], authoring["world"]), ("write", "editor"))
        targets, scoped = capabilities.write_scope(authoring, {
            "base_layer_path": "/Game/Base", "child_layer_paths": ["/Game/Child"],
            "reference_content_directory": "E:/Reference/Content", "reference_relative_package": "Animation/Base"})
        self.assertTrue(scoped)
        self.assertEqual(targets, ["/Game/Base", ["/Game/Child"]])
        observer = capabilities.tool_contract("BBBAnimationMigrationToolset", "get_pie_character_motion_capture_status", {"type": "object"})
        self.assertEqual((observer["access"], observer["world"]), ("read", "any"))

    def test_asset_copies_are_editor_operations_and_pie_tokens_remain_runtime(self):
        """/** @return 副本合并属于编辑器操作 显式 PIE 工具保留运行世界限制 */"""
        copies = capabilities.tool_contract("BBBAssetMaintenanceToolset", "consolidate_verified_asset_copies", {"type": "object"})
        self.assertEqual(copies["world"], "editor")
        runtime = capabilities.tool_contract("BBBGenericEditorToolset", "apply_pie_damage", {"type": "object"})
        self.assertEqual(runtime["world"], "pie")

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

    def test_schema_metadata_preserves_named_arguments(self):
        schema = {"type": "object", "title": "Metadata", "properties": {"description": {"type": "string"},
            "title": {"type": "string"}, "examples": {"type": "array", "items": {"type": "string"}}}}
        clean = capabilities.clean_schema(schema)
        self.assertNotIn("title", clean)
        self.assertEqual(clean["properties"], schema["properties"])

    def test_rejected_batch_remains_inspectable(self):
        value = {"batch": "a" * 16, "status": "rejected", "code": "TEST_HOST_FAILED", "results": []}
        self.assertEqual(decode_tool_result(response(value)), value)




    def test_native_function_presence_is_checked(self):
        """/** @return 类存在而函数缺失仍不可用 */"""
        unreal = types.SimpleNamespace(BBBTestLibrary=types.SimpleNamespace(present=lambda: None))
        status = capabilities.dependency_status({"BBBTestLibrary": {"present", "missing"}}, unreal)
        self.assertFalse(status["native_dependencies_ready"])
        self.assertEqual(status["missing_native_functions"], ["BBBTestLibrary.missing"])

    def test_source_dependencies_follow_helpers_and_dynamic_library_aliases(self):
        """/** @return 排版测量 群体库 刚性部件与旧辅助依赖均被发现 */"""
        graph = capabilities.native_requirements("BBBBlueprintGraphToolset", "format_blueprint_graph")
        self.assertIn("execute_graph_formatter", graph["BBBBlueprintEditorLibrary"])
        preview = capabilities.native_requirements("BBBAnimationPreviewToolset", "spawn_mass_inspection_population")
        self.assertIn("spawn_population", preview["BBBMassValidationLibrary"])
        transition = capabilities.native_requirements("BBBAnimationPreviewToolset", "capture_monster_animation_transition")
        self.assertEqual(transition["BBBMonsterBehavior"], set())
        rig = capabilities.native_requirements("BBBRigidPartToolset", "validate_rigid_part_selection")
        self.assertIn("BBBBlueprintEditorLibrary", rig)

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

    def test_selected_graph_view_requires_its_actual_native_symbols(self):
        """/** @return 逻辑读取使用逻辑依赖 几何读取增加显示依赖 */"""
        logic = capabilities._walk_native_requirements("BBBBlueprintGraphToolset", "inspect_blueprint_graph", set(), {"view": "logic"})
        geometry = capabilities._walk_native_requirements("BBBBlueprintGraphToolset", "inspect_blueprint_graph", set(), {"view": "geometry"})
        self.assertIn("inspect_blueprint_graph_logical_snapshot", logic["BBBBlueprintEditorLibrary"])
        self.assertNotIn("inspect_blueprint_graph_snapshot", logic["BBBBlueprintEditorLibrary"])
        self.assertIn("inspect_blueprint_graph_snapshot", geometry["BBBBlueprintEditorLibrary"])


if __name__ == "__main__":
    unittest.main()
