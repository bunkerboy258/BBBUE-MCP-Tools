import ast
from pathlib import Path
import unittest
from unittest.mock import Mock


class StaticMeshGeometryTests(unittest.TestCase):
    """/** 通用几何读取不得依赖伤口制作路径 */"""

    def setUp(self):
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBRigidPartToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "inspect_static_mesh_geometry")
        method.decorator_list = []
        self.engine = Mock()
        self.engine.StaticMesh = type("StaticMesh", (), {})
        self.scope = {"unreal": self.engine}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "mesh_geometry_test", "exec"), self.scope)

    def test_empty_and_duplicate_inputs_do_not_load_assets(self):
        """/** @return 无效清单不进入原生读取 */"""
        for paths in ([], ["/Game/Mesh", "/Game/Mesh"]):
            with self.assertRaises(RuntimeError):
                self.scope["inspect_static_mesh_geometry"](paths)
        self.engine.load_asset.assert_not_called()

    def test_non_mesh_does_not_call_native(self):
        """/** @return 非静态网格在调用原生前被拒绝 */"""
        self.engine.load_asset.return_value = object()
        with self.assertRaises(RuntimeError):
            self.scope["inspect_static_mesh_geometry"](["/Game/Mesh"])
        self.engine.BBBBlueprintEditorLibrary.inspect_static_mesh_geometry.assert_not_called()

    def test_native_result_is_read_only_and_not_wound_specific(self):
        """/** @return 通用读取保留诊断结果 不保存资产 */"""
        mesh = self.engine.StaticMesh()
        self.engine.load_asset.return_value = mesh
        native = self.engine.BBBBlueprintEditorLibrary.inspect_static_mesh_geometry
        native.return_value = '{"meshes":[]}'
        self.assertEqual(self.scope["inspect_static_mesh_geometry"](["/Game/Mesh"]), '{"meshes":[]}')
        native.assert_called_once_with([mesh])
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
