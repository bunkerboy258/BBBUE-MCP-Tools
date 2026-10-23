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
        for name in ("configure_corpse_physics_asset", "inspect_physics_asset_constraints"):
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



if __name__ == "__main__":
    unittest.main()
