import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest


class ControlRigBakeCurvesTests(unittest.TestCase):
    """/** 验证重复烘焙的曲线归属与内存快照清理 */"""

    def fixture(self, existing=True, export_success=True, duplicate_success=True):
        """/** @return 不加载 UE 的真实烘焙函数及独立引擎替身 */"""
        source_path = Path(__file__).resolve().parents[1] / "Scripts/BBBControlRigAuthoringToolset.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8-sig"))
        function = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == "bake_control_rig_animation")
        function.decorator_list = []

        class Animation:
            """/** 浮点曲线包含插值与切线测试数据 */"""
            def __init__(self, curves=None):
                self.curves = curves or {}
                self.sequence_length = 2.2

            def get_path_name(self):
                return "/Game/Test"

            def set_editor_property(self, name, value):
                setattr(self, name, value)

        source = Animation({"IK": [{"time": 1.9, "value": 0, "tangent": 0}]})
        target = Animation({"IK": [{"time": 2.03, "value": 1, "tangent": 0.7, "interp": "cubic"}]})
        snapshot = Animation(copy.deepcopy(target.curves))
        state = SimpleNamespace(saved=[], deleted=[], exported=[], copied_from=[], target=target, source=source)
        section = SimpleNamespace(get_editor_property=lambda name: SimpleNamespace(animation=source))
        track = SimpleNamespace(get_sections=lambda: [section])
        binding = SimpleNamespace(find_tracks_by_type=lambda kind: [track] if kind == "animation" else [object()])
        mesh = SimpleNamespace(get_editor_property=lambda name: object())

        def export(world, sequence, animation, options, binding, linked):
            state.exported.append(animation)
            animation.curves = {"Exported": []}
            return export_success

        def copy_curves(animation, destination):
            state.copied_from.append(animation)
            destination.curves = copy.deepcopy(animation.curves)
            return len(animation.curves)

        def save(animation, only_dirty):
            state.saved.append(animation)
            return True

        def delete(animation):
            state.deleted.append(animation)
            return True

        assets = SimpleNamespace(
            duplicate_asset=lambda name, folder, animation: snapshot if duplicate_success else None,
            create_asset=lambda *args: target,
        )
        unreal = SimpleNamespace(
            LevelSequence=object, SkeletalMesh=object, AnimSequence=Animation,
            MovieSceneControlRigParameterTrack="rig", MovieSceneSkeletalAnimationTrack="animation",
            AnimSequenceFactory=SimpleNamespace, AnimSeqExportOption=SimpleNamespace,
            UnrealEditorSubsystem=object,
            get_editor_subsystem=lambda kind: SimpleNamespace(get_editor_world=lambda: object()),
            AssetToolsHelpers=SimpleNamespace(get_asset_tools=lambda: assets),
            EditorAssetLibrary=SimpleNamespace(does_asset_exist=lambda path: existing,
                                              save_loaded_asset=save, delete_loaded_asset=delete),
            AnimationLibrary=SimpleNamespace(get_animation_curve_names=lambda animation, kind: list(animation.curves)),
            RawCurveTrackTypes=SimpleNamespace(RCT_FLOAT="float"),
            SequencerTools=SimpleNamespace(export_anim_sequence=export),
            BBBBlueprintEditorLibrary=SimpleNamespace(copy_animation_float_curves=copy_curves),
        )
        namespace = {"unreal": unreal, "json": json,
                     "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="unit")),
                     "_asset": lambda path, kind: target if path == "/Game/Test" else mesh,
                     "_mesh_binding": lambda sequence, mesh: binding,
                     "require_write_access": lambda animation: None,
                     "require_asset_write": lambda *args, **kwargs: None}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source_path), "exec"), namespace)
        return lambda: namespace["bake_control_rig_animation"]("/Game/Sequence", "/Game/Test", "/Game/Mesh"), state

    def test_existing_target_curves_keep_custom_timing_and_tangents(self):
        """/** @return 重复烘焙不使用旧底稿覆盖目标曲线 */"""
        bake, state = self.fixture()
        expected = copy.deepcopy(state.target.curves)
        bake()
        self.assertEqual(state.target.curves, expected)
        self.assertEqual(len(state.deleted), 1)
        self.assertIsNot(state.copied_from[0], state.source)

    def test_new_empty_target_uses_source_curves(self):
        """/** @return 首次烘焙没有目标曲线时从源动作初始化 */"""
        bake, state = self.fixture(existing=False)
        state.target.curves = {}
        bake()
        self.assertEqual(state.target.curves, state.source.curves)
        self.assertEqual(state.deleted, [])

    def test_export_failure_cleans_snapshot_without_saving_target(self):
        """/** @return 烘焙失败仍清理内存快照 */"""
        bake, state = self.fixture(export_success=False)
        with self.assertRaises(RuntimeError):
            bake()
        self.assertEqual(len(state.deleted), 1)
        self.assertEqual(state.saved, [])

    def test_snapshot_failure_does_not_start_export(self):
        """/** @return 快照失败在修改目标前拒绝烘焙 */"""
        bake, state = self.fixture(duplicate_success=False)
        with self.assertRaises(RuntimeError):
            bake()
        self.assertEqual(state.exported, [])
        self.assertEqual(state.saved, [])


if __name__ == "__main__":
    unittest.main()
