import ast
from contextlib import contextmanager
import json
from pathlib import Path
from time import perf_counter
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class AssetMovePersistenceTests(unittest.TestCase):
    """/** 原生资产迁移必须在验证之前保存实际包而不是加载旧资产 */"""

    def setUp(self):
        """/** @return 隔离加载原生保存边界并记录调用次序 */"""
        source = ROOT / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        self.runtime = {"json": json, "contextmanager": contextmanager, "perf_counter": perf_counter}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), self.runtime)
        self.calls = []
        self.old = self.package("/Game/Old/A")
        self.new = self.package("/Game/New/A")
        self.ref = self.package("/Game/Ref")
        self.report = {"referencer_packages": ["/Game/Ref"], "assets": [{"source": "/Game/Old/A", "destination": "/Game/New/A"}]}
        self.asset = types.SimpleNamespace(get_outermost=lambda: self.new)
        registry = types.SimpleNamespace(scan_paths_synchronous=lambda paths, **options: self.calls.append(("scan", paths, options)))
        self.runtime.update({
            "_move_registry": lambda: registry,
            "_move_filename": lambda path: path + ".uasset",
            "_move_file_sha256": lambda path: "source-sha",
            "os": __import__("os"),
            "_move_dirty_packages": lambda scope: [],
            "unreal": types.SimpleNamespace(ObjectIterator=lambda: iter([]), EditorLoadingAndSavingUtils=types.SimpleNamespace(save_packages=self.save)),
        })

    def package(self, path):
        """/** @param path 精确包路径 @return 独立原包或目标包对象 */"""
        return types.SimpleNamespace(get_path_name=lambda: path)

    def save(self, packages, only_dirty):
        """/** @param packages 实际包对象 @param only_dirty 脏包筛选 @return 保存成功并记录调用 */"""
        self.calls.append(("save", [package.get_path_name() for package in packages], only_dirty))
        return True

    def test_saves_real_destination_referencer_and_old_package_before_scan(self):
        """/** @return 目标及引用者先于原包保存 且重复包只保存一次 */"""
        result = self.runtime["_persist_asset_moves"](self.report, [self.old], [self.asset], [self.ref, self.new])
        self.assertTrue(result["success"])
        self.assertEqual(self.calls[:3], [("save", [p], False) for p in ["/Game/New/A", "/Game/Ref", "/Game/Old/A"]])
        self.assertEqual(self.calls[3][0], "scan")
        self.assertEqual(result["saved_packages"], ["/Game/New/A", "/Game/Ref", "/Game/Old/A"])

    def test_failed_native_save_is_not_reported_as_saved_or_retried(self):
        """/** @return 原生保存失败不会伪报已保存或重新执行 */"""
        def fail(packages, only_dirty):
            """/** @param packages 包对象 @param only_dirty 脏包筛选 @return 原生保存失败 */"""
            self.save(packages, only_dirty)
            return False
        self.runtime["unreal"].EditorLoadingAndSavingUtils.save_packages = fail
        result = self.runtime["_persist_asset_moves"](self.report, [self.old], [self.asset], [self.ref])
        self.assertFalse(result["success"])
        self.assertEqual(result["saved_packages"], [])
        self.assertEqual(sum(call[0] == "save" for call in self.calls), 3)

    def test_native_save_success_does_not_hide_remaining_dirty_packages(self):
        """/** @return 原生保存返回成功仍须检查实际未保存包 */"""
        self.runtime["_move_dirty_packages"] = lambda scope: ["/Game/Old/A"]
        result = self.runtime["_persist_asset_moves"](self.report, [self.old], [self.asset], [self.ref])
        self.assertFalse(result["success"])
        self.assertEqual(result["unsaved_packages"], ["/Game/Old/A"])

    def test_scope_escape_is_rejected_without_save(self):
        """/** @return 不保存原生移动意外带入的其它会话包 */"""
        with self.assertRaisesRegex(RuntimeError, "范围外"):
            self.runtime["_persist_asset_moves"](self.report, [self.old], [self.asset], [self.package("/Game/OtherSession")])
        self.assertEqual(self.calls, [])

    def test_execute_loads_referencer_then_renames_saves_and_verifies_once(self):
        """/** @return 正式执行先加载引用者 再改名 保存 刷新及验证 不能提前验证 */"""
        state = {"renamed": False}
        asset = types.SimpleNamespace(
            get_outermost=lambda: self.new if state["renamed"] else self.old,
            get_path_name=lambda: "/Game/New/A.A" if state["renamed"] else "/Game/Old/A.A",
            get_class=lambda: types.SimpleNamespace(get_class_path_name=lambda: types.SimpleNamespace(package_name="/Script/Engine", asset_name="StaticMesh")),
        )
        def rename(items):
            """/** @param items 唯一原生改名请求 @return 改名成功 */"""
            self.calls.append(("rename", len(items)))
            state["renamed"] = True
            return True
        def verify(moves):
            """/** @param moves 已执行映射 @return 确认实际保存后再核验 */"""
            self.assertEqual([call[0] for call in self.calls], ["load_ref", "rename", "save", "save", "save", "scan"])
            self.calls.append(("verify", len(json.loads(moves))))
            return json.dumps({"success": True})
        report = {
            "referencer_packages": ["/Game/Ref"],
            "assets": [{"source": "/Game/Old/A", "destination": "/Game/New/A", "source_object": "/Game/Old/A.A", "destination_object": "/Game/New/A.A", "class_path": "/Script/Engine.StaticMesh"}],
        }
        native = self.runtime["unreal"]
        native.log = lambda value: None
        native.log_error = lambda value: None
        native.EditorAssetLibrary = types.SimpleNamespace(load_asset=lambda path: asset)
        native.AssetRenameData = lambda **values: values
        native.AssetToolsHelpers = types.SimpleNamespace(get_asset_tools=lambda: types.SimpleNamespace(rename_assets=rename))
        native.load_package = lambda path: self.calls.append(("load_ref", path)) or self.ref
        self.runtime["require_asset_write"] = lambda *args: None
        self.runtime["_verify_asset_moves_json"] = verify
        result = json.loads(self.runtime["_execute_asset_moves"](report))
        self.assertTrue(result["success"])
        self.assertEqual(self.calls[-1], ("verify", 1))

    def _empty_source_fixture(self):
        """/** @return 目标已改名 原包完全空且磁盘仍是原资产的状态环境 */"""
        state = {"files": {"/Game/Old/A.uasset", "/Game/New/A.uasset"}, "dirty": True, "references": [], "class_name": "StaticMesh"}
        self.report["assets"][0].update(source_object="/Game/Old/A.A", class_path="/Script/Engine.StaticMesh", source_sha256="source-sha")
        self.report["object_results"] = [{"source": "/Game/Old/A", "renamed": True}]
        def cleanup(paths):
            """/** @param paths 精确空原包路径 @return 引擎清除旧文件并保留目标 */"""
            self.calls.append(("cleanup", list(paths)))
            state["dirty"] = False
            for path in paths:
                state["files"].remove(path + ".uasset")
            return True
        registry = self.runtime["_move_registry"]()
        registry.get_assets_by_package_name = lambda path: []
        self.runtime["_move_referencers"] = lambda registry, path: state["references"]
        self.runtime["_move_dirty_packages"] = lambda scope: ["/Game/Old/A"] if state["dirty"] and "/Game/Old/A" in scope else []
        native = self.runtime["unreal"]
        native.BBBAssetRepairEditorLibrary = types.SimpleNamespace(cleanup_empty_asset_packages=cleanup)
        return state

    def test_empty_original_is_reloaded_and_deleted_after_saved_target_and_referencer(self):
        """/** @return 真实原包残留语义先存目标再只清旧文件 不保存空包或改动新目标 */"""
        state = self._empty_source_fixture()
        with patch("os.path.isfile", side_effect=lambda path: path in state["files"]):
            result = self.runtime["_persist_asset_moves"](self.report, [self.old], [self.asset], [self.ref])
        self.assertTrue(result["success"])
        self.assertEqual(self.calls[0], ("save", ["/Game/Ref"], False))
        self.assertEqual(result["already_saved_packages"], ["/Game/New/A"])
        self.assertEqual(self.calls[1][0], "scan")
        self.assertEqual(self.calls[2], ("cleanup", ["/Game/Old/A"]))
        self.assertEqual(result["empty_source_cleanup"]["deleted"], ["/Game/Old/A"])
        self.assertEqual(state["files"], {"/Game/New/A.uasset"})

    def test_refreshes_saved_referencer_dependencies_before_no_external_reference_guard(self):
        """/** @return 保存后旧注册表缓存必须先按已存包刷新 真实组外引用保护仍严格 */"""
        state = self._empty_source_fixture()
        state["references"] = ["/Game/Ref"]
        registry = self.runtime["_move_registry"]()
        previous_scan = registry.scan_paths_synchronous
        def refresh(paths, **options):
            """/** @param paths 已保存目录 @param options 原生扫描选项 @return 从已存目标引用刷新旧缓存 */"""
            self.assertEqual(self.calls[0][0], "save")
            state["references"] = []
            previous_scan(paths, **options)
        registry.scan_paths_synchronous = refresh
        with patch("os.path.isfile", side_effect=lambda path: path in state["files"]):
            result = self.runtime["_persist_asset_moves"](self.report, [self.old], [self.asset], [self.ref])
        self.assertTrue(result["success"])
        self.assertEqual(result["empty_source_cleanup"]["deleted"], ["/Game/Old/A"])

    def test_empty_source_with_changed_hash_or_external_reference_is_not_discarded(self):
        """/** @return 摘要或组外引用不符时不重载 不删除原包 */"""
        for reason in ("hash", "reference"):
            with self.subTest(reason=reason):
                self.setUp()
                state = self._empty_source_fixture()
                if reason == "hash":
                    self.report["assets"][0]["source_sha256"] = "changed-before-rename"
                if reason == "reference":
                    state["references"] = ["/Game/OtherSession"]
                with patch("os.path.isfile", side_effect=lambda path: path in state["files"]):
                    with self.assertRaises(RuntimeError):
                        self.runtime["_persist_asset_moves"](self.report, [self.old], [self.asset], [self.ref])
                self.assertFalse(any(call[0] in {"cleanup"} for call in self.calls))


    def test_target_save_failure_never_discards_empty_source(self):
        """/** @return 目标未完成保存时不丢弃原包状态或删除原文件 */"""
        state = self._empty_source_fixture()
        self.runtime["unreal"].EditorLoadingAndSavingUtils.save_packages = lambda *args: False
        with patch("os.path.isfile", side_effect=lambda path: path in state["files"]):
            result = self.runtime["_persist_asset_moves"](self.report, [self.old], [self.asset], [self.ref])
        self.assertFalse(result["success"])
        self.assertFalse(any(call[0] in {"cleanup"} for call in self.calls))




    def test_empty_cleanup_releases_package_wrappers_and_passes_only_paths(self):
        """/** @return 原包包装引用释放后仅向原生清理传递路径 */"""
        state = self._empty_source_fixture()
        sources = [self.old]
        referencers = [self.ref]
        native = self.runtime["unreal"].BBBAssetRepairEditorLibrary
        original = native.cleanup_empty_asset_packages
        def cleanup(paths):
            """/** @param paths 精确路径 @return 核验包装引用已经释放 */"""
            self.assertEqual(sources, [])
            self.assertEqual(referencers, [])
            self.assertEqual(paths, ["/Game/Old/A"])
            return original(paths)
        native.cleanup_empty_asset_packages = cleanup
        with patch("os.path.isfile", side_effect=lambda path: path in state["files"]):
            result = self.runtime["_persist_asset_moves"](self.report, sources, [self.asset], referencers)
        self.assertTrue(result["success"])

    def test_empty_cleanup_checks_whole_group_before_one_native_call(self):
        """/** @return 整组摘要和引用通过后仅执行一次原生空包清理 */"""
        state = self._empty_source_fixture()
        state["files"].update({"/Game/Old/B.uasset", "/Game/New/B.uasset"})
        self.report["assets"].append({"source": "/Game/Old/B", "destination": "/Game/New/B", "source_sha256": "source-sha"})
        with patch("os.path.isfile", side_effect=lambda path: path in state["files"]):
            result = self.runtime["_cleanup_empty_move_sources"](self.report, [self.old, self.package("/Game/Old/B")])
        self.assertEqual([call for call in self.calls if call[0] == "cleanup"], [("cleanup", ["/Game/Old/A", "/Game/Old/B"])])
        self.assertEqual(result["deleted"], ["/Game/Old/A", "/Game/Old/B"])


if __name__ == "__main__":
    unittest.main()
