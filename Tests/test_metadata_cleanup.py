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



class ContentDependencyIntegrityTests(unittest.TestCase):
    """/** 硬软包引用的物理目录验收检查 */"""

    def setUp(self):
        """/** @return 建立不具备加载或保存接口的只读注册表环境 */"""
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "inspect_content_dependency_integrity")
        method.decorator_list = []
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.options = []
        self.dependencies = {"/Game/Owner": ["/Game/HardMissing", "/Game/SoftMissing", "/Game/Map", "/Engine/Virtual", "/Script/Engine"]}
        self.runtime = {
            "json": json,
            "os": os,
            "_move_path": lambda path: path,
            "_move_filename": lambda path, extension: str(Path(self.directory.name) / (path.rsplit("/", 1)[-1] + extension)),
            "_move_registry": lambda: types.SimpleNamespace(get_dependencies=lambda package, options: self.dependencies.get(package, [])),
            "_external_actor_package_path": lambda path: path,
            "_external_object_package_path": lambda path: path,
            "unreal": types.SimpleNamespace(AssetRegistryDependencyOptions=lambda **options: self.options.append(options) or options),
        }
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), self.runtime)
        self.audit = self.runtime[method.name]
        (Path(self.directory.name) / "Map.umap").touch()

    def test_reports_hard_and_soft_missing_packages_without_loading(self):
        """/** @return 硬软缺失包均报告且地图文件被认可 虚拟引擎包不误报 */"""
        report = json.loads(self.audit(["/Game/Owner"]))
        self.assertFalse(report["success"])
        self.assertEqual(report["missing_packages"], ["/Game/HardMissing", "/Game/SoftMissing"])
        self.assertEqual(report["referencers"][0]["package"], "/Game/Owner")
        self.assertTrue(self.options[1]["include_soft_package_references"])
        self.assertTrue(self.options[0]["include_hard_package_references"])

    def test_existing_assets_pass_and_duplicate_inputs_are_rejected(self):
        """/** @return 项目依赖实际存在时通过 重复输入拒绝不完整核验 */"""
        (Path(self.directory.name) / "HardMissing.uasset").touch()
        (Path(self.directory.name) / "SoftMissing.uasset").touch()
        self.assertTrue(json.loads(self.audit(["/Game/Owner"]))["success"])
        with self.assertRaises(RuntimeError):
            self.audit(["/Game/Owner", "/Game/Owner"])


class MissingSoftPathRepairTests(unittest.TestCase):
    """/** 缺失软路径修复的拒绝条件检查 */"""

    def setUp(self):
        """/** @return 构建记录加载与保存的最小原生接口环境 */"""
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "remap_missing_soft_object_paths")
        method.decorator_list = []
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.calls = []
        self.refs = ["/Game/Owner"]
        self.saved_ok = True
        record = types.SimpleNamespace(asset_name="Target", asset_class_path="/Script/Engine.Texture2D")
        owner = types.SimpleNamespace(asset_name="Owner", asset_class_path="/Script/Engine.Texture2D")
        self.registry = types.SimpleNamespace(
            get_assets_by_package_name=lambda path: [record] if path == "/Game/Target" else [owner],
            get_dependencies=lambda path, options: [],
            scan_paths_synchronous=lambda paths, **options: self.calls.append("scan"),
        )
        self.package = types.SimpleNamespace(get_path_name=lambda: "/Game/Owner")
        self.asset = types.SimpleNamespace(get_outermost=lambda: self.package, get_class=lambda: types.SimpleNamespace(get_class_path_name=lambda: "/Script/Engine.Texture2D"))
        def rename(packages, replacements):
            self.calls.append("rename")
            self.refs = []
        self.runtime = {
            "json": json,
            "os": os,
            "_move_path": lambda path: path,
            "_move_dirty_packages": lambda: [],
            "_move_registry": lambda: self.registry,
            "_move_filename": lambda path, extension: str(Path(self.directory.name) / (path.rsplit("/", 1)[-1] + extension)),
            "_move_primary_assets": lambda records: records,
            "_move_class_path": lambda path: path,
            "_move_referencers": lambda registry, path: self.refs,
            "_require_move_checkout": lambda paths, targets: self.calls.append("checkout"),
            "_move_blocking_blueprint_errors": lambda before, after, paths: [],
            "unreal": types.SimpleNamespace(
                LevelEditorSubsystem=object,
                get_editor_subsystem=lambda kind: types.SimpleNamespace(is_in_play_in_editor=lambda: False),
                SoftObjectPath=lambda path: ("soft", path),
                AssetRegistryDependencyOptions=lambda **options: options,
                ObjectIterator=lambda: [],
                Blueprint=type("Blueprint", (), {}),
                BlueprintStatus=types.SimpleNamespace(BS_ERROR="error"),
                load_package=lambda path: self.calls.append("load") or self.package,
                load_object=lambda outer, path, **options: self.asset,
                AssetToolsHelpers=types.SimpleNamespace(get_asset_tools=lambda: types.SimpleNamespace(rename_referencing_soft_object_paths=rename)),
                EditorLoadingAndSavingUtils=types.SimpleNamespace(save_packages=lambda packages, dirty: self.calls.append("save") or self.saved_ok),
                log=lambda message: self.calls.append("log"),
            ),
        }
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), self.runtime)
        self.repair = self.runtime[method.name]
        self.mapping = [{"source": "/Game/Missing.Missing", "destination": "/Game/Target.Target"}]
        (Path(self.directory.name) / "Target.uasset").touch()

    def test_preview_never_loads_or_saves(self):
        """/** @return 预检保持只读 */"""
        self.assertTrue(json.loads(self.repair(["/Game/Owner"], json.dumps(self.mapping)))["success"])
        self.assertEqual(self.calls, [])

    def test_existing_source_and_duplicate_mapping_are_rejected(self):
        """/** @return 不覆盖存在的资源 不接受重复软路径映射 */"""
        with self.assertRaises(RuntimeError):
            self.repair(["/Game/Owner"], json.dumps(self.mapping * 2))
        (Path(self.directory.name) / "Missing.uasset").touch()
        with self.assertRaises(RuntimeError):
            self.repair(["/Game/Owner"], json.dumps(self.mapping), False)
        self.assertEqual(self.calls, [])

    def test_invalid_target_and_unrelated_referencer_are_rejected(self):
        """/** @return 不猜测目标对象 不保存无关引用者 */"""
        bad = [{"source": "/Game/Missing.Missing", "destination": "/Game/Target.Wrong"}]
        with self.assertRaises(RuntimeError):
            self.repair(["/Game/Owner"], json.dumps(bad), False)
        with self.assertRaises(RuntimeError):
            self.repair(["/Game/Unrelated"], json.dumps(self.mapping), False)
        self.assertEqual(self.calls, [])

    def test_missing_hard_dependency_blocks_before_loading(self):
        """/** @return 缺失硬依赖不能在加载后被静默保存为丢失配置 */"""
        self.registry.get_dependencies = lambda path, options: ["/Game/HardMissing"]
        with self.assertRaises(RuntimeError):
            self.repair(["/Game/Owner"], json.dumps(self.mapping), False)
        self.assertEqual(self.calls, [])

    def test_failed_save_cannot_pass_acceptance(self):
        """/** @return 原生保存失败时不宣称成功 */"""
        self.saved_ok = False
        report = json.loads(self.repair(["/Game/Owner"], json.dumps(self.mapping), False))
        self.assertFalse(report["success"])
        self.assertEqual(report["saved"], [])
        self.assertEqual(self.calls, ["checkout", "load", "rename", "save"])

    def test_native_repair_requires_saved_packages_and_zero_old_references(self):
        """/** @return 原生修复并保存后核验旧引用清零 */"""
        report = json.loads(self.repair(["/Game/Owner"], json.dumps(self.mapping), False))
        self.assertTrue(report["success"])
        self.assertEqual(report["saved"], ["/Game/Owner"])
        self.assertEqual(report["remaining_selected"], {"/Game/Missing": []})

class AssetIsolationGuardTests(unittest.TestCase):
    """/** 资产隔离必须以物理删除和永久备份为验收条件 */"""

    def setUp(self):
        """/** @return 创建自动清理的隔离样例和原生调用记录 */"""
        import hashlib
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.content = root / "Content"
        self.backup = root / "Backup"
        self.content.mkdir()
        self.backup.mkdir()
        self.source = self.content / "Asset.uasset"
        self.source.write_bytes(b"verified-original")
        (self.backup / "Asset.uasset").write_bytes(self.source.read_bytes())
        self.calls = []
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "delete_unreferenced_asset_packages")
        method.decorator_list = []
        self.runtime = {
            "json": json,
            "os": os,
            "hashlib": hashlib,
            "_move_path": lambda path: path,
            "_move_dirty_packages": lambda: [],
            "_move_registry": lambda: object(),
            "_move_referencers": lambda registry, path: [],
            "_move_filename": lambda path: str(self.source),
            "_require_move_checkout": lambda paths, destinations: self.calls.append("checkout"),
            "unreal": types.SimpleNamespace(
                LevelEditorSubsystem=object,
                get_editor_subsystem=lambda kind: types.SimpleNamespace(is_in_play_in_editor=lambda: False),
                Paths=types.SimpleNamespace(project_content_dir=lambda: str(self.content)),
                load_object=lambda *args, **kwargs: self.calls.append("load") or object(),
                BBBAssetRepairEditorLibrary=types.SimpleNamespace(delete_asset_packages=lambda objects: self.calls.append("delete") or True),
                log_error=lambda message: self.calls.append("alarm"),
            ),
        }
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), self.runtime)
        self.cleanup = self.runtime[method.name]

    def tearDown(self):
        """/** @return 删除测试临时目录 */"""
        self.directory.cleanup()

    def test_dry_run_does_not_load_checkout_or_delete(self):
        """/** @return 永久备份核验不执行资产修改 */"""
        report = json.loads(self.cleanup(["/Game/Asset"], str(self.backup)))
        self.assertTrue(report["dry_run"])
        self.assertEqual(self.calls, [])

    def test_backup_hash_mismatch_rejects_deletion(self):
        """/** @return 漂移备份不能作为删除凭据 */"""
        (self.backup / "Asset.uasset").write_bytes(b"different")
        with self.assertRaises(RuntimeError):
            self.cleanup(["/Game/Asset"], str(self.backup), False)
        self.assertEqual(self.calls, [])

    def test_outside_reference_rejects_deletion(self):
        """/** @return 仍有有效消费者时拒绝隔离 */"""
        self.runtime["_move_referencers"] = lambda registry, path: ["/Game/ActiveWorld"]
        with self.assertRaises(RuntimeError):
            self.cleanup(["/Game/Asset"], str(self.backup), False)
        self.assertEqual(self.calls, [])

    def test_native_true_with_residual_file_is_failure(self):
        """/** @return 原生返回成功不能掩盖磁盘残留 */"""
        report = json.loads(self.cleanup(["/Game/Asset"], str(self.backup), False))
        self.assertFalse(report["success"])
        self.assertFalse(report["files"][0]["physical_file_absent"])
        self.assertIn("alarm", self.calls)


if __name__ == "__main__":
    unittest.main()
