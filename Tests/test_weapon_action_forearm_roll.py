from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Scripts'))
from BBBWeaponActionAuthoring import explicit_forearm_roll
from BBBGripPoseFitting import transform_matrix
from BBBGripAuthoring import quaternion_angle_degrees,matrix_values


def fixture():
    bones=[{'name':'upperarm_l','parent':-1},{'name':'lowerarm_l','parent':0},
        {'name':'hand_l','parent':1},{'name':'lowerarm_twist_01_l','parent':1}]
    def components(local):
        result=local.copy()
        for i,bone in enumerate(bones):
            if bone['parent']>=0:
                result[i]=result[bone['parent']]@local[i]
        return result
    surface=SimpleNamespace(bones=bones,names={b['name']:i for i,b in enumerate(bones)},components=components)
    local=np.asarray([transform_matrix(v) for v in [[4,-7,19,.2,-.3,.1,.9273618495,1,1,1],
        [3,5,-2,.1,.3,-.2,.9273618495,1,1,1],[12,4,-3,.2,.1,.3,.9273618495,1,1,1],
        [6,2,-1.5,-.1,.2,.3,.9273618495,1,1,1]]])
    return surface,local


class ForearmRollTests(unittest.TestCase):
    def test_non_axis_aligned_positive_negative_roll_preserves_wrist_and_endpoints(self):
        surface,local=fixture()
        before=surface.components(local)
        for angle in [-80,60]:
            output=explicit_forearm_roll(surface,local,12,[{'angle_degrees':angle,'phase_frames':[0,10,20,30],'twist_fraction':.5}])
            after=surface.components(output)
            np.testing.assert_allclose(after[2],before[2],atol=1e-12)
            np.testing.assert_allclose(after[:,:3,3],before[:,:3,3],atol=1e-12)
            np.testing.assert_allclose(output[:,:3,3],local[:,:3,3],atol=1e-12)
            self.assertAlmostEqual(quaternion_angle_degrees(matrix_values(before[1])[3:7],matrix_values(after[1])[3:7]),abs(angle),places=6)
            self.assertAlmostEqual(quaternion_angle_degrees(matrix_values(before[3])[3:7],matrix_values(after[3])[3:7]),abs(angle)*.5,places=6)
        np.testing.assert_array_equal(surface.components(local),before)

    def test_zero_phase_is_exact_and_invalid_windows_or_hierarchy_are_rejected(self):
        surface,local=fixture()
        good={'angle_degrees':60,'phase_frames':[0,10,20,30],'twist_fraction':.5}
        np.testing.assert_array_equal(explicit_forearm_roll(surface,local,0,[good]),local)
        for change in [{'angle_degrees':91},{'angle_degrees':float('nan')},{'angle_degrees':True},
            {'twist_fraction':-1},{'twist_fraction':float('inf')},{'phase_frames':[0,0,1,2]}]:
            with self.assertRaises(ValueError):
                explicit_forearm_roll(surface,local,12,[{**good,**change}])
        with self.assertRaises(ValueError):
            explicit_forearm_roll(surface,local,12,[good,good])
        surface.bones[2]['parent']=0
        with self.assertRaises(ValueError):
            explicit_forearm_roll(surface,local,12,[good])


if __name__=='__main__':
    unittest.main()
