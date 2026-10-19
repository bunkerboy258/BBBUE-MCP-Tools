import importlib.util
import math
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class ArmTwistGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).resolve().parents[1]/'Scripts/BBBArmTwistRigTools.py'
        spec=importlib.util.spec_from_file_location('arm_twist_test_subject',path)
        cls.module=importlib.util.module_from_spec(spec)
        policy=types.ModuleType('BBBAssetWritePolicy')
        policy.require_asset_write=lambda *args:None
        with patch.dict(sys.modules,{'unreal':types.ModuleType('unreal'),'BBBAssetWritePolicy':policy}):
            spec.loader.exec_module(cls.module)

    def test_quaternion_comparison_handles_sign_and_float_length(self):
        q=[.1,.2,.3,.9]
        self.assertLess(self.module._qerror(q,[-v*1.000001 for v in q]),.00001)
        self.assertAlmostEqual(self.module._qerror([0,0,0,1],[1,0,0,0]),180)

    def surface(self,collapse=False):
        points=[[0,0,0],[1,0,0],[0,1,0]]
        return {'bones':[{'name':'forearm'},{'name':'twist'}],
            'vertices':[{'id':i,'bindPosition':v,'position':[10+v[1],20-v[0],30]if not collapse else [10+v[0],20,30],'weights':[[0,.5],[1,.5]]}for i,v in enumerate(points)],
            'triangles':[{'vertices':[0,1,2]}]}

    def test_metric_is_invariant_under_rigid_motion(self):
        result=self.module._metrics(self.surface(),{'parent':'forearm','twist':'twist'})
        self.assertAlmostEqual(result['rmsLogEdgeStrain'],0)
        self.assertAlmostEqual(result['p05AreaRatio'],1)

    def test_metric_detects_collapsed_triangle(self):
        result=self.module._metrics(self.surface(True),{'parent':'forearm','twist':'twist'})
        self.assertEqual(result['minimumAreaRatio'],0)
        self.assertGreater(result['rmsLogEdgeStrain'],1)


if __name__=='__main__':
    unittest.main()
