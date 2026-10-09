import ast
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def extract_method(source, name, namespace):
    """/** @param source\t脚本 @param name\t入口 @param namespace\t替身 @return 独立入口 */"""
    tree = ast.parse((ROOT / "Scripts" / source).read_text(encoding="utf-8-sig"))
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
    method.decorator_list = []
    exec(compile(ast.Module(body=[method], type_ignores=[]), name, "exec"), namespace)
    return namespace[name]


class PrimitiveTextureBlendTests(unittest.TestCase):
    """/** 图元材质创建的权限 冲突和保存边界 */"""

    def setUp(self):
        """/** @return 引擎和源控隔离替身 */"""
        self.engine = Mock()
        self.engine.Material = Mock
        self.engine.MaterialExpressionTextureSampleParameter2D = Mock
        self.engine.MaterialExpressionScalarParameter = type("Scalar", (), {})
        self.engine.MaterialExpressionVectorParameter = type("Vector", (), {})
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = False
        self.engine.MaterialEditingLibrary.get_material_expressions.return_value = []
        self.access = Mock()
        self.policy = types.ModuleType("BBBAssetWritePolicy")
        self.policy.require_asset_write = self.access
        self.call = extract_method("BBBGenericEditorToolset.py", "create_primitive_texture_blend_material", {"unreal": self.engine, "json": json})
        self.arguments = ("/Game/Source", "/Game/_Project/NewMaterial", "Base", "Light", 0)

    def test_invalid_parameters_reject_before_loading(self):
        """/** @return 项目路径 参数重名和索引边界先拒绝 */"""
        with patch.dict(sys.modules, {"BBBAssetWritePolicy": self.policy}):
            for destination, source_name, light_name, index in [("/Game/ThirdParty/New", "Base", "Light", 0), ("/Game/_Project/New", "Base", "Base", 0), ("/Game/_Project/New", "Base", "Light", 32)]:
                with self.assertRaises(RuntimeError):
                    self.call("/Game/Source", destination, source_name, light_name, index)
        self.engine.load_asset.assert_not_called()

    def test_existing_target_and_access_failure_never_duplicate(self):
        """/** @return 已有目标和源控失败不产生资产 */"""
        with patch.dict(sys.modules, {"BBBAssetWritePolicy": self.policy}):
            self.engine.EditorAssetLibrary.does_asset_exist.return_value = True
            with self.assertRaises(RuntimeError):
                self.call(*self.arguments)
            self.engine.EditorAssetLibrary.does_asset_exist.return_value = False
            self.access.side_effect = RuntimeError("PIE 或源控拒绝")
            with self.assertRaises(RuntimeError):
                self.call(*self.arguments)
        self.engine.EditorAssetLibrary.duplicate_asset.assert_not_called()

    def test_missing_unique_source_parameter_never_duplicate(self):
        """/** @return 缺失或重复原参数不创建资产 */"""
        with patch.dict(sys.modules, {"BBBAssetWritePolicy": self.policy}):
            for count in [0, 2]:
                values = [Mock() for unused in range(count)]
                for value in values:
                    value.get_editor_property.return_value = "Base"
                self.engine.MaterialEditingLibrary.get_material_expressions.return_value = values
                with self.assertRaises(RuntimeError):
                    self.call(*self.arguments)
        self.engine.EditorAssetLibrary.duplicate_asset.assert_not_called()


class InPlaceCycleTests(unittest.TestCase):
    """/** 循环准备入口的写入和轨道边界 */"""

    def setUp(self):
        """/** @return 同骨架动画与访问替身 */"""
        self.engine = Mock()
        self.engine.AnimSequence = Mock
        self.sequence = Mock()
        self.reference = Mock()
        self.sequence.get_editor_property.return_value = "Skeleton"
        self.reference.get_editor_property.return_value = "Skeleton"
        self.engine.load_asset.side_effect = [self.sequence, self.reference]
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = []
        self.access = Mock()
        self.call = extract_method("BBBAnimationGraphToolset.py", "prepare_in_place_cycles", {"unreal": self.engine, "json": json, "require_asset_write": self.access})
        self.arguments = (["/Game/_Project/Animation"], "/Game/Reference")

    def test_invalid_list_rejects_before_loading(self):
        """/** @return 空 超限 重复和非项目资产拒绝 */"""
        for paths in [[], ["/Game/_Project/A"] * 2, ["/Game/Source"], ["/Game/_Project/" + str(index) for index in range(17)]]:
            with self.assertRaises(RuntimeError):
                self.call(paths, "/Game/Reference")
        self.engine.load_asset.assert_not_called()

    def test_access_dirty_or_incomplete_tracks_never_save(self):
        """/** @return 禁止写入 脏包和缺失轨道不保存 */"""
        for condition in ["access", "dirty", "track"]:
            self.setUp()
            if condition == "access":
                self.access.side_effect = RuntimeError("未签出")
            if condition == "dirty":
                package = Mock()
                package.get_path_name.return_value = self.sequence.get_outermost().get_path_name()
                self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = [package]
            if condition == "track":
                self.engine.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms.return_value = []
            with self.assertRaises(RuntimeError):
                self.call(*self.arguments)
            self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()


class VariationNetworkInspectionTests(unittest.TestCase):
    """/** 跨世界出生属性探针只读边界 */"""

    def test_each_world_is_queried_without_writes(self):
        """/** @return 主客机完整查询 且没有资产和实体写入 */"""
        engine = Mock()
        worlds = [Mock(), Mock(), Mock()]
        for index, world in enumerate(worlds):
            world.get_path_name.return_value = "PIE_" + str(index)
        engine.EditorLevelLibrary.get_pie_worlds.return_value = worlds
        engine.BBBMassValidationLibrary.inspect_population.return_value = '{"validEntities":50}'
        call = extract_method("BBBAnimationGraphToolset.py", "inspect_mass_variation_network", {"unreal": engine, "json": json})
        report = json.loads(call())
        self.assertEqual(len(report["worlds"]), 3)
        self.assertTrue(report["readOnly"])
        self.assertEqual(engine.BBBMassValidationLibrary.inspect_population.call_count, 3)
        engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()
        engine.BBBMassValidationLibrary.spawn_population.assert_not_called()
        engine.EditorLevelLibrary.get_pie_worlds.return_value = []
        with self.assertRaises(RuntimeError):
            call()
