import ast
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

from BBBMcpCapabilities import ArgumentValidationError, TOOL_DOMAINS, ToolCatalog, tool_contract
from MCP.mcp_asset_scope import asset_targets, conflicting_packages
from MCP.mcp_contracts import ScopeContractError, compile_contract, validate_scope_contract
from MCP.mcp_service import CachedCatalog
from MCP.mcp_task_gateway import TaskGateway, UnrealBackend, annotation_schema


def source_contracts():
    """/** @return 从当前源码签名编译的领域与第三方契约 */"""
    for module, domain in TOOL_DOMAINS.items():
        path = ROOT / "Scripts" / (module + ".py")
        if domain is None or not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        definition = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == module)
        for node in definition.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            if not any(ast.unparse(value) == "mcp_tool" for value in node.decorator_list):
                continue
            properties = {argument.arg: annotation_schema(argument.annotation) for argument in node.args.args}
            required_count = len(node.args.args) - len(node.args.defaults)
            for argument, default in zip(node.args.args[required_count:], node.args.defaults):
                properties[argument.arg]["default"] = ast.literal_eval(default)
            schema = {"type": "object", "properties": properties,
                "required": [argument.arg for argument in node.args.args[:required_count]], "additionalProperties": False}
            contract = tool_contract(module, node.name, schema, ast.get_docstring(node) or "")
            if contract is not None:
                yield contract
    backend = object.__new__(UnrealBackend)
    backend.external_name = "static.BBBExternalToolset"
    for contract in backend.external_contracts():
        yield compile_contract(contract)


def fixture(scope=None, access="write", world="editor"):
    """/** @param scope 范围声明 @param access 权限 @param world 世界 @return 静态工具契约 */"""
    return {"id": "fixture.edit", "name": "edit", "definition": "Fixture", "toolset": "Fixture",
        "parameters": {"type": "object", "properties": {"asset": {"type": "string"}}, "additionalProperties": False},
        "access": access, "world": world, "scope": scope or {}}


def empty_catalog():
    """/** @return 纯内存目录 */"""
    return ToolCatalog(SimpleNamespace(descriptors=lambda: (), external_contracts=lambda: ()))


class ScopeContractTests(unittest.TestCase):
    """/** 全源码范围覆盖与错误分流的静态核验 */"""

    def test_every_source_tool_has_valid_scope(self):
        contracts = list(source_contracts())
        self.assertGreater(len(contracts), 500)
        self.assertEqual(len(contracts), len({contract["id"] for contract in contracts}))
        for contract in contracts:
            with self.subTest(tool=contract["id"]):
                validate_scope_contract(contract)

    def test_all_non_pie_write_worlds_require_scope(self):
        for world in ("editor", "any"):
            with self.subTest(world=world), self.assertRaises(ScopeContractError):
                validate_scope_contract(compile_contract(fixture(world=world)))
        validate_scope_contract(compile_contract(fixture(access="read")))
        validate_scope_contract(compile_contract(fixture(access="pie", world="any")))
        validate_scope_contract(compile_contract(fixture(world="pie")))

    def test_invalid_selector_and_fields_are_rejected(self):
        scopes = [{"fields": ["missing"]}, {"fields": []}, {"join": ["asset"]},
            {"kind": "global"}, {"kind": "session", "fields": ["asset"]},
            {"rows": ["asset", "path"]}, {"fields": ["asset"], "referencers": "true"}]
        for scope in scopes:
            with self.subTest(scope=scope), self.assertRaises(ScopeContractError):
                validate_scope_contract(compile_contract(fixture(scope)))

    def test_batch_row_keys_and_nullable_arrays_are_checked(self):
        contract = fixture({"rows": ["requests", ["source", "destination"]]})
        row = {"type": "object", "properties": {"source": {"type": "string"}, "destination": {"type": "string"}}}
        contract["parameters"]["properties"] = {"requests": {"anyOf": [{"type": "array", "items": row}, {"type": "null"}]}}
        validate_scope_contract(compile_contract(contract))
        row["properties"].pop("destination")
        with self.assertRaises(ScopeContractError):
            validate_scope_contract(compile_contract(contract))

    def test_one_invalid_tool_keeps_other_tools_available(self):
        catalog = empty_catalog()
        with self.assertLogs(level="ERROR"):
            self.assertFalse(catalog.add(fixture()))
        self.assertEqual(catalog.find("fixture.edit"), [])
        self.assertIn("fixture.edit", catalog.scope_errors)
        self.assertTrue(catalog.add(fixture({"fields": ["asset"]})))
        self.assertEqual(catalog.find("fixture.edit")[0]["id"], "fixture.edit")
        self.assertEqual(catalog.scope_errors, {})

    def test_cached_precompiled_contract_uses_the_same_gate(self):
        valid = compile_contract(fixture({"fields": ["asset"]}))
        invalid = copy.deepcopy(valid)
        invalid.update(id="fixture.invalid", scope={"fields": ["missing"]})
        payload = json.dumps({"tools": {valid["id"]: valid, invalid["id"]: invalid}})
        with patch.object(Path, "exists", return_value=True), patch.object(Path, "read_text", return_value=payload):
            with self.assertLogs(level="ERROR"):
                catalog = CachedCatalog("catalog.json")
        self.assertEqual(set(catalog.tools), {valid["id"]})
        self.assertIn(invalid["id"], catalog.scope_errors)

    def test_missing_target_returns_the_argument_pointer(self):
        catalog = empty_catalog()
        catalog.add(fixture({"fields": ["asset"]}))
        with self.assertRaises(ArgumentValidationError) as failure:
            catalog.prepare([{"tool": "fixture.edit", "arguments": {"asset": ""}}])
        self.assertTrue(failure.exception.issues[0].startswith("/operations/0/arguments/asset: "))

    def test_optional_empty_target_preserves_other_targets(self):
        contract = fixture({"fields": ["asset", "children"]})
        contract["parameters"]["properties"]["children"] = {"type": "array", "items": {"type": "string"}, "default": []}
        catalog = empty_catalog()
        catalog.add(contract)
        operations = catalog.prepare([{"tool": "fixture.edit", "arguments": {"asset": "/Game/Target"}}])
        self.assertTrue(operations[0]["scoped"])
        self.assertEqual(asset_targets(operations[0]["targets"]), {"/Game/Target"})

    def test_explicit_game_root_is_a_valid_directory_scope(self):
        self.assertEqual(asset_targets("/Game"), {"/Game"})
        self.assertEqual(conflicting_packages(["/Game/A", "/Game/B/C"], ["/Game"]), {"/Game/A", "/Game/B/C"})
        self.assertEqual(asset_targets("/Gameplay"), set())

    def test_invalid_tool_has_a_maintenance_error(self):
        catalog = empty_catalog()
        with self.assertLogs(level="ERROR"):
            catalog.add(fixture())
        gateway = object.__new__(TaskGateway)
        gateway.catalog = catalog
        gateway.tools = {}
        parameters = {"name": "submit_batch", "arguments": {"operations": [{"tool": "fixture.edit", "arguments": {}}]}}
        value = gateway._argument_failure(parameters, "/operations/0/tool: unknown tool")
        self.assertEqual(value["code"], "TOOL_SCOPE_INVALID")
        self.assertIsNone(value["next"])

    def test_read_preview_can_have_empty_targets(self):
        contract = fixture({"fields": ["asset"]})
        contract["parameters"]["properties"]["dry_run"] = {"type": "boolean", "default": True}
        catalog = empty_catalog()
        catalog.add(contract)
        operations = catalog.prepare([{"tool": "fixture.edit", "arguments": {}}])
        self.assertEqual(operations[0]["access"], "read")

    def test_world_scope_requires_a_saved_map(self):
        from Tests.test_mcp_task_gateway import fixtures
        from MCP.mcp_jobs import JobConflict
        backend, catalog, queue = fixtures()
        self.addCleanup(queue.close)
        contract = fixture({"kind": "world"})
        catalog.add(contract)
        client = queue.connect()
        with self.assertRaises(JobConflict) as failure:
            queue.submit(client, [{"tool": "fixture.edit", "arguments": {}}])
        self.assertEqual(failure.exception.value["code"], "EDITOR_WORLD_REQUIRED")
        self.assertEqual(backend.calls, [])

    def test_map_loading_binds_the_current_and_destination_maps(self):
        from Tests.test_mcp_task_gateway import fixtures
        for current in ("/Engine/Maps/Entry", "/Temp/Untitled", "/Game/Maps/Current"):
            with self.subTest(current=current):
                backend, catalog, queue = fixtures()
                self.addCleanup(queue.close)
                backend.state["editor_world"] = current
                queue.observe(force=True)
                contract = fixture({"kind": "world", "fields": ["asset"]})
                catalog.add(contract)
                client = queue.connect()
                batch = queue.submit(client, [{"tool": "fixture.edit", "arguments": {"asset": "/Game/Maps/Target"}}])
                expected = asset_targets(current) | {"/Game/Maps/Target"}
                job = queue.jobs[batch["batch"]]
                self.assertEqual(job["targets"], expected)
                self.assertEqual(set(job["operations"][0]["world_targets"]), asset_targets(current))


if __name__ == "__main__":
    unittest.main()
