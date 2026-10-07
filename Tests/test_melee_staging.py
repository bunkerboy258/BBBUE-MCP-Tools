import ast
import hashlib
from pathlib import Path
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MeleeStagingTests(unittest.TestCase):
    """/** 独立宿主暂存必须保护正式资产及并行更改 */"""

    def setUp(self):
        """/** @return 创建独立正式项目和宿主路径 */"""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.source = root / "SourceProject"
        self.host = root / "HostProject"
        self.task = self.host / "Saved/temp/Task"
        self.file = self.source / "Content/_Project/Test.uasset"
        self.file.parent.mkdir(parents=True)
        self.file.write_bytes(b"original")
        self.digest = hashlib.sha256(self.file.read_bytes()).hexdigest()
        self.loaded = []
        self.state = types.SimpleNamespace(is_valid=True, is_unknown=False, is_deleted=False,
            is_checked_out_other=False, is_conflicted=False, can_edit=True, is_checked_out=True,
            is_added=False, is_source_controlled=True, is_current=True)
        control = types.SimpleNamespace(is_enabled=lambda: True, is_available=lambda: True,
            current_provider=lambda: "Perforce", query_file_states=lambda *a, **k: [self.state])
        unreal = types.SimpleNamespace(Paths=types.SimpleNamespace(project_dir=lambda: str(self.host)),
            SourceControl=control, load_asset=lambda path: self.loaded.append(path))
        tree = ast.parse((ROOT / "Scripts/BBBMeleeToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef) and node.name == "stage_character_aim_gate")
        method.decorator_list = []
        runtime = {"unreal": unreal, "Path": Path, "hashlib": hashlib}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "BBBMeleeToolset.py", "exec"), runtime)
        self.call = runtime[method.name]

    def invoke(self, **changes):
        """/** @param changes 参数覆盖 @return 暂存预检结果 */"""
        arguments = dict(blueprint_path="/Game/_Project/Test", node_path="/Game/_Project/Test.Test:Graph.Node",
            task_directory=str(self.task), source_project_directory=str(self.source), expected_source_sha256=self.digest)
        arguments.update(changes)
        return self.call(**arguments)

    def test_changed_source_rejects_before_loading(self):
        """/** @return 并行文件改变后禁止打开和修改目标 */"""
        self.file.write_bytes(b"parallel edit")
        with self.assertRaisesRegex(RuntimeError, "正式目标已变化"):
            self.invoke()
        self.assertEqual(self.loaded, [])
        self.assertEqual(self.file.read_bytes(), b"parallel edit")

    def test_invalid_source_control_rejects_before_loading(self):
        """/** @return 未签出 他人占用 冲突和非最新版本均拒绝 */"""
        for key, value in (("is_checked_out", False), ("is_checked_out_other", True),
                           ("is_conflicted", True), ("is_current", False), ("is_unknown", True), ("is_deleted", True)):
            previous = getattr(self.state, key)
            setattr(self.state, key, value)
            with self.assertRaises(RuntimeError):
                self.invoke()
            setattr(self.state, key, previous)
        self.assertEqual(self.loaded, [])

    def test_task_and_package_must_stay_in_authorized_directories(self):
        """/** @return 禁止正式项目执行 暂存目录越界和第三方目标 */"""
        for changes in ({"source_project_directory": str(self.host)},
                        {"task_directory": str(self.source)},
                        {"blueprint_path": "/Game/_ThirdParty/Test"},
                        {"blueprint_path": "/Game/_Project/../Test"}):
            with self.assertRaises(RuntimeError):
                self.invoke(**changes)
        self.assertEqual(self.loaded, [])


if __name__ == "__main__":
    unittest.main()
