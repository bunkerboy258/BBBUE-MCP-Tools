import ast
import copy
import json
from pathlib import Path
import random
import sys
import types
import unittest
from unittest.mock import patch


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))
from BBBBlueprintLayout import calculate_layout, layout_quality, _clear_wire_obstacles, _wire_points


def _node(key, execution=False, x=0, y=0, width=180, height=80):
    """/** @return 可独立测试的节点尺寸快照 */"""
    return {"id": key, "exec": execution, "x": x, "y": y, "width": width, "height": height}


def _edge(source, target, kind="data", source_order=0, target_order=0):
    """/** @return 带原始引脚顺序的连接快照 */"""
    return {"source": source, "target": target, "kind": kind, "sourceOrder": source_order, "targetOrder": target_order}


class BlueprintLayoutTests(unittest.TestCase):
    """/** 执行主链 数据依赖与固定分组回归检查 */"""

    def check_plan(self, nodes, edges, comments=None):
        """/** @return 无重叠且重复计算稳定的布局 */"""
        comments = comments or []
        baseline = copy.deepcopy((nodes, edges, comments))
        plan = calculate_layout(nodes, edges, comments)
        self.assertEqual(plan["after"]["overlaps"], 0)
        self.assertEqual((nodes, edges, comments), baseline)
        next_nodes = copy.deepcopy(nodes)
        for key, (x, y) in plan["positions"].items():
            next_nodes[key]["x"] = x
            next_nodes[key]["y"] = y

        repeated = calculate_layout(next_nodes, edges, comments)
        self.assertEqual(plan["positions"], repeated["positions"])
        return plan

    def test_execution_chain_is_horizontal(self):
        """/** @return 纯节点不拉歪执行主链 */"""
        nodes = {key: _node(key, key in "ABC", x=index * 1500, y=index * 700) for index, key in enumerate("ABCXYZ")}
        edges = [_edge("A", "B", "exec"), _edge("B", "C", "exec"), _edge("X", "Y"), _edge("Y", "B"), _edge("Z", "C")]
        plan = self.check_plan(nodes, edges)
        positions = plan["positions"]
        self.assertEqual(positions["A"][1], positions["B"][1])
        self.assertEqual(positions["B"][1], positions["C"][1])
        self.assertLess(positions["X"][0], positions["Y"][0])
        self.assertLess(positions["Y"][0], positions["B"][0])
        self.assertLess(positions["Z"][0], positions["C"][0])
        self.assertLess(plan["after"]["width"], plan["before"]["width"])

    def test_pose_chain_aligns_measured_pin_anchors(self):
        """/** @return 姿势链按真实引脚高度对齐而非按节点顶部对齐 */"""
        nodes = {key: _node(key, height=height) for key, height in (("Input", 80), ("IK", 240), ("Output", 180), ("Value", 60))}
        for key, anchor in (("Input", 30), ("IK", 65), ("Output", 110)):
            nodes[key]["pose"] = True
            nodes[key]["primaryOffset"] = anchor

        edges = [_edge("Input", "IK", "pose"), _edge("IK", "Output", "pose"), _edge("Value", "IK")]
        for edge in edges[:2]:
            edge["sourceOffset"] = (nodes[edge["source"]]["width"], nodes[edge["source"]]["primaryOffset"])
            edge["targetOffset"] = (0, nodes[edge["target"]]["primaryOffset"])

        plan = self.check_plan(nodes, edges)
        self.assertEqual(len({plan["positions"][key][1] + nodes[key]["primaryOffset"] for key in ("Input", "IK", "Output")}), 1)
        self.assertEqual(plan["after"]["backwardPoseEdges"], 0)
        self.assertEqual(plan["after"]["wireNodeIntersections"], 0)

    def test_measured_wire_blocker_is_moved_without_changing_main_chain(self):
        """/** @return 引脚高度而非节点中心决定穿线 辅助阻挡可被移开 */"""
        nodes = {"A": _node("A", True, width=100, height=200), "B": _node("B", True, width=100, height=200), "Blocker": _node("Blocker", width=80, height=40)}
        positions = {"A": (0, 0), "B": (500, 0), "Blocker": (250, 10)}
        edge = _edge("A", "B", "exec")
        edge.update(sourceOffset=(100, 30), targetOffset=(0, 30))
        self.assertEqual(layout_quality(nodes, [edge], positions)["wireNodeIntersections"], 1)
        original = copy.deepcopy((nodes, edge, positions))
        result = _clear_wire_obstacles(nodes, [edge], positions, {"Blocker": (-1000, 1000, [])})
        self.assertEqual(layout_quality(nodes, [edge], result)["wireNodeIntersections"], 0)
        self.assertEqual(result["A"], positions["A"])
        self.assertEqual(result["B"], positions["B"])
        self.assertEqual((nodes, edge, positions), original)

    def test_collinear_backward_curve_keeps_overshoot(self):
        """/** @return 共线回流曲线不能退化为端点间直线而漏掉外伸部分 */"""
        nodes = {key: _node(key, width=100, height=80) for key in ("A", "B")}
        edge = _edge("A", "B")
        edge["spline"] = {"backwardhorizontalTangent": (10, 0)}
        points = _wire_points(nodes, edge, {"A": (100, 0), "B": (0, 0)})
        self.assertGreater(max(point[0] for point in points), 200)
        self.assertLess(min(point[0] for point in points), 0)

    def test_branch_order_and_merge(self):
        """/** @return 分支保持引脚顺序 汇合位于分支之后 */"""
        nodes = {key: _node(key, True) for key in ("A", "ZTrue", "BFalse", "M")}
        edges = [
            _edge("A", "ZTrue", "exec", 0),
            _edge("A", "BFalse", "exec", 1),
            _edge("ZTrue", "M", "exec"),
            _edge("BFalse", "M", "exec"),
        ]
        positions = self.check_plan(nodes, edges)["positions"]
        self.assertLess(positions["ZTrue"][1], positions["BFalse"][1])
        self.assertGreater(positions["M"][0], positions["ZTrue"][0])
        self.assertGreater(positions["M"][0], positions["BFalse"][0])

    def test_shared_data_node_is_not_duplicated(self):
        """/** @return 共享数据保持一份并位于所有消费者左侧 */"""
        nodes = {key: _node(key, key != "Shared") for key in ("A", "B", "C", "Shared")}
        edges = [_edge("A", "B", "exec"), _edge("B", "C", "exec"), _edge("Shared", "B"), _edge("Shared", "C")]
        positions = self.check_plan(nodes, edges)["positions"]
        self.assertEqual(set(positions), set(nodes))
        self.assertLess(positions["Shared"][0], positions["B"][0])
        self.assertLess(positions["Shared"][0], positions["C"][0])

    def test_pure_data_chain(self):
        """/** @return 无执行线时输入计算输出仍从左到右 */"""
        nodes = {key: _node(key) for key in ("Input", "Compute", "Output")}
        edges = [_edge("Input", "Compute"), _edge("Compute", "Output")]
        plan = self.check_plan(nodes, edges)
        self.assertEqual(len({position[1] for position in plan["positions"].values()}), 1)
        self.assertEqual(plan["after"]["backwardDataEdges"], 0)

    def test_input_pin_order(self):
        """/** @return 同列输入遵循目标引脚顺序而非名称顺序 */"""
        nodes = {key: _node(key) for key in ("ZFirst", "ASecond", "Output")}
        edges = [_edge("ZFirst", "Output", target_order=0), _edge("ASecond", "Output", target_order=1)]
        positions = self.check_plan(nodes, edges)["positions"]
        self.assertLess(positions["ZFirst"][1], positions["ASecond"][1])

    def test_disconnected_components_are_packed(self):
        """/** @return 独立链左对齐 原画布散布不决定新位置 */"""
        nodes = {key: _node(key, True, x=index * 5000, y=index * 4000) for index, key in enumerate("ABCD")}
        edges = [_edge("A", "B", "exec"), _edge("C", "D", "exec")]
        plan = self.check_plan(nodes, edges)
        self.assertEqual(plan["components"], 2)
        self.assertEqual(plan["positions"]["A"][0], plan["positions"]["C"][0])
        self.assertGreater(plan["positions"]["C"][1], plan["positions"]["A"][1])

    def test_cycle_keeps_real_edges(self):
        """/** @return 环路只产生视觉回流 不删真实边 */"""
        nodes = {key: _node(key, True) for key in "ABC"}
        edges = [_edge("A", "B", "exec"), _edge("B", "C", "exec"), _edge("C", "A", "exec")]
        plan = self.check_plan(nodes, edges)
        self.assertEqual(plan["cycleBreaks"], 1)
        self.assertEqual(plan["after"]["backwardExecEdges"], 1)
        self.assertTrue(plan["warnings"])

    def test_large_node_dimensions(self):
        """/** @return 宽节点提高必要步距 不将步距重复作为留白 */"""
        nodes = {"A": _node("A", True, width=800), "B": _node("B", True, height=700)}
        plan = self.check_plan(nodes, [_edge("A", "B", "exec")])
        self.assertEqual(plan["positions"]["B"][0] - plan["positions"]["A"][0], 864)

    def test_comment_members_stay_inside(self):
        """/** @return 固定注释框内部重排不搬出成员 */"""
        nodes = {"A": _node("A", True, 100, 100), "B": _node("B", True, 500, 200), "Outside": _node("Outside", True, 2000, 2000)}
        comments = [_node("Comment", False, 0, 0, 1200, 800)]
        plan = self.check_plan(nodes, [_edge("A", "B", "exec")], comments)
        self.assertEqual(plan["commentMembers"], 2)
        for key in ("A", "B"):
            x, y = plan["positions"][key]
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + nodes[key]["width"], 1200)
            self.assertLessEqual(y + nodes[key]["height"], 800)

    def test_small_comment_preserves_original(self):
        """/** @return 放不下新布局时保留分组原位并报警 */"""
        nodes = {"A": _node("A", True, 20, 80, 100, 40), "B": _node("B", True, 180, 80, 100, 40)}
        comments = [_node("Comment", False, 0, 0, 300, 160)]
        plan = self.check_plan(nodes, [_edge("A", "B", "exec")], comments)
        self.assertEqual(plan["positions"], {"A": (20, 80), "B": (180, 80)})
        self.assertTrue(plan["warnings"])

    def test_nested_comments_preserve_members(self):
        """/** @return 嵌套注释不猜测成员归属 */"""
        nodes = {"A": _node("A", True, 100, 120)}
        comments = [_node("Outer", False, 0, 0, 1000, 800), _node("Inner", False, 80, 80, 500, 400)]
        plan = self.check_plan(nodes, [], comments)
        self.assertEqual(plan["positions"]["A"], (100, 120))
        self.assertTrue(plan["warnings"])

    def test_empty_graph(self):
        """/** @return 空图返回有效空计划 */"""
        self.assertEqual(self.check_plan({}, [])["positions"], {})

    def test_fixed_comment_never_reverses_external_flow(self):
        """/** @return 跨固定注释框连线不被局部分组排成回流 */"""
        for kind in ("exec", "data"):
            nodes = {"A": _node("A", kind == "exec", 500, 80, 100, 40), "B": _node("B", True, 700, 80, 100, 40)}
            comments = [_node("Comment", False, 0, 0, 300, 200)]
            comments[0]["members"] = ["B"]
            plan = self.check_plan(nodes, [_edge("A", "B", kind)], comments)
            self.assertEqual(plan["positions"], {"A": (500, 80), "B": (700, 80)})
            self.assertTrue(any("整条连通链" in warning for warning in plan["warnings"]))

    def test_native_comment_membership_protects_estimated_bounds(self):
        """/** @return 原生归属优先保护尺寸估算后超出框的节点 */"""
        nodes = {"A": _node("A", True, 20, 80, 500, 80)}
        comment = _node("Comment", False, 0, 0, 300, 200)
        comment["members"] = ["A"]
        plan = self.check_plan(nodes, [], [comment])
        self.assertEqual(plan["positions"]["A"], (20, 80))
        self.assertEqual(plan["commentMembers"], 1)
        self.assertTrue(plan["warnings"])

    def test_unconnected_nodes_stay_near_fixed_comments(self):
        """/** @return 无连线节点不因远处注释框被推到画布底部 */"""
        nodes = {"A": _node("A", True, 0, -200)}
        comments = [_node("Comment", False, 0, 0, 1200, 1800)]
        plan = self.check_plan(nodes, [], comments)
        self.assertEqual(plan["positions"]["A"], (0, -200))

    def test_random_acyclic_graphs_are_stable(self):
        """/** @return 混合分支与共享依赖保持前向 无重叠且稳定 */"""
        generator = random.Random(4721)
        for attempt in range(30):
            keys = [str(index).zfill(3) for index in range(35)]
            nodes = {
                key: _node(key, index % 3 == 0, generator.randrange(-3000, 3000), generator.randrange(-3000, 3000), generator.randrange(80, 600), generator.randrange(40, 300))
                for index, key in enumerate(keys)
            }
            edges = []
            for index, source in enumerate(keys):
                for target in keys[index + 1:]:
                    if generator.random() > 0.08:
                        continue

                    kind = "data"
                    if nodes[source]["exec"] and nodes[target]["exec"]:
                        kind = "exec"

                    edges.append(_edge(source, target, kind, len(edges) % 3))

            with self.subTest(attempt=attempt):
                plan = self.check_plan(nodes, edges)
                self.assertEqual(plan["after"]["backwardExecEdges"], 0)
                self.assertEqual(plan["after"]["backwardDataEdges"], 0)


class LayoutCaptureTests(unittest.TestCase):
    """/** 官方查询与原生引脚快照适配器检查 */"""

    def test_captures_comments_without_protected_graph_properties(self):
        """/** @return 注释框不漏查 执行类型不依赖本地化文字 */"""
        class Node:
            """/** 原生节点接口替身 */"""
            def __init__(instance, name, comment=False):
                instance.name = name
                instance.comment = comment
                instance.pins = []

            def get_path_name(instance):
                return instance.name

            def get_class(instance):
                return types.SimpleNamespace(get_name=lambda: "EdGraphNode_Comment" if instance.comment else "K2Node_CallFunction")

            def get_node_size(instance):
                return types.SimpleNamespace(x=500, y=400)

            def get_editor_property(instance, name):
                raise AssertionError("不允许读取受保护节点属性")

            def list_all_pins(instance):
                return instance.pins

        class Pin:
            """/** 原生引脚接口替身 */"""
            def __init__(instance, owner, output):
                instance.owner = owner
                instance.output = output
                instance.connected = []
                owner.pins.append(instance)

            def get_pin_type(instance):
                return types.SimpleNamespace(get_editor_property=lambda name: "exec")

            def get_pin_direction(instance):
                return "Output" if instance.output else "Input"

            def list_connected_pins(instance):
                return instance.connected

            def get_owning_node(instance):
                return instance.owner

            def is_same_native_pin(instance, other):
                return instance is other

            def get_pin_name(instance):
                return "then" if instance.output else "execute"

        first = Node("A")
        second = Node("B")
        comment = Node("Comment", True)
        source_pin = Pin(first, True)
        target_pin = Pin(second, False)
        source_pin.connected.append(target_pin)
        target_pin.connected.append(source_pin)
        editor = types.SimpleNamespace(list_all_nodes=lambda: [first, second], list_comment_nodes=lambda: [comment])
        geometry = {
            "graph": "/Game/Test.Test:Graph",
            "nodes": [
                {
                    "path": node.name, "x": 10, "y": 20, "width": 500, "height": 400,
                    "comment": node.comment, "estimated": False, "members": [],
                    "executionPins": ["output:then"] if node is first else ["input:execute"],
                    "pins": [] if node.comment else [{"direction": "output" if node is first else "input", "name": "then" if node is first else "execute", "kind": "exec", "x": 500 if node is first else 0, "y": 40}],
                }
                for node in (first, second, comment)
            ],
        }
        geometry["spline"] = {}
        fake = types.SimpleNamespace(
            K2Node=Node,
            BBBBlueprintEditorLibrary=types.SimpleNamespace(measure_blueprint_graph_visual_geometry=lambda graph: json.dumps(geometry)),
            BlueprintGraphEditor=types.SimpleNamespace(get_graph_editor=lambda graph: editor),
            EdGraphPinDirection=types.SimpleNamespace(EGPD_OUTPUT="Output"),
        )
        source = ast.parse((ROOT / "Scripts/BBBBlueprintGraphToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "_capture_layout_graph")
        environment = {"unreal": fake, "json": json}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "layout_capture", "exec"), environment)
        graph = types.SimpleNamespace(get_path_name=lambda: "/Game/Test.Test:Graph")
        objects, nodes, edges, comments, estimated = environment["_capture_layout_graph"](graph)
        self.assertEqual(set(objects), {"A", "B"})
        self.assertTrue(all(node["exec"] for node in nodes.values()))
        self.assertEqual(edges[0]["kind"], "exec")
        self.assertEqual(comments[0]["id"], "Comment")
        self.assertEqual(estimated, [])

        fake.BBBBlueprintEditorLibrary.measure_blueprint_graph_visual_geometry = lambda graph: '{"error":"几何检查失败"}'
        with self.assertRaisesRegex(RuntimeError, "几何检查失败"):
            environment["_capture_layout_graph"](graph)

        fake.BBBBlueprintEditorLibrary.measure_blueprint_graph_visual_geometry = None
        with self.assertRaisesRegex(RuntimeError, "请编译"):
            environment["_capture_layout_graph"](graph)


class LayoutToolSafetyTests(unittest.TestCase):
    """/** 工具入口的只读预览与坐标写入安全检查 */"""

    def setUp(self):
        """/** @return 不加载真实编辑器的最小方法执行环境 */"""
        self.events = []
        self.node = types.SimpleNamespace(
            modify=lambda: self.events.append("node_modify"),
            set_node_pos=lambda point: self.events.append(("move", point.x, point.y)),
        )
        class Blueprint:
            """/** 蓝图类型替身 */"""
            def modify(instance):
                self.events.append("blueprint_modify")

        self.blueprint = Blueprint()
        class Graph:
            """/** 图表类型替身 */"""
            def get_outer(instance):
                return self.blueprint

            def modify(instance):
                self.events.append("graph_modify")

            def notify_graph_changed(instance):
                self.events.append("notify")

        self.graph = Graph()
        self.snapshot = ({"A": self.node}, {"A": _node("A", True, 100, 100)}, [], [], [])
        class Transaction:
            """/** 事务类型替身 */"""
            def __init__(instance, name):
                self.events.append("transaction")

            def __enter__(instance):
                return instance

            def __exit__(instance, *args):
                return False

        fake = types.SimpleNamespace(
            EdGraph=Graph,
            Blueprint=Blueprint,
            load_object=lambda outer, path: self.graph,
            EditorLevelLibrary=types.SimpleNamespace(get_pie_worlds=lambda flag: []),
            log=self.events.append,
            log_warning=self.events.append,
            log_error=self.events.append,
            ScopedEditorTransaction=Transaction,
            IntPoint=lambda x, y: types.SimpleNamespace(x=x, y=y),
        )
        source = ast.parse((ROOT / "Scripts/BBBBlueprintGraphToolset.py").read_text(encoding="utf-8-sig"))
        definition = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "BBBBlueprintGraphToolset")
        method = next(node for node in definition.body if isinstance(node, ast.FunctionDef) and node.name == "optimize_blueprint_node_layout")
        method.decorator_list = []
        self.environment = {
            "unreal": fake,
            "json": json,
            "_capture_layout_graph": lambda graph: (
                self.snapshot[0], copy.deepcopy(self.snapshot[1]),
                copy.deepcopy(self.snapshot[2]), copy.deepcopy(self.snapshot[3]), self.snapshot[4],
            ),
            "_require_layout_checkout": lambda blueprint: self.events.append("checkout"),
        }
        exec(compile(ast.Module(body=[method], type_ignores=[]), "layout_method", "exec"), self.environment)
        self.call = self.environment["optimize_blueprint_node_layout"]

    def test_dry_run_never_writes_or_checks_out(self):
        """/** @return 预览无事务 无坐标写入 无源控写入 */"""
        result = json.loads(self.call("/Game/Test.Test:Graph", dry_run=True))
        self.assertTrue(result["dryRun"])
        self.assertEqual(result["moved"], 0)
        self.assertNotIn("transaction", self.events)
        self.assertNotIn("checkout", self.events)

    def test_invalid_spacing_and_path_rejected(self):
        """/** @return 非整数 布尔伪整数与越界输入被拒绝 */"""
        for spacing in (True, 1.5, "320", 0, -1, 10001):
            with self.assertRaises(RuntimeError):
                self.call("/Game/Test.Test:Graph", horizontal_spacing=spacing, dry_run=True)

        with self.assertRaises(RuntimeError):
            self.call("/Engine/Test.Test:Graph", dry_run=True)

    def test_pie_rejected(self):
        """/** @return PIE 期间不读取或移动节点 */"""
        self.environment["unreal"].EditorLevelLibrary.get_pie_worlds = lambda flag: [object()]
        with self.assertRaisesRegex(RuntimeError, "PIE"):
            self.call("/Game/Test.Test:Graph", dry_run=True)

    def test_unresolved_wire_hit_rejected_before_checkout(self):
        """/** @return 未解穿节点问题在签出检查和坐标事务之前拒绝 */"""
        plan = calculate_layout(self.snapshot[1], [], [])
        plan["positions"]["A"] = (200, 200)
        plan["after"]["wireNodeIntersections"] = 1
        with patch("BBBBlueprintLayout.calculate_layout", return_value=plan):
            with self.assertRaisesRegex(RuntimeError, "连线穿过节点"):
                self.call("/Game/Test.Test:Graph")

        self.assertNotIn("checkout", self.events)
        self.assertNotIn("transaction", self.events)
        self.assertFalse(any(isinstance(event, tuple) for event in self.events))

    def test_checkout_failure_precedes_transaction(self):
        """/** @return 未签出时任何节点都不移动 */"""
        self.snapshot = (
            {"A": self.node, "B": self.node},
            {"A": _node("A", True), "B": _node("B", True, 1000, 1000)},
            [_edge("A", "B", "exec")], [], [],
        )
        def reject(blueprint):
            """/** @return 明确模拟未签出错误 */"""
            raise RuntimeError("未签出")

        self.environment["_require_layout_checkout"] = reject
        with self.assertRaisesRegex(RuntimeError, "未签出"):
            self.call("/Game/Test.Test:Graph")

        self.assertNotIn("transaction", self.events)
        self.assertFalse(any(isinstance(event, tuple) for event in self.events))

    def test_readback_failure_restores_coordinates(self):
        """/** @return 回读不符时恢复本次坐标并明确失败 */"""
        self.snapshot = (
            {"A": self.node, "B": self.node},
            {"A": _node("A", True), "B": _node("B", True, 1000, 1000)},
            [_edge("A", "B", "exec")], [], [],
        )
        with self.assertRaisesRegex(RuntimeError, "回读不符"):
            self.call("/Game/Test.Test:Graph")

        self.assertIn("node_modify", self.events)
        self.assertIn(("move", 1000, 1000), self.events)
        self.assertIn("notify", self.events)

    def test_success_changes_only_coordinates_without_save(self):
        """/** @return 写入回读通过 不修改连线 不调用保存 */"""
        nodes = {"A": _node("A", True), "B": _node("B", True, 1000, 1000)}
        def move(point):
            """/** @return 更新替身实际坐标 */"""
            nodes["B"]["x"] = point.x
            nodes["B"]["y"] = point.y
            self.events.append(("move", point.x, point.y))

        self.node.set_node_pos = move
        self.snapshot = (
            {"A": self.node, "B": self.node}, nodes,
            [_edge("A", "B", "exec")], [], [],
        )
        result = json.loads(self.call("/Game/Test.Test:Graph"))
        self.assertEqual(result["moved"], 1)
        self.assertFalse(result["saved"])
        self.assertIn("checkout", self.events)
        self.assertEqual((nodes["B"]["x"], nodes["B"]["y"]), (320, 0))


class AnnotationBlockLayoutTests(unittest.TestCase):
    """/** 新区块整体布局与原有框约束测试 */"""

    def test_connected_blocks_keep_main_flow_and_shared_data(self):
        """/** @return 区块之间主链前向 共享数据节点保持一份 */"""
        from BBBBlueprintLayout import calculate_annotation_layout

        nodes = {key: _node(key, key != "Shared") for key in ("A", "B", "Shared")}
        edges = [_edge("A", "B", "exec"), _edge("Shared", "A"), _edge("Shared", "B")]
        blocks = [
            {"id": "First", "members": ["A"], "headerWidth": 100, "headerHeight": 30},
            {"id": "Second", "members": ["B"], "headerWidth": 100, "headerHeight": 30},
        ]
        result = calculate_annotation_layout(nodes, edges, [], blocks)
        self.assertEqual(set(result["positions"]), set(nodes))
        self.assertLess(result["positions"]["Shared"][0], result["positions"]["A"][0])
        self.assertLess(result["positions"]["A"][0], result["positions"]["B"][0])
        self.assertEqual(result["blockConflicts"], [])
        self.assertEqual(result["after"]["overlaps"], 0)

    def test_existing_frame_and_members_stay_fixed(self):
        """/** @return 新区块布局不能移动原有注释成员 */"""
        from BBBBlueprintLayout import calculate_annotation_layout

        nodes = {"A": _node("A", True, 32, 64), "B": _node("B", True, 1000, 1000)}
        comments = [{"id": "Fixed", "x": 0, "y": 0, "width": 400, "height": 300, "members": ["A"]}]
        blocks = [{"id": "New", "members": ["B"], "headerWidth": 100, "headerHeight": 30}]
        result = calculate_annotation_layout(nodes, [], comments, blocks)
        self.assertEqual(result["positions"]["A"], (32, 64))
        self.assertEqual(result["blockConflicts"], [])


if __name__ == "__main__":
    unittest.main()
