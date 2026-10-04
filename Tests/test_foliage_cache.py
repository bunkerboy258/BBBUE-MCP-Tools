import ast
from pathlib import Path
import types
import unittest


class FoliageCacheTests(unittest.TestCase):
    """/** 植被缓存修复入口的拒绝条件核验 */"""

    def setUp(self):
        """/** @return 隔离原生调用与签出依赖 不加载编辑器 */"""
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "repair_foliage_base_cache")
        method.decorator_list = []
        self.calls = []
        self.pie = False
        self.dirty = []
        self.runtime = {
            "_move_path": lambda path: path,
            "_move_dirty_packages": lambda: self.dirty,
            "_require_move_checkout": lambda paths, targets: self.calls.append("checkout"),
            "unreal": types.SimpleNamespace(
                LevelEditorSubsystem=object,
                get_editor_subsystem=lambda value: types.SimpleNamespace(is_in_play_in_editor=lambda: self.pie),
                BBBAssetRepairEditorLibrary=types.SimpleNamespace(repair_foliage_base_cache=lambda path, dry: self.calls.append("native") or "result"),
            ),
        }
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), self.runtime)
        self.repair = self.runtime[method.name]

    def test_preview_does_not_checkout(self):
        """/** @return 预检只进入原生只读分支 */"""
        self.repair("/Game/World")
        self.assertEqual(self.calls, ["native"])

    def test_pie_blocks_native_call(self):
        """/** @return PIE 期间禁止修改编辑器世界 */"""
        self.pie = True
        with self.assertRaises(RuntimeError):
            self.repair("/Game/World", False)
        self.assertEqual(self.calls, [])

    def test_dirty_packages_block_checkout(self):
        """/** @return 无关未保存工作阻止修复 */"""
        self.dirty = ["/Game/OtherWork"]
        with self.assertRaises(RuntimeError):
            self.repair("/Game/World", False)
        self.assertEqual(self.calls, [])

    def test_checkout_precedes_native_mutation(self):
        """/** @return 修改前必须完成独占签出核验 */"""
        self.repair("/Game/World", False)
        self.assertEqual(self.calls, ["checkout", "native"])

    def test_checkout_failure_blocks_native_mutation(self):
        """/** @return 签出失败不会进入原生修改 */"""
        def reject(paths, targets):
            raise RuntimeError("locked")
        self.runtime["_require_move_checkout"] = reject
        with self.assertRaises(RuntimeError):
            self.repair("/Game/World", False)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
