import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PIEStaticMeshInspectionTests(unittest.TestCase):
    """/** 验证网格检查同时覆盖独立弹壳与角色手持组件 */"""

    def test_actor_and_attached_component_are_both_reported(self):
        """/** @return 同一网格的物理实例和附着实例不会漏检 */"""
        mesh = object()
        other_mesh = object()

        class Component:
            def __init__(self, asset, physics, parent):
                self.asset = asset
                self.physics = physics
                self.parent = parent

            def get_editor_property(self, name):
                return self.asset

            def get_attach_parent(self):
                return self.parent

            def get_path_name(self):
                return "Component"

            def is_simulating_physics(self):
                return self.physics

            def get_physics_linear_velocity(self):
                return [300, 20, 40]

            def get_world_location(self):
                return [1, 2, 3]

            def get_attach_socket_name(self):
                return "hand_l" if self.parent else "None"

        class Actor:
            def __init__(self, components):
                self.components = components

            def get_components_by_class(self, component_class):
                return self.components

            def get_path_name(self):
                return "Actor"

        class StaticMeshActor(Actor):
            def get_life_span(self):
                return 2.5

        parent = SimpleNamespace(get_path_name=lambda: "CharacterMesh")
        actors = [StaticMeshActor([Component(mesh, True, None)]),
                  Actor([Component(mesh, False, parent), Component(other_mesh, False, parent)])]
        queried_classes = []

        def get_actors(world, actor_class):
            queried_classes.append(actor_class)
            return actors

        tree = ast.parse((ROOT / "Scripts/BBBGenericEditorToolset.py").read_text(encoding="utf-8-sig"))
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                        and node.name == "inspect_pie_static_mesh_instances")
        function.decorator_list = []
        namespace = {"json": json, "_serialize_value": lambda value: value,
                     "unreal": SimpleNamespace(load_asset=lambda path: mesh, StaticMesh=object,
                                                Actor=Actor, StaticMeshActor=StaticMeshActor,
                                                StaticMeshComponent=Component,
                                                EditorLevelLibrary=SimpleNamespace(get_pie_worlds=lambda _: [object()]),
                                                GameplayStatics=SimpleNamespace(get_all_actors_of_class=get_actors))}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "inspection", "exec"), namespace)
        result = json.loads(namespace["inspect_pie_static_mesh_instances"]("/Game/Test"))
        self.assertEqual(queried_classes, [Actor])
        self.assertEqual(result["count"], 2)
        self.assertTrue(result["instances"][0]["simulatingPhysics"])
        self.assertEqual(result["instances"][0]["remainingLifeSeconds"], 2.5)
        self.assertEqual(result["instances"][1]["attachParent"], "CharacterMesh")
        self.assertEqual(result["instances"][1]["attachSocket"], "hand_l")
        self.assertIsNone(result["instances"][1]["remainingLifeSeconds"])


if __name__ == "__main__":
    unittest.main()
