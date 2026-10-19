import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class RightHandGripConfigurationTests(unittest.TestCase):
    """/** 验证共享图修改在未交接或原生失败时不保存资产 */"""

    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBHandPoseLayerTools.py").read_text(encoding="utf-8-sig"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "configure_right_hand_grip_rotation")

        class Blueprint:
            def __init__(self, path, parent=None):
                self.path = path
                self.parent = parent
                self.status = "ready"

            def generated_class(self):
                return self.path + "_C"

            def get_blueprint_parent_class(self):
                return self.parent

            def get_outermost(self):
                return SimpleNamespace(get_path_name=lambda: self.path)

            def get_path_name(self):
                return self.path

            def get_editor_property(self, name):
                return self.status

        self.base = Blueprint("/Game/Base")
        self.child = Blueprint("/Game/Child", self.base.generated_class())
        self.main = Blueprint("/Game/Main")
        self.assets = {x.path: x for x in [self.base, self.child, self.main]}
        self.dirty = []
        self.native = Mock(return_value=json.dumps({"status": "ok", "compiled": True}))
        self.save = Mock(return_value=True)
        self.compile = Mock()
        self.write = Mock()
        namespace = {"json": json, "require_asset_write": self.write,
                     "unreal": SimpleNamespace(AnimBlueprint=Blueprint, UnrealEditorSubsystem=object,
                         get_editor_subsystem=lambda kind: SimpleNamespace(get_game_world=lambda: None),
                         load_asset=lambda path: self.assets[path],
                         EditorLoadingAndSavingUtils=SimpleNamespace(get_dirty_content_packages=lambda: self.dirty),
                         BBBHandPoseLayerEditorLibrary=SimpleNamespace(configure_right_hand_grip_rotation=self.native),
                         BlueprintEditorLibrary=SimpleNamespace(compile_blueprint=self.compile),
                         BlueprintStatus=SimpleNamespace(BS_UP_TO_DATE="ready"),
                         EditorAssetLibrary=SimpleNamespace(save_loaded_asset=self.save))}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "right_hand_grip", "exec"), namespace)
        self.run_tool = lambda: namespace[function.name]("/Game/Base", ["/Game/Child"], "/Game/Main", "Skeletal", "a-guid")

    def test_dirty_target_blocks_native_edit(self):
        self.dirty = [self.base.get_outermost()]
        with self.assertRaisesRegex(RuntimeError, "未保存"):
            self.run_tool()
        self.native.assert_not_called()
        self.save.assert_not_called()

    def test_native_failure_is_not_saved(self):
        self.native.return_value = json.dumps({"status": "error", "compiled": False})
        with self.assertRaisesRegex(RuntimeError, "配置失败"):
            self.run_tool()
        self.save.assert_not_called()

    def test_child_compile_failure_stops_all_saves(self):
        self.child.status = "error"
        with self.assertRaisesRegex(RuntimeError, "编译失败"):
            self.run_tool()
        self.save.assert_not_called()

    def test_success_saves_exact_targets_in_order(self):
        result = self.run_tool()
        self.assertEqual(result["saved"], ["/Game/Base", "/Game/Child", "/Game/Main"])
        self.assertEqual([call.args[0] for call in self.save.call_args_list], [self.base, self.child, self.main])


if __name__ == "__main__":
    unittest.main()
