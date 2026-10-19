from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Scripts'))
from BBBWeaponActionAuthoring import explicit_wrist_component_path
from BBBGripPoseFitting import transform_matrix
from BBBGripAuthoring import matrix_values


class WristPathTests(unittest.TestCase):
    def test_explicit_contact_short_path_keeps_boundaries_and_native_targets_immutable(self):
        a=transform_matrix([2,5,-8,.1,.2,-.3,.9273618495,1,1,1])
        b=transform_matrix([9,-4,3,-.3,.2,.1,.9273618495,1,1,1])
        targets=[a.copy()for _ in range(31)]
        keys=[{'frame':4,'transform':matrix_values(a)},{'frame':12,'transform':matrix_values(b)},{'frame':24,'transform':matrix_values(a)}]
        output=explicit_wrist_component_path(targets,keys)
        for frame in [0,3,4,24,25,30]:
            np.testing.assert_allclose(output[frame],targets[frame],atol=1e-10)
        np.testing.assert_allclose(output[12],b,atol=1e-10)
        np.testing.assert_allclose(output[8][:3,3],(a[:3,3]+b[:3,3])*.5,atol=1e-10)
        np.testing.assert_array_equal(targets[12],a)
        for bad in [[keys[0],keys[0]], [{'frame':-1,'transform':matrix_values(a)},keys[-1]],
            [keys[0],{'frame':24,'transform':matrix_values(b)}],
            [keys[0],{'frame':12.5,'transform':matrix_values(b)},keys[-1]]]:
            with self.assertRaises(ValueError):
                explicit_wrist_component_path(targets,bad)


if __name__=='__main__':
    unittest.main()
