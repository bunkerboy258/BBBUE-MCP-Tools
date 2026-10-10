import ast
import json
import math
from pathlib import Path
import unittest
from unittest.mock import Mock


class ConfiguredPIESpawnTests(unittest.TestCase):
    """/** 验证运行配置先于演员构造 不改资产默认对象 */"""

    def setUp(self):
        """/** @return 可记录生成顺序的引擎替身 */"""
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBGenericEditorToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "spawn_configured_pie_actor")
        method.decorator_list = []
        self.engine = Mock()
        self.engine.Actor = Mock
        self.world = Mock()
        self.world.get_path_name.return_value = "PIEWorld"
        self.engine.EditorLevelLibrary.get_pie_worlds.return_value = [self.world]
        self.actor = Mock()
        self.actor.get_path_name.return_value = "PIEActor"
        self.engine.BBBBlueprintEditorLibrary.begin_transient_pie_actor.return_value = self.actor
        self.events = []
        self.apply = Mock(side_effect=lambda actor, name, value: self.events.append((name, value)))
        self.engine.BBBBlueprintEditorLibrary.finish_transient_pie_actor.side_effect = lambda actor, transform: self.events.append("BeginPlay") or actor
        scope = {"unreal": self.engine, "json": json, "math": math, "_apply_editor_property": self.apply}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "configured_spawn", "exec"), scope)
        self.spawn = scope[method.name]

    def test_configuration_precedes_begin_play_and_defaults_are_read_only(self):
        """/** @return 数组引用在创建前解析 配置在 BeginPlay 前完成 */"""
        asset = object()
        self.engine.load_asset.return_value = asset
        result = json.loads(self.spawn("ActorClass", "PIEWorld", '{"Items":[{"refPath":"Item"}],"Index":1}', [0, 0, 0]))
        self.assertEqual(result["actor"], "PIEActor")
        self.assertEqual(self.events, [("Items", [asset]), ("Index", 1), "BeginPlay"])
        self.engine.get_default_object.return_value.set_editor_property.assert_not_called()

    def test_wrong_world_never_spawns(self):
        """/** @return 编辑器世界及失效世界不可生成 */"""
        with self.assertRaises(RuntimeError):
            self.spawn("ActorClass", "EditorWorld", "{}", [0, 0, 0])
        self.engine.BBBBlueprintEditorLibrary.begin_transient_pie_actor.assert_not_called()

    def test_invalid_array_reference_never_spawns(self):
        """/** @return 无效物品引用在生成前拒绝 */"""
        self.engine.load_asset.return_value = None
        with self.assertRaises(RuntimeError):
            self.spawn("ActorClass", "PIEWorld", '{"Items":[{"refPath":"Missing"}]}', [0, 0, 0])
        self.engine.BBBBlueprintEditorLibrary.begin_transient_pie_actor.assert_not_called()

    def test_failed_configuration_destroys_only_new_actor(self):
        """/** @return 不留下半配置的运行演员 */"""
        self.apply.side_effect = RuntimeError("Write failed")
        with self.assertRaisesRegex(RuntimeError, "Write failed"):
            self.spawn("ActorClass", "PIEWorld", '{"Index":1}', [0, 0, 0])
        self.actor.destroy_actor.assert_called_once()
        self.engine.BBBBlueprintEditorLibrary.finish_transient_pie_actor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
