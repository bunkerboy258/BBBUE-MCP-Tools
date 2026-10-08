import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class AssetWritePolicyTests(unittest.TestCase):
    """/** 独占签出与批量写入前置规则回归 */"""

    def setUp(self):
        """/** @return 隔离源控与编辑器 不加载或写入资产 */"""
        self.queries = []
        self.pie = False
        self.overrides = {}
        self.states = {}

        def query(paths, **options):
            """/** @param paths 包路径 @param options 查询选项 @return 最新状态 */"""
            self.queries.append((paths, options))
            return [self.states.get(path, types.SimpleNamespace(**self.state())) for path in paths]

        control = types.SimpleNamespace(is_enabled=lambda: True, is_available=lambda: True,
            current_provider=lambda: "Perforce", query_file_states=query)
        self.unreal = types.SimpleNamespace(SourceControl=control, LevelEditorSubsystem=object,
            Paths=types.SimpleNamespace(project_content_dir=lambda: "E:/BBB_Evac/Content"),
            log_warning=lambda message: None,
            SystemLibrary=types.SimpleNamespace(get_command_line=lambda: ""),
            Actor=type("Actor", (), {}), ActorComponent=type("ActorComponent", (), {}),
            get_editor_subsystem=lambda kind: types.SimpleNamespace(is_in_play_in_editor=lambda: self.pie))
        with patch.dict(sys.modules, {"unreal": self.unreal}):
            spec = importlib.util.spec_from_file_location("write_policy_test", ROOT / "Scripts/BBBAssetWritePolicy.py")
            self.policy = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.policy)

    def state(self, **changes):
        """
        /**
         * @param changes	状态覆盖
         * @return 已签出且最新的默认状态
         */
        """
        return dict(is_valid=True, is_unknown=False, is_checked_out_other=False, is_conflicted=False,
            is_deleted=False, is_source_controlled=True, is_checked_out=True, is_added=False,
            can_edit=True, can_add=False, is_current=True, **changes)

    def test_deduplicated_batch_refreshes_states_on_each_request(self):
        """/** @return 多对象同包去重 下一请求重新查询且不使用缓存 */"""
        self.policy.require_asset_write(["/Game/A.A", "/Game/A", "/Game/B.B"])
        self.policy.require_asset_write(["/Game/A"])
        self.assertEqual([query[0] for query in self.queries], [["/Game/A", "/Game/B"], ["/Game/A"]])
        self.assertTrue(all(query[1]["use_source_control_state_cache"] is False for query in self.queries))

    def test_commandlet_has_no_level_editor_subsystem(self):
        """/** @return 命令行编辑器保留源控检查且不访问不存在的视口子系统 */"""
        self.unreal.SystemLibrary.get_command_line = lambda: "Project.uproject -run=pythonscript -unattended"
        self.unreal.get_editor_subsystem = lambda kind: self.fail("命令行不能读取 LevelEditorSubsystem")
        self.policy.require_asset_write(["/Game/A"])
        values = self.state()
        values["is_checked_out_other"] = True
        self.states["/Game/A"] = types.SimpleNamespace(**values)
        with self.assertRaisesRegex(RuntimeError, "冲突"):
            self.policy.require_asset_write(["/Game/A"])

    def test_unchecked_out_conflicted_stale_or_foreign_states_reject(self):
        """/** @return 写入前拒绝无签出 冲突 非最新与他人占用 */"""
        for key in ["is_valid", "can_edit", "is_checked_out", "is_current"]:
            values = self.state()
            values[key] = False
            self.states["/Game/A"] = types.SimpleNamespace(**values)
            with self.assertRaises(RuntimeError):
                self.policy.require_asset_write(["/Game/A"])
        for key in ["is_unknown", "is_checked_out_other", "is_conflicted", "is_deleted"]:
            values = self.state()
            values[key] = True
            self.states["/Game/A"] = types.SimpleNamespace(**values)
            with self.assertRaises(RuntimeError):
                self.policy.require_asset_write(["/Game/A"])

    def test_added_asset_and_new_destination_have_distinct_rules(self):
        """/** @return 待添加资产可写 新目标要求可添加且无仓库冲突 */"""
        added = self.state()
        added.update(is_added=True, is_current=False, is_checked_out=False)
        self.states["/Game/A"] = types.SimpleNamespace(**added)
        target = self.state()
        target.update(is_source_controlled=False, is_checked_out=False, can_add=True, can_edit=False)
        self.states["/Game/New"] = types.SimpleNamespace(**target)
        self.policy.require_asset_write(["/Game/A"], ["/Game/New"])
        target["is_added"] = True
        self.states["/Game/New"] = types.SimpleNamespace(**target)
        with self.assertRaises(RuntimeError):
            self.policy.require_asset_write(["/Game/A"], ["/Game/New"])

    def test_pie_provider_paths_and_incomplete_states_reject(self):
        """/** @return 无效目标与不完整源控状态不继续写入 */"""
        for path in ["/Engine/A", "/Game/../A", "/Game//A", "/Game/A:Node", "E:/A"]:
            with self.assertRaises(RuntimeError):
                self.policy.require_asset_write([path])
        self.assertEqual(self.queries, [])
        self.pie = True
        with self.assertRaisesRegex(RuntimeError, "PIE"):
            self.policy.require_asset_write(["/Game/A"])
        self.pie = False
        self.unreal.SourceControl.current_provider = lambda: "Git"
        self.assertEqual(self.policy.require_asset_write(["/Game/A"]), {"/Game/A": None})
        self.unreal.SourceControl.current_provider = lambda: "Perforce"
        self.unreal.SourceControl.query_file_states = lambda *args, **kwargs: []
        with self.assertRaisesRegex(RuntimeError, "完整"):
            self.policy.require_asset_write(["/Game/A"])

    def test_subobject_uses_owning_asset_package(self):
        """/** @return 修改子对象检查其资产包 不查询子对象路径 */"""
        child = types.SimpleNamespace(get_outermost=lambda: types.SimpleNamespace(get_path_name=lambda: "/Game/Blueprint"))
        self.policy.require_write_access(child)
        self.assertEqual(self.queries[0][0], ["/Game/Blueprint"])

    def test_uncontrolled_package_does_not_require_client_mapping(self):
        """/** @return 非受控骨架可编辑 受控文件的冲突保护仍存在 */"""
        values = self.state()
        values.update(is_source_controlled=False, is_valid=False, is_unknown=True,
                      is_checked_out=False, can_edit=False, can_add=False)
        self.states["/Game/ThirdParty/Skeleton"] = types.SimpleNamespace(**values)
        result = self.policy.require_asset_write(["/Game/ThirdParty/Skeleton"])
        self.assertIn("/Game/ThirdParty/Skeleton", result)
        values["is_checked_out_other"] = True
        self.states["/Game/ThirdParty/Skeleton"] = types.SimpleNamespace(**values)
        with self.assertRaisesRegex(RuntimeError, "他人占用"):
            self.policy.require_asset_write(["/Game/ThirdParty/Skeleton"])

    def test_uncontrolled_readonly_file_rejects(self):
        """/** @return 无源控映射不等于能够覆盖只读文件 */"""
        values = self.state()
        values.update(is_source_controlled=False, is_checked_out=False)
        self.states["/Game/Skeleton"] = types.SimpleNamespace(**values)
        with patch.object(self.policy.os.path, "isfile", return_value=True), \
                patch.object(self.policy.os, "access", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "只读"):
                self.policy.require_asset_write(["/Game/Skeleton"])

    def test_public_property_setter_rejects_before_mutation(self):
        """/** @return 真实属性工具的签出拒绝发生在事务 修改和保存之前 */"""
        source = ROOT / "Scripts/BBBGenericEditorToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "set_asset_object_property")
        method.decorator_list = []
        mutations = []
        asset = types.SimpleNamespace(get_editor_property=lambda name: mutations.append("read_property"),
            modify=lambda: mutations.append("modify"), set_editor_property=lambda *args: mutations.append("set"))
        unreal = types.SimpleNamespace(UnrealEditorSubsystem=object,
            get_editor_subsystem=lambda kind: types.SimpleNamespace(get_game_world=lambda: None),
            EditorAssetLibrary=types.SimpleNamespace(load_asset=lambda path: asset,
                save_loaded_asset=lambda *args: mutations.append("save")))

        def reject(obj):
            """/** @param obj 目标 @return 拒绝无签出的写入 */"""
            raise RuntimeError("独占签出拒绝")

        runtime = {"unreal": unreal}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), runtime)
        with patch.dict(sys.modules, {"BBBAssetWritePolicy": types.SimpleNamespace(require_write_access=reject)}):
            with self.assertRaisesRegex(RuntimeError, "独占签出"):
                runtime[method.name]("/Game/A", "object", "/Game/B")
        self.assertEqual(mutations, [])

    def test_resave_batch_checks_every_target_before_first_save(self):
        """/** @return 完整批次先预检 后续目标失败不会先保存首个资产 */"""
        source = ROOT / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "resave_assets")
        method.decorator_list = []
        loaded = []
        saved = []
        unreal = types.SimpleNamespace(EditorAssetLibrary=types.SimpleNamespace(
            load_asset=lambda path: loaded.append(path) or path,
            save_asset=lambda *args, **kwargs: saved.append(args)))

        def reject(assets):
            """/** @param assets 完整批次 @return 拒绝第二项目标 */"""
            self.assertEqual(assets, ["/Game/A.A", "/Game/B.B"])
            raise RuntimeError("第二项未签出")

        runtime = {"unreal": unreal}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), runtime)
        with patch.dict(sys.modules, {"BBBAssetWritePolicy": types.SimpleNamespace(require_asset_write=reject)}):
            with self.assertRaisesRegex(RuntimeError, "未签出"):
                runtime[method.name](["/Game/A", "/Game/B"])
        self.assertEqual(len(loaded), 2)
        self.assertEqual(saved, [])


if __name__ == "__main__":
    unittest.main()
