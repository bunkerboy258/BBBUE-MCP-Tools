import ast
import json
import math
from pathlib import Path
from types import SimpleNamespace
import unittest


class MetadataInspectionTests(unittest.TestCase):
    """/** 批量动画元数据的原生时间与身份防护检查 */"""

    def setUp(self):
        """/** @return 不依赖编辑器的通知与原生时间夹具 */"""
        tree = ast.parse((Path(__file__).parents[1] / 'Scripts/BBBAnimationCurveTools.py').read_text(encoding='utf8'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_animation_metadata')
        self.cost = -0.1
        self.row = {'sourceIndex': 0, 'notifyInstance': 'sequence:state', 'nativeTriggerTime': 0.0001,
                    'triggerTimeOffset': 0.0001, 'nativeDuration': 0.25}
        state = SimpleNamespace(get_path_name=lambda: 'sequence:state',
            get_class=lambda: SimpleNamespace(get_path_name=lambda: '/Script/PoseSearch.AnimNotifyState_PoseSearchOverrideContinuingPoseCostBias'),
            get_editor_property=lambda name: self.cost)
        event = SimpleNamespace(get_editor_property=lambda name: {'notify': None, 'notify_state_class': state,
                                                                 'notify_name': 'search'}[name])
        self.report = {'readOnly': True, 'events': [self.row]}
        runtime = SimpleNamespace(Object=type('Object', (), {}),
            AnimationLibrary=SimpleNamespace(get_animation_notify_events=lambda animation: [event]),
            BBBHandPoseLayerEditorLibrary=SimpleNamespace(inspect_animation_notify_timing=lambda animation: json.dumps(self.report)))
        scope = {'unreal': runtime, 'math': math, 'json': json}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<metadata>', 'exec'), scope)
        self.inspect = scope['_animation_metadata']
        self.animation = SimpleNamespace(get_editor_property=lambda name: False, get_path_name=lambda: 'sequence')

    def test_authored_start_excludes_trigger_offset_and_retains_cost(self):
        """/** @return 作者时间不包含触发偏移且原始成本保持 */"""
        value = self.inspect(self.animation)
        self.assertEqual(value['notifies'][0]['time'], 0.0)
        self.assertEqual(value['notifies'][0]['duration'], 0.25)
        self.assertEqual(value['notifies'][0]['properties']['cost_addend'], -0.1)
        self.assertFalse(value['settings']['loop'])

    def test_native_count_mismatch_rejects_unpaired_times(self):
        """/** @return 数量变化时拒绝把原生时间配给错误通知 */"""
        self.report['events'] = []
        with self.assertRaisesRegex(RuntimeError, 'TIMING_INVALID'):
            self.inspect(self.animation)

    def test_native_instance_mismatch_rejects_wrong_notify_time(self):
        """/** @return 同数量但实例身份不同的事件仍被拒绝 */"""
        self.row['notifyInstance'] = 'sequence:other'
        with self.assertRaisesRegex(RuntimeError, 'IDENTITY_MISMATCH'):
            self.inspect(self.animation)

    def test_nonfinite_search_cost_is_rejected(self):
        """/** @return 非有限成本不能进入批量编辑依据 */"""
        self.cost = float('nan')
        with self.assertRaisesRegex(RuntimeError, 'COST_NOT_FINITE'):
            self.inspect(self.animation)

    def test_nonfinite_authored_time_is_rejected(self):
        """/** @return 无效作者时间不能成为迁移区间 */"""
        self.row['nativeTriggerTime'] = float('inf')
        with self.assertRaisesRegex(RuntimeError, 'TIME_NOT_FINITE'):
            self.inspect(self.animation)
