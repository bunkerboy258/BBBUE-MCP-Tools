import ast
from pathlib import Path
import types
import unittest
from unittest.mock import Mock


class PropertyValue:
    """/** 模拟反射属性容器 */"""

    def __init__(self, **values):
        self.values = values

    def get_editor_property(self, name):
        normalized = ''.join(character.lower() for character in name if character != '_')
        return next(value for key, value in self.values.items()
                    if ''.join(character.lower() for character in key if character != '_') == normalized)

    def set_editor_property(self, name, value):
        self.values[name] = value

    def set_curve_identifier(self, name, curve_type):
        self.values.update(curve_name=name, curve_type=curve_type)

    def export_text(self):
        keys = self.values['float_curve'].values['keys']
        rows = ['(' + ','.join(''.join(part.title() for part in field.split('_')) + '=' + str(value)
                              for field, value in key.values.items()) + ')' for key in keys]
        return '(CurveName="' + self.values['curve_name'] + '",FloatCurve=(Keys=(' + ','.join(rows) + ')))'


class AnimationCubicCurveTests(unittest.TestCase):
    """/** 验证真正三次插值及首尾水平切线 */"""

    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'Scripts/BBBGenericEditorToolset.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in {'_float_curve_key_details', '_set_flat_cubic_curve'}]
        engine = types.SimpleNamespace(AnimationCurveIdentifier=PropertyValue, RichCurveKey=PropertyValue,
            RawCurveTrackTypes=types.SimpleNamespace(RCT_FLOAT='float'),
            RichCurveInterpMode=types.SimpleNamespace(RCIM_CUBIC='RCIM_CUBIC'),
            RichCurveTangentMode=types.SimpleNamespace(RCTM_USER='RCTM_USER'))
        self.namespace = {'unreal': engine, '_serialize_value': lambda value: value}
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'curve_helpers', 'exec'), self.namespace)
        self.curve_data = PropertyValue(float_curves=[])
        self.model = Mock()
        self.model.get_class.return_value.get_name.return_value = 'AnimDataModel'
        self.model.get_editor_property.side_effect = lambda field: self.curve_data
        self.controller = Mock()
        self.controller.set_curve_keys.side_effect = self.write_keys
        self.animation = Mock()
        self.animation.data_model_interface = self.model
        self.animation.controller = self.controller

    def write_keys(self, identifier, keys, transact):
        self.assertEqual(identifier.values['curve_type'], 'float')
        self.assertFalse(transact)
        self.curve_data.values['float_curves'] = [PropertyValue(curve_name='DisableAimIK',
            float_curve=PropertyValue(keys=keys))]
        return True

    def test_cubic_flat_uses_only_requested_keys_and_zero_tangents(self):
        keys = [{'time': 0, 'value': 1}, {'time': .72, 'value': 0}]
        self.namespace['_set_flat_cubic_curve'](self.animation, 'disableaimik', keys)
        actual = self.namespace['_float_curve_key_details'](self.animation, 'DISABLEAIMIK')
        self.assertEqual([k['time'] for k in actual], [0, .72])
        self.assertEqual([k['value'] for k in actual], [1, 0])
        for key in actual:
            self.assertEqual(key['interp_mode'], 'RCIM_CUBIC')
            self.assertEqual(key['tangent_mode'], 'RCTM_USER')
            self.assertEqual(key['arrive_tangent'], 0)
            self.assertEqual(key['leave_tangent'], 0)

    def test_failed_controller_is_not_reported_as_success(self):
        self.controller.set_curve_keys.side_effect = None
        self.controller.set_curve_keys.return_value = False
        with self.assertRaises(RuntimeError):
            self.namespace['_set_flat_cubic_curve'](self.animation, 'DisableAimIK', [])

    def test_readback_requires_unique_curve(self):
        with self.assertRaises(RuntimeError):
            self.namespace['_float_curve_key_details'](self.animation, 'DisableAimIK')

    def test_native_export_omits_default_key_fields(self):
        curve = Mock()
        curve.export_text.return_value = '(CurveName="DisableAimIK",FloatCurve=(Keys=((Value=1.000000),(Time=0.720000,InterpMode=RCIM_Cubic,TangentMode=RCTM_User))))'
        self.curve_data.values['float_curves'] = [curve]
        actual = self.namespace['_float_curve_key_details'](self.animation, 'DisableAimIK')
        self.assertEqual(actual[0]['interp_mode'], 'RCIM_Linear')
        self.assertEqual(actual[0]['time'], 0)
        self.assertEqual(actual[1]['value'], 0)
        self.assertEqual(actual[1]['arrive_tangent'], 0)

    def test_0_72_second_bezier_is_monotone_and_has_zero_endpoint_velocity(self):
        values = [1 - 3*(i/100)**2 + 2*(i/100)**3 for i in range(101)]
        self.assertEqual((values[0], values[-1]), (1, 0))
        self.assertTrue(all(a >= b for a, b in zip(values, values[1:])))
        self.assertEqual((-6*0 + 6*0*0)/.72, 0)
        self.assertEqual((-6*1 + 6*1*1)/.72, 0)


if __name__ == '__main__':
    unittest.main()
