import ast
import json
from pathlib import Path
import re
import types
import unittest
from unittest.mock import Mock


class WoundAssetTests(unittest.TestCase):
    """/** 伤口资源制作的写入范围与失败边界 */"""

    def setUp(self):
        """/** @return 隔离编辑器和精确资产对象 无真实资产读写 */"""
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBHitReactionToolset.py").read_text(encoding="utf-8-sig"))
        self.engine = Mock()
        for name in ("SkeletalMesh", "StaticMesh", "BBBMonsterDefinition", "MaterialInterface"):
            setattr(self.engine, name, type(name, (), {}))
        self.engine.Material = type("Material", (self.engine.MaterialInterface,), {})
        self.engine.MaterialInstanceConstant = type("MaterialInstanceConstant", (self.engine.MaterialInterface,), {})
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = False
        self.access = Mock()
        self.scope = {"unreal": self.engine, "json": json, "re": re, "require_asset_write": self.access}
        for name in ("_wound_asset_plan", "plan_zombie_wound_presentation_set", "bake_zombie_wound_presentation_set", "finalize_zombie_wound_material_masks", "rebuild_zombie_wound_cut_geometry"):
            method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
            method.decorator_list = []
            exec(compile(ast.Module(body=[method], type_ignores=[]), "wound_asset_test", "exec"), self.scope)
        self.body_path = "/Game/_Project/Body"
        self.definition_path = "/Game/_Project/Definition"
        self.output = "/Game/_Project/Wounds"
        self.parts = []
        for bone in ("head", "upperarm_l", "upperarm_r", "thigh_l", "thigh_r"):
            props = {"bone": bone}
            for key, suffix in (("detached_mesh", "_Part"), ("cap_mesh", "_Cap")):
                mesh = self.engine.StaticMesh()
                package = "/Game/_Project/Parts/SM_Body_" + bone + suffix
                mesh.get_path_name = lambda package=package: package + "." + package.rsplit("/", 1)[-1]
                props[key] = mesh
            self.parts.append(types.SimpleNamespace(get_editor_property=lambda key, props=props: props[key]))
        self.body = self.engine.SkeletalMesh()
        self.body.get_name = lambda: "Body"
        self.body.get_path_name = lambda: self.body_path + ".Body"
        material = self.engine.Material()
        material.get_name = lambda: "Surface"
        material.get_editor_property = lambda key: False
        self.body.get_editor_property = lambda key: [types.SimpleNamespace(get_editor_property=lambda key: material)]
        self.definition = self.engine.BBBMonsterDefinition()
        self.definition.get_path_name = lambda: self.definition_path + ".Definition"
        self.definition.get_editor_property = lambda key: self.parts
        self.engine.load_asset.side_effect = lambda path: {self.body_path: self.body, self.definition_path: self.definition}.get(path)

    def test_plan_lists_exact_inputs_and_outputs_without_write(self):
        """/** @return 十二个待改资产和六个蒙皮输出 不修改资产 */"""
        result = json.loads(self.scope["plan_zombie_wound_presentation_set"](self.body_path, self.definition_path, self.output))
        self.assertEqual(len(result["changed"]), 12)
        self.assertEqual(len([path for path in result["destinations"] if path.startswith(self.output + "/SK_")]), 6)
        self.assertFalse(result["saved"])
        self.access.assert_not_called()
        self.engine.BBBZombieSeveringEditorLibrary.bake_wound_presentation_set.assert_not_called()

    def test_live_pie_rejected_before_loading(self):
        """/** @return 活跃世界中没有资源读写 */"""
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        with self.assertRaises(RuntimeError):
            self.scope["bake_zombie_wound_presentation_set"](self.body_path, self.definition_path, self.output)
        self.engine.load_asset.assert_not_called()
        self.access.assert_not_called()

    def test_instance_parent_uses_reflected_property(self):
        """/** @return 共享材质实例通过真实父引用解析 不依赖不存在的编辑器函数 */"""
        base = self.engine.Material()
        base.get_name = lambda: "Surface"
        base.get_editor_property = lambda key: False
        instance = self.engine.MaterialInstanceConstant()
        instance.get_name = lambda: "Skin"
        instance.get_editor_property = lambda key: base if key == "parent" else None
        self.body.get_editor_property = lambda key: [types.SimpleNamespace(get_editor_property=lambda key: instance)]
        result = json.loads(self.scope["plan_zombie_wound_presentation_set"](self.body_path, self.definition_path, self.output))
        self.assertIn("/Game/_Project/System/Mass/Monster/Zombie/Shared/Wounds/MI_Skin_Wound", result["destinations"])
        self.engine.MaterialEditingLibrary.get_material_instance_parent.assert_not_called()

    def test_external_input_and_unsafe_output_rejected(self):
        """/** @return 不能覆盖第三方或逃逸输出目录 */"""
        for paths in (("/Game/_ThirdParty/Body", self.definition_path, self.output),
                      (self.body_path, self.definition_path, "/Game/_Project/../Other")):
            with self.assertRaises(RuntimeError):
                self.scope["bake_zombie_wound_presentation_set"](*paths)
        self.access.assert_not_called()
        self.engine.BBBZombieSeveringEditorLibrary.bake_wound_presentation_set.assert_not_called()

    def test_duplicate_bones_and_existing_outputs_rejected(self):
        """/** @return 缺部位或已有输出不重复烘焙 */"""
        self.parts[4] = self.parts[0]
        with self.assertRaises(RuntimeError):
            self.scope["bake_zombie_wound_presentation_set"](self.body_path, self.definition_path, self.output)
        self.setUp()
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = True
        with self.assertRaises(RuntimeError):
            self.scope["bake_zombie_wound_presentation_set"](self.body_path, self.definition_path, self.output)
        self.access.assert_not_called()

    def test_unregistered_part_path_rejected(self):
        """/** @return 原生重建路径必须与签出清单逐项一致 */"""
        mesh = self.parts[0].get_editor_property("cap_mesh")
        mesh.get_path_name = lambda: "/Game/_Project/Parts/Unexpected.Unexpected"
        with self.assertRaises(RuntimeError):
            self.scope["bake_zombie_wound_presentation_set"](self.body_path, self.definition_path, self.output)
        self.access.assert_not_called()

    def test_source_control_failure_prevents_native_mutation(self):
        """/** @return 独占检查失败时原生接口不执行 */"""
        self.access.side_effect = RuntimeError("未独占持有")
        with self.assertRaisesRegex(RuntimeError, "未独占持有"):
            self.scope["bake_zombie_wound_presentation_set"](self.body_path, self.definition_path, self.output)
        self.engine.BBBZombieSeveringEditorLibrary.bake_wound_presentation_set.assert_not_called()

    def test_native_failure_propagates_without_save(self):
        """/** @return 原生失败不是成功或重复重试 */"""
        native = self.engine.BBBZombieSeveringEditorLibrary.bake_wound_presentation_set
        native.return_value = "失败 拓扑不完整"
        with self.assertRaisesRegex(RuntimeError, "拓扑不完整"):
            self.scope["bake_zombie_wound_presentation_set"](self.body_path, self.definition_path, self.output)
        native.assert_called_once_with(self.body, self.definition, self.output)
        self.engine.EditorAssetLibrary.save_asset.assert_not_called()

    def test_success_retains_native_unsaved_result(self):
        """/** @return 核验和签出后只烘焙一次 保存由显式调用负责 */"""
        result = json.dumps({"wounds": self.output + "/SK_Body_Wounds", "saved": False})
        self.engine.BBBZombieSeveringEditorLibrary.bake_wound_presentation_set.return_value = result
        self.assertEqual(self.scope["bake_zombie_wound_presentation_set"](self.body_path, self.definition_path, self.output), result)
        self.access.assert_called_once()
        self.engine.EditorAssetLibrary.save_asset.assert_not_called()

    def test_gib_probe_requires_pie_and_does_not_mutate(self):
        """/** @return 新探针无 PIE 拒绝 有世界仅查询当前计数 */"""
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBHitReactionToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "inspect_zombie_gib_presentation")
        method.decorator_list = []
        exec(compile(ast.Module(body=[method], type_ignores=[]), "gib_probe_test", "exec"), self.scope)
        with self.assertRaises(RuntimeError):
            self.scope["inspect_zombie_gib_presentation"]()
        world = object()
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = world
        self.engine.BBBZombieSeveringEditorLibrary.inspect_gib_presentation.return_value = '{"simulating":32,"settled":128}'
        self.assertEqual(json.loads(self.scope["inspect_zombie_gib_presentation"]())["settled"], 128)
        self.engine.BBBZombieSeveringEditorLibrary.inspect_gib_presentation.assert_called_once_with(world)
        self.access.assert_not_called()

    def test_mask_finalize_rejects_pie_external_duplicates_and_non_material(self):
        """/** @return 裁剪整理不能跨目录或重复写入 活跃世界不允许资产变更 */"""
        method = self.scope["finalize_zombie_wound_material_masks"]
        path = "/Game/_Project/System/Mass/Monster/Zombie/Shared/Wounds/M_Skin_Wound"
        for paths in ([], ["/Game/_ThirdParty/M_Skin"], [path, path], [path]):
            with self.assertRaises(RuntimeError):
                method(paths)
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        with self.assertRaises(RuntimeError):
            method([path])
        self.access.assert_not_called()
        self.engine.BBBZombieSeveringEditorLibrary.finalize_wound_material_masks.assert_not_called()

    def test_mask_finalize_checks_access_and_preserves_unsaved_result(self):
        """/** @return 原生整理前检查源控 不隐式保存或重烘网格 */"""
        path = "/Game/_Project/System/Mass/Monster/Zombie/Shared/Wounds/M_Skin_Wound"
        material = self.engine.Material()
        self.engine.load_asset.side_effect = lambda _: material
        native = self.engine.BBBZombieSeveringEditorLibrary.finalize_wound_material_masks
        native.return_value = '{"constantsReplaced":1,"saved":false}'
        result = self.scope["finalize_zombie_wound_material_masks"]([path])
        self.assertEqual(json.loads(result)["constantsReplaced"], 1)
        self.access.assert_called_once_with([path], [])
        native.assert_called_once_with([material])
        self.engine.EditorAssetLibrary.save_asset.assert_not_called()
        self.engine.BBBZombieSeveringEditorLibrary.bake_wound_presentation_set.assert_not_called()

    def test_mask_finalize_source_control_and_native_failures_propagate(self):
        """/** @return 权限失败不调用原生 原生失败不作为成功 */"""
        path = "/Game/_Project/System/Mass/Monster/Zombie/Shared/Wounds/M_Skin_Wound"
        self.engine.load_asset.side_effect = lambda _: self.engine.Material()
        self.access.side_effect = RuntimeError("未独占持有")
        native = self.engine.BBBZombieSeveringEditorLibrary.finalize_wound_material_masks
        with self.assertRaisesRegex(RuntimeError, "未独占持有"):
            self.scope["finalize_zombie_wound_material_masks"]([path])
        native.assert_not_called()
        self.access.side_effect = None
        native.return_value = "失败 遮罩表达式缺失"
        with self.assertRaisesRegex(RuntimeError, "遮罩表达式缺失"):
            self.scope["finalize_zombie_wound_material_masks"]([path])

    def test_cut_geometry_rejects_pie_paths_duplicates_and_types(self):
        """/** @return 未通过全部前置条件时不进入原生重建 */"""
        method = self.scope["rebuild_zombie_wound_cut_geometry"]
        path = "/Game/_Project/System/Mass/Monster/Zombie/Male/Connor/SK_Connor_Wounds"
        for paths in ([], ["/Game/_ThirdParty/SK_Body"], [path, path], [None], [path]):
            with self.assertRaises(RuntimeError):
                method(paths)
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        with self.assertRaises(RuntimeError):
            method([path])
        self.access.assert_not_called()
        self.engine.BBBZombieSeveringEditorLibrary.rebuild_wound_cut_geometry.assert_not_called()

    def test_cut_geometry_source_control_failure_prevents_mutation(self):
        """/** @return 独占检查失败不修改网格 */"""
        path = "/Game/_Project/System/Mass/Monster/Zombie/Male/Connor/SK_Connor_Wounds"
        self.engine.load_asset.side_effect = lambda _: self.body
        self.access.side_effect = RuntimeError("未独占持有")
        with self.assertRaisesRegex(RuntimeError, "未独占持有"):
            self.scope["rebuild_zombie_wound_cut_geometry"]([path])
        self.engine.BBBZombieSeveringEditorLibrary.rebuild_wound_cut_geometry.assert_not_called()

    def test_cut_geometry_native_failure_propagates(self):
        """/** @return 原生拒绝不伪装为成功 不隐式保存 */"""
        path = "/Game/_Project/System/Mass/Monster/Zombie/Male/Connor/SK_Connor_Wounds"
        self.engine.load_asset.side_effect = lambda _: self.body
        self.engine.BBBZombieSeveringEditorLibrary.rebuild_wound_cut_geometry.return_value = "失败 UV不完整"
        with self.assertRaisesRegex(RuntimeError, "UV不完整"):
            self.scope["rebuild_zombie_wound_cut_geometry"]([path])
        self.engine.EditorAssetLibrary.save_asset.assert_not_called()

    def test_cut_geometry_preserves_exact_unsaved_result(self):
        """/** @return 仅重建明确网格 保存由显式入口负责 */"""
        path = "/Game/_Project/System/Mass/Monster/Zombie/Male/Connor/SK_Connor_Wounds"
        self.engine.load_asset.side_effect = lambda _: self.body
        native = self.engine.BBBZombieSeveringEditorLibrary.rebuild_wound_cut_geometry
        native.return_value = '{"removedTorsoPolygons":40,"saved":false}'
        self.assertEqual(json.loads(self.scope["rebuild_zombie_wound_cut_geometry"]([path]))["removedTorsoPolygons"], 40)
        self.access.assert_called_once_with([path], [])
        native.assert_called_once_with([self.body])
        self.engine.EditorAssetLibrary.save_asset.assert_not_called()

    def test_only_gib_probe_has_shared_query_permission(self):
        """/** @return 烘焙及其资产加载计划仍需独占编辑阶段 */"""
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
        from BBBMcpCapabilities import tool_contract
        self.assertEqual(tool_contract("BBBHitReactionToolset", "inspect_zombie_gib_presentation", {})["access"], "read")
        self.assertEqual(tool_contract("BBBHitReactionToolset", "plan_zombie_wound_presentation_set", {})["access"], "write")
        self.assertEqual(tool_contract("BBBHitReactionToolset", "bake_zombie_wound_presentation_set", {})["access"], "write")


if __name__ == "__main__":
    unittest.main()
