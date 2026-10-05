import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
import types
import unittest


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))
from BBBBlueprintAnnotations import prepare_annotations, plan_annotations, layout_inputs


def _fixture():
    """/** @return 含真实引脚连接形状的隔离语义与测量快照 */"""
    nodes = []
    measured = []
    for key, x in (("A", 0), ("B", 1000)):
        output = key == "A"
        pin = {
            "pinId": key + "Pin", "name": "then" if output else "execute",
            "direction": "output" if output else "input", "kind": "exec",
            "links": [{"nodeGuid": "B" if output else "A", "pinId": "BPin" if output else "APin"}],
        }
        nodes.append({"guid": key, "path": key, "isComment": False, "x": x, "y": 0, "nodeComment": "", "pins": [pin]})
        measured.append({"guid": key, "width": 180, "height": 80, "visualBounds": [0, 0, 180, 80], "pins": [dict(pin, x=180 if output else 0, y=40)]})

    return {"snapshot": "original", "nodes": nodes, "layoutSupported": True, "warnings": []}, {"nodes": measured, "blocks": [{"headerWidth": 260, "headerHeight": 40}], "spline": {}}


def _request(snapshot, blocks=True):
    """
    /**
     * @param snapshot	目标语义快照
     * @param blocks	是否请求新区块
     * @return 完整外部请求
     */
    """
    return {
        "expectedSnapshot": snapshot["snapshot"],
        "blocks": [{"title": "更新逻辑", "description": "读取输入并更新结果", "members": ["A", "B"]}] if blocks else [],
        "nodeComments": [{"nodeGuid": "A", "text": "检查输入条件"}],
    }


class AnnotationRequestTests(unittest.TestCase):
    """/** 外部方案的身份及已有注释保护测试 */"""

    def setUp(self):
        """/** @return 创建独立快照与请求 */"""
        self.snapshot, self.measurement = _fixture()
        self.request = _request(self.snapshot)

    def prepare(self):
        """/** @return 校验当前请求 */"""
        return prepare_annotations(self.snapshot, json.dumps(self.request, ensure_ascii=False))

    def test_stale_snapshot_rejected(self):
        """/** @return 分析后图表变化必须拒绝 */"""
        self.request["expectedSnapshot"] = "stale"
        with self.assertRaisesRegex(RuntimeError, "快照已变化"):
            self.prepare()

    def test_existing_node_text_never_overwritten(self):
        """/** @return 已有正文必须拒绝覆盖 */"""
        self.snapshot["nodes"][0]["nodeComment"] = "原有说明"
        with self.assertRaisesRegex(RuntimeError, "禁止覆盖"):
            self.prepare()

    def test_same_node_text_is_noop(self):
        """/** @return 同正文重复执行不会产生写入 */"""
        self.request["blocks"] = []
        self.snapshot["nodes"][0]["nodeComment"] = "检查输入条件"
        result = self.prepare()
        self.assertEqual(result["nodeComments"], [])
        self.assertEqual(result["skipped"], [{"kind": "node", "guid": "A"}])

    def test_shared_node_cannot_have_two_owners(self):
        """/** @return 区块重复认领共享节点必须拒绝 */"""
        self.request["blocks"].append({"title": "第二分组", "description": "", "members": ["B"]})
        with self.assertRaisesRegex(RuntimeError, "共享节点"):
            self.prepare()

    def test_missing_and_duplicate_targets_rejected(self):
        """/** @return 节点和成员身份错误不会进入测量 */"""
        for field, value in (("members", ["Unknown"]), ("members", ["A", "A"])):
            with self.subTest(value=value):
                self.request["blocks"][0][field] = value
                with self.assertRaises(RuntimeError):
                    self.prepare()

        self.request["blocks"] = []
        self.request["nodeComments"] *= 2
        with self.assertRaisesRegex(RuntimeError, "重复"):
            self.prepare()

    def test_invalid_text_and_unknown_fields_rejected(self):
        """/** @return 正文及未知字段不静默接受 */"""
        for text in ("", "English only", "中文，逗号", "中文,逗号", "中文\x00字符", "中" * 2049):
            with self.subTest(text=text[:20]):
                self.request["nodeComments"][0]["text"] = text
                with self.assertRaises(RuntimeError):
                    self.prepare()

        self.request = _request(self.snapshot)
        self.request["overwrite"] = True
        with self.assertRaisesRegex(RuntimeError, "必须只包含"):
            self.prepare()

    def test_existing_block_match_is_noop_and_conflict_is_rejected(self):
        """/** @return 重复区块识别成功 不同正文不覆盖 */"""
        self.snapshot["nodes"].append({"guid": "C", "isComment": True, "members": ["B", "A"], "nodeComment": "更新逻辑", "details": "读取输入并更新结果"})
        result = self.prepare()
        self.assertEqual(result["blocks"], [])
        self.assertEqual(result["skipped"][0]["guid"], "C")
        self.request["blocks"][0]["title"] = "新标题"
        with self.assertRaisesRegex(RuntimeError, "已有注释框"):
            self.prepare()

    def test_inputs_not_mutated(self):
        """/** @return 请求与语义快照不会被校验修改 */"""
        before = deepcopy((self.snapshot, self.request))
        self.prepare()
        self.assertEqual(before, (self.snapshot, self.request))


class AnnotationLayoutTests(unittest.TestCase):
    """/** 注释显示边界与逻辑区块的联合排版测试 */"""

    def test_block_encloses_measured_bubble_and_body(self):
        """/** @return 气泡增加的空间参与框尺寸和坐标换算 */"""
        snapshot, measurement = _fixture()
        measurement["nodes"][0]["visualBounds"] = [-30, -100, 300, 80]
        before = deepcopy((snapshot, measurement))
        prepared = prepare_annotations(snapshot, json.dumps(_request(snapshot), ensure_ascii=False))
        plan = plan_annotations(snapshot, prepared, measurement)
        self.assertTrue(plan["canApply"], plan)
        block = plan["blocks"][0]
        x, y = plan["positions"]["A"]
        self.assertGreaterEqual(x - 30, block["x"] + 16)
        self.assertGreaterEqual(y - 100, block["y"] + 56)
        self.assertLessEqual(x + 300, block["x"] + block["width"] - 16)
        self.assertLessEqual(y + 80, block["y"] + block["height"] - 16)
        self.assertEqual(before, (snapshot, measurement))

    def test_preview_is_deterministic(self):
        """/** @return 同快照重复计算结果一致 */"""
        snapshot, measurement = _fixture()
        prepared = prepare_annotations(snapshot, json.dumps(_request(snapshot), ensure_ascii=False))
        self.assertEqual(plan_annotations(snapshot, prepared, measurement), plan_annotations(snapshot, prepared, measurement))

    def test_measurement_must_cover_all_original_nodes(self):
        """/** @return 不完整测量不能推算缺失节点 */"""
        snapshot, measurement = _fixture()
        measurement["nodes"].pop()
        with self.assertRaisesRegex(RuntimeError, "遗漏"):
            layout_inputs(snapshot, measurement)

    def test_bubble_outside_fixed_frame_is_reported(self):
        """/** @return 新气泡不能逃出已有固定框 */"""
        snapshot, measurement = _fixture()
        snapshot["nodes"].append({"guid": "C", "isComment": True, "x": -10, "y": -10, "members": ["A"], "nodeComment": "已有分组", "details": ""})
        measurement["nodes"].append({"guid": "C", "width": 200, "height": 120, "pins": []})
        measurement["nodes"][0]["visualBounds"] = [0, -100, 180, 80]
        request = _request(snapshot, False)
        prepared = prepare_annotations(snapshot, json.dumps(request, ensure_ascii=False))
        result = plan_annotations(snapshot, prepared, measurement)
        self.assertFalse(result["canApply"])
        self.assertTrue(any(item["reason"] == "固定框不能容纳显示边界" for item in result["blockConflicts"]))

    def test_connected_pin_anchor_required(self):
        """/** @return 连接引脚不能使用估算锚点 */"""
        snapshot, measurement = _fixture()
        measurement["nodes"][1]["pins"] = []
        with self.assertRaisesRegex(RuntimeError, "锚点"):
            layout_inputs(snapshot, measurement)


class AnnotationToolSafetyTests(unittest.TestCase):
    """/** MCP 包装层只读预览与失败顺序测试 */"""

    def setUp(self):
        """/** @return 通过真实方法构建最小编辑器替身 */"""
        self.snapshot, self.measurement = _fixture()
        self.events = []
        self.graph = types.SimpleNamespace(get_outer=lambda: "Blueprint")
        self.native = types.SimpleNamespace(
            measure_blueprint_graph_annotation_geometry=lambda *args: self.measure(),
            apply_blueprint_graph_annotations=lambda *args: self.apply(),
        )
        fake = types.SimpleNamespace(
            EditorLevelLibrary=types.SimpleNamespace(get_pie_worlds=lambda unused: []),
            load_object=lambda *args: self.graph,
            BBBBlueprintEditorLibrary=self.native,
            log=self.events.append, log_warning=self.events.append,
        )
        tree = ast.parse((ROOT / "Scripts/BBBBlueprintGraphToolset.py").read_text(encoding="utf-8-sig"))
        definition = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BBBBlueprintGraphToolset")
        method = next(node for node in definition.body if isinstance(node, ast.FunctionDef) and node.name == "annotate_blueprint_graph")
        method.decorator_list = []
        self.environment = {
            "unreal": fake, "json": json,
            "BBBBlueprintGraphToolset": types.SimpleNamespace(inspect_blueprint_graph=lambda path: json.dumps(self.snapshot)),
            "_require_layout_checkout": lambda blueprint: self.events.append("checkout"),
        }
        exec(compile(ast.Module(body=[method], type_ignores=[]), "annotation_tool", "exec"), self.environment)
        self.call = self.environment["annotate_blueprint_graph"]

    def measure(self):
        """/** @return 记录真实测量入口调用 */"""
        self.events.append("measure")
        return json.dumps(self.measurement)

    def apply(self):
        """/** @return 记录原生写入调用并模拟校验完成 */"""
        self.events.append("apply")
        return json.dumps({"changed": True, "createdBlocks": ["C"], "snapshot": "after"})

    def request(self):
        """/** @return 当前快照的外部方案 */"""
        return json.dumps(_request(self.snapshot), ensure_ascii=False)

    def test_preview_has_no_checkout_or_write(self):
        """/** @return 默认预览只测量和计算 */"""
        result = json.loads(self.call("/Game/Test.Test:Graph", self.request()))
        self.assertTrue(result["dryRun"])
        self.assertFalse(result["changed"])
        self.assertNotIn("checkout", self.events)
        self.assertNotIn("apply", self.events)

    def test_write_requires_checkout_before_native_apply(self):
        """/** @return 写入严格晚于签出检查 */"""
        result = json.loads(self.call("/Game/Test.Test:Graph", self.request(), False))
        self.assertTrue(result["changed"])
        self.assertLess(self.events.index("checkout"), self.events.index("apply"))

    def test_stale_and_measurement_failure_never_write(self):
        """/** @return 身份与测量失败都不启动写入 */"""
        request = _request(self.snapshot)
        request["expectedSnapshot"] = "stale"
        with self.assertRaisesRegex(RuntimeError, "快照已变化"):
            self.call("/Game/Test.Test:Graph", json.dumps(request), False)

        self.assertEqual(self.events, [])
        self.measurement = {"error": "测量异常"}
        with self.assertRaisesRegex(RuntimeError, "测量异常"):
            self.call("/Game/Test.Test:Graph", self.request(), False)

        self.assertNotIn("checkout", self.events)
        self.assertNotIn("apply", self.events)

    def test_repeated_request_never_measures_or_writes(self):
        """/** @return 已完成的相同节点正文不生成事务 */"""
        self.snapshot["nodes"][0]["nodeComment"] = "检查输入条件"
        request = _request(self.snapshot, False)
        result = json.loads(self.call("/Game/Test.Test:Graph", json.dumps(request), False))
        self.assertFalse(result["changed"])
        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main()
