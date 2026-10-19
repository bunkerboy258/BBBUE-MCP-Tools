from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Scripts'))
from BBBWeaponActionAuthoring import entry_hold_weight


class EntryHoldTests(unittest.TestCase):
    def test_explicit_first_segment_can_release_hold_without_forcing_loop_hold(self):
        """/** @return 起始分段从静态释放而装填循环不被误识别为重新入场 */"""
        start={'kind':'reload_start','entry_hold_release_frame':4}
        self.assertEqual([entry_hold_weight(start,frame) for frame in [0,2,4,25]],[1,.5,0,0])
        self.assertEqual(entry_hold_weight({'kind':'reload_loop'},0),0)
        self.assertEqual(entry_hold_weight({'kind':'reload_end'},0),0)
        self.assertEqual(entry_hold_weight({'kind':'reload','release_frame':4},2),.5)
        for invalid in [0,-1,float('inf'),float('nan'),None,True]:
            with self.assertRaises(ValueError):
                entry_hold_weight({'kind':'reload_start','entry_hold_release_frame':invalid},0)


if __name__=='__main__':
    unittest.main()
