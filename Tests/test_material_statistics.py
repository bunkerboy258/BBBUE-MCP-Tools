import ast
from collections import UserList
import json
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import Mock


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))
import BBBMcpCapabilities as capabilities


class MaterialStatisticsTests(unittest.TestCase):
    """/** 材质统计的输入 权限与缺失结果边界 */"""

    def setUp(self):
        """/** @return 不加载 UE 的材质与统计替身 */"""
        self.engine = Mock()
        self.engine.Array = UserList
        self.engine.MaterialInterface = type("MaterialInterface", (), {})
        self.engine.SystemLibrary.get_command_line.return_value = "-RenderOffscreen"
        self.engine.SystemLibrary.get_engine_version.return_value = "5.8"
        self.engine.GameplayStatics.get_platform_name.return_value = "Windows"
        self.material = self.engine.MaterialInterface()
        self.material.get_path_name = Mock(return_value="/Game/TestMaterial.TestMaterial")
        self.material.get_class = Mock(
            return_value=types.SimpleNamespace(
                get_path_name=lambda: "/Script/Engine.MaterialInstanceConstant"
            )
        )
        self.engine.load_asset.return_value = self.material
        self.values = {
            "num_vertex_shader_instructions": 55,
            "num_pixel_shader_instructions": 120,
            "num_samplers": 0,
            "num_vertex_texture_samples": 0,
            "num_pixel_texture_samples": 0,
            "num_virtual_texture_samples": 0,
            "num_uv_scalars": 2,
            "num_interpolator_scalars": 0,
        }
        self.engine.MaterialEditingLibrary.get_statistics.return_value = types.SimpleNamespace(
            get_editor_property=lambda name: self.values[name]
        )
        source = ROOT / "Scripts/BBBGenericEditorToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "inspect_material_statistics"
        )
        method.decorator_list = []
        namespace = {"json": json, "re": re, "unreal": self.engine}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
        self.inspect = namespace["inspect_material_statistics"]

    def tearDown(self):
        """/** @return 每次检查均保持资产无写入 */"""
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()
        self.engine.MaterialEditingLibrary.recompile_material.assert_not_called()
        self.engine.MaterialEditingLibrary.update_material_instance.assert_not_called()
        self.engine.MaterialEditingLibrary.set_material_instance_scalar_parameter_value.assert_not_called()

    def test_invalid_input_rejects_before_asset_load(self):
        """/** @return 非数组 空 超限 重复 非字符串与非法路径全部先拒绝 */"""
        cases = [
            None,
            "/Game/Material",
            [],
            ["/Game/M" + str(index) for index in range(33)],
            ["/Game/Material", "/Game/Material"],
            [None],
            ["/Engine/Material"],
            ["/Game/Material.Material"],
            ["/Game/../Material"],
            ["/Game//Material"],
            ["/Game/Folder/"],
        ]

        for paths in cases:
            with self.subTest(paths=paths):
                with self.assertRaises(RuntimeError):
                    self.inspect(paths)

        self.engine.load_asset.assert_not_called()
        self.engine.MaterialEditingLibrary.get_statistics.assert_not_called()

    def test_entire_batch_types_checked_before_statistics(self):
        """/** @return 缺失或错误类型使完整批次拒绝 不先计算前项 */"""
        for invalid in [None, object()]:
            with self.subTest(invalid=invalid):
                self.engine.load_asset.side_effect = [self.material, invalid]

                with self.assertRaises(RuntimeError):
                    self.inspect(["/Game/TestMaterial", "/Game/Invalid"])

        self.engine.MaterialEditingLibrary.get_statistics.assert_not_called()

    def test_null_rhi_returns_unavailable_without_compilation(self):
        """/** @return 无渲染宿主保留类型证据 不读取统计或误报零成本 */"""
        self.engine.SystemLibrary.get_command_line.return_value = "-Multiprocess -NullRHI"
        result = json.loads(self.inspect(["/Game/TestMaterial"]))
        item = result["assets"][0]
        self.assertTrue(result["nullRHI"])
        self.assertFalse(result["mayWaitForShaderCompilation"])
        self.assertFalse(item["statisticsAvailable"])
        self.assertIsNone(item["statistics"])
        self.assertEqual(item["unavailableReason"], "NULL_RHI")
        self.engine.MaterialEditingLibrary.get_statistics.assert_not_called()

    def test_incomplete_instructions_or_negative_counts_are_not_costs(self):
        """/** @return 缺失代表指令与负值产生警告及空成本 */"""
        for field, value in [
            ("num_vertex_shader_instructions", 0),
            ("num_pixel_shader_instructions", 0),
            ("num_pixel_shader_instructions", -1),
            ("num_samplers", -1),
        ]:
            with self.subTest(field=field, value=value):
                previous = self.values[field]
                self.values[field] = value
                item = json.loads(self.inspect(["/Game/TestMaterial"]))["assets"][0]
                self.values[field] = previous
                self.assertFalse(item["statisticsAvailable"])
                self.assertIsNone(item["statistics"])
                self.assertEqual(
                    item["unavailableReason"],
                    "REPRESENTATIVE_SHADER_STATISTICS_INCOMPLETE",
                )

        self.assertEqual(self.engine.log_warning.call_count, 4)

    def test_complete_statistics_preserve_zero_texture_counts_and_unknown_context(self):
        """/** @return 完整统计保留合法零采样 不推断平台能力 */"""
        result = json.loads(self.inspect(["/Game/TestMaterial"]))
        item = result["assets"][0]
        self.assertTrue(result["readOnly"])
        self.assertEqual(result["platform"], "Windows")
        self.assertEqual(result["shaderPlatform"], "unknown")
        self.assertEqual(result["featureLevel"], "unknown")
        self.assertTrue(result["mayWaitForShaderCompilation"])
        self.assertTrue(item["statisticsAvailable"])
        self.assertEqual(item["statistics"], self.values)
        self.assertIsNone(item["unavailableReason"])
        self.engine.MaterialEditingLibrary.get_statistics.assert_called_once_with(self.material)
        self.engine.log_warning.assert_not_called()

    def test_missing_platform_remains_unknown(self):
        """/** @return 平台空值不替换为猜测值 */"""
        self.engine.GameplayStatics.get_platform_name.return_value = ""
        result = json.loads(self.inspect(["/Game/TestMaterial"]))
        self.assertEqual(result["platform"], "unknown")

    def test_binding_array_accepts_valid_material_paths(self):
        """/** @return 官方绑定数组按值转为列表 非列表子类仍可检查 */"""
        paths = self.engine.Array(["/Game/TestMaterial"])
        self.assertNotIsInstance(paths, list)
        item = json.loads(self.inspect(paths))["assets"][0]
        self.assertTrue(item["statisticsAvailable"])
        self.engine.MaterialEditingLibrary.get_statistics.assert_called_once_with(self.material)

    def test_binding_array_preserves_input_rejection_before_loading(self):
        """/** @return 绑定数组转换后保留空 超限 重复 非字符串与路径边界 */"""
        cases = [
            [],
            ["/Game/M" + str(index) for index in range(33)],
            ["/Game/Material", "/Game/Material"],
            [None],
            ["/Engine/Material"],
        ]

        for paths in cases:
            with self.subTest(paths=paths):
                with self.assertRaises(RuntimeError):
                    self.inspect(self.engine.Array(paths))

        self.engine.load_asset.assert_not_called()
        self.engine.MaterialEditingLibrary.get_statistics.assert_not_called()

    def test_contract_is_read_only_in_editor_and_test(self):
        """/** @return 契约分类 范围及基线与公开方法一致 */"""
        baseline = json.loads(
            (ROOT / "Tests/tool_schema_baseline.json").read_text(encoding="utf-8")
        )
        schema = baseline["BBBGenericEditorToolset"]["inspect_material_statistics"]
        contract = capabilities.tool_contract(
            "BBBGenericEditorToolset",
            "inspect_material_statistics",
            schema["inputSchema"],
        )
        self.assertEqual(contract["id"], "editor.inspect_material_statistics")
        self.assertEqual((contract["access"], contract["world"]), ("read", "any"))
        targets, scoped = capabilities.write_scope(
            contract, {"asset_paths": ["/Game/TestMaterial"]}
        )
        self.assertTrue(scoped)
        self.assertEqual(targets, [])
        backend = types.SimpleNamespace(
            descriptors=lambda: [(
                "BBBGenericEditorToolset",
                [{
                    "name": "inspect_material_statistics",
                    "inputSchema": schema["inputSchema"],
                }],
            )],
            external_contracts=lambda: [],
        )
        catalog = capabilities.ToolCatalog(backend)
        self.assertEqual(
            catalog.describe("editor.inspect_material_statistics")["environments"],
            ["editor", "test"],
        )


if __name__ == "__main__":
    unittest.main()
