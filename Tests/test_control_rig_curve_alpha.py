import ast
import copy
import json
from pathlib import Path
import types
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class ControlRigCurveAlphaTests(unittest.TestCase):
    """/** 连续权重迁移的占用 结构与只读预检边界 */"""

    def setUp(self):
        """/** @return 提取实际工具并构造最小的旧图表 */"""
        tree = ast.parse((ROOT / "Scripts/BBBBlueprintGraphToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "configure_control_rig_curve_alpha")
        method.decorator_list = []
        self.engine = Mock()
        self.engine.AnimBlueprint = Mock
        self.engine.AnimGraphNode_ControlRig = Mock
        self.blueprint = Mock()
        self.blueprint.get_outermost.return_value.get_path_name.return_value = "/Game/Test/ABP"
        self.node = Mock()
        self.graph = Mock()
        self.graph.get_path_name.return_value = "/Game/Test/ABP.ABP:Old"
        self.main = Mock()
        self.main.get_path_name.return_value = "/Game/Test/ABP.ABP:AnimGraph"
        self.main.get_outer.return_value = self.blueprint
        self.node.get_outer.return_value = self.main
        self.engine.load_asset.return_value = self.blueprint
        self.engine.load_object.return_value = self.node
        self.engine.BlueprintEditorLibrary.find_graph.side_effect = lambda bp, name: self.graph if name == "Old" else None
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = []
        self.function = {"snapshot": "snap", "nodes": [
            {"nodeClass": ".K2Node_FunctionEntry"}, {"nodeClass": ".K2Node_FunctionResult"},
            {"nodeClass": ".K2Node_CallFunction", "function": {"name": "GetCurveValue"}, "pins": [{"name": "CurveName", "defaultValue": "DisableIK"}]},
            {"nodeClass": ".K2Node_VariableGet", "variable": {"name": "UseIK"}},
            {"nodeClass": ".K2Node_CallFunction", "function": {"name": "BooleanAND"}},
            {"nodeClass": ".K2Node_CallFunction", "function": {"name": "LessEqual_DoubleDouble"}},
            {"nodeClass": ".Comment", "isComment": True}, {"nodeClass": ".Comment", "isComment": True}]}
        for node in self.function["nodes"]:
            node.setdefault("isComment", False)
        self.main_snapshot = {"nodes": [
            {"guid": "rig", "path": "/Game/Test/ABP.ABP:AnimGraph.Rig", "function": {},
             "animNodeProperties": {"alphaInputType": "Bool"},
             "pins": [{"name": "bAlphaBoolEnabled", "links": [{"nodeGuid": "call"}]}]},
            {"guid": "call", "function": {"name": "Old"}, "pins": [{"name": "ReturnValue", "links": [{"nodeGuid": "rig"}]}]}]}
        self.access = Mock()
        self.inspector = Mock(side_effect=lambda path: json.dumps(self.function if path.endswith(":Old") else self.main_snapshot))
        self.tools = Mock()
        namespace = {"json": json, "unreal": self.engine, "require_write_access": self.access,
                     "BlueprintTools": self.tools, "BBBBlueprintGraphToolset": types.SimpleNamespace(inspect_blueprint_graph_logic=self.inspector)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "curve_alpha_test", "exec"), namespace)
        self.configure = namespace["configure_control_rig_curve_alpha"]
        self.args = ("/Game/Test/ABP", "/Game/Test/ABP.ABP:AnimGraph.Rig", "Old", "NewAlpha", "UseIK", "DisableIK", "snap")

    def test_dry_run_checks_access_without_mutating(self):
        """/** @return 只读预检不能创建节点 编译或保存 */"""
        result = json.loads(self.configure(*self.args))
        self.assertFalse(result["saved"])
        self.assertTrue(result["dryRun"])
        self.access.assert_called_once_with(self.blueprint)
        self.engine.BlueprintGraphEditor.get_graph_editor.assert_not_called()
        self.tools.compile_blueprint.assert_not_called()
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_stale_snapshot_rejected(self):
        """/** @return 不使用其他会话写入前的快照 */"""
        with self.assertRaises(RuntimeError):
            self.configure(*self.args[:-1], "old-snap")

    def test_dirty_or_access_failure_rejected(self):
        """/** @return 脏包与占用不能进入写入 */"""
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = [self.blueprint.get_outermost.return_value]
        with self.assertRaises(RuntimeError):
            self.configure(*self.args)
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = []
        self.access.side_effect = RuntimeError("占用")
        with self.assertRaises(RuntimeError):
            self.configure(*self.args)

    def test_wrong_curve_or_extra_logic_rejected(self):
        """/** @return 不推测曲线与额外逻辑的用途 */"""
        self.function["nodes"][2]["pins"][0]["defaultValue"] = "OtherCurve"
        with self.assertRaises(RuntimeError):
            self.configure(*self.args)
        self.function["nodes"][2]["pins"][0]["defaultValue"] = "DisableIK"
        self.function["nodes"].append({"nodeClass": ".Unknown", "isComment": False})
        with self.assertRaises(RuntimeError):
            self.configure(*self.args)

    def test_wrong_or_shared_consumer_rejected(self):
        """/** @return 只迁移明确的唯一布尔消费者 */"""
        original = copy.deepcopy(self.main_snapshot)
        self.main_snapshot["nodes"][0]["pins"][0]["links"][0]["nodeGuid"] = "other"
        with self.assertRaises(RuntimeError):
            self.configure(*self.args)
        self.main_snapshot = original
        self.main_snapshot["nodes"][1]["pins"][0]["links"].append({"nodeGuid": "other"})
        with self.assertRaises(RuntimeError):
            self.configure(*self.args)

    def test_existing_new_function_or_non_bool_rejected(self):
        """/** @return 不留下兼容入口或重复迁移 */"""
        self.main_snapshot["nodes"][0]["animNodeProperties"]["alphaInputType"] = "Float"
        with self.assertRaises(RuntimeError):
            self.configure(*self.args)
        self.engine.BlueprintEditorLibrary.find_graph.side_effect = lambda bp, name: self.graph
        with self.assertRaises(RuntimeError):
            self.configure(*self.args)


if __name__ == "__main__":
    unittest.main()
