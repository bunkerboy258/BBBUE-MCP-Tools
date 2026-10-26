import importlib.util
import math
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class Position:
    def __init__(self, x, y=0.0, z=0.0):
        self.values = (x, y, z)

    def __sub__(self, other):
        return Position(*(a - b for a, b in zip(self.values, other.values)))

    def length(self):
        return math.sqrt(sum(value * value for value in self.values))


class AnimationCurveFrameAlignmentTests(unittest.TestCase):
    """/** 验证首尾裁帧的时间对应及曲线键语义边界 */"""

    def setUp(self):
        api = types.SimpleNamespace(BBBBlueprintEditorLibrary=types.SimpleNamespace(
            get_animation_bone_track_transforms=lambda asset, bone: asset.tracks[bone]))
        with patch.dict(sys.modules, {'unreal': api}):
            path = Path(__file__).parents[1] / 'Scripts/BBBAnimationCurveTools.py'
            spec = importlib.util.spec_from_file_location('aligned_curves_tested', path)
            self.tools = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.tools)

    def animation(self, frames, fps=30):
        tracks = {bone: [types.SimpleNamespace(
            translation=Position(frame * frame * 0.01 + frame, math.sin(frame / 8)),
            rotation=types.SimpleNamespace(to_tuple=lambda: (0.0, 0.0, 0.0, 1.0)))
            for frame in frames] for bone in ('root', 'pelvis')}
        return types.SimpleNamespace(tracks=tracks,
            data_model_interface=types.SimpleNamespace(get_frame_rate=lambda: types.SimpleNamespace(numerator=fps, denominator=1)),
            get_path_name=lambda: '/Game/_Project/Target')

    def test_one_leading_frame_and_two_total_missing_frames(self):
        result = self.tools._trimmed_frame_alignment(self.animation(range(101)), self.animation(range(1, 100)))
        self.assertEqual(result['source_frame_offset'], 1)
        self.assertAlmostEqual(result['source_time_offset'], 1 / 30)
        self.assertAlmostEqual(result['verified_target_end_time'], 98 / 30)
        self.assertEqual(result['max_position_error_cm'], 0)

    def test_longer_tail_is_excluded_from_verified_search_interval(self):
        result = self.tools._trimmed_frame_alignment(self.animation(range(119)), self.animation(range(1, 124)))
        self.assertEqual(result['source_frame_offset'], 1)
        self.assertAlmostEqual(result['verified_target_end_time'], 117 / 30)

    def test_frame_rate_change_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.tools._trimmed_frame_alignment(self.animation(range(101)), self.animation(range(1, 100), 60))

    def test_unrelated_root_motion_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.tools._trimmed_frame_alignment(self.animation(range(101)), self.animation(range(100, 200)))

    def test_root_repair_is_reported_without_corrupting_pose_time_alignment(self):
        source = self.animation(range(101))
        target = self.animation(range(1, 100))
        target.tracks['root'] = self.animation(range(100, 199)).tracks['root']
        result = self.tools._trimmed_frame_alignment(source, target)
        self.assertEqual(result['source_frame_offset'], 1)
        self.assertFalse(result['root_motion_matches'])
        self.assertGreater(result['root_max_position_error_cm'], 0.1)

    def test_large_duration_change_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.tools._trimmed_frame_alignment(self.animation(range(101)), self.animation(range(1, 80)))

    def test_truncated_pelvis_track_is_rejected(self):
        target = self.animation(range(1, 100))
        target.tracks['pelvis'] = target.tracks['pelvis'][:2]
        with self.assertRaises(RuntimeError):
            self.tools._trimmed_frame_alignment(self.animation(range(101)), target)

    def test_nonfinite_root_position_is_rejected(self):
        target = self.animation(range(1, 100))
        target.tracks['root'][10].translation = Position(float('nan'))
        with self.assertRaises(RuntimeError):
            self.tools._trimmed_frame_alignment(self.animation(range(101)), target)

    def test_sequencer_time_rounding_and_signed_zero_are_accepted(self):
        left = '(FloatCurve=(Keys=((Time=-0.000000,Value=1),(Time=0.016666,Value=1))),CurveTypeFlags=4)'
        right = '(FloatCurve=(Keys=((Value=1),(Time=0.016667,Value=1))),CurveTypeFlags=4)'
        self.assertTrue(self.tools._aligned_curve_equal(left, right))

    def test_larger_time_shift_is_rejected(self):
        left = '(FloatCurve=(Keys=((Time=0.1,Value=1))),CurveTypeFlags=4)'
        self.assertFalse(self.tools._aligned_curve_equal(left, left.replace('Time=0.1', 'Time=0.1001')))

    def test_zero_time_zero_value_key_is_not_lost(self):
        left = '(FloatCurve=(Keys=((Time=-0.000000),(Time=0.033334))))'
        right = '(FloatCurve=(Keys=((),(Time=0.033333))))'
        self.assertTrue(self.tools._aligned_curve_equal(left, right))

    def test_key_values_tangents_flags_and_metadata_remain_strict(self):
        left = '(FloatCurve=(Keys=((InterpMode=RCIM_Cubic,Time=0.1,Value=1,LeaveTangent=2))),Color=(R=1),Comment="plant",CurveTypeFlags=4)'
        for old, new in [('Value=1', 'Value=2'), ('LeaveTangent=2', 'LeaveTangent=3'),
                         ('R=1', 'R=0'), ('plant', 'swing'), ('CurveTypeFlags=4', 'CurveTypeFlags=0')]:
            self.assertFalse(self.tools._aligned_curve_equal(left, left.replace(old, new)))


if __name__ == '__main__':
    unittest.main()
