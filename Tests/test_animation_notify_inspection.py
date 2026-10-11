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


if __name__ == "__main__":
    unittest.main()
