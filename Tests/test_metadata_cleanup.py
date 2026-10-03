import ast
import json
import os
from pathlib import Path
import tempfile
import types
import unittest


class MetadataCleanupTests(unittest.TestCase):
    """/** 元数据空包清理的拒绝条件检查 */"""

    def setUp(self):
        """/** @return 隔离执行工具方法并记录破坏性调用 */"""
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "delete_metadata_only_package")
        method.decorator_list = []
        self.calls = []
        self.report = {"success": True, "export_count": 1, "objects": [{"class": "/Script/CoreUObject.MetaData", "is_asset": False}]}
        self.registry = types.SimpleNamespace(get_assets_by_package_name=lambda path: [])
        self.runtime = {
            "json": json,
            "_move_path": lambda path: path,
            "_move_dirty_packages": lambda: [],
            "_move_registry": lambda: self.registry,
            "_move_referencers": lambda registry, path: [],
            "_require_move_checkout": lambda sources, targets: self.calls.append("checkout"),
            "unreal": types.SimpleNamespace(
                LevelEditorSubsystem=object,
                get_editor_subsystem=lambda kind: types.SimpleNamespace(is_in_play_in_editor=lambda: False),
                BBBAssetRepairEditorLibrary=types.SimpleNamespace(
                    inspect_package_objects=lambda path: json.dumps(self.report),
                    delete_metadata_only_package=lambda path: self.calls.append("delete") or True,
                ),
                log_error=lambda message: self.calls.append("alarm"),
            ),
        }
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), self.runtime)
        self.cleanup = self.runtime[method.name]

    def test_dry_run_never_deletes(self):
        """/** @return 预检只读且不签出文件 */"""
        self.assertTrue(json.loads(self.cleanup("/Game/Empty"))["success"])
        self.assertEqual(self.calls, [])

    def test_referenced_package_is_rejected(self):
        """/** @return 存在引用者时不调用原生删除 */"""
        self.runtime["_move_referencers"] = lambda registry, path: ["/Game/Reference"]
        with self.assertRaises(RuntimeError):
            self.cleanup("/Game/Empty", False)
        self.assertEqual(self.calls, [])

    def test_pie_blocks_cleanup(self):
        """/** @return 游戏预览期间不加载或删除包 */"""
        self.runtime["unreal"].get_editor_subsystem = lambda kind: types.SimpleNamespace(is_in_play_in_editor=lambda: True)
        with self.assertRaises(RuntimeError):
            self.cleanup("/Game/Empty", False)
        self.assertEqual(self.calls, [])

    def test_real_or_unknown_exports_are_rejected(self):
        """/** @return 真实对象与未知导出都不能当作空包 */"""
        for report in [
            {"success": True, "export_count": 2, "objects": []},
            {"success": False, "export_count": 1, "objects": []},
            {"success": True, "export_count": 1, "objects": [{"class": "/Script/Engine.Texture2D", "is_asset": True}]},
        ]:
            self.report = report
            with self.assertRaises(RuntimeError):
                self.cleanup("/Game/Empty", False)
        self.assertEqual(self.calls, [])

    def test_native_failure_is_reported(self):
        """/** @return 删除失败时保留失败结果并报警 */"""
        self.runtime["unreal"].BBBAssetRepairEditorLibrary.delete_metadata_only_package = lambda path: False
        self.assertFalse(json.loads(self.cleanup("/Game/Empty", False))["success"])
        self.assertEqual(self.calls, ["checkout", "alarm"])


class MapRedirectorDeletionTests(unittest.TestCase):
    """/** 地图重定向包的物理文件验收检查 */"""

    def test_map_file_remaining_blocks_success(self):
        """/** @return 原生返回成功但地图文件残留时必须拒绝验收 */"""
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "delete_asset_redirectors")
        method.decorator_list = []
        deleted = []
        record = types.SimpleNamespace(asset_class_path="/Script/CoreUObject.ObjectRedirector", asset_name="OldWorld")
        registry = types.SimpleNamespace(get_assets_by_package_name=lambda path: [] if deleted else [record])
        redirector = types.SimpleNamespace(
            get_path_name=lambda: "/Game/OldWorld.OldWorld",
            get_class=lambda: types.SimpleNamespace(get_name=lambda: "ObjectRedirector"),
        )

        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "OldWorld.umap").touch()
            runtime = {
                "json": json,
                "os": os,
                "_move_path": lambda path: path,
                "_move_registry": lambda: registry,
                "_move_dirty_packages": lambda: [],
                "_move_referencers": lambda registry, path: [],
                "_move_class_path": lambda value: value,
                "_require_move_checkout": lambda sources, targets: None,
                "_move_filename": lambda path, extension=".uasset": str(Path(directory) / ("OldWorld" + extension)),
                "unreal": types.SimpleNamespace(
                    LevelEditorSubsystem=object,
                    get_editor_subsystem=lambda kind: types.SimpleNamespace(is_in_play_in_editor=lambda: False),
                    load_object=lambda outer, path, **options: redirector,
                    BBBAssetRepairEditorLibrary=types.SimpleNamespace(delete_redirector_packages=lambda objects: deleted.append(True) or True),
                    log=lambda message: None,
                    log_error=lambda message: None,
                ),
            }
            exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), runtime)
            result = json.loads(runtime[method.name](["/Game/OldWorld"], False))
            self.assertEqual(result["remaining_files"], ["/Game/OldWorld"])
            self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
