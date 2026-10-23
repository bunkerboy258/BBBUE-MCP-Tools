import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class AimOffsetAuthoringTests(unittest.TestCase):
    """/** AO 创建与公共层迁移的独占写入和保存边界 */"""

    def setUp(self):
        """/** @return 隔离加载工具函数 不启动编辑器 */"""
        tree = ast.parse((ROOT / "Scripts/BBBAnimationGraphToolset.py").read_text(encoding="utf-8-sig"))
        owner = next(value for value in tree.body if isinstance(value, ast.ClassDef))
        names = {"create_aim_offset_from_template", "configure_aim_offset_layer", "override_aim_offset_layer"}
        functions = [value for value in owner.body if isinstance(value, ast.FunctionDef) and value.name in names]
        for function in functions:
            function.decorator_list = []
        self.engine = Mock()
        self.engine.AnimSequence = type("Sequence", (), {})
        self.engine.AimOffsetBlendSpace = type("AimOffset", (), {})
        self.engine.AnimBlueprint = type("Blueprint", (), {})
        self.access = Mock()
        self.scope = {"unreal": self.engine, "json": json, "require_asset_write": self.access}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "aim_offset_tools", "exec"), self.scope)
        self.source = self.engine.AimOffsetBlendSpace()
        self.source.get_editor_property = Mock(return_value=[object()])
        self.sequence = self.engine.AnimSequence()
        self.skeleton = Mock()
        self.skeleton.get_path_name.return_value = "/Game/Skeleton"
        self.sequence.get_editor_property = Mock(side_effect=lambda name: self.skeleton if name == "skeleton"
            else self.engine.AdditiveAnimationType.AAT_ROTATION_OFFSET_MESH_SPACE)
        self.sequence.get_path_name = Mock(return_value="/Game/Sequence.Sequence")
        self.asset = self.engine.AimOffsetBlendSpace()
        sample = Mock()
        sample.get_editor_property.return_value = self.sequence
        self.asset.get_editor_property = Mock(side_effect=lambda name: self.skeleton if name == "skeleton" else [sample])
        self.asset.get_path_name = Mock(return_value="/Game/_Project/AO.AO")
        self.engine.load_asset.side_effect = lambda path: self.source if path == "/Game/Source" else self.sequence
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = False
        self.engine.EditorAssetLibrary.duplicate_asset.return_value = self.asset
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True
        self.engine.BBBAimOffsetEditorLibrary.configure_aim_offset.return_value = True

    def test_create_preserves_source_and_reads_saved_samples(self):
        """/** @return 只配置新副本并按源顺序保存回读 */"""
        result = json.loads(self.scope["create_aim_offset_from_template"](
            "/Game/Source", "/Game/_Project/AO", ["/Game/Sequence"]))
        self.access.assert_called_once_with([], destinations=["/Game/_Project/AO"])
        self.engine.BBBAimOffsetEditorLibrary.configure_aim_offset.assert_called_once_with(
            self.asset, self.source, [self.sequence])
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.asset, False)
        self.assertEqual(result["samples"], ["/Game/Sequence.Sequence"])

    def test_existing_and_external_destinations_rejected_before_write(self):
        """/** @return 不覆盖已有资产且不创建第三方目标 */"""
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = True
        for destination in ("/Game/_Project/AO", "/Game/_ThirdParty/AO"):
            with self.assertRaises(RuntimeError):
                self.scope["create_aim_offset_from_template"]("/Game/Source", destination, ["/Game/Sequence"])
        self.access.assert_not_called()
        self.engine.EditorAssetLibrary.duplicate_asset.assert_not_called()

    def test_invalid_samples_rejected_before_duplicate(self):
        """/** @return 错误采样类型或加法设置不产生新资产 */"""
        self.sequence.get_editor_property.return_value = None
        self.sequence.get_editor_property.side_effect = lambda name: self.skeleton if name == "skeleton" else "LocalSpace"
        with self.assertRaises(RuntimeError):
            self.scope["create_aim_offset_from_template"]("/Game/Source", "/Game/_Project/AO", ["/Game/Sequence"])
        self.engine.EditorAssetLibrary.duplicate_asset.assert_not_called()

    def test_failed_native_configuration_is_not_saved(self):
        """/** @return 原生配置失败时不保存 */"""
        self.engine.BBBAimOffsetEditorLibrary.configure_aim_offset.return_value = False
        with self.assertRaises(RuntimeError):
            self.scope["create_aim_offset_from_template"]("/Game/Source", "/Game/_Project/AO", ["/Game/Sequence"])
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_recoil_snapshot_has_no_target_offset_fallback(self):
        """/** @return 采样与构图只使用当前后坐力快照 不恢复旧引脚 */"""
        text = (ROOT / "Scripts/BBBWeaponHandlingTools.py").read_text(encoding="utf-8-sig")
        self.assertIn("main.get_recoil_angles()", text)
        self.assertIn("WeaponPoseOffsetAngles", text)
        self.assertNotIn("get_aim_offset_degrees", text)
        self.assertNotIn("WeaponAimOffsetDegrees", text)
        self.assertNotIn('"AimOffsetDegrees"', text)

    def test_migration_checks_dirty_and_compile_before_save(self):
        """/** @return 写入前拒绝脏包且无警告编译后才保存 */"""
        tree = ast.parse((ROOT / "Scripts/BBBAnimationGraphToolset.py").read_text(encoding="utf-8-sig"))
        owner = next(value for value in tree.body if isinstance(value, ast.ClassDef))
        for name in ("configure_aim_offset_layer", "override_aim_offset_layer"):
            function = next(value for value in owner.body if isinstance(value, ast.FunctionDef) and value.name == name)
            calls = [value for value in ast.walk(function) if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)]
            dirty = next(value.lineno for value in calls if value.func.attr == "get_dirty_content_packages")
            native = next(value.lineno for value in calls if value.func.attr in ("insert_aim_offset_layer", "override_aim_offset_assets"))
            compile_line = next(value.lineno for value in calls if value.func.attr == "compile_blueprint")
            save = next(value.lineno for value in calls if value.func.attr == "save_loaded_asset")
            self.assertLess(dirty, native)
            self.assertLess(native, compile_line)
            self.assertLess(compile_line, save)

    def configure_fixture(self, connected):
        """/** @param connected 基础姿势是否有效 @return 隔离的图表写入实参 */"""
        blueprint = self.engine.AnimBlueprint()
        blueprint.get_outermost = Mock()
        blueprint.get_editor_property = Mock(return_value=self.engine.BlueprintStatus.BS_UP_TO_DATE)
        blueprint.get_path_name = Mock(return_value="/Game/_Project/Layer.Layer")
        self.engine.load_asset.side_effect = lambda path: blueprint if path == "/Game/_Project/Layer" else self.asset
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = []
        snapshot = {"nodes": [
            {"guid": "input", "nodeClass": "AnimGraphNode_LinkedInputPose"},
            {"guid": "apply", "nodeClass": "AnimGraphNode_ApplyMeshSpaceAdditive",
             "pins": [{"name": "Base", "pinId": "base", "links":
                       [{"nodeGuid": "input", "pinId": "pose"}] if connected else []}]},
            *[{"guid": str(index), "nodeClass": "AnimGraphNode_BlendSpacePlayer"} for index in range(3)]]}
        self.engine.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot.return_value = json.dumps(snapshot)
        return ("/Game/_Project/Layer", "Controls", "Recoil", ["/AO"] * 3,
                ["Crouching"], "control", "", "GetRecoilAngles", "", "AimOffsetDegrees")

    def test_single_base_pose_connection_is_required(self):
        """/** @return 编译通过但基础姿势断开时仍明确拒绝成功 */"""
        arguments = self.configure_fixture(False)
        with self.assertRaisesRegex(RuntimeError, "基础姿势"):
            self.scope["configure_aim_offset_layer"](*arguments)

    def test_additive_selection_keeps_the_base_pose(self):
        """/** @return 仅加法分支混合并保留唯一基础姿势连接 */"""
        arguments = self.configure_fixture(True)
        result = json.loads(self.scope["configure_aim_offset_layer"](*arguments))
        self.assertTrue(result["saved"])
        self.assertEqual(len(result["poses"]), 3)

    def test_override_result_serializes_engine_arrays(self):
        """/** @return 引擎数组转换为普通列表后返回标准 JSON */"""
        class EngineArray:
            def __iter__(self):
                return iter(["/AO"] * 3)

        self.configure_fixture(True)
        result = json.loads(self.scope["override_aim_offset_layer"](
            "/Game/_Project/Layer", "/Game/_Project/Layer", "Controls", EngineArray()))
        self.assertEqual(result["offsets"], ["/AO"] * 3)


if __name__ == "__main__":
    unittest.main()
