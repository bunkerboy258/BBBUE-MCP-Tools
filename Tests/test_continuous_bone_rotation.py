import ast
from pathlib import Path
import unittest
from unittest.mock import Mock


class ContinuousBoneRotationTests(unittest.TestCase):
    """/** 连续枪管表现工具的预检与依赖边界 */"""

    def setUp(self):
        """/** @return 不加载 Unreal 的工具函数与引擎替身 */"""
        path = Path(__file__).resolve().parents[1] / "Scripts/BBBWeaponHandlingTools.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        self.method = next(value for value in ast.walk(tree) if isinstance(value, ast.FunctionDef)
                           and value.name == "configure_continuous_bone_rotation")
        self.engine = Mock()
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        scope = {"unreal": self.engine}
        exec(compile(ast.Module(body=[self.method], type_ignores=[]), "continuous_rotation", "exec"), scope)
        self.configure = scope[self.method.name]

    def test_invalid_fact_properties_rejected_before_loading(self):
        """/** @return 缺少或重复快照字段时不碰蓝图 */"""
        for properties in [[], ["A", "B", "C"], ["A", "A", "C", "D"]]:
            with self.assertRaises(RuntimeError):
                self.configure("Blueprint", "Bone", properties)
        self.engine.load_asset.assert_not_called()

    def test_pie_prevents_asset_edits(self):
        """/** @return 运行验收期间不修改图表 */"""
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        with self.assertRaises(RuntimeError):
            self.configure("Blueprint", "Bone", ["Driving", "Up", "Down", "Degrees"])
        self.engine.load_asset.assert_not_called()

    def test_no_action_menu_or_gameplay_call(self):
        """/** @return 节点按明确原生类创建 不枚举菜单或读取装备 */"""
        calls = [ast.unparse(value.func) for value in ast.walk(self.method) if isinstance(value, ast.Call)]
        self.assertFalse(any("list_available_nodes" in value or "find_node_types" in value for value in calls))
        self.assertFalse(any("TryGetWeaponAnimInstance" in value or "SubmitInput" in value for value in calls))
        source = ast.unparse(self.method)
        self.assertIn("create_native_animation_node", source)
        self.assertIn("FInterpTo_Constant", source)
        self.assertIn("BarrelVisualRotation", source)

    def test_each_stored_step_reads_the_previous_assignment(self):
        """/** @return 纯函数不在后续赋值时再次加速或重复累计角度 */"""
        assignments = {value.targets[0].id: value.value for value in ast.walk(self.method)
                       if isinstance(value, ast.Assign) and len(value.targets) == 1
                       and isinstance(value.targets[0], ast.Name)}
        increment = ast.unparse(assignments["increment"])
        rotation = ast.unparse(assignments["rotation"])
        self.assertIn("g.get('BarrelVisualSpeed')", increment)
        self.assertIn("g.get('BarrelVisualAngle')", rotation)

    def test_promoted_inputs_connect_before_literal_defaults(self):
        """/** @return 数学通配引脚先确定类型 再接受数值默认值 */"""
        path = Path(__file__).resolve().parents[1] / "Scripts/BBBWeaponHandlingTools.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        graph_type = next(value for value in tree.body if isinstance(value, ast.ClassDef) and value.name == "_Graph")
        events = []

        class Pin:
            """/** 用于验证类型确定顺序的引脚替身 */"""

            def set_pin_value(self, value):
                """/** @param value 默认数值 @return 已连接其它输入时才可写入 */"""
                events.append(("literal", value))
                return events[0] == "connected"

        engine = Mock()
        engine.BlueprintGraphPin = Pin
        scope = {"unreal": engine}
        exec(compile(ast.Module(body=[graph_type], type_ignores=[]), "rotation_graph", "exec"), scope)
        graph = object.__new__(scope["_Graph"])
        graph.editor = Mock()
        node = Mock()
        node.find_input_pin.return_value = Pin()
        graph.place = Mock(return_value=node)
        graph.link = Mock(side_effect=lambda source, target: events.append("connected"))
        graph.call("Divide_DoubleDouble", inputs={"A": 1, "B": Pin()})
        self.assertEqual(events, ["connected", ("literal", "1")])


if __name__ == "__main__":
    unittest.main()
