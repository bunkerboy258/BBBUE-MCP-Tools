import ast
import json
import math
from pathlib import Path
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class CharacterRescueStateTests(unittest.TestCase):
    """/** 帮扶构图的共享宿主与持久化失败边界 */"""

    def setUp(self):
        """/** @return 隔离引擎与构图入口 */"""
        tree = ast.parse((ROOT / "Scripts/BBBAnimationGraphToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "configure_character_rescue_state")
        method.decorator_list = []
        self.engine = Mock()
        self.engine.AnimBlueprint = Mock
        self.engine.AnimSequence = Mock
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        self.engine.BlueprintStatus.BS_UP_TO_DATE = "Ready"
        self.paths = ["/Game/Main", "/Game/Interface", "/Game/Base", "/Game/Help", "/Game/Rifle"]
        self.assets = {path: Mock() for path in self.paths}
        self.base = self.assets["/Game/Base"]
        for path, value in self.assets.items():
            value.get_path_name.return_value = path
            value.get_outermost.return_value.get_path_name.return_value = path
            value.get_blueprint_parent_class.return_value = self.base.generated_class()
            value.get_editor_property.return_value = "Ready"
            value.sequence_length = 2.0
        self.engine.load_asset.side_effect = self.assets.__getitem__
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = []
        self.engine.BBBBlueprintEditorLibrary.ensure_animation_layer_interface_function.return_value = 1
        self.engine.BBBAnimationGraphEditorLibrary.configure_character_rescue_state.return_value = True
        self.engine.AnimationLibrary.get_animation_curve_names.return_value = []
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True
        self.access = Mock()
        namespace = {"unreal": self.engine, "json": json, "math": math, "require_asset_write": self.access}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "rescue_state_test", "exec"), namespace)
        self.configure = namespace[method.name]
        self.arguments = (*self.paths[:4], self.paths[4:])

    def test_shared_pie_rejects_before_loading(self):
        """/** @return 其它会话运行期间不加载或修改目标 */"""
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)
        self.engine.load_asset.assert_not_called()
        self.access.assert_not_called()

    def test_dirty_target_and_wrong_inheritance_reject(self):
        """/** @return 脏包与错误父类不能混入新状态 */"""
        self.assets["/Game/Rifle"].get_blueprint_parent_class.return_value = object()
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)
        self.assets["/Game/Rifle"].get_blueprint_parent_class.return_value = self.base.generated_class()
        dirty = Mock()
        dirty.get_path_name.return_value = "/Game/Base"
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = [dirty]
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)
        self.engine.BBBBlueprintEditorLibrary.ensure_animation_layer_interface_function.assert_not_called()

    def test_permission_native_and_compile_failures_never_save(self):
        """/** @return 写入许可 构图与编译失败均阻止持久化 */"""
        self.access.side_effect = RuntimeError("其它会话占用")
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)
        self.access.side_effect = None
        self.engine.BBBAnimationGraphEditorLibrary.configure_character_rescue_state.return_value = False
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)
        self.engine.BBBAnimationGraphEditorLibrary.configure_character_rescue_state.return_value = True
        self.base.get_editor_property.return_value = "Warning"
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_success_saves_only_declared_targets(self):
        """/** @return 继承层统一编译成功后保存显式目标 */"""
        result = json.loads(self.configure(*self.arguments))
        targets = [self.assets[path] for path in [self.paths[1], self.paths[2], self.paths[0], self.paths[4], self.paths[3]]]
        self.access.assert_called_once_with(targets)
        self.assertEqual(result["saved"], [value.get_path_name() for value in targets])
        self.assertEqual(result["recoveryBlendSeconds"], 0.5)
        self.engine.BBBAnimationGraphEditorLibrary.configure_character_rescue_state.assert_called_once_with(
            self.assets[self.paths[0]], self.base, self.assets[self.paths[3]], 0.5)


if __name__ == "__main__":
    unittest.main()
