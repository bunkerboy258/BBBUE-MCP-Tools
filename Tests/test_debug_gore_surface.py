import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock


class DebugGoreSurfaceTests(unittest.TestCase):
    """/** 不启动编辑器的调试伤口工具边界 */"""

    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBHitReactionToolset.py").read_text(encoding="utf-8-sig"))
        self.engine = Mock()
        self.access = Mock()
        self.scope = {"unreal": self.engine, "json": json, "require_asset_write": self.access}
        for name in ("build_zombie_debug_gore_surface", "inspect_zombie_debug_gore_surface", "repack_zombie_debug_wound_atlas"):
            method = next(item for item in ast.walk(tree) if isinstance(item, ast.FunctionDef) and item.name == name)
            method.decorator_list = []
            exec(compile(ast.Module(body=[method], type_ignores=[]), "debug_gore_surface", "exec"), self.scope)

    def test_rejects_formal_output(self):
        """/** @return 不能把调试资源写入正式尸群目录 */"""
        with self.assertRaises(RuntimeError):
            self.scope["build_zombie_debug_gore_surface"]("/Game/_Project/Body", "/Game/_Project/Mass/Monster")
        self.access.assert_not_called()

    def test_rejects_third_party_source(self):
        """/** @return 不能修改第三方源资源 */"""
        with self.assertRaises(RuntimeError):
            self.scope["build_zombie_debug_gore_surface"]("/Game/_ThirdParty/Body", "/Game/_Project/Debug/ZombieHitReaction/Gore")
        self.engine.load_asset.assert_not_called()

    def test_rejects_live_pie(self):
        """/** @return 运行中不构建身体或物理资源 */"""
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        with self.assertRaises(RuntimeError):
            self.scope["build_zombie_debug_gore_surface"]("/Game/_Project/Body", "/Game/_Project/Debug/ZombieHitReaction/Gore")
        self.access.assert_not_called()

    def test_inspect_rejects_formal_definition(self):
        """/** @return 检查入口只接受独立调试定义 */"""
        with self.assertRaises(RuntimeError):
            self.scope["inspect_zombie_debug_gore_surface"]("/Game/_Project/Mass/Definition")
        self.engine.BBBZombieSeveringEditorLibrary.inspect_debug_gore_surface.assert_not_called()

    def test_repack_rejects_formal_folder(self):
        """/** @return 重排不能写入正式身体 */"""
        with self.assertRaises(RuntimeError):
            self.scope["repack_zombie_debug_wound_atlas"]("/Game/_Project/Mass")
        self.access.assert_not_called()


if __name__ == "__main__":
    unittest.main()
