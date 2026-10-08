import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class CharacterTraversalStateTests(unittest.TestCase):
    """/** 攀爬状态构图的权限 编译与保存边界 */"""

    def setUp(self):
        """/** @return 隔离构图入口与目标资产 */"""
        tree = ast.parse((ROOT / "Scripts/BBBTraversalToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "configure_character_traversal_state")
        method.decorator_list = []
        self.engine = Mock()
        self.engine.AnimMontage = Mock
        self.engine.BlueprintStatus.BS_UP_TO_DATE = "Ready"
        self.paths = ["/Game/Main", "/Game/Interface", "/Game/Base", "/Game/Rifle", "/Game/Unarmed",
                      "/Game/Vault", "/Game/Low", "/Game/High"]
        self.assets = {path: Mock() for path in self.paths}
        self.skeleton = Mock()
        self.skeleton.get_path_name.return_value = "/Game/Skeleton.Skeleton"
        self.base = self.assets["/Game/Base"]
        for path, asset in self.assets.items():
            asset.get_path_name.return_value = path + "." + path.rsplit("/", 1)[-1]
            asset.get_outermost.return_value.get_path_name.return_value = path
            asset.get_blueprint_parent_class.return_value = self.base.generated_class()
            asset.get_editor_property.side_effect = self.properties
        self.engine.load_asset.side_effect = self.assets.__getitem__
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = []
        self.engine.BBBBlueprintEditorLibrary.ensure_animation_layer_interface_function.return_value = 1
        self.engine.BBBAnimationGraphEditorLibrary.configure_character_traversal_state.return_value = True
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True
        self.access = Mock()
        namespace = {"unreal": self.engine, "json": json, "require_asset_write": self.access,
                     "_blueprint": self.assets.__getitem__}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "traversal_state_test", "exec"), namespace)
        self.configure = namespace[method.name]
        self.arguments = (*self.paths[:3], self.paths[3:5], self.paths[5:])

    def properties(self, name):
        """/** @param name 属性名 @return 构图所需的真实契约替身 */"""
        if name in ["target_skeleton", "skeleton"]:
            return self.skeleton
        if name == "status":
            return "Ready"
        if name == "slot_anim_tracks":
            return [Mock()]
        return Mock()

    def test_only_declared_targets_saved_after_compile(self):
        """/** @return 编译成功仅保存显式目标 骨架缺口交给统一权限层 */"""
        result = json.loads(self.configure(*self.arguments))
        targets = [self.assets[path] for path in self.paths[1:3]]
        targets.insert(1, self.assets[self.paths[0]])
        targets.extend(self.assets[path] for path in self.paths[3:])
        targets.append(self.skeleton)
        self.access.assert_called_once_with(targets)
        self.assertEqual([call.args for call in self.engine.EditorAssetLibrary.save_loaded_asset.call_args_list],
                         [(value, False) for value in targets])
        self.assertEqual(result["state"], "Traversal")
        self.assertEqual(result["layer"], "FullBody_TraversalState")
        self.engine.SourceControl.mark_file_for_add.assert_not_called()

    def test_duplicate_montages_rejected_before_loading(self):
        """/** @return 无效动作映射不产生任何编辑 */"""
        for paths in [self.paths[5:7], [self.paths[5]] * 3]:
            with self.assertRaises(RuntimeError):
                self.configure(*self.arguments[:4], paths)
        self.engine.load_asset.assert_not_called()
        self.access.assert_not_called()

    def test_slot_array_is_copied_and_written_back(self):
        """/** @return UE 数组元素的值复制不能吞掉槽修改 */"""
        self.configure(*self.arguments)
        for path in self.paths[5:]:
            calls = [call for call in self.assets[path].set_editor_property.call_args_list
                     if call.args[0] == "slot_anim_tracks"]
            self.assertEqual(len(calls), 1)
            tracks = calls[0].args[1]
            self.assertIs(type(tracks), list)
            self.assertEqual(len(tracks), 1)
            tracks[0].set_editor_property.assert_called_once_with("slot_name", "Traversal")

    def test_foreign_dirty_asset_is_not_overwritten(self):
        """/** @return 未保存的目标在构图前拒绝 */"""
        dirty = Mock()
        dirty.get_path_name.return_value = "/Game/Base"
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = [dirty]
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)
        self.engine.BBBBlueprintEditorLibrary.ensure_animation_layer_interface_function.assert_not_called()
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_wrong_inheritance_or_skeleton_rejected(self):
        """/** @return 具体层不允许脱离 Base 或替换骨架 */"""
        self.assets["/Game/Rifle"].get_blueprint_parent_class.return_value = object()
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)
        self.assets["/Game/Rifle"].get_blueprint_parent_class.return_value = self.base.generated_class()
        self.base.get_editor_property.side_effect = lambda name: object() if name == "target_skeleton" else self.properties(name)
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)
        self.access.assert_not_called()

    def test_permission_or_native_failure_does_not_save(self):
        """/** @return 占用或原生构图失败保留现场 不保存 */"""
        self.access.side_effect = RuntimeError("其它会话占用")
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)
        self.engine.BBBAnimationGraphEditorLibrary.configure_character_traversal_state.assert_not_called()
        self.access.side_effect = None
        self.engine.BBBAnimationGraphEditorLibrary.configure_character_traversal_state.return_value = False
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_compile_warning_prevents_all_saves(self):
        """/** @return 警告同错误一样阻止持久化 */"""
        self.base.get_editor_property.side_effect = lambda name: "Warning" if name == "status" else self.properties(name)
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_schema_has_one_current_authoring_entry(self):
        """/** @return 旧事件和旁路构图不再作为兼容入口保留 */"""
        schema = json.loads((ROOT / "Tests/tool_schema_baseline.json").read_text(encoding="utf-8"))["BBBTraversalToolset"]
        self.assertIn("configure_character_traversal_state", schema)
        self.assertNotIn("configure_traversal_blueprints", schema)
        self.assertNotIn("configure_traversal_ik_transition", schema)


class CharacterMovementInputTests(unittest.TestCase):
    """/** 移动意图构图只能持久化无警告的明确目标 */"""

    def setUp(self):
        """/** @return 隔离真实工具方法与编辑器依赖 */"""
        tree = ast.parse((ROOT / "Scripts/BBBTraversalToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "configure_character_movement_input")
        method.decorator_list = []
        self.engine = Mock()
        self.main = Mock()
        self.main.get_path_name.return_value = "/Game/Main.Main"
        self.main.get_outermost.return_value.get_path_name.return_value = "/Game/Main"
        self.main.get_editor_property.return_value = "Ready"
        self.engine.BlueprintStatus.BS_UP_TO_DATE = "Ready"
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = []
        self.engine.BBBAnimationGraphEditorLibrary.configure_character_movement_input.return_value = True
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True
        self.access = Mock()
        namespace = {"unreal": self.engine, "json": json, "require_asset_write": self.access,
                     "_blueprint": lambda path: self.main}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "movement_input_test", "exec"), namespace)
        self.configure = namespace[method.name]

    def test_only_main_saved(self):
        """/** @return 急转保留真实加速度 不保存整个工作区 */"""
        result = json.loads(self.configure("/Game/Main"))
        self.assertEqual(result["pivotFact"], "SourceAcceleration")
        self.assertEqual(result["movementFact"], "SourceMovementInput")
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.main, False)

    def test_dirty_target_rejected(self):
        """/** @return 别人的未保存目标不能被覆盖 */"""
        dirty = Mock()
        dirty.get_path_name.return_value = "/Game/Main"
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = [dirty]
        with self.assertRaises(RuntimeError):
            self.configure("/Game/Main")
        self.engine.BBBAnimationGraphEditorLibrary.configure_character_movement_input.assert_not_called()

    def test_native_failure_and_compile_warning_do_not_save(self):
        """/** @return 构图或严格编译失败时保留现场 */"""
        self.engine.BBBAnimationGraphEditorLibrary.configure_character_movement_input.return_value = False
        with self.assertRaises(RuntimeError):
            self.configure("/Game/Main")
        self.engine.BBBAnimationGraphEditorLibrary.configure_character_movement_input.return_value = True
        self.main.get_editor_property.return_value = "Warning"
        with self.assertRaises(RuntimeError):
            self.configure("/Game/Main")
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()


class TraversalFixtureRemovalTests(unittest.TestCase):
    """/** 提前退出验收必须保持各副本碰撞几何一致 */"""

    def setUp(self):
        """/** @return 隔离真实删除方法与三个 PIE 世界 */"""
        tree = ast.parse((ROOT / "Scripts/BBBTraversalToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "remove_pie_traversal_obstacle")
        method.decorator_list = []
        self.engine = Mock()
        self.worlds = [Mock() for _ in range(3)]
        self.fixtures = {world: [Mock(), Mock()] for world in self.worlds}
        for index, world in enumerate(self.worlds):
            world.get_path_name.return_value = "/PIE/World" + str(index)
        self.obstacles = [self.fixtures[world][1] for world in self.worlds]
        self.engine.EditorLevelLibrary.get_pie_worlds.return_value = self.worlds
        self.engine.SystemLibrary.is_valid.return_value = False
        namespace = {"unreal": self.engine, "json": json, "_fixtures": self.fixtures}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "fixture_removal_test", "exec"), namespace)
        self.remove = namespace[method.name]

    def test_default_removes_all_obstacles_and_keeps_floors(self):
        """/** @return 默认同时删除三副本障碍 地板保留 */"""
        result = json.loads(self.remove())
        self.assertEqual(result["worlds"], ["/PIE/World0", "/PIE/World1", "/PIE/World2"])
        for world, actor in zip(self.worlds, self.obstacles):
            actor.destroy_actor.assert_called_once_with()
            self.assertEqual(len(self.fixtures[world]), 1)

    def test_explicit_world_does_not_touch_other_fixtures(self):
        """/** @return 指定世界仅操作对应的临时障碍 */"""
        self.remove(1)
        self.obstacles[1].destroy_actor.assert_called_once_with()
        self.obstacles[0].destroy_actor.assert_not_called()
        self.obstacles[2].destroy_actor.assert_not_called()

    def test_invalid_index_or_missing_fixture_rejected(self):
        """/** @return 越界或无障碍时拒绝删除 */"""
        for index in [-2, 3]:
            with self.assertRaises(RuntimeError):
                self.remove(index)
        self.fixtures.clear()
        with self.assertRaises(RuntimeError):
            self.remove()


if __name__ == "__main__":
    unittest.main()
