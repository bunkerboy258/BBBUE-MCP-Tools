import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class AnimationLibrarySampleRateTests(unittest.TestCase):
    """/** 验证半帧动作可使用明确采样率且无效请求不会进入资产操作 */"""

    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'Scripts/BBBAnimationLibraryImport.py'
        spec = importlib.util.spec_from_file_location('sample_rate_import_test', path)
        self.module = importlib.util.module_from_spec(spec)
        policy = types.SimpleNamespace(require_asset_write=lambda *args: self.fail('不得写入'))
        with patch.dict(sys.modules, {'unreal': types.SimpleNamespace(), 'BBBAssetWritePolicy': policy}):
            spec.loader.exec_module(self.module)

    def test_explicit_rate_preserves_half_frame_duration(self):
        rate = self.module._sample_rate({'sample_rate': 60})
        self.assertEqual(rate, 60)
        self.assertAlmostEqual((245 / 60) * rate, 245)

    def test_default_rate(self):
        self.assertEqual(self.module._sample_rate({}), 30)

    def test_invalid_rates_rejected_before_asset_access(self):
        for rate in (0, 241, True, 30.5, '60'):
            with self.subTest(rate=rate), self.assertRaisesRegex(RuntimeError, '采样率'):
                self.module.import_animation_library_batch(json.dumps([
                    {'asset_path': '/Game/NewClip', 'sample_rate': rate},
                ]))


if __name__ == '__main__':
    unittest.main()
