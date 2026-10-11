import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest


class AnimationNotifyInspectionTests(unittest.TestCase):
    """/** 验证完整通知数组不被轨道缓存漏报 */"""

    def inspect(self, events, cached_events=None):
        """/** @return 不加载 UE 的真实检查函数输出 */"""
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBGenericEditorToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        function = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef)
                        and node.name == "inspect_animation_notifies")
        function.decorator_list = []
        asset_class = type("Asset", (), {"get_play_length": lambda self: 2.0})
        library = SimpleNamespace(
            get_animation_notify_track_names=lambda asset: ["Cases"],
            get_animation_notify_events=lambda asset: events,
            get_animation_notify_events_for_track=lambda asset, track: events if cached_events is None else cached_events,
            get_anim_notify_event_trigger_time=lambda event: 0.5,
            get_anim_notify_event_duration=lambda event: 0.01,
        )
        unreal = SimpleNamespace(
            AnimSequenceBase=asset_class,
            EditorAssetLibrary=SimpleNamespace(load_asset=lambda path: asset_class()),
            AnimationLibrary=library,
        )
        namespace = {"unreal": unreal, "json": json}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        return json.loads(namespace["inspect_animation_notifies"]("/Game/Test"))

    def event(self, index=0):
        """/** @return 同类同刻但独立的通知事件 */"""
        instance = SimpleNamespace(get_class=lambda: SimpleNamespace(get_path_name=lambda: "/Script/Test.Case"))
        values = {"track_index": index, "notify": None,
                  "notify_state_class": instance, "notify_name": "Case"}
        return SimpleNamespace(get_editor_property=lambda name: values[name])

    def test_same_track_same_time_preserves_all_six_instances(self):
        """/** @return 六枚退壳不会因缓存而漏报为一枚 */"""
        result = self.inspect([self.event() for _ in range(6)])
        self.assertEqual(len(result["events"]), 6)
        self.assertTrue(all(event["track"] == "Cases" for event in result["events"]))

    def test_incomplete_cache_does_not_omit_events_or_guess_tracks(self):
        """/** @return 缓存缺失时保留全部事件并明确未知轨道 */"""
        events = [self.event() for _ in range(6)]
        result = self.inspect(events, events[:1])
        self.assertEqual(len(result["events"]), 6)
        self.assertEqual(result["events"][0]["track"], "Cases")
        self.assertTrue(all(event["track"] is None for event in result["events"][1:]))


class AnimationNotifyPropertySelectionTests(unittest.TestCase):
    """/** 验证同类多实例通知属性选择不混淆变换 */"""

    def inspect(self, classes, match_index=-1):
        """/** @param classes 实例类型与位置 @param match_index 同类零基索引 @return 实际检查函数的输出 */"""
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBGenericEditorToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        function = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef)
                        and node.name == "inspect_animation_notify_properties")
        function.decorator_list = []
        events = []
        for index, class_path in enumerate(classes):
            instance = SimpleNamespace(
                get_class=lambda path=class_path: SimpleNamespace(get_path_name=lambda: path),
                get_path_name=lambda number=index: "Notify_" + str(number),
                get_editor_property=lambda name, number=index: [number, 2, 3],
            )
            event = SimpleNamespace(get_editor_property=lambda name, notify=instance:
                                    notify if name == "notify_state_class" else None)
            events.append(event)

        asset_class = type("Asset", (), {})
        unreal = SimpleNamespace(
            AnimSequenceBase=asset_class,
            Transform=type("Transform", (), {}),
            EditorAssetLibrary=SimpleNamespace(load_asset=lambda path: asset_class()),
            AnimationLibrary=SimpleNamespace(
                get_animation_notify_events=lambda asset: events,
                get_anim_notify_event_trigger_time=lambda event: 1.5,
                get_anim_notify_event_duration=lambda event: 0.5,
            ),
        )
        namespace = {"unreal": unreal, "json": json, "_serialize_value": lambda value: value}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        result = namespace["inspect_animation_notify_properties"](
            "/Game/Test", "/Script/Test.Held", ["AttachmentTransform"], match_index)
        return json.loads(result)

    def test_two_instances_keep_distinct_properties_and_identity(self):
        """/** @return 双弹通知分别返回自身位置与稳定实例身份 */"""
        classes = ["/Script/Test.Held", "/Script/Test.Held"]
        first = self.inspect(classes, 0)
        second = self.inspect(classes, 1)
        self.assertEqual(first["properties"]["AttachmentTransform"], [0, 2, 3])
        self.assertEqual(second["properties"]["AttachmentTransform"], [1, 2, 3])
        self.assertEqual(second["instance"], "Notify_1")
        self.assertEqual(second["matchCount"], 2)
        self.assertEqual(second["time"], 1.5)
        self.assertEqual(second["duration"], 0.5)

    def test_index_is_relative_to_matching_class(self):
        """/** @return 其它通知不会占用目标类型的实例索引 */"""
        result = self.inspect(["/Script/Test.Other", "/Script/Test.Held", "/Script/Test.Held"], 1)
        self.assertEqual(result["instance"], "Notify_2")
        self.assertEqual(result["matchIndex"], 1)

    def test_default_accepts_only_unambiguous_instance(self):
        """/** @return 未指定索引时禁止猜测多实例目标 */"""
        self.assertEqual(self.inspect(["/Script/Test.Held"])["matchCount"], 1)
        with self.assertRaises(RuntimeError):
            self.inspect(["/Script/Test.Held", "/Script/Test.Held"])

    def test_invalid_or_missing_match_fails(self):
        """/** @return 缺少匹配或索引越界时明确失败 */"""
        for classes, index in [([], -1), ([], 0), (["/Script/Test.Held"], -2),
                               (["/Script/Test.Held"], 1)]:
            with self.subTest(classes=classes, index=index), self.assertRaises(RuntimeError):
                self.inspect(classes, index)


if __name__ == "__main__":
    unittest.main()
