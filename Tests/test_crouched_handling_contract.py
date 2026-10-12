import ast
import pathlib
import unittest


SOURCE = pathlib.Path(__file__).resolve().parents[1] / "Scripts" / "BBBWeaponHandlingTools.py"


class CrouchedHandlingContractTests(unittest.TestCase):
    def setUp(self):
        self.module = ast.parse(SOURCE.read_text(encoding="utf-8"))

    def function(self, name):
        return next(node for node in self.module.body if isinstance(node, ast.FunctionDef) and node.name == name)

    def strings(self, node):
        return [value.value for value in ast.walk(node) if isinstance(value, ast.Constant) and isinstance(value.value, str)]

    def test_handling_reads_actual_character_crouch_fact(self):
        values = self.strings(self.function("configure_animation_handling"))
        self.assertIn("bSourceCrouching", values)
        self.assertIn("/Script/ABBB_Evac.BBBAnimInstance", values)

    def test_handling_multiplies_independent_posture_scales(self):
        parent = self.function("configure_animation_handling")
        scale = next(node for node in parent.body if isinstance(node, ast.FunctionDef) and node.name == "scale")
        values = self.strings(scale)
        self.assertIn("Airborne", values)
        self.assertIn("Crouched", values)
        self.assertIn("Multiply_DoubleDouble", values)
        selects = [node for node in ast.walk(scale) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Attribute) and node.func.attr == "select"]
        self.assertEqual(len(selects), 2)
        self.assertTrue(all(isinstance(node.args[1], ast.Constant) and node.args[1].value == 1 for node in selects))

    def test_all_four_handling_scales_use_the_posture_selector(self):
        node = self.function("configure_animation_handling")
        names = [call.args[0].value for call in ast.walk(node) if isinstance(call, ast.Call)
                 and isinstance(call.func, ast.Name) and call.func.id == "scale"
                 and call.args and isinstance(call.args[0], ast.Constant)]
        self.assertEqual(set(names), {"AimFollowScale", "BackwardRecoilScale", "SwayAmplitudeScale", "SwayFrequencyScale"})

    def test_camera_reads_both_crouched_scales_without_scaling_retention(self):
        node = self.function("configure_camera_recoil")
        values = self.strings(node)
        self.assertIn("bSourceCrouching", values)
        self.assertIn("GetCrouchedCameraImpulseScale", values)
        self.assertIn("GetCrouchedCameraRecoveryScale", values)
        assignment = next(value for value in ast.walk(node) if isinstance(value, ast.Assign)
                          and any(isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
                                  and target.slice.value == "PitchRetention" for target in value.targets))
        self.assertEqual(assignment.value.func.attr, "select")
        self.assertNotIn("Multiply_DoubleDouble", self.strings(assignment))


if __name__ == "__main__":
    unittest.main()
