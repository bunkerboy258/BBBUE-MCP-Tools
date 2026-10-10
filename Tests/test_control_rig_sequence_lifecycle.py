import ast
import json
import math
from pathlib import Path
import unittest
from unittest.mock import Mock, MagicMock


ROOT = Path(__file__).resolve().parents[1]


class ControlRigSourcePoseTests(unittest.TestCase):
    """/** 检查原姿势批量读取保持骨骼顺序与源变换 */"""

    def test_unchanged_source_uses_official_component_pose_array(self):
        """/** @return 不重复合成姿势且保留每帧官方组件变换 */"""
        tree = ast.parse((ROOT / "Scripts/BBBControlRigAuthoringToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "build_pose_control_keys")
        method.decorator_list = []
        engine = Mock()
        animation = Mock()
        animation.data_model_interface.get_number_of_keys.return_value = 2
        animation.data_model_interface.get_frame_rate.return_value = Mock(numerator=30, denominator=1)
        pose = Mock()
        engine.AnimPoseExtensions.get_bone_names.return_value = ["root", "hand_l"]
        engine.AnimPoseExtensions.get_bone_pose.side_effect = lambda pose, name, space: name + "Pose"
        reader = Mock(side_effect=lambda value: {"source": value})
        namespace = {"unreal": engine, "json": json, "_asset": lambda path, kind: animation,
                     "_pose": Mock(return_value=pose), "_read_transform": reader}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "source_pose_test", "exec"), namespace)
        keys = json.loads(namespace[method.name]("Animation", "Mesh", "[]", 0, 1))
        self.assertEqual([key["control"] for key in keys], ["source_root", "source_hand_l"] * 2)
        self.assertEqual([key["value"]["source"] for key in keys], ["rootPose", "hand_lPose"] * 2)
        engine.MathLibrary.compose_transforms.assert_not_called()
        self.assertEqual(engine.AnimPoseExtensions.get_bone_pose.call_count, 4)


class AttachmentAnimationTimingTests(unittest.TestCase):
    """/** 验证附件机构动画不会在角色动作期间循环 */"""

    def setUp(self):
        """/** @return 隔离的序列时间轴与官方时间变换接口 */"""
        tree = ast.parse((ROOT / "Scripts/BBBControlRigAuthoringToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "configure_sequence_attachment_animation")
        method.decorator_list = []
        self.engine = Mock()
        self.sequence = Mock()
        self.animation = Mock()
        self.animation.get_play_length.return_value = 1.0
        self.sequence.get_playback_start.return_value = 0
        self.sequence.get_playback_end.return_value = 67
        self.sequence.get_display_rate.return_value = Mock(numerator=30, denominator=1)
        self.section = Mock()
        self.binding = Mock()
        self.binding.get_name.return_value = "Gun"
        self.binding.find_tracks_by_type.return_value = [Mock(get_sections=Mock(return_value=[self.section]))]
        self.sequence.get_bindings.return_value = [self.binding]
        self.engine.MovieSceneTimeWarpExtensions.to_fixed_play_rate.return_value = 30.0 / 67.0
        self.access = Mock()
        namespace = {"unreal": self.engine, "json": json, "math": math,
                     "require_write_access": self.access,
                     "_asset": lambda path, kind: self.sequence if path == "Sequence" else self.animation}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "attachment_timing_test", "exec"), namespace)
        self.configure = namespace[method.name]

    def test_explicit_non_looping_time_warp_is_saved(self):
        """/** @return 一秒机构动画只播放一次并覆盖角色时间轴 */"""
        result = json.loads(self.configure("Sequence", "Gun", "Animation", 0, 67, 30.0 / 67.0))
        self.assertAlmostEqual(result["playRate"], 30.0 / 67.0)
        self.engine.MovieSceneTimeWarpExtensions.make_time_warp.assert_called_once()
        self.section.set_range.assert_called_once_with(0, 67)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once()

    def test_looping_range_is_rejected_before_write(self):
        """/** @return 隐式循环请求不能修改序列 */"""
        with self.assertRaises(RuntimeError):
            self.configure("Sequence", "Gun", "Animation", 0, 67, 1.0)
        self.access.assert_not_called()
        self.sequence.modify.assert_not_called()

    def test_missing_attachment_track_is_created_after_validation(self):
        """/** @return 已有武器附件可直接添加唯一机构动画轨道 */"""
        self.binding.find_tracks_by_type.return_value = []
        track = Mock()
        track.get_sections.return_value = [self.section]
        self.binding.add_track.return_value = track
        self.configure("Sequence", "Gun", "Animation", 0, 67, 30.0 / 67.0)
        self.binding.add_track.assert_called_once_with(self.engine.MovieSceneSkeletalAnimationTrack)
        track.add_section.assert_called_once()
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once()

    def test_speed_readback_failure_is_not_saved(self):
        """/** @return 速度写入不一致不能冒充成功 */"""
        self.engine.MovieSceneTimeWarpExtensions.to_fixed_play_rate.return_value = 1.0
        with self.assertRaises(RuntimeError):
            self.configure("Sequence", "Gun", "Animation", 0, 67, 30.0 / 67.0)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()


class AttachmentBindingSelectionTests(unittest.TestCase):
    """/** 验证附件绑定顺序变化不会改变挂接角色 */"""

    def setUp(self):
        """/** @return 隔离的角色和附件绑定 */"""
        tree = ast.parse((ROOT / "Scripts/BBBControlRigAuthoringToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "create_sequence_attachment")
        method.decorator_list = []
        self.engine = Mock()
        self.engine.SkeletalMeshActor = type("SkeletalActor", (), {})
        self.engine.SkeletalMesh = type("SkeletalMesh", (), {})
        self.engine.StaticMesh = type("StaticMesh", (), {})
        self.sequence = Mock()
        self.sequence.get_playback_end.return_value = 67
        self.parent = Mock()
        template = self.engine.SkeletalMeshActor()
        template.skeletal_mesh_component = Mock()
        template.skeletal_mesh_component.does_socket_exist.return_value = True
        template.skeletal_mesh_component.get_name.return_value = "CharacterMesh"
        self.parent.get_object_template.return_value = template
        self.parent.get_name.return_value = "Character"
        self.prop = Mock()
        self.prop.get_name.return_value = "ExistingMagazine"
        self.prop.get_object_template.return_value = object()
        self.sequence.get_bindings.return_value = [self.prop, self.parent]
        section = Mock()
        section.get_all_channels.return_value = [Mock()]
        track = Mock()
        track.get_sections.return_value = []
        track.add_section.return_value = section
        self.created = Mock()
        self.created.find_tracks_by_type.return_value = []
        self.created.add_track.return_value = track
        self.sequence.add_spawnable_from_instance.return_value = self.created
        transform = Mock()
        transform.translation.to_tuple.return_value = (0, 0, 0)
        transform.scale3d.to_tuple.return_value = (1, 1, 1)
        transform.rotation.rotator.return_value = Mock(roll=0, pitch=0, yaw=0)
        namespace = {"unreal": self.engine, "json": json, "require_write_access": Mock(),
                     "_asset": lambda path, kind: self.sequence, "_transform": lambda value: transform}
        self.engine.load_asset.return_value = self.engine.StaticMesh()
        exec(compile(ast.Module(body=[method], type_ignores=[]), "attachment_binding_test", "exec"), namespace)
        self.create = namespace[method.name]

    def test_static_attachment_first_does_not_change_parent(self):
        """/** @return 父绑定按插槽识别而不是取列表首项 */"""
        self.create("Sequence", "NewMagazine", "Mesh", "hand_l", "{}", "[[25,36]]", "")
        self.engine.MovieSceneObjectBindingID.return_value.set_editor_property.assert_called_once_with("guid", self.parent.get_id.return_value)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.sequence)

    def test_missing_socket_is_rejected_before_spawn(self):
        """/** @return 缺少挂接骨骼不能产生残留演员或绑定 */"""
        self.parent.get_object_template.return_value.skeletal_mesh_component.does_socket_exist.return_value = False
        with self.assertRaises(RuntimeError):
            self.create("Sequence", "NewMagazine", "Mesh", "hand_l", "{}", "[[25,36]]", "")
        self.engine.get_editor_subsystem.assert_not_called()
        self.sequence.add_spawnable_from_instance.assert_not_called()

    def test_ambiguous_socket_is_rejected_before_spawn(self):
        """/** @return 多个同名挂接骨骼不能隐式挑选目标 */"""
        self.sequence.get_bindings.return_value = [self.parent, self.parent]
        with self.assertRaises(RuntimeError):
            self.create("Sequence", "NewMagazine", "Mesh", "hand_l", "{}", "[[25,36]]", "")
        self.engine.get_editor_subsystem.assert_not_called()
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()


class ControlRigSequenceLifecycleTests(unittest.TestCase):
    """/** 验证 Sequencer 重建实例时的写键顺序与失败保护 */"""

    def setUp(self):
        """/** @return 隔离的官方序列与控制器 API */"""
        tree = ast.parse((ROOT / "Scripts/BBBControlRigAuthoringToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "configure_sequence_rig")
        method.decorator_list = []
        self.engine = Mock()
        self.sequence = Mock()
        self.asset = Mock()
        self.mesh = Mock()
        self.track = Mock()
        self.binding = Mock()
        self.binding.find_tracks_by_type.return_value = []
        self.track.get_sections.return_value = []
        self.rig = Mock()
        self.engine.ControlRigSequencerLibrary.is_layered_control_rig.return_value = False
        self.track.get_path_name.return_value = "Track"
        self.rig.get_path_name.return_value = "RigInstance"
        self.opened = False
        self.old_rig = Mock()
        self.engine.LevelSequenceEditorBlueprintLibrary.open_level_sequence.side_effect = self.open
        self.engine.ControlRigSequencerLibrary.find_or_create_control_rig_track.return_value = self.track
        self.engine.ControlRigSequencerLibrary.get_control_rigs.side_effect = self.proxies
        self.access = Mock()
        namespace = {"unreal": self.engine, "json": json, "require_write_access": self.access,
                     "_asset": lambda path, kind: {"Sequence": self.sequence, "Rig": self.asset, "Mesh": self.mesh}[path],
                     "_mesh_binding": lambda sequence, mesh: self.binding}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "sequence_lifecycle_test", "exec"), namespace)
        self.configure = namespace[method.name]

    def open(self, sequence):
        """/** @return 打开序列使旧预览实例失效 */"""
        self.opened = True

    def proxies(self, sequence):
        """/** @return 打开前后分别返回不同控制器实例 */"""
        proxy = Mock()
        proxy.track = self.track
        proxy.control_rig = self.rig if self.opened else self.old_rig
        return [proxy]

    def test_open_before_instance_lookup(self):
        """/** @return 写键使用打开后建立的当前实例 */"""
        channel = Mock()
        channel.get_keys.return_value = [object()]
        self.track.get_sections.return_value = [Mock(get_all_channels=Mock(return_value=[channel]))]
        self.configure("Sequence", "Rig", json.dumps([{"frame": 0, "control": "Weight", "value": 1.0}]), False, "Mesh")
        self.engine.ControlRigSequencerLibrary.set_local_control_rig_float.assert_called_once()
        self.assertIs(self.engine.ControlRigSequencerLibrary.set_local_control_rig_float.call_args.args[1], self.rig)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.sequence)

    def test_missing_keys_never_save(self):
        """/** @return 官方 API 静默漏写时阻止保存 */"""
        with self.assertRaises(RuntimeError):
            self.configure("Sequence", "Rig", json.dumps([{"frame": 0, "control": "Weight", "value": 1.0}]), False, "Mesh")
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_write_denied_before_sequencer_open(self):
        """/** @return 写入被拒绝时不打开或构造编辑轨道 */"""
        self.access.side_effect = RuntimeError("PIE")
        with self.assertRaises(RuntimeError):
            self.configure("Sequence", "Rig", "[]", False, "Mesh")
        self.engine.LevelSequenceEditorBlueprintLibrary.open_level_sequence.assert_not_called()
        self.engine.ControlRigSequencerLibrary.find_or_create_control_rig_track.assert_not_called()

    def test_existing_layered_track_is_converted_before_keying(self):
        """/** @return 已有叠加轨道切换后再取得实例和写键 */"""
        self.engine.ControlRigSequencerLibrary.is_layered_control_rig.return_value = True
        self.configure("Sequence", "Rig", "[]", False, "Mesh")
        self.engine.ControlRigSequencerLibrary.set_control_rig_layered_mode.assert_called_once_with(self.track, False)
        self.engine.ControlRigSequencerLibrary.get_control_rigs.assert_called_with(self.sequence)

    def test_mode_conversion_failure_does_not_save(self):
        """/** @return 模式切换失败禁止写键和保存 */"""
        self.engine.ControlRigSequencerLibrary.is_layered_control_rig.return_value = True
        self.engine.ControlRigSequencerLibrary.set_control_rig_layered_mode.return_value = False
        with self.assertRaises(RuntimeError):
            self.configure("Sequence", "Rig", "[]", False, "Mesh")
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_source_keys_are_batched_and_every_frame_is_checked(self):
        """/** @return 同控制器批量写入后逐帧检查 */"""
        transform = MagicMock()
        actual = MagicMock()
        difference = MagicMock(w=1.0)
        actual.rotation.quaternion.return_value.__mul__.return_value = difference
        actual.location.__sub__.return_value.length.return_value = 0.0
        self.engine.ControlRigSequencerLibrary.get_local_control_rig_euler_transforms.return_value = [actual, actual]
        self.configure.__globals__["_transform"] = lambda value: transform
        channel = Mock(get_keys=Mock(return_value=[object(), object()]))
        self.track.get_sections.return_value = [Mock(get_all_channels=Mock(return_value=[channel]))]
        keys = [{"frame": frame, "control": "source_hand_l", "value": {"position": [1, 2, 3]}} for frame in [0, 1]]
        self.configure("Sequence", "Rig", json.dumps(keys), False, "Mesh")
        self.engine.ControlRigSequencerLibrary.set_local_control_rig_euler_transforms.assert_called_once()
        self.engine.ControlRigSequencerLibrary.set_local_control_rig_euler_transform.assert_not_called()
        self.assertEqual(actual.location.__sub__.call_count, 2)

    def test_incomplete_source_readback_never_saves(self):
        """/** @return 批量接口少返回一帧时拒绝保存 */"""
        self.configure.__globals__["_transform"] = lambda value: Mock()
        self.engine.ControlRigSequencerLibrary.get_local_control_rig_euler_transforms.return_value = []
        with self.assertRaises(RuntimeError):
            self.configure("Sequence", "Rig", json.dumps([{"frame": 0, "control": "source_hand_l", "value": {}}]), False, "Mesh")
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
