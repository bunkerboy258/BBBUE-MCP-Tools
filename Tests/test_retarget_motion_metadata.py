import ast
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class RetargetMotionMetadataTests(unittest.TestCase):
    def fixture(self, omit_curves=False):
        tree = ast.parse((ROOT / "Scripts/BBBRetargetAssetAuditToolset.py").read_text(encoding="utf-8"))
        definition = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        method = next(node for node in definition.body if isinstance(node, ast.FunctionDef) and node.name == "configure_fk_retargeter")
        method.decorator_list = []
        bones = ["root", "pelvis", "hand_l", "hand_r", "foot_l", "foot_r", "ik_foot_root", "ik_hand_root", "ik_hand_gun", "ik_foot_l", "ik_foot_r", "ik_hand_l", "ik_hand_r"]
        mesh = types.SimpleNamespace(get_editor_property=lambda name: object())
        names = ["Spine", "Neck", "Head", "LeftArm", "RightArm", "LeftLeg", "RightLeg", "LeftIndex", "RightIndex"]
        rig = types.SimpleNamespace(
            get_skeletal_mesh=lambda: mesh,
            get_retarget_chains=lambda: [types.SimpleNamespace(chain_name=name) for name in names],
            get_retarget_root=lambda: "pelvis",
        )

        class Op:
            def __init__(self, kind, settings):
                self.kind = kind
                self.settings = settings
                self.pairs = {}

            def get_class(self):
                return types.SimpleNamespace(get_name=lambda: self.kind)

            def get_settings(self):
                return self.settings

            def set_settings(self, value):
                self.settings = value

            def set_source_root_bone(self, value):
                self.source_root = value

            def set_target_root_bone(self, value):
                self.target_root = value

            def set_target_pelvis_bone(self, value):
                self.target_pelvis = value

            def set_bone_pair(self, parent, helper):
                self.pairs[helper] = parent

            def get_all_bone_pairs(self):
                return self.pairs

        fk = Op("IKRetargetFKChainsController", types.SimpleNamespace(chains_to_retarget=[types.SimpleNamespace(target_chain_name=name) for name in names]))
        root = Op("IKRetargetRootMotionController", types.SimpleNamespace())
        curves = Op("IKRetargetCurveRemapController", types.SimpleNamespace(copy_all_source_curves=False, remap_curves=True))
        ops = [fk, Op("IKRetargetRunIKRigController", None), root, Op("IKRetargetPinBoneController", None)]
        if not omit_curves:
            ops.append(curves)
        writes = []

        def add_op(path):
            ops.append(Op("IKRetargetPinBoneController", None))
            return len(ops) - 1

        controller = types.SimpleNamespace(
            get_ik_rig=lambda side: rig,
            set_preview_mesh=lambda *args: None,
            auto_map_chains=lambda *args: None,
            get_source_chain=lambda name: name,
            auto_align_all_bones=lambda *args: None,
            get_num_retarget_ops=lambda: len(ops),
            get_op_controller=lambda index: ops[index],
            remove_retarget_op=lambda index: ops.pop(index),
            add_retarget_op=add_op,
            set_op_name=lambda *args: None,
        )
        asset = types.SimpleNamespace(modify=lambda: None)
        unreal = types.SimpleNamespace(
            IKRetargeter=object,
            IKRetargeterController=types.SimpleNamespace(get_controller=lambda value: controller),
            IKRigController=types.SimpleNamespace(get_controller=lambda value: value),
            RetargetSourceOrTarget=types.SimpleNamespace(SOURCE=0, TARGET=1),
            AnimPoseExtensions=types.SimpleNamespace(get_reference_pose=lambda value: value, get_bone_names=lambda pose: bones),
            AutoMapChainType=types.SimpleNamespace(EXACT=0),
            RetargetAutoAlignMethod=types.SimpleNamespace(CHAIN_TO_CHAIN=0),
            FKChainTranslationMode=types.SimpleNamespace(NONE="none"),
            FKChainRotationMode=types.SimpleNamespace(ONE_TO_ONE="one", INTERPOLATED="interpolated"),
            RootMotionSource=types.SimpleNamespace(COPY_FROM_SOURCE_ROOT="copy", GENERATE_FROM_TARGET_PELVIS="generate"),
            RootMotionHeightSource=types.SimpleNamespace(COPY_HEIGHT_FROM_SOURCE="copy_height", SNAP_TO_GROUND="ground"),
            EditorAssetLibrary=types.SimpleNamespace(save_loaded_asset=lambda value, force: writes.append(value) or True),
        )
        scope = {"unreal": unreal, "json": json, "_asset": lambda *args: asset}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "configure_retargeter", "exec"), scope)
        return scope["configure_fk_retargeter"], fk, root, curves, ops, writes

    def test_configuration_keeps_root_height_curves_and_utility_tracks(self):
        run, fk, root, curves, ops, writes = self.fixture()
        with patch.dict(sys.modules, {"BBBAssetWritePolicy": types.SimpleNamespace(require_asset_write=lambda assets: None)}):
            result = json.loads(run("/Game/Retargeter"))
        modes = {str(chain.target_chain_name): chain.rotation_mode for chain in fk.settings.chains_to_retarget}
        self.assertEqual(modes["Spine"], "interpolated")
        self.assertEqual(modes["Neck"], "interpolated")
        self.assertEqual(modes["LeftArm"], "one")
        self.assertEqual(root.source_root, "root")
        self.assertEqual(root.settings.root_motion_source, "copy")
        self.assertEqual(root.settings.root_height_source, "copy_height")
        self.assertTrue(curves.settings.copy_all_source_curves)
        self.assertFalse(curves.settings.remap_curves)
        self.assertEqual(len(result["ikPairs"]), 7)
        self.assertNotIn("IKRetargetRunIKRigController", [op.kind for op in ops])
        self.assertEqual(len(writes), 1)

    def test_missing_curve_operation_cannot_be_saved_as_complete(self):
        run, fk, root, curves, ops, writes = self.fixture(omit_curves=True)
        with patch.dict(sys.modules, {"BBBAssetWritePolicy": types.SimpleNamespace(require_asset_write=lambda assets: None)}):
            with self.assertRaisesRegex(RuntimeError, "曲线"):
                run("/Game/Retargeter")
        self.assertEqual(writes, [])


if __name__ == "__main__":
    unittest.main()
