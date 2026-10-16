import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CharacterPoseTempRouteTests(unittest.TestCase):
    """/** 验证实际角色截图按任务隔离且拒绝路径越界 */"""

    def test_pose_uses_shared_focused_capture(self):
        """/** @return 取景和补光复用同一实现且保留尺寸参数 */"""
        tree = ast.parse((ROOT / "Scripts/BBBAnimationMigrationToolset.py").read_text(encoding="utf-8-sig"))
        function = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == "capture_pie_character_pose")
        calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "_capture_image"]
        self.assertEqual(len(calls), 1)
        self.assertEqual([node.id for node in calls[0].args][-3:], ["focus_bone", "width", "height"])
        self.assertNotIn("spawn_transient_pie_actor", ast.unparse(function))

    def test_invalid_destinations_fail_before_world_access(self):
        """/** @return 非法目录和无归属文件名均不进入 UE */"""
        tree = ast.parse((ROOT / "Scripts/BBBAnimationMigrationToolset.py").read_text(encoding="utf-8-sig"))
        function = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == "capture_pie_character_pose")
        function.decorator_list = []
        namespace = {"os": __import__("os")}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), "pose_route", "exec"), namespace)
        for destination in ("old.png", "../other.png", "task/../other.png", "task/C:other.png", "/root.png", "task/.png"):
            with self.subTest(destination=destination), self.assertRaises(RuntimeError):
                namespace["capture_pie_character_pose"]([0, 1, 2], destination)


class AnimationCurveWritePolicyTests(unittest.TestCase):
    """/** 验证曲线写入遵守无备份和不办理源控操作的边界 */"""

    def test_curve_write_never_creates_backup_or_queries_perforce(self):
        """/** @return 保留资产写入预检与回读且没有备份或 Perforce 副作用 */"""
        tree = ast.parse((ROOT / "Scripts/BBBGenericEditorToolset.py").read_text(encoding="utf-8-sig"))
        function = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == "replace_animation_float_curve")
        calls = [ast.unparse(node.func) for node in ast.walk(function) if isinstance(node, ast.Call)]
        self.assertIn("require_write_access", calls)
        self.assertIn("os.access", calls)
        self.assertEqual(calls.count("library.get_float_keys"), 3)
        for forbidden in ("shutil.copy2", "os.makedirs", "open", "unreal.SourceControl.query_file_state",
                          "AssetTools.is_checked_out", "AssetTools.can_edit_asset"):
            self.assertNotIn(forbidden, calls)


if __name__ == "__main__":
    unittest.main()
