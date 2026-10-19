from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Scripts'))
from BBBWeaponActionAuthoring import compensate_hand_attachment_grip
from BBBGripPoseFitting import transform_matrix


class AttachmentGripShiftTests(unittest.TestCase):
    def test_changed_local_grip_preserves_real_magazine_world_path_under_rotated_wrist(self):
        """/** @return 非交换腕部旋转下附件局部改握不改变匣体世界姿态 */"""
        wrist=transform_matrix([3,7,11,.2,-.3,.1,.9273618495,1,1,1])
        local=transform_matrix([12.5,-4.5,1.5,.7622022172,.5533124236,.2880882522,.1729112517,1,1,1])
        delta=local[:3,2]*-7
        desired=local.copy()
        desired[:3,3]+=delta
        changed=[float(value) for value in [*desired[:3,3],.7622022172,.5533124236,.2880882522,.1729112517,1,1,1]]
        shift={'bone':'hand_l','reference_attachment_local':[12.5,-4.5,1.5,.7622022172,.5533124236,.2880882522,.1729112517,1,1,1],
               'attachment_local':changed,'phase_frames':[20,24,36,43]}
        corrected=compensate_hand_attachment_grip(wrist,29,[shift])
        np.testing.assert_allclose(corrected@desired,wrist@local,atol=1e-12)
        np.testing.assert_allclose(corrected[:3,:3],wrist[:3,:3],atol=1e-12)
        np.testing.assert_array_equal(compensate_hand_attachment_grip(wrist,18,[shift]),wrist)

    def test_wrong_bone_nonfinite_or_overlapping_shifts_are_rejected(self):
        """/** @return 错误手侧、非法向量及重复反补偿不能生成动作 */"""
        identity=[0,0,0,0,0,0,1,1,1,1]
        valid={'bone':'hand_l','reference_attachment_local':identity,'attachment_local':identity,'phase_frames':[4,10,17,20]}
        invalid=[{**valid,'bone':'hand_r'},{**valid,'attachment_local':[1,2]},
                 {**valid,'attachment_local':[float('nan')]+identity[1:]},
                 {**valid,'attachment_local':identity[:7]+[2,1,1]},
                 {**valid,'attachment_local':identity[:6]+[0]+identity[7:]}]
        for shift in invalid:
            with self.assertRaises(ValueError):
                compensate_hand_attachment_grip(np.eye(4),10,[shift])
        with self.assertRaises(ValueError):
            compensate_hand_attachment_grip(np.eye(4),10,[valid,valid])


if __name__=='__main__':
    unittest.main()
