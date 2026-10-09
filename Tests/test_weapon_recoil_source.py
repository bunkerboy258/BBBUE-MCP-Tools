import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "Scripts/BBBAnimationMigrationToolset.py").read_text(encoding="utf-8-sig"))
TOOLSET = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "BBBAnimationMigrationToolset")
FUNCTION = next(node for node in TOOLSET.body if isinstance(node, ast.FunctionDef) and node.name == "configure_weapon_recoil_animation_source")


class WeaponRecoilSourceTests(unittest.TestCase):
    """/** 检查专属后坐力资产接入的最小写入范围 */"""

    def test_no_hardcoded_asset_or_graph_rebuild(self):
        """/** @return 不使用固定资产路径 不删除原图节点 */"""
        strings = [node.value for node in ast.walk(FUNCTION) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        self.assertFalse(any(value.startswith("/Game/") for value in strings))
        attributes = [node.attr for node in ast.walk(FUNCTION) if isinstance(node, ast.Attribute)]
        self.assertNotIn("remove_nodes", attributes)
        self.assertNotIn("remove_function_graph", attributes)

    def test_preflight_before_write_and_compile_before_save(self):
        """/** @return 写前结构预检 编译成功才保存目标 */"""
        calls = [node for node in ast.walk(FUNCTION) if isinstance(node, ast.Call)]
        write = next(node.lineno for node in calls if isinstance(node.func, ast.Name) and node.func.id == "require_asset_write")
        add = next(node.lineno for node in calls if isinstance(node.func, ast.Attribute) and node.func.attr == "add_object_variable")
        compile_line = next(node.lineno for node in calls if isinstance(node.func, ast.Attribute) and node.func.attr == "compile_blueprint")
        save = next(node.lineno for node in calls if isinstance(node.func, ast.Attribute) and node.func.attr == "save_loaded_asset")
        self.assertLess(write, add)
        self.assertLess(add, compile_line)
        self.assertLess(compile_line, save)
        self.assertTrue(any(node.lineno < write for node in ast.walk(FUNCTION) if isinstance(node, ast.Raise)))

    def test_clear_static_sequence_and_bind_snapshot(self):
        """/** @return 清除共用静态序列 只绑定当前武器动画快照 */"""
        calls = [node for node in ast.walk(FUNCTION) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        clear = next(node for node in calls if node.func.attr == "set_editor_property" and isinstance(node.args[0], ast.Constant) and node.args[0].value == "sequence")
        self.assertIsNone(clear.args[1].value)
        bind = next(node for node in calls if node.func.attr == "bind_animation_node_input")
        self.assertEqual(ast.literal_eval(bind.args[1]), "Sequence")
        self.assertEqual(ast.literal_eval(bind.args[2]), ["WeaponRecoilAnimation"])


if __name__ == "__main__":
    unittest.main()
