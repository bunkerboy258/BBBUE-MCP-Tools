import ast
import json
from pathlib import Path
import types
import unittest
from unittest.mock import Mock
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))
from MCP.mcp_contracts import compile_contract


class HandContactRetargetTests(unittest.TestCase):
    def test_source_rigs_are_outside_write_scope(self):
        contract = compile_contract({"id": "retarget.configure_hand_contact_retargeters", "definition": "BBBRetargetAssetAuditToolset",
                                     "name": "configure_hand_contact_retargeters", "world": "editor", "access": "write",
                                     "parameters": {"type": "object", "properties": {}}})
        self.assertEqual(contract["scope"], {"fields": ["retargeter_paths", "target_rig_path"]})

    def fixture(self, source_bones=None, foreign_refs=(), missing_operation=None):
        tree = ast.parse((ROOT / "Scripts/BBBHandContactRetarget.py").read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef))

        class Rig:
            pass

        class Retargeter:
            pass

        names = ["pelvis", "upperarm_l", "upperarm_r", "hand_l", "hand_r", "ik_hand_l", "ik_hand_r", "ik_hand_gun"]

        def mesh(bones):
            reference = types.SimpleNamespace(get_bone_names=lambda: bones)
            return types.SimpleNamespace(skeleton=types.SimpleNamespace(get_reference_pose=lambda: reference))

        target_mesh = mesh(names)
        source_mesh = mesh(source_bones if source_bones is not None else names)
        chains = [types.SimpleNamespace(chain_name=name) for name in ("LeftArm", "RightArm")]
        target_rig = Rig()
        target_rig.controller = types.SimpleNamespace(get_skeletal_mesh=lambda: target_mesh, get_retarget_chains=lambda: chains)
        source_rig = Rig()
        source_rig.controller = types.SimpleNamespace(get_skeletal_mesh=lambda: source_mesh, get_retarget_chains=lambda: chains)
        asset = Retargeter()
        kinds = ["IKRetargetFKChainsController", "IKRetargetRootMotionController", "IKRetargetCurveRemapController", "IKRetargetPinBoneController"]
        if missing_operation:
            kinds.remove(missing_operation)
        asset.controller = types.SimpleNamespace(
            get_ik_rig=lambda side: target_rig,
            get_preview_mesh=lambda side: target_mesh,
            get_num_retarget_ops=lambda: len(kinds),
            get_op_controller=lambda index: types.SimpleNamespace(get_class=lambda: types.SimpleNamespace(get_name=lambda: kinds[index])),
            get_op_name=lambda index: "Utility IK Bones" if kinds[index] == "IKRetargetPinBoneController" else kinds[index],
        )
        path = "/Game/_Project/Rigs/Retargeter"
        target = "/Game/_Project/Rigs/Target"
        source = "/Game/_ThirdParty/SourceRig"
        values = {path: asset, target: target_rig, source: source_rig}
        writes = Mock(side_effect=AssertionError("预检拒绝前不得请求写入"))
        unreal = types.SimpleNamespace(
            EditorAssetLibrary=types.SimpleNamespace(does_asset_exist=lambda value: value in values,
                                                   find_package_referencers_for_asset=lambda value: [path, *foreign_refs]),
            load_asset=lambda value: values.get(value),
            IKRetargeter=Retargeter,
            IKRigDefinition=Rig,
            IKRetargeterController=types.SimpleNamespace(get_controller=lambda value: value.controller),
            IKRigController=types.SimpleNamespace(get_controller=lambda value: value.controller),
            RetargetSourceOrTarget=types.SimpleNamespace(SOURCE=0, TARGET=1),
        )
        scope = {"unreal": unreal, "require_asset_write": writes, "json": json}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "hand_contact", "exec"), scope)
        return scope[function.name], path, source, target, writes

    def test_third_party_output_rejected_before_loading(self):
        function, path, source, _, writes = self.fixture()
        with self.assertRaisesRegex(RuntimeError, "自有资产"):
            function([path], [source], "/Game/_ThirdParty/Target")
        writes.assert_not_called()

    def test_missing_actual_hand_rejected_before_writes(self):
        function, path, source, target, writes = self.fixture(source_bones=["hand_l"])
        with self.assertRaisesRegex(RuntimeError, "实际双手"):
            function([path], [source], target)
        writes.assert_not_called()

    def test_missing_curve_operation_rejected_before_writes(self):
        function, path, source, target, writes = self.fixture(missing_operation="IKRetargetCurveRemapController")
        with self.assertRaisesRegex(RuntimeError, "唯一 FK"):
            function([path], [source], target)
        writes.assert_not_called()

    def test_shared_target_rig_rejected_before_writes(self):
        function, path, source, target, writes = self.fixture(foreign_refs=["/Game/_Project/OtherUser"])
        with self.assertRaisesRegex(RuntimeError, "其它制作链路"):
            function([path], [source], target)
        writes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
