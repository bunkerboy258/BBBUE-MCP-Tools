import ast
from collections import UserList
import json
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import Mock


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))
import BBBMcpCapabilities as capabilities


class SkeletalMeshSkinningTests(unittest.TestCase):
    """/** 网格参考姿势 源蒙皮与只读权限边界 */"""

    def setUp(self):
        """/** @return 隔离官方绑定数组和临时 modifier */"""
        self.engine = Mock()
        self.engine.Array = UserList
        self.engine.SkeletalMesh = type("SkeletalMesh", (), {})
        self.mesh = self.engine.SkeletalMesh()
        self.mesh.get_path_name = Mock(return_value="/Game/Mesh.Mesh")
        self.mesh.get_outermost = Mock(
            return_value=types.SimpleNamespace(get_path_name=lambda: "/Game/Mesh")
        )
        self.skeleton = types.SimpleNamespace(
            get_path_name=lambda: "/Game/Skeleton.Skeleton"
        )
        self.mesh.get_editor_property = Mock(return_value=self.skeleton)
        self.mesh.set_editor_property = Mock()
        self.mesh.modify = Mock()
        self.mesh.mark_package_dirty = Mock()
        self.engine.load_asset.return_value = self.mesh
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = []
        self.reference = Mock()
        self.reference.set_skeletal_mesh.return_value = True
        self.reference.get_all_bone_names.return_value = UserList(["root", "spine"])
        self.reference.get_parent_name.side_effect = (
            lambda name: {"root": "None", "spine": "root"}[name]
        )
        self.pose = types.SimpleNamespace(
            translation=types.SimpleNamespace(x=100.0, y=3.0, z=4.0),
            rotation=types.SimpleNamespace(x=0.1, y=0.2, z=0.3, w=0.4),
            scale3d=types.SimpleNamespace(x=1.0, y=2.0, z=3.0),
        )
        self.reference.get_bone_transform.return_value = self.pose
        self.weights = Mock()
        self.weights.set_skeletal_mesh.return_value = True
        self.weights.get_num_vertices.return_value = 3
        self.vertex_weights = [
            {"root": 0.7, "spine": 0.2},
            {},
            {"root": 0.0, "spine": 1.0},
        ]
        self.weights.get_vertex_weights.side_effect = (
            lambda vertex_id: self.vertex_weights[vertex_id]
        )
        self.engine.SkeletonModifier.return_value = self.reference
        self.engine.SkinWeightModifier.return_value = self.weights
        tree = ast.parse(
            (ROOT / "Scripts/BBBGenericEditorToolset.py").read_text(encoding="utf-8-sig")
        )
        method = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "inspect_skeletal_mesh_skinning"
        )
        method.decorator_list = []
        namespace = {"json": json, "re": re, "unreal": self.engine}
        exec(compile(ast.Module(body=[method], type_ignores=[]), method.name, "exec"), namespace)
        self.inspect = namespace[method.name]

    def tearDown(self):
        """/** @return 所有成功和失败路径均不编辑 提交或保存资产 */"""
        for modifier in [self.reference, self.weights]:
            for name in [
                "commit_skeleton_to_skeletal_mesh",
                "commit_weights_to_skeletal_mesh",
                "set_bone_transform",
                "set_bones_transforms",
                "set_vertex_weights",
                "normalize_vertex_weights",
                "normalize_all_weights",
                "prune_all_weights",
            ]:
                getattr(modifier, name).assert_not_called()

        self.mesh.set_editor_property.assert_not_called()
        self.mesh.modify.assert_not_called()
        self.mesh.mark_package_dirty.assert_not_called()
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_invalid_list_and_binding_array_reject_before_loading(self):
        """/** @return 空 超限 重复 非字符串 非 Game 与子路径先拒绝 */"""
        cases = [
            [],
            ["/Game/M" + str(index) for index in range(9)],
            ["/Game/Mesh", "/Game/Mesh"],
            [None],
            ["/Engine/Mesh"],
            ["/Game/Mesh.Mesh"],
            ["/Game/../Mesh"],
            ["/Game//Mesh"],
        ]

        for paths in cases:
            for value in [paths, self.engine.Array(paths)]:
                with self.subTest(paths=value):
                    with self.assertRaises(RuntimeError):
                        self.inspect(value)

        for value in [None, "/Game/Mesh"]:
            with self.assertRaises(RuntimeError):
                self.inspect(value)

        self.engine.load_asset.assert_not_called()
        self.engine.SkeletonModifier.assert_not_called()
        self.engine.SkinWeightModifier.assert_not_called()

    def test_entire_batch_type_and_skeleton_preflight_precede_modifiers(self):
        """/** @return 第二项缺失或错误类型与缺骨架不先读取前项蒙皮 */"""
        for invalid in [None, object()]:
            self.engine.load_asset.side_effect = [self.mesh, invalid]

            with self.assertRaises(RuntimeError):
                self.inspect(["/Game/Mesh", "/Game/Invalid"])

        self.engine.load_asset.side_effect = None
        self.mesh.get_editor_property.return_value = None

        with self.assertRaises(RuntimeError):
            self.inspect(["/Game/Mesh"])

        self.engine.SkeletonModifier.assert_not_called()
        self.engine.SkinWeightModifier.assert_not_called()

    def test_dirty_target_rejects_before_modifier_initialization(self):
        """/** @return 任何目标未保存时完整批次不创建临时副本 */"""
        dirty = types.SimpleNamespace(get_path_name=lambda: "/Game/Mesh")
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = [dirty]

        with self.assertRaises(RuntimeError):
            self.inspect(["/Game/Mesh"])

        self.engine.SkeletonModifier.assert_not_called()
        self.engine.SkinWeightModifier.assert_not_called()

    def test_unrelated_dirty_package_does_not_block_reading_target(self):
        """/** @return 不以其他会话的脏包拒绝当前只读目标 */"""
        dirty = types.SimpleNamespace(get_path_name=lambda: "/Game/Other")
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = [dirty]
        result = json.loads(self.inspect(["/Game/Mesh"]))
        self.assertTrue(result["supported"])

    def test_missing_modifier_class_returns_explicit_unsupported(self):
        """/** @return 缺任一插件类返回不可用 不制造网格数据 */"""
        for name in ["SkeletonModifier", "SkinWeightModifier"]:
            with self.subTest(name=name):
                definition = getattr(self.engine, name)
                setattr(self.engine, name, None)
                result = json.loads(self.inspect(["/Game/Mesh"]))
                setattr(self.engine, name, definition)
                self.assertFalse(result["supported"])
                self.assertTrue(result["readOnly"])
                self.assertIsNone(result["meshes"])
                self.assertEqual(result["missingClasses"], [name])
                self.assertEqual(
                    result["unavailableReason"],
                    "SKELETAL_MESH_MODIFIERS_UNAVAILABLE",
                )

        self.engine.SkeletonModifier.assert_not_called()
        self.engine.SkinWeightModifier.assert_not_called()

    def test_failed_loading_empty_bones_or_invalid_vertex_count_reject(self):
        """/** @return 不以默认姿势或空权重替代读取失败 */"""
        cases = [
            (self.reference.set_skeletal_mesh, False),
            (self.weights.set_skeletal_mesh, False),
            (self.reference.get_all_bone_names, []),
            (self.weights.get_num_vertices, -1),
        ]

        for method, value in cases:
            with self.subTest(method=method):
                previous = method.return_value
                method.return_value = value

                with self.assertRaises(RuntimeError):
                    self.inspect(["/Game/Mesh"])

                method.return_value = previous

    def test_reference_pose_and_all_weights_preserve_original_values(self):
        """/** @return 局部参考骨架 全顶点 空权重与未归一化权重原样输出 */"""
        result = json.loads(self.inspect(self.engine.Array(["/Game/Mesh"])))
        item = result["meshes"][0]
        self.assertTrue(result["readOnly"])
        self.assertTrue(result["supported"])
        self.assertEqual(result["lodIndex"], 0)
        self.assertEqual(result["rotationFormat"], "quaternion XYZW")
        self.assertEqual(result["vertexIdSpace"], "LOD0 MeshDescription")
        self.assertEqual(item["mesh"], "/Game/Mesh.Mesh")
        self.assertEqual(item["skeleton"], "/Game/Skeleton.Skeleton")
        self.assertEqual(item["vertexCount"], 3)
        self.assertEqual(item["boneCount"], 2)
        self.assertIsNone(item["bones"][0]["parent"])
        self.assertEqual(item["bones"][1]["parent"], "root")
        self.assertEqual(
            item["bones"][1]["local"],
            {
                "position": [100.0, 3.0, 4.0],
                "rotation": [0.1, 0.2, 0.3, 0.4],
                "scale": [1.0, 2.0, 3.0],
            },
        )
        self.assertEqual(
            item["weights"],
            {str(index): value for index, value in enumerate(self.vertex_weights)},
        )
        self.assertEqual(
            self.reference.get_bone_transform.call_args_list,
            [unittest.mock.call("root", False), unittest.mock.call("spine", False)],
        )
        self.assertEqual(
            self.weights.get_vertex_weights.call_args_list,
            [unittest.mock.call(0), unittest.mock.call(1), unittest.mock.call(2)],
        )

    def test_nonfinite_source_data_is_not_serialized_as_valid_json(self):
        """/** @return 非有限原始数据明确失败 不改写或填补 */"""
        self.vertex_weights[0]["root"] = float("nan")

        with self.assertRaises(ValueError):
            self.inspect(["/Game/Mesh"])

    def test_eight_meshes_are_supported_without_sampling_vertices(self):
        """/** @return 最大合法批次读取每项全部源顶点 */"""
        paths = ["/Game/M" + str(index) for index in range(8)]
        result = json.loads(self.inspect(paths))
        self.assertEqual(len(result["meshes"]), 8)
        self.assertEqual(self.engine.load_asset.call_count, 8)
        self.assertEqual(self.weights.get_vertex_weights.call_count, 24)

    def test_contract_is_read_only_in_editor_and_test(self):
        """/** @return 单工具 schema 分类与公开查询环境一致 */"""
        baseline = json.loads(
            (ROOT / "Tests/tool_schema_baseline.json").read_text(encoding="utf-8")
        )
        schema = baseline["BBBGenericEditorToolset"]["inspect_skeletal_mesh_skinning"]
        contract = capabilities.tool_contract(
            "BBBGenericEditorToolset",
            "inspect_skeletal_mesh_skinning",
            schema["inputSchema"],
        )
        self.assertEqual(contract["id"], "editor.inspect_skeletal_mesh_skinning")
        self.assertEqual((contract["access"], contract["world"]), ("read", "any"))
        self.assertEqual(
            capabilities.write_scope(contract, {"mesh_paths": ["/Game/Mesh"]}),
            ([], True),
        )
        backend = types.SimpleNamespace(
            descriptors=lambda: [(
                "BBBGenericEditorToolset",
                [{
                    "name": "inspect_skeletal_mesh_skinning",
                    "inputSchema": schema["inputSchema"],
                }],
            )],
            external_contracts=lambda: [],
        )
        self.assertEqual(
            capabilities.ToolCatalog(backend).describe(
                "editor.inspect_skeletal_mesh_skinning"
            )["environments"],
            ["editor", "test"],
        )


if __name__ == "__main__":
    unittest.main()
