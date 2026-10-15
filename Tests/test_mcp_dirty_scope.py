import ast
import json
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

from BBBMcpCapabilities import TOOL_DOMAINS, write_scope
from MCP.mcp_contracts import TOOL_POLICIES
from MCP.mcp_asset_scope import asset_targets, conflicting_packages
from MCP.mcp_result import McpBusinessError
from Tests.test_mcp_task_gateway import fixtures, operation


class DirtyScopeTests(unittest.TestCase):
    """/** @return 调度范围与保存交接回归 */"""

    def setUp(self):
        """
        /**
         * @return 建立隔离宿主与范围证据
         */
        """
        self.backend, self.catalog, self.queue = fixtures()
        self.first = self.queue.connect()
        self.second = self.queue.connect()
        self.addCleanup(self.queue.close)

    def submit(self, owner, *operations):
        """
        /**
         * @param owner	测试输入
         * @param operations	本次操作
         * @return 登记本客户端批次
         */
        """
        return self.queue.submit(owner, list(operations))["batch"]

    def test_saved_owner_releases_waiter_automatically(self):
        original = self.submit(self.first, operation("write", asset="/Game/A"))
        waiter = self.submit(self.second, operation("write", asset="/Game/A"))
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[original]["status"], "completed")
        self.assertEqual(self.queue.jobs[waiter]["status"], "queued")
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[waiter]["status"], "completed")
        self.assertEqual(self.backend.state["dirty_packages"], [])
        self.assertEqual(self.queue.assets.claims, {})

    def test_unknown_effect_keeps_review_after_package_is_clean(self):
        """
        /**
         * @return 核验资产范围与批次交接
         */
        """
        self.backend.reconcile = lambda packages: (_ for _ in ()).throw(RuntimeError("readback unavailable"))
        original = self.submit(self.first, operation("unknown", asset="/Game/A"))
        self.queue.run_once()
        self.queue.observe(force=True)
        self.assertEqual(self.queue.jobs[original]["status"], "failed")
        other = self.submit(self.second, operation("write", asset="/Game/B"), operation("save_assets", asset_paths=["/Game/B"]))
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[other]["status"], "completed")

    def test_dirty_directory_scope_blocks_descendants_and_preserves_siblings(self):
        """
        /**
         * @return 核验资产范围与批次交接
         */
        """
        self.backend.state["dirty_packages"] = ["/Game/Pack/A", "/Game/PackExtra/B"]
        self.queue.observe(force=True)
        batch = self.submit(self.second, operation("write", asset="/Game/Pack"))
        self.assertFalse(self.queue.run_once())
        blocked = self.queue.inspect(self.second, batch)
        self.assertEqual(blocked["code"], "ASSET_SAVE_REQUIRED")
        self.assertEqual(blocked["blocked"]["packages"], ["/Game/Pack/A"])
        self.assertEqual(blocked["blocked"]["count"], 1)
        self.assertEqual(conflicting_packages(self.backend.state["dirty_packages"], ["/Game/PackExtra"]), {"/Game/PackExtra/B"})

    def test_unknown_scope_reports_action_without_dumping_all_dirty_packages(self):
        self.backend.state["dirty_packages"] = ["/Game/A" + str(index) for index in range(191)]
        self.catalog.add({"id": "scene.unknown", "name": "unknown", "definition": "Scene", "toolset": "Scene", "parameters": {"type": "object"}, "access": "write", "world": "editor"})
        with self.assertRaises(McpBusinessError) as failure:
            self.queue.submit(self.second, [{"tool": "scene.unknown", "arguments": {}}])
        self.assertEqual(failure.exception.value["code"], "ASSET_SCOPE_REQUIRED")
        self.assertEqual(self.queue.queue, [])
        self.assertLess(len(json.dumps(failure.exception.value)), 512)

    def test_async_resume_claims_only_its_scope(self):
        """
        /**
         * @return 核验资产范围与批次交接
         */
        """
        batch = self.submit(self.first, operation("write", asset="/Game/A"))
        job = self.queue.jobs[batch]
        job["started"] = True
        job["yield_dirty"] = []
        self.backend.state["dirty_packages"] = ["/Game/Other"]
        self.queue.observe(force=True)
        self.queue.run_once()
        self.assertEqual(job["owned_dirty"], {"/Game/A"})
        self.assertEqual(job["dirty"], [])
        self.assertEqual(self.backend.state["dirty_packages"], ["/Game/Other"])

    def test_package_normalization_respects_case_and_subobjects(self):
        """
        /**
         * @return 核验资产范围与批次交接
         */
        """
        self.assertEqual(asset_targets(["/Game/A.A:Graph.Node", ("/Game/B.B",)]), {"/Game/A", "/Game/B"})
        self.assertEqual(conflicting_packages(["/Game/a"], ["/Game/A.A"]), {"/Game/a"})

    def test_json_scope_uses_only_mutated_assets(self):
        """
        /**
         * @return 核验资产范围与批次交接
         */
        """
        contract = {"id": "assets.repair_animation_property_queries", "definition": "BBBAssetMaintenanceToolset", "parameters": {}, "access": "write", "world": "editor"}
        targets, scoped = write_scope(contract, {"operations": [{"asset": "/Game/A", "paths": [{"old": "/Game/ReadOnly"}]}]})
        self.assertTrue(scoped)
        self.assertEqual(asset_targets(targets), {"/Game/A"})
        self.assertEqual(write_scope(contract, {"operations": [{"paths": []}]}), ([], False))

    def test_pie_runtime_objects_do_not_become_saved_asset_targets(self):
        """/** @return PIE 临时演员不参与磁盘版本检查 正式地图仍在范围中 */"""
        actor = "/Game/Maps/UEDPIE_1_Main.Main:PersistentLevel.PlayerController_0"
        self.assertEqual(asset_targets({"actor_path": actor}), set())
        self.assertEqual(asset_targets([actor, "/Game/Maps/Main.Main"]), {"/Game/Maps/Main"})
        self.assertEqual(asset_targets(actor, normalize=False), set())
        self.assertEqual(asset_targets("/Game/Maps/MyUEDPIE_1_Main.MyUEDPIE_1_Main"), {"/Game/Maps/MyUEDPIE_1_Main"})

    def test_empty_optional_target_list_keeps_known_scope(self):
        """
        /**
         * @return 核验资产范围与批次交接
         */
        """
        contract = {"id": "animation_graph.configure_character_continuous_locomotion", "definition": "BBBAnimationGraphToolset", "parameters": {}, "access": "write", "world": "editor"}
        targets, scoped = write_scope(contract, {"asset_path": "/Game/Main", "base_layer_path": "/Game/Base", "child_layer_paths": [], "output_directory": "/Game/Output"})
        self.assertTrue(scoped)
        self.assertEqual(asset_targets(targets), {"/Game/Main", "/Game/Base", "/Game/Output"})

    def test_scope_fields_match_actual_tool_parameters(self):
        """
        /**
         * @return 核验资产范围与批次交接
         */
        """
        definitions = {domain: name for name, domain in TOOL_DOMAINS.items() if domain}
        for tool, policy in TOOL_POLICIES.items():
            fields = policy.get("scope", {}).get("fields", [])
            if tool.startswith("external."):
                continue
            domain, method = tool.split(".", 1)
            if domain not in definitions:
                continue
            source = ROOT / "Scripts" / (definitions[domain] + ".py")
            if not source.exists():
                continue
            tree = ast.parse(source.read_text(encoding="utf-8-sig"))
            functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == method]
            self.assertTrue(functions, tool)
            self.assertTrue(set(fields) <= {arg.arg for arg in functions[0].args.args}, tool)
        self.assertTrue(all(not field.endswith("_json") for policy in TOOL_POLICIES.values() if "rows" in policy.get("scope", {}) for field, key in [policy["scope"]["rows"]]))


class DomainDirtyScopeTests(unittest.TestCase):
    """/** @return 原生调用前的领域范围回归 */"""

    def setUp(self):
        """
        /**
         * @return 建立隔离宿主与范围证据
         */
        """
        source = ROOT / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        names = {"_move_dirty_packages", "repair_missing_animation_skeleton", "normalize_material_auxiliary_data", "repair_foliage_base_cache"}
        nodes = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
        for node in nodes:
            node.decorator_list = []
        self.dirty = ["/Game/Other"]
        packages = lambda: [types.SimpleNamespace(get_path_name=lambda path=path: path) for path in self.dirty]
        self.engine = types.SimpleNamespace(
            EditorLoadingAndSavingUtils=types.SimpleNamespace(get_dirty_content_packages=packages, get_dirty_map_packages=lambda: []),
            LevelEditorSubsystem=object,
            get_editor_subsystem=lambda kind: types.SimpleNamespace(is_in_play_in_editor=lambda: False),
            BBBAssetRepairEditorLibrary=types.SimpleNamespace(repair_missing_animation_skeleton=lambda a, b: '{"success":true}'),
            EditorAssetLibrary=types.SimpleNamespace(save_asset=self.save),
            log=lambda message: None,
        )
        self.runtime = {"unreal": self.engine, "json": json, "_move_path": lambda path: path, "require_asset_write": lambda *args: None}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), self.runtime)

    def save(self, path, **options):
        """
        /**
         * @param path	测试输入
         * @return 保存明确包并保留其他任务内容
         */
        """
        self.dirty[:] = [package for package in self.dirty if package != path]
        return True

    def test_repair_saves_its_target_and_preserves_other_task(self):
        """
        /**
         * @return 核验资产范围与批次交接
         */
        """
        report = json.loads(self.runtime["repair_missing_animation_skeleton"]("/Game/Animation", "/Game/Skeleton"))
        self.assertTrue(report["success"])
        self.assertEqual(self.dirty, ["/Game/Other"])

    def test_repair_waits_for_dirty_target_or_input(self):
        """
        /**
         * @return 核验资产范围与批次交接
         */
        """
        for path in ["/Game/Animation", "/Game/Skeleton"]:
            self.dirty.append(path)
            with self.assertRaises(RuntimeError):
                self.runtime["repair_missing_animation_skeleton"]("/Game/Animation", "/Game/Skeleton")
            self.dirty.remove(path)

    def test_scoped_dirty_query_checks_both_maps_and_content(self):
        """
        /**
         * @return 核验资产范围与批次交接
         */
        """
        self.engine.EditorLoadingAndSavingUtils.get_dirty_map_packages = lambda: [types.SimpleNamespace(get_path_name=lambda: "/Game/Maps/Test")]
        self.assertEqual(self.runtime["_move_dirty_packages"](["/Game/Maps"]), ["/Game/Maps/Test"])
        self.assertEqual(self.runtime["_move_dirty_packages"](), ["/Game/Maps/Test", "/Game/Other"])


if __name__ == "__main__":
    unittest.main()
