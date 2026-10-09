import ast
import json
import math
import re
from pathlib import Path
import unittest
from unittest.mock import Mock


class CorpsePhysicsConfigurationTests(unittest.TestCase):
    """/** 验证尸体资产配置的权限和参数边界 */"""

    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBHitReactionToolset.py").read_text(encoding="utf-8-sig"))
        self.engine = Mock()
        self.engine.PhysicsAsset = type("PhysicsAsset", (), {})
        self.engine.SkeletalMesh = type("SkeletalMesh", (), {})
        self.asset = self.engine.PhysicsAsset()
        self.engine.load_asset.return_value = self.asset
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        self.access = Mock()
        self.asset_write = Mock()
        self.scope = {"unreal": self.engine, "math": math, "json": json, "re": re,
            "require_write_access": self.access, "require_asset_write": self.asset_write}
        for name in ("configure_corpse_physics_asset", "inspect_physics_asset_constraints", "create_zombie_sealed_part_meshes", "configure_monster_severing_parts"):
            method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
            method.decorator_list = []
            exec(compile(ast.Module(body=[method], type_ignores=[]), "corpse_physics_test", "exec"), self.scope)

    def test_invalid_mass_rejected_before_asset_load(self):
        """/** @return 无效质量不读取或修改资产 */"""
        for value in (math.nan, math.inf, 0.0, 34.0, 151.0):
            with self.assertRaises(RuntimeError):
                self.scope["configure_corpse_physics_asset"]("/Game/_Project/PA", value)
        self.engine.load_asset.assert_not_called()
        self.access.assert_not_called()

    def test_live_pie_and_third_party_rejected(self):
        """/** @return 不修改运行中或第三方物理资产 */"""
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        with self.assertRaises(RuntimeError):
            self.scope["configure_corpse_physics_asset"]("/Game/_Project/PA")
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        with self.assertRaises(RuntimeError):
            self.scope["configure_corpse_physics_asset"]("/Game/_ThirdParty/PA")
        self.engine.load_asset.assert_not_called()

    def test_exclusive_checkout_precedes_native_write(self):
        """/** @return 未签出时不进入原生修改 */"""
        self.access.side_effect = RuntimeError("需要独占签出")
        with self.assertRaises(RuntimeError):
            self.scope["configure_corpse_physics_asset"]("/Game/_Project/PA")
        self.engine.BBBHitReactionEditorLibrary.configure_corpse_physics.assert_not_called()

    def test_success_does_not_save_and_inspection_does_not_request_write(self):
        """/** @return 调用方保存 查询不申请资产写入 */"""
        self.engine.BBBHitReactionEditorLibrary.configure_corpse_physics.return_value = '{"constraints":[]}'
        self.assertEqual(self.scope["configure_corpse_physics_asset"]("/Game/_Project/PA", 75.0), '{"constraints":[]}')
        self.access.assert_called_once_with(self.asset)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()
        self.access.reset_mock()
        self.scope["inspect_physics_asset_constraints"]("/Game/_Project/PA")
        self.access.assert_not_called()

    def test_severing_rejects_unsafe_output_and_unknown_bone(self):
        """/** @return 非自有输出或未知骨骼不读取和创建资产 */"""
        for folder, bone in (("/Game/_ThirdParty/Parts", "head"), ("/Game/_Project/../Parts", "head"), ("/Game/_Project/Parts", "pelvis")):
            with self.assertRaises(RuntimeError):
                self.scope["create_zombie_sealed_part_meshes"]("/Game/Source", bone, folder)
        self.engine.load_asset.assert_not_called()
        self.asset_write.assert_not_called()

    def test_severing_refuses_existing_output_before_native_creation(self):
        """/** @return 已有输出不覆盖和调用原生提取 */"""
        source = self.engine.SkeletalMesh()
        source.get_name = lambda: "Source"
        self.engine.load_asset.return_value = source
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = True
        with self.assertRaises(RuntimeError):
            self.scope["create_zombie_sealed_part_meshes"]("/Game/Source", "head", "/Game/_Project/Parts")
        self.engine.BBBZombieSeveringEditorLibrary.create_sealed_part_meshes.assert_not_called()

    def test_non_closed_cut_propagates_native_failure_without_saving(self):
        """/** @return 非闭合切口保持失败 不将缺口部件冒充成功 */"""
        source = self.engine.SkeletalMesh()
        source.get_name = lambda: "Source"
        self.engine.load_asset.return_value = source
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = False
        self.engine.BBBZombieSeveringEditorLibrary.create_sealed_part_meshes.return_value = "失败 切口拓扑非闭环"
        with self.assertRaisesRegex(RuntimeError, "非闭环"):
            self.scope["create_zombie_sealed_part_meshes"]("/Game/Source", "head", "/Game/_Project/Parts")
        self.asset_write.assert_called_once()
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_severing_rebuild_requires_complete_pair(self):
        """/** @return 重建不能补写部分存在的部件或隐式创建资产 */"""
        source = self.engine.SkeletalMesh()
        source.get_name = lambda: "Source"
        self.engine.load_asset.return_value = source
        self.engine.EditorAssetLibrary.does_asset_exist.side_effect = [True, False]
        with self.assertRaisesRegex(RuntimeError, "完整"):
            self.scope["create_zombie_sealed_part_meshes"]("/Game/Source", "head", "/Game/_Project/Parts", True)
        self.asset_write.assert_not_called()
        self.engine.BBBZombieSeveringEditorLibrary.create_sealed_part_meshes.assert_not_called()

    def test_severing_rebuild_requires_exclusive_write_before_native(self):
        """/** @return 同名原地重建也必须先验证独占签出 */"""
        source = self.engine.SkeletalMesh()
        source.get_name = lambda: "Source"
        self.engine.load_asset.return_value = source
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = True
        self.asset_write.side_effect = RuntimeError("需要独占签出")
        with self.assertRaisesRegex(RuntimeError, "独占"):
            self.scope["create_zombie_sealed_part_meshes"]("/Game/Source", "head", "/Game/_Project/Parts", True)
        self.asset_write.assert_called_once_with(["/Game/_Project/Parts/SM_Source_head_Part", "/Game/_Project/Parts/SM_Source_head_Cap"], [])
        self.engine.BBBZombieSeveringEditorLibrary.create_sealed_part_meshes.assert_not_called()

    def test_severing_rebuild_is_explicit_and_never_saves(self):
        """/** @return 权限通过后明确原地重建 不创建历史版本 不自动保存 */"""
        source = self.engine.SkeletalMesh()
        source.get_name = lambda: "Source"
        self.engine.load_asset.return_value = source
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = True
        self.engine.BBBZombieSeveringEditorLibrary.create_sealed_part_meshes.return_value = '{"part":"/Game/_Project/Parts/SM_Source_head_Part"}'
        self.scope["create_zombie_sealed_part_meshes"]("/Game/Source", "head", "/Game/_Project/Parts", True)
        self.engine.BBBZombieSeveringEditorLibrary.create_sealed_part_meshes.assert_called_once_with(source, "head", "/Game/_Project/Parts", True)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_incomplete_severing_mapping_never_changes_definition(self):
        """/** @return 缺少或重复部位不读取配置 不申请签出 */"""
        for rows in ([], [{"region": 1}] * 5):
            with self.assertRaises(RuntimeError):
                self.scope["configure_monster_severing_parts"]("/Game/_Project/Definition", json.dumps(rows))
        self.engine.load_asset.assert_not_called()
        self.access.assert_not_called()


if __name__ == "__main__":
    unittest.main()
