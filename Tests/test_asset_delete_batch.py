import ast
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import mock_open, patch


ROOT = Path(__file__).resolve().parents[1]


class AssetDeleteBatchTests(unittest.TestCase):
    """/** 验证整组原生删除保持全部预检和逐包核验 */"""

    def setUp(self):
        """/** @return 两个互相引用的明确资产和单次原生调用计数 */"""
        self.paths = ["/Game/_Project/A", "/Game/_Project/B"]
        self.objects = {path + "." + path.rsplit("/", 1)[-1]: SimpleNamespace(get_path_name=lambda value=path: value + "." + value.rsplit("/", 1)[-1]) for path in self.paths}
        self.deleted = []
        self.files = {path + ".uasset" for path in self.paths}
        self.refs = {self.paths[0]: [self.paths[1]], self.paths[1]: [self.paths[0]]}
        self.dirty = []
        self.native_result = True
        self.leave_file = False
        tree = ast.parse((ROOT / "Scripts/BBBAssetMaintenanceToolset.py").read_text(encoding="utf-8-sig"))
        node = next(x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef) and x.name == "delete_unreferenced_project_assets")
        node.decorator_list = []
        self.runtime = {
            "json": json, "hashlib": hashlib, "os": os,
            "_move_path": lambda value: value,
            "_move_dirty_packages": lambda paths: self.dirty,
            "_move_registry": lambda: object(),
            "_move_referencers": lambda registry, path: self.refs[path],
            "_move_filename": lambda path: path + ".uasset",
            "require_asset_write": lambda *args: None,
            "unreal": SimpleNamespace(
                LevelEditorSubsystem=object,
                get_editor_subsystem=lambda subsystem: SimpleNamespace(is_in_play_in_editor=lambda: False),
                load_object=lambda outer, path, **options: self.objects.get(path),
                BBBAssetRepairEditorLibrary=SimpleNamespace(delete_asset_packages=self.delete),
            ),
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "delete_batch", "exec"), self.runtime)
        self.tool = self.runtime[node.name]
        self.sha = hashlib.sha256(b"reviewed").hexdigest()

    def delete(self, objects):
        """/** @param objects 全部显式对象 @return 单次原生结果且模拟逐文件残留 */"""
        self.deleted.append(list(objects))
        if not self.leave_file:
            self.files.clear()
        return self.native_result

    def run_delete(self, hashes=None):
        """/** @param hashes 对应审阅摘要 @return 在真实组边界运行工具 */"""
        with patch("builtins.open", mock_open(read_data=b"reviewed")), patch("os.path.exists", side_effect=lambda path: path in self.files):
            return json.loads(self.tool(self.paths, hashes or [self.sha] * 2, False))

    def test_internal_references_delete_as_one_native_group_and_verify_each_file(self):
        """/** @return 相互引用组只删除一次 所有文件分别回读不存在 */"""
        result = self.run_delete()
        self.assertTrue(result["success"])
        self.assertEqual(len(self.deleted), 1)
        self.assertEqual(self.deleted[0], list(self.objects.values()))
        self.assertEqual([x["package"] for x in result["files"]], self.paths)
        self.assertTrue(all(x["nativeDeleted"] and x["fileAbsent"] for x in result["files"]))

    def test_last_hash_mismatch_prevents_entire_native_group(self):
        """/** @return 后一项摘要不符不能先删除前一项 */"""
        with self.assertRaisesRegex(RuntimeError, "哈希"):
            self.run_delete([self.sha, "0" * 64])
        self.assertEqual(self.deleted, [])

    def test_reference_created_during_loading_prevents_entire_group(self):
        """/** @return 加载引入外部引用仍在原生变更前拦截 */"""
        previous = self.runtime["unreal"].load_object
        def load(*args, **kwargs):
            """/** @return 模拟加载最后对象产生外部引用 */"""
            asset = previous(*args, **kwargs)
            self.refs[self.paths[1]] = ["/Game/_Project/Other"]
            return asset
        self.runtime["unreal"].load_object = load
        with self.assertRaisesRegex(RuntimeError, "组外引用"):
            self.run_delete()
        self.assertEqual(self.deleted, [])

    def test_missing_object_prevents_group_and_native_failure_is_not_retried(self):
        """/** @return 缺对象整组不执行 原生失败不重试 */"""
        missing = self.objects.pop(self.paths[1] + ".B")
        with self.assertRaisesRegex(RuntimeError, "路径不符"):
            self.run_delete()
        self.assertEqual(self.deleted, [])
        self.objects[self.paths[1] + ".B"] = missing
        self.native_result = False
        with self.assertRaisesRegex(RuntimeError, "删除核验失败"):
            self.run_delete()
        self.assertEqual(len(self.deleted), 1)

    def test_native_success_cannot_hide_remaining_file(self):
        """/** @return 原生成功但磁盘仍存在也必须失败 */"""
        self.leave_file = True
        with self.assertRaisesRegex(RuntimeError, "删除核验失败"):
            self.run_delete()
        self.assertEqual(len(self.deleted), 1)


if __name__ == "__main__":
    unittest.main()
