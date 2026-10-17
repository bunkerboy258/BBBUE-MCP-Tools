import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HandRetargetMetadataTests(unittest.TestCase):
    """/** 验证复制动画后的通知身份及加法参考约束 */"""

    def setUp(self):
        """/** @return 提取元数据校验函数及最小引擎替身 */"""
        source = ROOT / "Scripts/BBBHandRetargetBatchToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        names = {"_notify_signature", "_validate_additive_reference", "_set_component_keys"}
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.namespace = {"unreal": SimpleNamespace(
            AdditiveAnimationType=SimpleNamespace(AAT_NONE=0, AAT_LOCAL_SPACE_BASE=1),
            AdditiveBasePoseType=SimpleNamespace(ABPT_LOCAL_ANIM_FRAME=4, ABPT_ANIM_FRAME=3),
            MovieSceneTimeUnit=SimpleNamespace(DISPLAY_RATE=0),
            MovieSceneKeyInterpolation=SimpleNamespace(LINEAR=1),
            AnimationLibrary=SimpleNamespace(
                get_animation_notify_events=lambda animation: animation,
                get_anim_notify_event_trigger_time=lambda event: 0.5,
                get_anim_notify_event_duration=lambda event: 0.25,
            ),
        ), "_frame_count": lambda source: (29, None),
            "authoring": SimpleNamespace(_key=lambda name, kind: name)}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), self.namespace)

    def test_notify_state_copy_keeps_identity_without_instance_path(self):
        """/** @return 同类同时间的复制通知不因包路径变化误报 */"""
        signatures = []
        for path in ("/Source:Notify_0", "/Output:Notify_0"):
            state = SimpleNamespace(
                get_path_name=lambda value=path: value,
                get_class=lambda: SimpleNamespace(get_path_name=lambda: "/Script/Test.NotifyState"),
            )
            values = {"notify": None, "notify_state_class": state, "notify_name": "FootPlant"}
            event = SimpleNamespace(get_editor_property=values.__getitem__)
            signatures.append(self.namespace["_notify_signature"]([event]))
        self.assertEqual(signatures[0], signatures[1])
        self.assertIn("/Script/Test.NotifyState", signatures[0][0])

    def test_selected_reference_frame_accepts_self_but_rejects_external(self):
        """/** @return 自身末帧参考保持合法且不放宽到任意外部动画 */"""
        source = object()
        values = {"additive_anim_type": 1, "ref_pose_type": 3,
                  "ref_pose_seq": source, "ref_frame_index": 28}
        output = SimpleNamespace(get_editor_property=values.__getitem__)
        self.assertEqual(self.namespace["_validate_additive_reference"](output, source), 28)
        values["ref_pose_seq"] = output
        self.assertEqual(self.namespace["_validate_additive_reference"](output, source), 28)
        values["ref_pose_seq"] = object()
        with self.assertRaisesRegex(RuntimeError, "自身源动画"):
            self.namespace["_validate_additive_reference"](output, source)

    def test_control_channels_keep_short_rotation_across_angle_boundary(self):
        """/** @return 跨越180度时不产生一帧反向整圈旋转 */"""
        suffixes = ["Location.X", "Location.Y", "Location.Z", "Rotation.X",
                    "Rotation.Y", "Rotation.Z", "Scale.X", "Scale.Y", "Scale.Z"]
        values = {"Hand." + name: [] for name in suffixes}
        channels = {name: SimpleNamespace(add_key=lambda *args, target=keys: target.append(args))
                    for name, keys in values.items()}
        hierarchy = SimpleNamespace(get_parents=lambda key: [],
                                    get_global_control_offset_transform=lambda key, initial: None)
        transforms = []
        for angle in (179.0, -179.0):
            transform = SimpleNamespace(
                translation=SimpleNamespace(x=1.0, y=2.0, z=3.0),
                rotation=SimpleNamespace(rotator=lambda value=angle:
                    SimpleNamespace(roll=value, pitch=0.0, yaw=0.0)),
                scale3d=SimpleNamespace(x=1.0, y=1.0, z=1.0),
            )
            transform.make_relative = lambda offset, value=transform: value
            transforms.append(transform)
        self.namespace["_set_component_keys"](channels, hierarchy, "Hand", transforms, [0, 1])
        self.assertTrue(all(len(keys) == 2 for keys in values.values()))
        self.assertEqual([key[1] for key in values["Hand.Rotation.X"]], [179.0, 181.0])
        self.assertEqual([key[1] for key in values["Hand.Location.Z"]], [3.0, 3.0])


if __name__ == "__main__":
    unittest.main()
