import ast
import hashlib
import json
import math
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, mock_open, patch


ROOT = Path(__file__).resolve().parents[1]


def load_method(filename, name, namespace):
    """/** @return 只加载目标工具函数以隔离编辑器依赖 */"""
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8-sig"))
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
    method.decorator_list = []
    method.body = [node for node in method.body if not isinstance(node, ast.ImportFrom)]
    exec(compile(ast.Module(body=[method], type_ignores=[]), name, "exec"), namespace)
    return namespace[name]


class ConsumableAuthoringTests(unittest.TestCase):
    """/** 验证动作配置和精确资产清理的失败边界 */"""

    def setUp(self):
        self.engine = Mock()
        self.engine.AnimMontage = Mock
        self.montage = Mock()
        self.engine.load_asset.return_value = self.montage
        self.access = Mock()
        self.native = self.engine.BBBAssetRepairEditorLibrary.configure_action_montage
        self.native.return_value = '{"success":true,"segments":2}'
        self.configure = load_method("Scripts/BBBGenericEditorToolset.py", "configure_action_montage",
                                     {"unreal": self.engine, "math": math, "json": json, "require_write_access": self.access})

    def test_invalid_timing_never_calls_native_editor(self):
        for starts, ends, rates, loop in [([0], [1, 2], [1], -1), ([0], [1], [float("nan")], -1), ([0], [1], [1], 1)]:
            with self.assertRaises(RuntimeError):
                self.configure("/Game/_Project/AM", ["/Game/AS"], starts, ends, rates, loop)
        self.native.assert_not_called()
        self.access.assert_not_called()

    def test_native_failure_never_saves_asset(self):
        self.native.return_value = '{"success":false}'
        with self.assertRaises(RuntimeError):
            self.configure("/Game/_Project/AM", ["/Game/AS"], [0], [1], [1])
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_success_saves_after_native_configuration(self):
        result = json.loads(self.configure("/Game/_Project/AM", ["/Game/AS"], [0], [1], [1]))
        self.assertTrue(result["saved"])
        self.assertEqual(result["sequences"], ["/Game/AS"])
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.montage, False)

    def deletion(self, referencers=(), dirty=False):
        self.engine.get_editor_subsystem.return_value.is_in_play_in_editor.return_value = False
        self.write = Mock()
        return load_method("Scripts/BBBAssetMaintenanceToolset.py", "delete_unreferenced_project_assets", {
            "unreal": self.engine, "json": json, "hashlib": hashlib, "os": os,
            "_move_path": lambda path: path, "_move_dirty_packages": lambda paths: dirty,
            "_move_registry": Mock(), "_move_referencers": lambda registry, path: referencers,
            "_move_filename": lambda path: "asset.uasset", "require_asset_write": self.write})

    def test_delete_rejects_external_reference_before_file_access(self):
        with patch("builtins.open", mock_open(read_data=b"asset")) as disk:
            with self.assertRaises(RuntimeError):
                self.deletion(["/Game/Outside"])(["/Game/_Project/Old"], ["0" * 64], False)
        disk.assert_not_called()
        self.write.assert_not_called()

    def test_delete_hash_mismatch_never_mutates(self):
        with patch("builtins.open", mock_open(read_data=b"changed")):
            with self.assertRaises(RuntimeError):
                self.deletion()(["/Game/_Project/Old"], [hashlib.sha256(b"reviewed").hexdigest()], False)
        self.write.assert_not_called()
        self.engine.BBBAssetRepairEditorLibrary.delete_asset_packages.assert_not_called()

    def test_delete_dry_run_checks_hash_without_mutation(self):
        with patch("builtins.open", mock_open(read_data=b"reviewed")):
            result = json.loads(self.deletion()(["/Game/_Project/Old"], [hashlib.sha256(b"reviewed").hexdigest()]))
        self.assertTrue(result["dryRun"])
        self.write.assert_not_called()

    def test_capture_age_uses_world_time_when_interface_stalls(self):
        self.engine.NiagaraSystem = Mock
        self.engine.load_asset.return_value.get_path_name.return_value = "System.System"
        world = self.engine.get_editor_subsystem.return_value.get_game_world.return_value
        self.engine.GameplayStatics.get_time_seconds.side_effect = [100.0, 100.05, 100.30]
        self.engine.BBBNiagaraEditorLibrary.read_preview_system_age.side_effect = [0.05, 0.30]
        self.engine.SystemLibrary.is_valid.return_value = True
        self.engine.Paths.project_saved_dir.return_value = "E:/Virtual/Saved"
        self.engine.Vector.side_effect = lambda *values: tuple(values)
        namespace = {"unreal": self.engine, "json": json, "math": math, "os": os,
                     "time": time, "stat": __import__("stat"), "_capture_handle": None}
        capture = load_method("Scripts/BBBDisplayAssetCaptureTools.py", "capture_niagara_asset", namespace)
        with patch("os.path.lexists", return_value=False), patch.dict(sys.modules, {
                "BBBMcpCapabilities": SimpleNamespace(register_activity=Mock())}):
            capture("System", 0.25, [100, 0, 0], "task/image.png")
            tick = self.engine.register_slate_post_tick_callback.call_args.args[0]
            tick(5.0)
            self.assertAlmostEqual(namespace["_capture"]["simulationSeconds"], 0.05)
            self.assertFalse(namespace["_capture"]["captured"])
            tick(5.0)
            self.assertTrue(namespace["_capture"]["captured"])


if __name__ == "__main__":
    unittest.main()
