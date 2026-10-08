import ast
import json
import math
import re
from pathlib import Path
import unittest
from unittest.mock import Mock


class BloodResidueToolTests(unittest.TestCase):
    """/** 血迹构建与纯表现诊断的失败边界 */"""

    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "Scripts/BBBHitReactionToolset.py").read_text(encoding="utf-8-sig"))
        methods = next(node for node in tree.body if isinstance(node, ast.ClassDef)).body
        self.engine = Mock()
        self.engine.Texture = Mock
        self.engine.load_asset.return_value = Mock()
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = False
        self.engine.SystemLibrary.get_command_line.return_value = "-RenderOffscreen"
        self.access = Mock()
        scope = {"unreal": self.engine, "json": json, "math": math, "re": re, "require_asset_write": self.access}
        chosen = []
        for node in methods:
            if isinstance(node, ast.FunctionDef) and node.name in {"create_blood_residue_material", "preview_blood_residue", "inspect_blood_residue", "start_blood_residue_capture"}:
                node.decorator_list = []
                chosen.append(node)
                for parameter in node.args.args:
                    self.assertNotIn("list[list", ast.unparse(parameter.annotation))
        exec(compile(ast.Module(body=chosen, type_ignores=[]), "blood_tools_test", "exec"), scope)
        self.functions = scope

    def test_existing_or_vendor_material_cannot_be_overwritten(self):
        create = self.functions["create_blood_residue_material"]
        with self.assertRaises(RuntimeError):
            create("/Game/_ThirdParty/Material", "/Game/Mask", "/Game/Noise")
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = True
        with self.assertRaises(RuntimeError):
            create("/Game/_Project/Material", "/Game/Mask", "/Game/Noise")
        self.access.assert_not_called()

    def test_write_access_is_required_and_native_failure_is_not_success(self):
        create = self.functions["create_blood_residue_material"]
        self.access.side_effect = RuntimeError("权限拒绝")
        with self.assertRaises(RuntimeError):
            create("/Game/_Project/Material", "/Game/Mask", "/Game/Noise")
        self.engine.BBBBloodResidueEditorLibrary.create_residue_material.assert_not_called()
        self.access.side_effect = None
        self.engine.BBBBloodResidueEditorLibrary.create_residue_material.return_value = "ERROR: 保存失败"
        with self.assertRaises(RuntimeError):
            create("/Game/_Project/Material", "/Game/Mask", "/Game/Noise")

    def test_invalid_or_unbounded_contacts_prevent_native_publish(self):
        preview = self.functions["preview_blood_residue"]
        for positions in ([], [[0, 0, 0]] * 65, [[0, 0]], [[0, 0, float("inf")]], ["bad"]):
            with self.assertRaises(RuntimeError):
                preview("/Game/Settings", json.dumps(positions), [1, 0, 0], [1, 0, 0])
        self.engine.BBBBloodResidueEditorLibrary.preview_residue.assert_not_called()

    def test_nullrhi_and_absent_world_cannot_claim_visual_acceptance(self):
        preview = self.functions["preview_blood_residue"]
        self.engine.SystemLibrary.get_command_line.return_value = "-NullRHI"
        with self.assertRaises(RuntimeError):
            preview("/Game/Settings", "[[0,0,0]]", [1, 0, 0], [1, 0, 0])
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        with self.assertRaises(RuntimeError):
            self.functions["inspect_blood_residue"]()
        self.engine.BBBBloodResidueEditorLibrary.preview_residue.assert_not_called()

    def test_engine_vector_arrays_are_normalized_before_publish(self):
        self.engine.BBBBloodResidueEditorLibrary.preview_residue.return_value = "OK: 已发布"
        result = self.functions["preview_blood_residue"]("/Game/Settings", "[[0,0,0]]", (1, 0, 0), (0, 0, 1))
        self.assertTrue(result.startswith("OK:"))
        self.engine.BBBBloodResidueEditorLibrary.preview_residue.assert_called_once()

    def test_capture_duration_and_scene_are_bounded_before_creation(self):
        capture = self.functions["start_blood_residue_capture"]
        for duration in (0, 3.9, 130.1, float("nan"), float("inf")):
            with self.assertRaises(RuntimeError):
                capture("/Game/Settings", "floor", "Task", duration_seconds=duration)
        for scale in (0, .9, 20.1, float("nan"), float("inf")):
            with self.assertRaises(RuntimeError):
                capture("/Game/Settings", "floor", "Task", aging_time_scale=scale)
        with self.assertRaises(RuntimeError):
            capture("/Game/Settings", "wrong", "Task")
        with self.assertRaises(RuntimeError):
            capture("/Game/Settings", "floor", "../Task")
        self.engine.get_editor_subsystem.assert_not_called()


if __name__ == "__main__":
    unittest.main()
