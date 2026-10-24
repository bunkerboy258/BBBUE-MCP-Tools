import ast
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))
from BBBMcpCapabilities import tool_contract


class MonsterGoreTests(unittest.TestCase):
    """/** 新制作入口的边界 不把工具测试当作表现验收 */"""

    def setUp(self):
        tree = ast.parse((ROOT / "Scripts/BBBMonsterGoreToolset.py").read_text(encoding="utf-8-sig"))
        self.engine = Mock()
        self.access = Mock()
        self.scope = {"unreal": self.engine, "json": json, "re": re, "require_asset_write": self.access}
        for name in ("configure_monster_wound_materials",):
            function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
            function.decorator_list = []
            exec(compile(ast.Module(body=[function], type_ignores=[]), "monster_gore_test", "exec"), self.scope)

    def test_source_and_output_rejected_before_writing(self):
        """/** @return 第三方源和不明确输出均不触发写入 */"""
        for definition in ("/Game/_ThirdParty/Body", "/Game/_Project/Mass/Monster", "/Game/_Project/Mass/Monster/Zombie/Shared/Gore/Connor/DA_Gore"):
            with self.assertRaises(RuntimeError):
                self.scope["configure_monster_wound_materials"](definition)
        self.access.assert_not_called()

    def test_pie_rejected_before_loading_or_building(self):
        """/** @return 运行中的世界不能重做配对资源 */"""
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        with self.assertRaises(RuntimeError):
            self.scope["configure_monster_wound_materials"]("/Game/_Project/Mass/Monster/Zombie/Shared/Injury/Connor/DA_Wounds")
        self.engine.load_asset.assert_not_called()

    def test_gib_probe_queries_only_the_current_world(self):
        """/** @return 残肢探针仅查询当前世界 不修改或恢复表现 */"""
        tree = ast.parse((ROOT / "Scripts/BBBHitReactionToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "inspect_zombie_gib_presentation")
        method.decorator_list = []
        exec(compile(ast.Module(body=[method], type_ignores=[]), "gib_probe_test", "exec"), self.scope)
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        with self.assertRaises(RuntimeError):
            self.scope["inspect_zombie_gib_presentation"]()
        world = object()
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = world
        native = self.engine.BBBMonsterGoreEditorLibrary.inspect_gib_presentation
        native.return_value = '{"simulating":32,"settled":128}'
        self.assertEqual(json.loads(self.scope["inspect_zombie_gib_presentation"]())["settled"], 128)
        native.assert_called_once_with(world)
        self.access.assert_not_called()

    def test_retired_body_cutting_tools_have_no_aliases(self):
        """/** @return 旧制作入口从公共工具目录消失 不建立转发兼容 */"""
        from BBBMcpCapabilities import source_index
        current = source_index("BBBHitReactionToolset")["public_tools"]
        retired = {"create_zombie_sealed_part_meshes", "configure_monster_severing_parts",
            "plan_zombie_wound_presentation_set", "bake_zombie_wound_presentation_set",
            "finalize_zombie_wound_material_masks", "rebuild_zombie_wound_cut_geometry",
            "rebuild_zombie_debug_gore_cuts", "build_zombie_debug_gore_surface",
            "inspect_zombie_debug_gore_surface", "repack_zombie_debug_wound_atlas",
            "normalize_zombie_gib_material_bindings"}
        self.assertFalse(retired.intersection(current))
        self.assertEqual(tool_contract("BBBHitReactionToolset", "inspect_zombie_gib_presentation", {})["access"], "read")

    def test_preview_interface_is_removed_without_aliases(self):
        """/** @return 专用预览窗口与后台预览接口均不再注册 */"""
        from BBBMcpCapabilities import source_index
        current = source_index("BBBMonsterGoreToolset")["public_tools"]
        self.assertFalse({"open_monster_gore_editor", "control_monster_gore_preview",
                          "adjust_monster_wound_preview"}.intersection(current))


if __name__ == "__main__":
    unittest.main()
