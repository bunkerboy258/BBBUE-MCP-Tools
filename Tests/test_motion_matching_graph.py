import ast
import copy
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_planner():
    """/** @return 不依赖运行中编辑器的边界验证函数 */"""
    tree = ast.parse((ROOT / "Scripts/BBBMotionMatchingGraph.py").read_text(encoding="utf-8-sig"))
    names = {"_pin", "plan_pose_replacement"}
    body = [node for node in tree.body if isinstance(node, ast.Assign)
            or isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {}
    exec(compile(ast.Module(body=body, type_ignores=[]), "<motion-matching-boundary>", "exec"), namespace)
    return namespace["plan_pose_replacement"]


def pose_pin(name, pin_id, direction, links):
    """/** @param name\t引脚名 @param pin_id\t标识 @param direction\t方向 @param links\t连线 @return 测试姿态引脚 */"""
    return {"name": name, "pinId": pin_id, "direction": direction, "kind": "pose",
            "typeObject": "/Script/Engine.PoseLink", "links": links}


class MotionMatchingBoundaryTests(unittest.TestCase):
    """/** 验证删除边界拒绝共享姿态 子图以及无关节点 */"""

    def setUp(self):
        """/** @return 建立最小既有姿态链 */"""
        self.plan = load_planner()
        self.snapshot = {"nodes": [
            {"guid": "SOURCE", "nodeClass": "/Script/AnimGraph.AnimGraphNode_SequencePlayer",
             "pins": [pose_pin("Pose", "SOURCE_POSE", "output", [{"nodeGuid": "TARGET", "pinId": "TARGET_POSE"}])]},
            {"guid": "TARGET", "nodeClass": "/Script/AnimGraph.AnimGraphNode_Root",
             "pins": [pose_pin("Result", "TARGET_POSE", "input", [{"nodeGuid": "SOURCE", "pinId": "SOURCE_POSE"}])]},
        ]}

    def invoke(self, removed=()):
        """/** @param removed\t明确删除范围 @return 边界计划 */"""
        return self.plan(self.snapshot, "SOURCE", "Pose", "TARGET", "Result", removed)

    def test_preview_does_not_change_snapshot(self):
        """/** @return 有效计划不改变来源快照 */"""
        before = copy.deepcopy(self.snapshot)
        self.assertEqual(self.invoke()["removeNodeGuids"], ["SOURCE"])
        self.assertEqual(self.snapshot, before)

    def test_shared_source_is_rejected(self):
        """/** @return 禁止替换还有第二个使用者的姿态 */"""
        self.snapshot["nodes"][0]["pins"][0]["links"].append({"nodeGuid": "OTHER", "pinId": "OTHER_POSE"})
        with self.assertRaisesRegex(RuntimeError, "共享"):
            self.invoke()

    def test_unmapped_dependency_is_rejected(self):
        """/** @return 不允许留下旧源的上游计算节点 */"""
        self.snapshot["nodes"][0]["pins"].append({"name": "Time", "pinId": "SOURCE_TIME", "direction": "input",
            "kind": "data", "links": [{"nodeGuid": "VALUE", "pinId": "VALUE_OUT"}]})
        self.snapshot["nodes"].append({"guid": "VALUE", "nodeClass": "/Script/BlueprintGraph.K2Node_VariableGet",
            "pins": [{"name": "Time", "pinId": "VALUE_OUT", "direction": "output", "kind": "data",
                      "links": [{"nodeGuid": "SOURCE", "pinId": "SOURCE_TIME"}]}]})
        with self.assertRaisesRegex(RuntimeError, "未授权边界"):
            self.invoke()
        self.assertEqual(self.invoke(["SOURCE", "VALUE"])["removeNodeGuids"], ["SOURCE", "VALUE"])

    def test_unrelated_deletion_is_rejected(self):
        """/** @return 禁止顺带删除不属于姿态源的节点 */"""
        self.snapshot["nodes"].append({"guid": "OTHER", "nodeClass": "/Script/BlueprintGraph.K2Node_VariableGet", "pins": []})
        with self.assertRaisesRegex(RuntimeError, "无关"):
            self.invoke(["SOURCE", "OTHER"])

    def test_nested_state_machine_is_rejected(self):
        """/** @return 禁止把完整状态机当普通节点删除 */"""
        self.snapshot["nodes"][0]["boundGraph"] = "LocomotionSM"
        with self.assertRaisesRegex(RuntimeError, "子图"):
            self.invoke()

    def test_cached_pose_source_is_rejected(self):
        """/** @return 禁止隐藏的跨图缓存依赖被删除 */"""
        self.snapshot["nodes"][0]["nodeClass"] = "/Script/AnimGraph.AnimGraphNode_UseCachedPose"
        with self.assertRaisesRegex(RuntimeError, "共享姿态缓存"):
            self.invoke()

    def test_component_pose_boundary_is_rejected(self):
        """/** @return 不允许插入隐含姿态空间转换 */"""
        self.snapshot["nodes"][0]["pins"][0]["typeObject"] = "/Script/Engine.ComponentSpacePoseLink"
        with self.assertRaisesRegex(RuntimeError, "本地空间"):
            self.invoke()

    def test_repeated_mm_construction_is_rejected(self):
        """/** @return 重复执行无法生成第二个 MM 节点 */"""
        self.snapshot["nodes"][0]["nodeClass"] = "/Script/PoseSearchEditor.AnimGraphNode_MotionMatching"
        with self.assertRaisesRegex(RuntimeError, "重复构造"):
            self.invoke()

    def test_duplicate_guid_is_rejected(self):
        """/** @return 不接受有歧义的节点标识 */"""
        self.snapshot["nodes"].append(copy.deepcopy(self.snapshot["nodes"][0]))
        with self.assertRaisesRegex(RuntimeError, "重复节点"):
            self.invoke()

    def test_downstream_deletion_is_rejected(self):
        """/** @return 删除范围必须保留下游处理链 */"""
        with self.assertRaisesRegex(RuntimeError, "保留下游"):
            self.invoke(["SOURCE", "TARGET"])

    def test_cross_graph_link_is_rejected(self):
        """/** @return 拒绝快照之外的链接目标 */"""
        self.snapshot["nodes"][0]["pins"].append({"name": "Time", "pinId": "TIME", "direction": "input",
            "kind": "data", "links": [{"nodeGuid": "OUTSIDE", "pinId": "TIME"}]})
        with self.assertRaisesRegex(RuntimeError, "跨图"):
            self.invoke()




if __name__ == "__main__":
    unittest.main()
