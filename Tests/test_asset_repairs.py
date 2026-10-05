import ast
import json
from pathlib import Path
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AssetRepairTests(unittest.TestCase):
    """/** 姿势缓存维护的拒绝条件和载荷保护回归检查 */"""

    def setUp(self):
        """/** @return 隔离执行通用工具方法 不加载编辑器或写入资产 */"""
        source = ROOT / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "repair_pose_asset_source_guids")
        method.decorator_list = []
        self.before = {"asset": "/Game/Poses/Pose.Pose", "stored_guid": "old", "legacy_matches": True, "current_matches": False, "payload_hash": "same"}
        self.calls = []
        self.runtime = {
            "json": json,
            "_move_path": lambda path: path,
            "_move_dirty_packages": lambda: [],
            "require_asset_write": lambda paths, targets: self.calls.append("checkout"),
            "BBBAssetMaintenanceToolset": types.SimpleNamespace(inspect_pose_asset_source_guids=lambda paths: json.dumps([self.before])),
            "unreal": types.SimpleNamespace(
                EditorAssetLibrary=types.SimpleNamespace(
                    load_asset=lambda path: path,
                    save_loaded_asset=lambda asset, **kwargs: self.calls.append("save") or True,
                ),
                BBBAssetRepairEditorLibrary=types.SimpleNamespace(
                    repair_pose_source_guid=lambda asset, expected, allow_samples: json.dumps(dict(self.before, current_matches=True)),
                ),
            ),
        }
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), self.runtime)
        self.repair = self.runtime[method.name]

    def test_dry_run_is_read_only(self):
        """/** @return 预检不签出 不写缓存 不保存 */"""
        self.assertEqual(json.loads(self.repair(json.dumps([self.before]))), [self.before])
        self.assertEqual(self.calls, [])

    def test_guid_mismatch_cannot_be_hidden(self):
        """/** @return 不匹配旧算法的 GUID 不得直接覆盖 */"""
        self.before["legacy_matches"] = False
        with self.assertRaises(RuntimeError):
            self.repair(json.dumps([self.before]), False)
        self.assertEqual(self.calls, [])

    def test_report_drift_is_rejected(self):
        """/** @return 执行阶段拒绝检查报告发生漂移 */"""
        expected = dict(self.before, payload_hash="changed")
        with self.assertRaises(RuntimeError):
            self.repair(json.dumps([expected]), False)
        self.assertEqual(self.calls, [])

    def test_dirty_packages_block_execution(self):
        """/** @return 无关脏包存在时不开始维护 */"""
        self.runtime["_move_dirty_packages"] = lambda: ["/Game/UserWork"]
        with self.assertRaises(RuntimeError):
            self.repair(json.dumps([self.before]), False)
        self.assertEqual(self.calls, [])

    def test_payload_change_blocks_save(self):
        """/** @return 原生修复返回载荷变化时禁止保存 */"""
        self.runtime["unreal"].BBBAssetRepairEditorLibrary.repair_pose_source_guid = lambda asset, expected, allow_samples: json.dumps(dict(self.before, current_matches=True, payload_hash="different"))
        with self.assertRaises(RuntimeError):
            self.repair(json.dumps([self.before]), False)
        self.assertEqual(self.calls, ["checkout"])

    def test_verified_metadata_can_be_saved(self):
        """/** @return GUID 与载荷核验通过才保存 */"""
        result = json.loads(self.repair(json.dumps([self.before]), False))
        self.assertTrue(result[0]["current_matches"])
        self.assertEqual(self.calls, ["checkout", "save"])

    def test_sample_proof_requires_explicit_opt_in(self):
        """/** @return 默认拒绝逐键证明 显式启用后仍要求校验通过 */"""
        self.before.update(legacy_matches=False, samples_match=True)
        with self.assertRaises(RuntimeError):
            self.repair(json.dumps([self.before]), False)
        self.assertEqual(self.calls, [])
        result = json.loads(self.repair(json.dumps([self.before]), False, True))
        self.assertTrue(result[0]["current_matches"])

    def test_failed_sample_proof_is_rejected(self):
        """/** @return 显式启用也不能覆盖校验失败的真实姿势差异 */"""
        self.before.update(legacy_matches=False, samples_match=False)
        with self.assertRaises(RuntimeError):
            self.repair(json.dumps([self.before]), False, True)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
