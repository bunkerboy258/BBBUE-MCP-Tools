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


class AnimationCurveTempRouteTests(unittest.TestCase):
    """/** 验证曲线编辑备份使用独立任务临时目录 */"""

    def test_curve_backup_uses_saved_temp_operation_directory(self):
        """/** @return 不加载 UE 核验目录构造与操作隔离 */"""
        tree = ast.parse((ROOT / "Scripts/BBBGenericEditorToolset.py").read_text(encoding="utf-8-sig"))
        function = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == "replace_animation_float_curve")
        assignment = next(node for node in ast.walk(function)
                          if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == "backup_directory"
                                  for target in node.targets))
        arguments = assignment.value.args
        self.assertEqual(len(arguments), 3)
        self.assertEqual(arguments[1].value, "temp")
        self.assertIsInstance(arguments[2], ast.BinOp)
        self.assertEqual(arguments[2].left.value, "AnimationCurveEdit_")
        self.assertEqual(arguments[2].right.id, "timestamp")


if __name__ == "__main__":
    unittest.main()
