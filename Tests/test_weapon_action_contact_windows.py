from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Scripts'))
from BBBWeaponActionAuthoring import contact_translation_weight


class ContactWindowTests(unittest.TestCase):
    def test_actual_detach_and_insert_contacts_leave_body_space_interval_unchanged(self):
        """/** @return 两次接触之间的身体取匣空程不受到枪空间平移 */"""
        correction={'phase_windows':[[4,10,10,14],[29,36,36,40]]}
        self.assertEqual([contact_translation_weight(frame,correction) for frame in [0,4,10,14,18,25,29,36,40,66]],
                         [0,0,1,0,0,0,0,1,0,0])
        self.assertEqual(contact_translation_weight(36,{'phase_frames':[29,36,36,40]}),1)

    def test_ambiguous_overlap_bad_shape_and_nonfinite_windows_fail(self):
        """/** @return 接触来源不明确或非法时拒绝输出动作 */"""
        invalid=[{}, {'phase_frames':[4,10,10,14],'phase_windows':[[29,36,36,40]]},
                 {'phase_windows':[]},{'phase_windows':[[4,10,10,14],[13,36,36,40]]},
                 {'phase_windows':[[29,36,36,40],[4,10,10,14]]},
                 {'phase_windows':[[0,10,float('inf'),40]]},{'phase_windows':[[0,10,10]]},
                 {'phase_windows':[[0,0,10,14]]},{'phase_windows':[[-1,10,10,14]]}]
        for correction in invalid:
            with self.subTest(correction=correction):
                with self.assertRaises(ValueError):
                    contact_translation_weight(10,correction)


if __name__=='__main__':
    unittest.main()
