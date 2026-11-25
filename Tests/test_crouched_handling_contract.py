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

    def test_camera_scales_impulse_with_crouch_and_stationary_without_scaling_retention(self):
        node = self.function("configure_camera_recoil")
        values = self.strings(node)
        self.assertIn("bSourceCrouching", values)
        self.assertIn("GetCrouchedCameraImpulseScale", values)
        self.assertIn("GetStationaryCameraImpulseScale", values)
        self.assertTrue(any("IsStationaryForRecoil" in value for value in values))
        self.assertNotIn("GetCrouchedCameraRecoveryScale", values)
        self.assertNotIn("GetAirborneCameraRecoveryScale", values)
        self.assertNotIn("RecoverySpeed", values)
        assignment = next(value for value in ast.walk(node) if isinstance(value, ast.Assign)
                          and any(isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
                                  and target.slice.value == "PitchRetention" for target in value.targets))
        self.assertEqual(assignment.value.func.attr, "select")
        self.assertNotIn("Multiply_DoubleDouble", self.strings(assignment))


if __name__ == "__main__":
    unittest.main()
