import ast
import json
from pathlib import Path
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AssetMoveTests(unittest.TestCase):
    """/** 资产迁移的路径与类型识别回归检查 */"""

    def setUp(self):
        """/** @return 隔离加载纯辅助函数 不注册编辑器工具 */"""
        source = ROOT / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        module = ast.Module(body=nodes, type_ignores=[])
        self.runtime = {"json": json, "os": __import__("os"), "re": __import__("re")}
        exec(compile(module, str(source), "exec"), self.runtime)

    def test_ownerless_actor_delete_preserves_exact_backup_and_rejects_backup_collision(self):
        """/** @return 历史 Actor 清理只删除无主包 且不覆盖不匹配的恢复原件 */"""
        source = ROOT / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "delete_ownerless_external_actor_packages")
        method.decorator_list = []
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), self.runtime)
        with tempfile.TemporaryDirectory() as directory:
            content = Path(directory) / "Content"
            file = content / "__ExternalActors__/World/A/BC/Actor.uasset"
            file.parent.mkdir(parents=True)
            file.write_bytes(b"exact original actor")
            backup_root = Path(directory) / "Recovery"
            backup = backup_root / file.relative_to(content)
            package = "/Game/__ExternalActors__/World/A/BC/Actor"
            calls = []
            state = types.SimpleNamespace(is_valid=True, is_unknown=False, is_checked_out_other=False, is_conflicted=False, is_deleted=False, is_source_controlled=True, is_added=True, is_current=False)
            def native_delete(filenames, silent):
                calls.extend(filenames)
                for filename in filenames:
                    Path(filename).unlink()
                return True
            control = types.SimpleNamespace(is_enabled=lambda: True, is_available=lambda: True, current_provider=lambda: "Perforce", query_file_states=lambda paths, **options: [state], mark_files_for_delete=native_delete)
            registry = types.SimpleNamespace(get_assets_by_package_name=lambda path: [])
            self.runtime.update({"_move_registry": lambda: registry, "_move_dirty_packages": lambda: [], "_move_referencers": lambda registry, path: [], "unreal": types.SimpleNamespace(Paths=types.SimpleNamespace(project_content_dir=lambda: str(content)), SourceControl=control, LevelEditorSubsystem=object, get_editor_subsystem=lambda kind: types.SimpleNamespace(is_in_play_in_editor=lambda: False), log=lambda message: None)})
            preview = json.loads(self.runtime[method.name]([package], str(backup_root), True))
            self.assertTrue(preview["success"])
            self.assertFalse(backup.exists())
            self.assertEqual(calls, [])
            backup.parent.mkdir(parents=True)
            backup.write_bytes(b"different protected backup")
            with self.assertRaisesRegex(RuntimeError, "原件备份不匹配"):
                self.runtime[method.name]([package], str(backup_root), False)
            self.assertTrue(file.exists())
            self.assertEqual(calls, [])
            backup.unlink()
            result = json.loads(self.runtime[method.name]([package], str(backup_root), False))
            self.assertTrue(result["success"])
            self.assertFalse(file.exists())
            self.assertEqual(backup.read_bytes(), b"exact original actor")
            self.assertEqual([Path(value).resolve() for value in calls], [file.resolve()])

    def test_external_object_path_has_separate_strict_root(self):
        """/** @return 外部 Object 清理入口不能接收 Actor 根或对象后缀 */"""
        with tempfile.TemporaryDirectory() as directory:
            self.runtime["unreal"] = types.SimpleNamespace(Paths=types.SimpleNamespace(project_content_dir=lambda: directory))
            file = Path(directory) / "__ExternalObjects__/World/A/BC/Folder.uasset"
            file.parent.mkdir(parents=True)
            file.touch()
            path = "/Game/__ExternalObjects__/World/A/BC/Folder"
            self.assertEqual(self.runtime["_external_object_package_path"](path), path)
            for invalid in [path.replace("__ExternalObjects__", "__ExternalActors__"), path + ".Folder", "/Game/__ExternalObjects__/World/../Folder"]:
                with self.assertRaises(RuntimeError):
                    self.runtime["_external_object_package_path"](invalid)

    def test_external_actor_save_guard_requires_actual_owner_world(self):
        """/** @return 缺失关卡和旧重定向关卡不能通过外部 Actor 保存前置检查 */"""
        self.runtime["_move_class_path"] = lambda value: value
        with tempfile.TemporaryDirectory() as directory:
            self.runtime["unreal"] = types.SimpleNamespace(Paths=types.SimpleNamespace(project_content_dir=lambda: directory))
            record = types.SimpleNamespace(asset_class_path="/Script/Engine.World")
            registry = types.SimpleNamespace(get_assets_by_package_name=lambda path: [record])
            actor = "/Game/__ExternalActors__/_ThirdParty/Environment/Pack/Maps/World/A/BC/Actor"
            with self.assertRaises(RuntimeError):
                self.runtime["_require_external_actor_world_owners"](registry, [actor])
            world = Path(directory) / "_ThirdParty/Environment/Pack/Maps/World.umap"
            world.parent.mkdir(parents=True)
            world.touch()
            self.assertEqual(self.runtime["_require_external_actor_world_owners"](registry, [actor]), ["/Game/_ThirdParty/Environment/Pack/Maps/World"])
            record.asset_class_path = "/Script/CoreUObject.ObjectRedirector"
            with self.assertRaises(RuntimeError):
                self.runtime["_require_external_actor_world_owners"](registry, [actor])

    def test_external_actor_metadata_inspection_never_loads_missing_owner_objects(self):
        """/** @return 所属地图缺失时仍能读取外部包引用 且不会加载 Actor */"""
        source = ROOT / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and any(isinstance(item, ast.FunctionDef) and item.name == "inspect_external_actor_package_metadata" for item in node.body))
        method = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == "inspect_external_actor_package_metadata")
        method.decorator_list = []
        record = types.SimpleNamespace(asset_name="Actor", asset_class_path="/Script/Engine.Actor")
        registry = types.SimpleNamespace(get_assets_by_package_name=lambda path: [record])
        runtime = {"json": json, "_move_registry": lambda: registry, "_external_actor_package_path": lambda path: path, "_move_class_path": lambda path: path, "_move_referencers": lambda registry, path: ["/Game/Referencer"], "unreal": types.SimpleNamespace(log=lambda message: None)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), runtime)
        report = json.loads(runtime["inspect_external_actor_package_metadata"](["/Game/__ExternalActors__/World/A/B/Actor"]))
        self.assertTrue(report["read_only"])
        self.assertEqual(report["packages"][0]["referencers"], ["/Game/Referencer"])
        self.assertEqual(report["packages"][0]["records"][0]["class_path"], "/Script/Engine.Actor")

    def test_external_actor_inspection_uses_stable_guid_conversion(self):
        """/** @return Actor 身份核验使用稳定 GUID 值而非 Python 对象地址 */"""
        source = ROOT / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and any(isinstance(item, ast.FunctionDef) and item.name == "inspect_external_actor_packages" for item in node.body))
        method = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == "inspect_external_actor_packages")
        method.decorator_list = []
        actor = types.SimpleNamespace(get_destroy_on_system_finish=lambda: False, get_attach_parent_actor=lambda: None, get_path_name=lambda: "/Game/World.World:PersistentLevel.Actor", get_class=lambda: types.SimpleNamespace(get_path_name=lambda: "/Script/Engine.Actor"), get_editor_property=lambda name: types.SimpleNamespace(to_string=lambda: "01234567-89AB-CDEF-0123-456789ABCDEF"))
        record = types.SimpleNamespace(get_asset=lambda: actor)
        registry = types.SimpleNamespace(get_assets_by_package_name=lambda path: [record])
        runtime = {"json": json, "_move_dirty_packages": lambda: [], "_move_registry": lambda: registry, "_external_actor_package_path": lambda path: path, "_move_referencers": lambda registry, path: [], "unreal": types.SimpleNamespace(Actor=types.SimpleNamespace, NiagaraActor=types.SimpleNamespace, LevelEditorSubsystem=object, get_editor_subsystem=lambda kind: types.SimpleNamespace(is_in_play_in_editor=lambda: False), log=lambda message: None)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), runtime)
        report = json.loads(runtime["inspect_external_actor_packages"](["/Game/__ExternalActors__/World/A/B/Actor"]))
        self.assertEqual(report["packages"][0]["actors"][0]["actor_guid"], "01234567-89AB-CDEF-0123-456789ABCDEF")
        self.assertFalse(report["packages"][0]["actors"][0]["destroy_on_system_finish"])
        self.assertTrue(report["read_only"])
        self.assertTrue(report["success"])

    def test_native_dependency_scan_detects_missing_transitive_classes_without_loading(self):
        """/** @return 间接物理资产的原生依赖缺失时能在重存前发现 且循环不重复遍历 */"""
        dependencies = {
            "/Game/Mesh": ["/Game/Physics", "/Script/Engine"],
            "/Game/Physics": ["/Game/Material"],
            "/Game/Material": ["/Script/LyraGame", "/Game/Mesh"],
        }
        visited = []
        registry = types.SimpleNamespace(get_dependencies=lambda package, options: visited.append(package) or dependencies.get(package, []))
        self.runtime["unreal"] = types.SimpleNamespace(AssetRegistryDependencyOptions=lambda **options: options, find_object=lambda outer, package: object() if package == "/Script/Engine" else None)
        report = self.runtime["_move_native_dependency_report"](registry, ["/Game/Mesh"])
        self.assertEqual(report["missing_script_packages"], ["/Script/LyraGame"])
        self.assertEqual(report["visited_package_count"], 3)
        self.assertEqual(len(visited), 3)
        self.runtime["unreal"].find_object = lambda outer, package: object()
        self.assertEqual(self.runtime["_move_native_dependency_report"](registry, ["/Game/Mesh"])["missing_script_packages"], [])

    def test_external_reference_move_preserves_other_blockers(self):
        """/** @return 允许外部 Actor 时仍拒绝外部 Object 关卡与目标冲突 */"""
        with tempfile.TemporaryDirectory() as directory:
            self.runtime["unreal"] = types.SimpleNamespace(Paths=types.SimpleNamespace(project_content_dir=lambda: directory))
            actor = "/Game/__ExternalActors__/World/A1/B2/Actor"
            disk = Path(directory) / "__ExternalActors__/World/A1/B2/Actor.uasset"
            disk.parent.mkdir(parents=True)
            disk.touch()
            reason = "存在项目外或关卡外部数据引用者 需专用迁移"
            retained = [
                {"package": "/Game/__ExternalObjects__/World/A1/B2/Object", "reason": reason},
                {"package": "/Game/Maps/World", "reason": "重定向器和关卡数据不属于通用资产移动范围"},
                {"package": "/Game/New/Asset", "reason": "目标包或同名目录已存在"},
            ]
            report = {"asset_count": 1, "blockers": [{"package": actor, "reason": reason}] + retained}
            result = self.runtime["_permit_external_actor_move_references"](report)
            self.assertEqual(result["external_actor_referencers"], [actor])
            self.assertEqual(result["blockers"], retained)
            self.assertFalse(result["can_execute_after_checkout"])

    def test_external_reference_move_rejects_missing_actor_file(self):
        """/** @return 注册表存在的外部引用不能代替磁盘包存在证明 */"""
        with tempfile.TemporaryDirectory() as directory:
            self.runtime["unreal"] = types.SimpleNamespace(Paths=types.SimpleNamespace(project_content_dir=lambda: directory))
            report = {
                "asset_count": 1,
                "blockers": [{"package": "/Game/__ExternalActors__/World/A1/B2/Missing", "reason": "存在项目外或关卡外部数据引用者 需专用迁移"}],
            }
            with self.assertRaises(RuntimeError):
                self.runtime["_permit_external_actor_move_references"](report)

    def test_external_reference_move_rejects_oversized_expansion(self):
        """/** @return 目录展开后超过单批容量也必须拒绝执行 */"""
        with self.assertRaises(RuntimeError):
            self.runtime["_permit_external_actor_move_references"]({"asset_count": 65, "blockers": []})

    def test_redirector_fixup_ignores_unrelated_existing_blueprint_errors(self):
        existing = ["/Game/Blueprints/BP_PreExisting.BP_PreExisting"]
        current = existing + ["/Game/Maps/MapA.MapA:PersistentLevel.BP_NewError"]
        self.assertEqual(
            self.runtime["_move_blocking_blueprint_errors"](existing, current, ["/Game/Maps/MapA"]),
            ["/Game/Maps/MapA.MapA:PersistentLevel.BP_NewError"],
        )

    def test_redirector_fixup_blocks_existing_error_in_selected_package(self):
        existing = ["/Game/Maps/MapA.MapA:PersistentLevel.BP_PreExisting"]
        self.assertEqual(
            self.runtime["_move_blocking_blueprint_errors"](existing, existing, ["/Game/Maps/MapA"]),
            existing,
        )

    def test_redirector_fixup_refreshes_referencers_before_reporting_success(self):
        source = (ROOT / "Scripts/BBBAssetMaintenanceToolset.py").read_text(encoding="utf-8-sig")
        method = source.split("def fixup_redirector_references_batch", 1)[1].split("def delete_asset_redirectors", 1)[0]
        self.assertIn("registry.scan_paths_synchronous(referencer_folders, force_rescan=True)", method)
        self.assertIn('report["remaining_selected"]', method)
        self.assertIn('not any(report["remaining_selected"].values())', method)

    def test_primary_asset_filter(self):
        """/** @return 蓝图生成对象不参与独立包移动 */"""
        main = types.SimpleNamespace(is_u_asset=lambda: True)
        generated = types.SimpleNamespace(is_u_asset=lambda: False)
        self.assertEqual(self.runtime["_move_primary_assets"]([main, generated]), [main])

    def test_class_path_is_stable(self):
        """/** @return 类型名称不使用结构体地址文本 */"""
        for name in ("ObjectRedirector", "World", "AnimSequence"):
            path = types.SimpleNamespace(package_name="/Script/Engine", asset_name=name)
            self.assertEqual(self.runtime["_move_class_path"](path), "/Script/Engine." + name)

    def test_reject_unsafe_paths(self):
        """/** @return 文件系统路径与受保护关卡数据被拒绝 */"""
        for path in (None, "/Game", "/Engine/Test", "E:/Game/Test", "/Game/A.A", "/Game/A/../B", "/Game/__ExternalActors__/A", "/Game/__externalobjects__/A"):
            with self.subTest(path=path):
                with self.assertRaises(RuntimeError):
                    self.runtime["_move_path"](path)

    def test_mapping_validation(self):
        """/** @return 大小写改名与空映射不能通过 */"""
        for request in ([], [{"source": "/Game/Old", "destination": "/Game/old"}], [{"source": "/Game/A", "destination": "/Game/A"}]):
            with self.assertRaises(RuntimeError):
                self.runtime["_move_requests"](json.dumps(request))

    def test_disk_path_stays_in_content(self):
        """/** @return 精确包路径映射到正确的 Content 文件 */"""
        with tempfile.TemporaryDirectory() as directory:
            self.runtime["unreal"] = types.SimpleNamespace(Paths=types.SimpleNamespace(project_content_dir=lambda: directory))
            result = self.runtime["_move_filename"]("/Game/Folder/Asset")
            self.assertEqual(Path(result), (Path(directory) / "Folder/Asset.uasset").resolve())
            with self.assertRaises(RuntimeError):
                self.runtime["_move_filename"]("/Game/../../Outside")

    def test_external_actor_package_path_is_exact_and_present(self):
        """/** @return 外部 Actor 包路径只允许映射到 Content 下已存在的包 */"""
        with tempfile.TemporaryDirectory() as directory:
            self.runtime["unreal"] = types.SimpleNamespace(Paths=types.SimpleNamespace(project_content_dir=lambda: directory))
            package = Path(directory) / "__ExternalActors__/World/A1/B2/ActorPackage.uasset"
            package.parent.mkdir(parents=True)
            package.touch()
            path = "/Game/__ExternalActors__/World/A1/B2/ActorPackage"
            self.assertEqual(self.runtime["_external_actor_package_path"](path), path)
            for invalid in (
                "/Game/__ExternalObjects__/World/A1/B2/ActorPackage",
                "/Game/__ExternalActors__/World/../ActorPackage",
                "/Game/__ExternalActors__/World/A1/B2/ActorPackage.ActorPackage",
                "/Game/__ExternalActors__/World/A1/B2/MissingPackage",
            ):
                with self.subTest(path=invalid):
                    with self.assertRaises(RuntimeError):
                        self.runtime["_external_actor_package_path"](invalid)

    def test_redirector_batch_preview_does_not_load(self):
        """/** @return 分批预检只检查注册表 不加载或保存对象 */"""
        source = ROOT / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "fixup_redirector_references_batch")
        method.decorator_list = []
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), self.runtime)
        redirector = types.SimpleNamespace(asset_name="Old", asset_class_path=types.SimpleNamespace(package_name="/Script/CoreUObject", asset_name="ObjectRedirector"), get_tag_value=lambda name: "/Script/Engine.Skeleton'/Game/New.New'")
        referencer = types.SimpleNamespace(asset_name="Reference", asset_class_path=types.SimpleNamespace(package_name="/Script/Engine", asset_name="AnimSequence"), is_u_asset=lambda: True)
        registry = types.SimpleNamespace(get_assets_by_package_name=lambda path: [redirector] if path == "/Game/Old" else [referencer])
        self.runtime["_move_registry"] = lambda: registry
        self.runtime["_move_dirty_packages"] = lambda: []
        self.runtime["_move_referencers"] = lambda registry, path: ["/Game/Reference"]
        self.runtime["unreal"] = types.SimpleNamespace(LevelEditorSubsystem=object(), get_editor_subsystem=lambda subsystem: types.SimpleNamespace(is_in_play_in_editor=lambda: False), SoftObjectPath=lambda path: path)
        result = json.loads(self.runtime["fixup_redirector_references_batch"](["/Game/Old"], ["/Game/Reference"], True))
        self.assertTrue(result["success"])
        self.assertEqual(result["saved"], [])
        world = types.SimpleNamespace(asset_name="Reference", asset_class_path=types.SimpleNamespace(package_name="/Script/Engine", asset_name="World"), is_u_asset=lambda: True)
        registry.get_assets_by_package_name = lambda path: [redirector] if path == "/Game/Old" else [world]
        result = json.loads(self.runtime["fixup_redirector_references_batch"](["/Game/Old"], ["/Game/Reference"], True))
        self.assertTrue(result["success"])
        with self.assertRaises(RuntimeError):
            self.runtime["fixup_redirector_references_batch"](["/Game/Old"], ["/Game/Unrelated"], True)
        with self.assertRaises(RuntimeError):
            self.runtime["fixup_redirector_references_batch"](["/Game/Old"], ["/Game/Reference"] * 33, True)

    def test_external_actor_fixup_accepts_generated_objects_without_loading_preview(self):
        """/** @return 生成类与默认对象允许作为精确目标 预检不加载对象或保存包 */"""
        source = ROOT / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "fixup_external_actor_redirector_references")
        method.decorator_list = []
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), self.runtime)
        actor = "/Game/__ExternalActors__/World/A/B/Actor"
        target = types.SimpleNamespace(asset_name="New", asset_class_path="/Script/Engine.Blueprint", is_u_asset=lambda: True)
        redirectors = [types.SimpleNamespace(asset_name=name, asset_class_path="/Script/CoreUObject.ObjectRedirector", get_tag_value=lambda tag, name=name: "/Game/New." + name) for name in ["New_C", "Default__New_C"]]
        registry = types.SimpleNamespace(get_assets_by_package_name=lambda path: redirectors if path == "/Game/Old" else [target])
        self.runtime.update({
            "_move_registry": lambda: registry,
            "_move_class_path": lambda value: value,
            "_move_dirty_packages": lambda: [],
            "_move_referencers": lambda registry, path: [actor],
            "_external_actor_package_path": lambda path: path,
            "_require_external_actor_world_owners": lambda registry, paths: ["/Game/World"],
            "unreal": types.SimpleNamespace(LevelEditorSubsystem=object(), get_editor_subsystem=lambda subsystem: types.SimpleNamespace(is_in_play_in_editor=lambda: False), SoftObjectPath=lambda path: path),
        })
        result = json.loads(self.runtime[method.name](["/Game/Old"], [actor], True))
        self.assertTrue(result["success"])
        self.assertEqual(result["saved"], [])
        target.get_tag_value = lambda tag: "BlueprintGeneratedClass'/Game/New.Legacy_C'"
        redirectors[:] = [types.SimpleNamespace(asset_name="Old", asset_class_path="/Script/CoreUObject.ObjectRedirector", get_tag_value=lambda tag: "/Game/New.New")]
        mapped_paths = []
        self.runtime["unreal"].SoftObjectPath = lambda path: mapped_paths.append(path) or path
        result = json.loads(self.runtime[method.name](["/Game/Old"], [actor], True))
        self.assertTrue(result["success"])
        self.assertIn("/Game/New.Legacy_C", mapped_paths)
        self.assertIn("/Game/New.Default__Legacy_C", mapped_paths)
        self.assertNotIn("/Game/New.New_C", mapped_paths)
        registry.get_assets_by_package_name = lambda path: redirectors if path == "/Game/Old" else []
        with self.assertRaises(RuntimeError):
            self.runtime[method.name](["/Game/Old"], [actor], True)

    def test_external_actor_fixup_rejects_missing_exact_generated_target_before_actor_load(self):
        """/** @return 目标生成对象缺失时必须在加载或保存外部 Actor 之前拒绝执行 */"""
        source = ROOT / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "fixup_external_actor_redirector_references")
        method.decorator_list = []
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), self.runtime)
        actor = "/Game/__ExternalActors__/World/A/B/Actor"
        redirector = types.SimpleNamespace(asset_name="New_C", asset_class_path="/Script/CoreUObject.ObjectRedirector", get_tag_value=lambda tag: "/Game/New.New_C")
        target = types.SimpleNamespace(asset_name="New", asset_class_path="/Script/Engine.Blueprint", is_u_asset=lambda: True)
        registry = types.SimpleNamespace(get_assets_by_package_name=lambda path: [redirector] if path == "/Game/Old" else [target])
        loaded = []
        self.runtime.update({
            "_move_registry": lambda: registry,
            "_move_class_path": lambda value: value,
            "_move_dirty_packages": lambda: [],
            "_move_referencers": lambda registry, path: [actor],
            "_external_actor_package_path": lambda path: path,
            "_require_external_actor_world_owners": lambda registry, paths: ["/Game/World"],
            "_require_move_checkout": lambda sources, references: None,
            "unreal": types.SimpleNamespace(LevelEditorSubsystem=object(), get_editor_subsystem=lambda subsystem: types.SimpleNamespace(is_in_play_in_editor=lambda: False), SoftObjectPath=lambda path: path, load_object=lambda outer, path, **options: loaded.append(path)),
        })
        with self.assertRaisesRegex(RuntimeError, "无法加载精确重定向目标对象"):
            self.runtime[method.name](["/Game/Old"], [actor], False)
        self.assertEqual(loaded, ["/Game/New.New_C"])

    def test_nonprimary_redirector_is_verified_after_name_normalization(self):
        """/** @return 非主旧重定向器必须核对目标且不能忽略残留真实对象 */"""
        source_file = ROOT / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source_file.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "verify_asset_moves")
        method.decorator_list = []
        old_path = "/Game/Old/BadPackage"
        new_path = "/Game/New/GoodPackage"
        old_data = types.SimpleNamespace(
            asset_name="DifferentObjectName",
            asset_class_path="/Script/CoreUObject.ObjectRedirector",
            is_u_asset=lambda: False,
            get_tag_value=lambda tag: "StaticMesh'" + new_path + ".GoodPackage'",
        )
        new_data = types.SimpleNamespace(
            asset_name="GoodPackage",
            asset_class_path="/Script/Engine.StaticMesh",
            is_u_asset=lambda: True,
        )
        registry = types.SimpleNamespace(
            get_assets_by_package_name=lambda path: [old_data] if path == old_path else [new_data],
            get_assets_by_path=lambda path, **options: [],
        )

        with tempfile.TemporaryDirectory() as directory:
            for package in [old_path, new_path]:
                file = Path(directory) / (package[len("/Game/"):] + ".uasset")
                file.parent.mkdir(parents=True)
                file.touch()
            self.runtime.update({
                "unreal": types.SimpleNamespace(Paths=types.SimpleNamespace(project_content_dir=lambda: directory), log=lambda message: None),
                "_move_registry": lambda: registry,
                "_move_dirty_packages": lambda: [],
                "_move_referencers": lambda registry, path: ["/Game/Showroom"],
                "_move_class_path": lambda value: value,
            })
            exec(compile(ast.Module(body=[method], type_ignores=[]), str(source_file), "exec"), self.runtime)
            moves = json.dumps([{"source": old_path, "destination": new_path, "class_path": "/Script/Engine.StaticMesh"}])
            self.assertTrue(json.loads(self.runtime[method.name](moves))["success"])
            generated_redirector = types.SimpleNamespace(
                asset_name="GoodPackage_C",
                asset_class_path="/Script/CoreUObject.ObjectRedirector",
                is_u_asset=lambda: False,
                get_tag_value=lambda tag: "BlueprintGeneratedClass'" + new_path + ".GoodPackage_C'",
            )
            registry.get_assets_by_package_name = lambda path: [old_data, generated_redirector] if path == old_path else [new_data]
            self.assertTrue(json.loads(self.runtime[method.name](moves))["success"])
            generated_redirector.get_tag_value = lambda tag: "BlueprintGeneratedClass'/Game/Foreign.GoodPackage_C'"
            self.assertFalse(json.loads(self.runtime[method.name](moves))["success"])
            registry.get_assets_by_package_name = lambda path: [old_data] if path == old_path else [new_data]
            old_data.asset_class_path = "/Script/Engine.StaticMesh"
            self.assertFalse(json.loads(self.runtime[method.name](moves))["success"])

    def test_move_and_verify_use_canonical_classes(self):
        """/** @return 原生对象与注册表类型检查均使用稳定类型辅助函数 */"""
        source = (ROOT / "Scripts/BBBAssetMaintenanceToolset.py").read_text(encoding="utf-8-sig")
        self.assertNotIn("str(asset_data.asset_class_path)", source)
        self.assertNotIn("str(target_data[0].asset_class_path)", source)
        self.assertNotIn("str(asset.get_class().get_class_path_name())", source)
        tree = ast.parse(source)
        names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
