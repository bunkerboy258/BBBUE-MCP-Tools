import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class Blueprint:
    """/** 测试动画蓝图的保存边界与继承关系 */"""

    def __init__(self, path, parent=None):
        self.path = path
        self.parent = parent
        self.status = "ready"

    def generated_class(self):
        return self.path + "_C"

    def get_blueprint_parent_class(self):
        return self.parent

    def get_path_name(self):
        return self.path

    def get_outermost(self):
        return self

    def get_editor_property(self, name):
        return getattr(self, name)


class HandPoseLayerTests(unittest.TestCase):
    """/** 校验共享握姿工具的写入顺序与失败保存边界 */"""

    def setUp(self):
        self.calls = []
        self.assets = {name: Blueprint("/Game/" + name) for name in ("Main", "Base", "Interface", "Rifle")}
        self.assets["Rifle"].parent = self.assets["Base"].generated_class()
        self.world = None
        self.dirty = []
        self.native_result = {"status": "ok", "compiled": True}
        self.fail_compile = None
        unreal = types.ModuleType("unreal")
        unreal.AnimBlueprint = Blueprint
        unreal.SkeletalMesh = type("SkeletalMesh", (), {})
        unreal.AnimSequence = type("AnimSequence", (), {})
        self.assets["Mesh"] = unreal.SkeletalMesh()
        self.assets["BaseSequence"] = unreal.AnimSequence()
        self.assets["GripSequence"] = unreal.AnimSequence()
        unreal.UnrealEditorSubsystem = object
        unreal.get_editor_subsystem = lambda _: types.SimpleNamespace(get_game_world=lambda: self.world)
        unreal.load_asset = lambda path: self.assets[path.split("/")[-1]]
        unreal.EditorLoadingAndSavingUtils = types.SimpleNamespace(get_dirty_content_packages=lambda: self.dirty)
        unreal.BBBHandPoseLayerEditorLibrary = types.SimpleNamespace(configure_hand_pose_layer=self.native, sample_hand_pose_layer=self.sample)
        self.audit_dirties = False
        unreal.BlueprintEditorLibrary = types.SimpleNamespace(compile_blueprint=self.compile)
        unreal.BlueprintStatus = types.SimpleNamespace(BS_UP_TO_DATE="ready")
        unreal.EditorAssetLibrary = types.SimpleNamespace(save_loaded_asset=self.save)
        policy = types.ModuleType("BBBAssetWritePolicy")
        policy.require_asset_write = lambda targets: self.calls.append("write")
        self.patch = patch.dict(sys.modules, {"unreal": unreal, "BBBAssetWritePolicy": policy})
        self.patch.start()
        spec = importlib.util.spec_from_file_location("hand_pose_layer_under_test", ROOT / "Scripts/BBBHandPoseLayerTools.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def tearDown(self):
        self.patch.stop()

    def native(self, *args):
        self.calls.append("native")
        return json.dumps(self.native_result)

    def sample(self, *args):
        self.calls.append("sample")
        if self.audit_dirties:
            self.dirty.append(self.assets["Main"])
        return json.dumps({"status": "ok", "passed": True, "saved": False, "mainGameplayEvaluated": False})

    def compile(self, value):
        self.calls.append("compile:" + value.path)
        if value.path == self.fail_compile:
            value.status = "error"

    def save(self, value, only_if_dirty):
        self.calls.append("save:" + value.path)
        return True

    def execute(self, old_name="LeftHandPose", new_name="HandPose"):
        return self.module.configure_hand_pose_layer(
            "/Game/Main", "/Game/Base", "/Game/Interface", ["/Game/Rifle"],
            old_name, new_name, "SkeletalControls", "GetCharacterGripPose",
            "DisableLeftHandPoseOverride", "DisableRightHandPoseOverride",
            ["index_01_l", "thumb_01_l"], ["index_01_r", "thumb_01_r"])

    def assert_no_save(self):
        self.assertFalse(any(call.startswith("save:") for call in self.calls))

    def test_all_targets_compile_before_first_save(self):
        report = self.execute()
        first_save = next(index for index, call in enumerate(self.calls) if call.startswith("save:"))
        self.assertEqual(sum(call.startswith("compile:") for call in self.calls[:first_save]), 4)
        self.assertLess(self.calls.index("write"), self.calls.index("native"))
        self.assertEqual(report["saved"], ["/Game/Interface", "/Game/Base", "/Game/Rifle", "/Game/Main"])
        self.assertEqual(report["runtimeAcceptance"], "pending")

    def test_pie_refuses_before_write(self):
        self.world = object()
        with self.assertRaises(RuntimeError):
            self.execute()
        self.assertEqual(self.calls, [])

    def test_dirty_target_refuses_before_write(self):
        self.dirty = [self.assets["Main"]]
        with self.assertRaises(RuntimeError):
            self.execute()
        self.assertEqual(self.calls, [])

    def test_wrong_parent_refuses_before_write(self):
        self.assets["Rifle"].parent = "another_class"
        with self.assertRaises(RuntimeError):
            self.execute()
        self.assertEqual(self.calls, [])

    def test_native_failure_never_saves(self):
        self.native_result = {"status": "error", "error": "connection failed"}
        with self.assertRaises(RuntimeError):
            self.execute()
        self.assert_no_save()

    def test_child_compile_failure_never_saves(self):
        self.fail_compile = "/Game/Rifle"
        with self.assertRaises(RuntimeError):
            self.execute()
        self.assert_no_save()

    def test_explicit_same_name_configuration_reaches_native(self):
        report = self.execute("HandPose", "HandPose")
        self.assertIn("native", self.calls)
        self.assertEqual(report["runtimeAcceptance"], "pending")

    def test_already_configured_native_rejection_never_saves(self):
        self.native_result = {"status": "error", "code": "ALREADY_CONFIGURED", "error": "已配置"}
        with self.assertRaisesRegex(RuntimeError, "ALREADY_CONFIGURED"):
            self.execute("HandPose", "HandPose")
        self.assert_no_save()
        self.assertFalse(any(call.startswith("compile:") for call in self.calls))

    def audit(self, alphas=None):
        return self.module.audit_hand_pose_layer(
            "/Game/Mesh", "/Game/BaseSequence", "/Game/GripSequence", "/Game/Base", "/Game/Interface",
            "HandPose", [0.0, 0.5, 1.0] if alphas is None else alphas)

    def test_audit_uses_only_native_sampling_and_never_saves(self):
        report = self.audit()
        self.assertEqual(self.calls, ["sample"])
        self.assertTrue(report["projectDirtyPackagesUnchanged"])
        self.assertFalse(report["mainGameplayEvaluated"])

    def test_audit_rejects_pie(self):
        self.world = object()
        with self.assertRaises(RuntimeError):
            self.audit()
        self.assertEqual(self.calls, [])

    def test_audit_rejects_non_finite_alpha(self):
        with self.assertRaises(RuntimeError):
            self.audit([float("nan")])
        self.assertEqual(self.calls, [])

    def test_audit_detects_project_dirty_state_change(self):
        self.audit_dirties = True
        with self.assertRaises(RuntimeError):
            self.audit()
        self.assert_no_save()


if __name__ == "__main__":
    unittest.main()
