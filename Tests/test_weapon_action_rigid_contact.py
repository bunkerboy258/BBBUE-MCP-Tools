from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Scripts'))
from BBBWeaponActionAuthoring import explicit_rigid_contact,compensate_hand_attachment_grip
from BBBGripPoseFitting import transform_matrix


class RigidContactTests(unittest.TestCase):
    def test_noncommuting_gun_contact_and_changed_grip_keep_actual_magazine_seat(self):
        """/** @return 枪空间非交换接槽及手掌新握持按物理刚体顺序组合 */"""
        gun=transform_matrix([19,4,-7,.1,-.2,.4,.8888194417,1,1,1])
        wrist=transform_matrix([3,7,11,.2,-.3,.1,.9273618495,1,1,1])
        values=[2,-1,3,-.1,.3,.2,.9273618495,1,1,1]
        original=[12.5,-4.5,1.5,.7622022172,.5533124236,.2880882522,.1729112517,1,1,1]
        current=[4,2,3,.1,.2,.3,.9273618495,1,1,1]
        contact={'delta_weapon':values,'phase_frames':[29,36,36,40]}
        seated=explicit_rigid_contact(wrist,gun,36,[contact])
        np.testing.assert_allclose(np.linalg.inv(gun)@seated,transform_matrix(values)@np.linalg.inv(gun)@wrist,atol=1e-12)
        change={'bone':'hand_l','reference_attachment_local':original,'attachment_local':current,'phase_frames':[20,24,36,43]}
        corrected=compensate_hand_attachment_grip(seated,36,[change])
        np.testing.assert_allclose(corrected@transform_matrix(current),gun@transform_matrix(values)@np.linalg.inv(gun)@wrist@transform_matrix(original),atol=1e-12)
        np.testing.assert_array_equal(explicit_rigid_contact(wrist,gun,18,[contact]),wrist)
        with self.assertRaises(ValueError):
            explicit_rigid_contact(wrist,gun,36,[contact,contact])


if __name__=='__main__':
    unittest.main()
