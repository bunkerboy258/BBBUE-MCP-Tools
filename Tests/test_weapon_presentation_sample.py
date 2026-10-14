import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class PresentationSampleTests(unittest.TestCase):
    """/** 武器表现采样的世界过滤 生命周期与池化边界 */"""

    def test_world_filter_and_physics_lifetime(self):
        """/** @return 只记录本世界物理对象及特效 不累计池化组件 */"""
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBWeaponHandlingTools.py").read_text(encoding="utf-8-sig"))
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_presentation_sample")
        world = object()
        mesh = Mock()
        mesh.get_children_components.return_value = []
        actor = Mock()
        actor.is_actor_being_destroyed.return_value = False
        component = actor.get_component_by_class.return_value
        component.is_simulating_physics.return_value = True
        component.get_physics_linear_velocity.return_value = SimpleNamespace(x=1, y=2, z=3)
        component.get_editor_property.return_value = None
        actor.get_path_name.return_value = "case"
        actor.get_life_span.return_value = 2.5
        effect = Mock()
        effect.get_owner.return_value.get_world.return_value = world
        effect.get_asset.return_value = None
        effect.get_path_name.return_value = "pooled"
        effect.is_active.return_value = False
        foreign = Mock()
        foreign.get_owner.return_value.get_world.return_value = object()
        engine = Mock()
        engine.StaticMeshComponent = type("StaticMeshComponent", (), {})
        engine.GameplayStatics.get_all_actors_of_class.return_value = [actor]
        engine.ObjectIterator.return_value = [effect, foreign]
        namespace = {"unreal": engine}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "presentation_test", "exec"), namespace)
        weapon_mesh = Mock()
        weapon_mesh.does_socket_exist.return_value = True
        weapon_mesh.is_bone_hidden_by_name.return_value = True
        weapon_mesh.get_num_bones.return_value = 0
        result = namespace["_presentation_sample"](world, mesh, weapon_mesh)
        self.assertEqual(result["physicsObjects"][0]["velocity"], [1, 2, 3])
        self.assertEqual(result["physicsObjects"][0]["remainingLife"], 2.5)
        self.assertEqual(result["niagaraComponents"], [{"path": "pooled", "asset": None, "active": False}])
        self.assertTrue(result["magazineHidden"])
        self.assertEqual(result["mechanismPose"], [])
        self.assertNotIn("spawnCount", result)


class NestedComponentPropertyTests(unittest.TestCase):
    """/** 只读组件引用与值类型结构的属性更新边界 */"""

    def test_component_reference_is_not_reassigned(self):
        """/** @return 修改组件内部配置时不回写只读组件指针 */"""
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBGenericEditorToolset.py").read_text(encoding="utf-8-sig"))
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_apply_editor_property")
        object_type = type("EngineObject", (), {})
        component = object_type()
        component.get_editor_property = Mock(return_value=1)
        component.set_editor_property = Mock()
        target = Mock()
        target.get_editor_property.return_value = component
        namespace = {"unreal": SimpleNamespace(Object=object_type)}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "property_test", "exec"), namespace)
        namespace["_apply_editor_property"](target, "ReadOnlyComponent", {"Value": 2})
        component.set_editor_property.assert_called_once_with("Value", 2)
        target.set_editor_property.assert_not_called()

    def test_value_struct_is_written_back(self):
        """/** @return 值类型结构仍然回写修改后的副本 */"""
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBGenericEditorToolset.py").read_text(encoding="utf-8-sig"))
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_apply_editor_property")
        value = Mock()
        value.get_editor_property.return_value = 1
        target = Mock()
        target.get_editor_property.return_value = value
        namespace = {"unreal": SimpleNamespace(Object=type("EngineObject", (), {}))}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "property_test", "exec"), namespace)
        namespace["_apply_editor_property"](target, "ValueStruct", {"Value": 2})
        target.set_editor_property.assert_called_once_with("ValueStruct", value)


if __name__ == "__main__":
    unittest.main()
