import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest


class RedirectorRecoveryTests(unittest.TestCase):
    """/** 精确迁移的重定向收尾保护 */"""

    def setUp(self):
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBAssetMoveRecovery.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        self.deleted = []
        self.target = "/Game/_ThirdParty/Test/A.A"
        self.references = []
        self.asset_class = "/Script/CoreUObject.ObjectRedirector"
        record = SimpleNamespace(asset_class_path=None, get_tag_value=lambda key: "ObjectRedirector'" + self.target + "'")
        registry = SimpleNamespace(get_assets_by_package_name=lambda path: [record])
        def cleanup(paths, dry_run):
            if not dry_run:
                self.deleted.extend(paths)
            return json.dumps({"success": True})
        maintenance = SimpleNamespace(
            _move_registry=lambda: registry,
            _move_class_path=lambda path: self.asset_class,
            _verify_asset_moves_json=lambda rows: json.dumps({"success": True, "results": [{"success": True, "old_referencers": self.references}]}),
            BBBAssetMaintenanceToolset=SimpleNamespace(delete_asset_redirectors=cleanup))
        self.runtime = {"maintenance": maintenance, "json": json, "McpExecutionError": RuntimeError}
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "finish_redirectors")
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), self.runtime)
        self.report = {"assets": [{"source": "/Game/Old/A", "destination": "/Game/_ThirdParty/Test/A", "destination_object": self.target}]}

    def test_exact_unreferenced_redirector_is_removed_and_verified(self):
        result = self.runtime["finish_redirectors"](self.report)
        self.assertTrue(result["success"])
        self.assertEqual(self.deleted, ["/Game/Old/A"])

    def test_other_target_or_remaining_reference_prevents_delete(self):
        for failure in ("target", "reference"):
            self.setUp()
            if failure == "target":
                self.target = "/Game/Other/A.A"
            if failure == "reference":
                self.references = ["/Game/Other"]
            with self.assertRaises(RuntimeError):
                self.runtime["finish_redirectors"](self.report)
            self.assertEqual(self.deleted, [])

    def test_real_asset_is_never_treated_as_redirector(self):
        self.asset_class = "/Script/Engine.StaticMesh"
        self.assertIsNone(self.runtime["finish_redirectors"](self.report))
        self.assertEqual(self.deleted, [])


if __name__ == "__main__":
    unittest.main()
