import ast
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class TimelineRepairTests(unittest.TestCase):
    """/** 验证无效窗口状态必须销毁且正常缩放保持原样 */"""

    def make_repair(self, view):
        state = {'view': list(view), 'work': [-1.0, 4.0], 'stale_editor': True}
        sequence = SimpleNamespace(
            get_view_range_start=lambda: state['view'][0],
            get_view_range_end=lambda: state['view'][1],
            get_work_range_start=lambda: state['work'][0],
            get_work_range_end=lambda: state['work'][1],
            get_playback_start=lambda: 0,
            get_playback_end=lambda: 86,
            get_display_rate=lambda: SimpleNamespace(numerator=30, denominator=1),
        )
        for field in ('view', 'work'):
            for index, bound in enumerate(('start', 'end')):
                setattr(sequence, 'set_' + field + '_range_' + bound,
                        lambda value, field=field, index=index: state[field].__setitem__(index, value))

        def destroy_editor(asset):
            self.assertIs(asset, sequence)
            state['stale_editor'] = False
            return 1

        def reopen(asset):
            if state['stale_editor']:
                state['view'][1] = float('nan')

        subsystem = SimpleNamespace(close_all_editors_for_asset=Mock(side_effect=destroy_editor))
        library = SimpleNamespace(close_level_sequence=Mock(), open_level_sequence=Mock(side_effect=reopen),
                                  set_current_time=Mock(), refresh_current_level_sequence=Mock(), force_update=Mock())
        unreal = SimpleNamespace(AssetEditorSubsystem=object(), get_editor_subsystem=lambda cls: subsystem,
                                 LevelSequenceEditorBlueprintLibrary=library,
                                 EditorAssetLibrary=SimpleNamespace(save_loaded_asset=Mock(return_value=True)))
        path = Path(__file__).resolve().parents[1] / 'Scripts/BBBManualActionNative.py'
        node = next(node for node in ast.parse(path.read_text(encoding='utf-8-sig')).body
                    if isinstance(node, ast.FunctionDef) and node.name == 'repair_timeline_range')
        scope = {'math': math, 'unreal': unreal, '_channel_digest': lambda asset: 'unchanged',
                 'require_asset_write': Mock()}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), scope)
        return scope['repair_timeline_range'], sequence, state, subsystem, unreal

    def test_stale_asset_editor_cannot_reintroduce_nan_on_reopen(self):
        """/** @return 实际资产编辑器关闭后才重开并验证关键帧未动 */"""
        repair, sequence, state, subsystem, unreal = self.make_repair([0.0, float('nan')])
        result = repair(sequence)
        self.assertTrue(result['repaired'])
        self.assertEqual(result['closed_asset_editors'], 1)
        self.assertTrue(result['channels_preserved'])
        self.assertTrue(result['playback_preserved'])
        self.assertTrue(all(math.isfinite(value) for value in state['view']))
        subsystem.close_all_editors_for_asset.assert_called_once_with(sequence)
        unreal.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(sequence, False)

    def test_valid_zoom_does_not_close_editor_or_save(self):
        """/** @return 已有正常视图不会因准备动作而被重置 */"""
        repair, sequence, state, subsystem, unreal = self.make_repair([0.5, 1.0])
        self.assertFalse(repair(sequence)['repaired'])
        self.assertEqual(state['view'], [0.5, 1.0])
        subsystem.close_all_editors_for_asset.assert_not_called()
        unreal.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_deferred_reopen_leaves_editor_closed(self):
        """/** @return 分帧恢复先关闭窗口 保留关键帧 等下一次调用再打开 */"""
        repair, sequence, state, subsystem, unreal = self.make_repair([0.0, float('nan')])
        result = repair(sequence, reopen=False)
        self.assertTrue(result['repaired'])
        self.assertFalse(result['reopened'])
        self.assertTrue(result['channels_preserved'])
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence.assert_not_called()
        unreal.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(sequence, False)


if __name__ == '__main__':
    unittest.main()
