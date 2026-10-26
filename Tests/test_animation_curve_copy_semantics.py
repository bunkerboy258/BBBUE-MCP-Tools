import ast
import re
import unittest
from pathlib import Path


class AnimationCurveCopySemanticsTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'Scripts' / 'BBBAnimationCurveTools.py'
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_curve_semantics')
        namespace = {'re': re}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
        self.normalize = namespace['_curve_semantics']

    def test_linear_tangent_cache_does_not_reject_equal_curves(self):
        source = '(FloatCurve=(Keys=((Value=-1.000000),(Time=0.5,Value=1.000000))),CurveName="phase",CurveTypeFlags=4)'
        copied = source.replace('Value=-1.000000)', 'Value=-1.000000,LeaveTangent=4.000000)')
        self.assertEqual(self.normalize(source), self.normalize(copied))

    def test_cubic_tangents_remain_part_of_verification(self):
        source = '(FloatCurve=(Keys=((InterpMode=RCIM_Cubic,Value=1.0,LeaveTangent=2.0))),CurveName="contact_l")'
        self.assertNotEqual(self.normalize(source), self.normalize(source.replace('LeaveTangent=2.0', 'LeaveTangent=3.0')))

    def test_key_time_value_and_extrapolation_remain_checked(self):
        source = '(FloatCurve=(Keys=((Time=0.5,Value=1.0)),PreInfinityExtrap=RCCE_Constant),CurveName="phase")'
        for old, new in [('Time=0.5', 'Time=0.6'), ('Value=1.0', 'Value=0.0'), ('RCCE_Constant', 'RCCE_Cycle')]:
            self.assertNotEqual(self.normalize(source), self.normalize(source.replace(old, new)))

    def test_curve_metadata_remains_checked(self):
        source = '(FloatCurve=(Keys=((Value=1.0))),Color=(R=1,G=0,B=0,A=1),Comment="plant",CurveName="contact_l",CurveTypeFlags=4)'
        for old, new in [('R=1', 'R=0'), ('Comment="plant"', 'Comment="swing"'), ('CurveTypeFlags=4', 'CurveTypeFlags=0')]:
            self.assertNotEqual(self.normalize(source), self.normalize(source.replace(old, new)))


if __name__ == '__main__':
    unittest.main()
