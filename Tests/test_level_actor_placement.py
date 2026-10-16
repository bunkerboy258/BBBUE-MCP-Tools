import ast
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class LevelActorPlacementTests(unittest.TestCase):
    """/** 明确关卡放置的输入与保存边界 */"""

    def setUp(self):
        """/** @return 不加载编辑器的独立函数环境 */"""
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBLevelEditingToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        owner = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        function = next(node for node in owner.body if isinstance(node, ast.FunctionDef)
            and node.name == "place_actor_from_class")
        function.decorator_list = []
        self.world = Mock()
        self.world.get_path_name.return_value = "/Game/Test.Test"
        self.level = Mock()
        self.level.get_path_name.return_value = "/Game/Test.Test:PersistentLevel"
        self.actor_type = type("Actor", (), {})
        self.actor = Mock(spec=["get_world", "get_outer", "set_actor_label", "get_path_name", "get_actor_location"])
        self.actor.get_world.return_value = self.world
        self.actor.get_outer.return_value = self.level
        self.actor.get_path_name.return_value = "/Game/Test.Test:PersistentLevel.Target"
        self.actor.get_actor_location.return_value = SimpleNamespace(x=1, y=2, z=3)
        self.engine = Mock()
        self.engine.Actor = self.actor_type
        self.engine.EditorLevelLibrary.get_pie_worlds.return_value = []
        self.subsystem = Mock()
        self.subsystem.get_editor_world.return_value = self.world
        self.subsystem.get_all_level_actors.return_value = []
        self.subsystem.spawn_actor_from_class.return_value = self.actor
        self.engine.get_editor_subsystem.return_value = self.subsystem
        self.engine.get_default_object.return_value = self.actor_type()
        self.engine.EditorLoadingAndSavingUtils.save_map.return_value = True
        namespace = {"unreal": self.engine, "json": json, "math": math}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "level_placement_test", "exec"), namespace)
        self.function = namespace["place_actor_from_class"]
        self.write = Mock()
        context = patch.dict(sys.modules, {"BBBAssetWritePolicy": SimpleNamespace(require_write_access=self.write)})
        context.start()
        self.addCleanup(context.stop)

    def call(self, **changes):
        """/** @param changes 单项输入变化 @return 实际函数结果 */"""
        values = dict(asset_path="/Game/Test", class_path="/Script/Engine.Actor", label="Target",
            location=[1, 2, 3], rotation=[0, 180, 0])
        values.update(changes)
        return json.loads(self.function(**values))

    def test_success_saves_only_explicit_world(self):
        """/** @return 创建核对与保存同一关卡 */"""
        self.assertTrue(self.call()["saved"])
        self.write.assert_called_once_with(self.world)
        self.engine.EditorLoadingAndSavingUtils.save_map.assert_called_once_with(self.world, "/Game/Test")

    def test_reject_pie(self):
        """/** @return 游戏期间不创建 */"""
        self.engine.EditorLevelLibrary.get_pie_worlds.return_value = [object()]
        with self.assertRaises(RuntimeError):
            self.call()
        self.subsystem.spawn_actor_from_class.assert_not_called()

    def test_reject_wrong_world(self):
        """/** @return 错误关卡不创建 */"""
        with self.assertRaises(RuntimeError):
            self.call(asset_path="/Game/Other")
        self.subsystem.spawn_actor_from_class.assert_not_called()

    def test_reject_invalid_transform(self):
        """/** @return 非有限数和错误维度不创建 */"""
        for location in ([1, 2], [1, 2, math.nan], [True, 2, 3]):
            with self.assertRaises(RuntimeError):
                self.call(location=location)
        self.subsystem.spawn_actor_from_class.assert_not_called()

    def test_reject_duplicate_label(self):
        """/** @return 不重复放置已有标签 */"""
        existing = Mock()
        existing.get_actor_label.return_value = "Target"
        self.subsystem.get_all_level_actors.return_value = [existing]
        with self.assertRaises(RuntimeError):
            self.call()
        self.subsystem.spawn_actor_from_class.assert_not_called()

    def test_reject_non_actor_class(self):
        """/** @return 非演员类不创建 */"""
        self.engine.get_default_object.return_value = object()
        with self.assertRaises(RuntimeError):
            self.call()
        self.subsystem.spawn_actor_from_class.assert_not_called()

    def test_reject_wrong_outer(self):
        """/** @return 非持久关卡对象不声称保存成功 */"""
        self.level.get_path_name.return_value = "/Game/Other.Other:PersistentLevel"
        with self.assertRaisesRegex(RuntimeError, "禁止盲目重放"):
            self.call()
        self.engine.EditorLoadingAndSavingUtils.save_map.assert_not_called()

    def test_report_save_failure_without_replay(self):
        """/** @return 保存失败保留对象证据 不重复创建 */"""
        self.engine.EditorLoadingAndSavingUtils.save_map.return_value = False
        with self.assertRaisesRegex(RuntimeError, "禁止盲目重放"):
            self.call()
        self.assertEqual(self.subsystem.spawn_actor_from_class.call_count, 1)


if __name__ == "__main__":
    unittest.main()
