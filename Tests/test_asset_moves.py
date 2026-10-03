import ast
import json
from pathlib import Path
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AssetMoveTests(unittest.TestCase):
    """/** 资产迁移的路径与类型识别回归检查 */"""

    def setUp(self):
        """/** @return 隔离加载纯辅助函数 不注册编辑器工具 */"""
        source = ROOT / "Scripts/BBBAssetMaintenanceToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        module = ast.Module(body=nodes, type_ignores=[])
        self.runtime = {"json": json, "os": __import__("os"), "re": __import__("re")}
        exec(compile(module, str(source), "exec"), self.runtime)

    def test_primary_asset_filter(self):
        """/** @return 蓝图生成对象不参与独立包移动 */"""
        main = types.SimpleNamespace(is_u_asset=lambda: True)
        generated = types.SimpleNamespace(is_u_asset=lambda: False)
        self.assertEqual(self.runtime["_move_primary_assets"]([main, generated]), [main])

    def test_class_path_is_stable(self):
        """/** @return 类型名称不使用结构体地址文本 */"""
        for name in ("ObjectRedirector", "World", "AnimSequence"):
            path = types.SimpleNamespace(package_name="/Script/Engine", asset_name=name)
            self.assertEqual(self.runtime["_move_class_path"](path), "/Script/Engine." + name)

    def test_reject_unsafe_paths(self):
        """/** @return 文件系统路径与受保护关卡数据被拒绝 */"""
        for path in (None, "/Game", "/Engine/Test", "E:/Game/Test", "/Game/A.A", "/Game/A/../B", "/Game/__ExternalActors__/A", "/Game/__externalobjects__/A"):
            with self.subTest(path=path):
                with self.assertRaises(RuntimeError):
                    self.runtime["_move_path"](path)

    def test_mapping_validation(self):
        """/** @return 大小写改名与空映射不能通过 */"""
        for request in ([], [{"source": "/Game/Old", "destination": "/Game/old"}], [{"source": "/Game/A", "destination": "/Game/A"}]):
            with self.assertRaises(RuntimeError):
                self.runtime["_move_requests"](json.dumps(request))

    def test_disk_path_stays_in_content(self):
        """/** @return 精确包路径映射到正确的 Content 文件 */"""
        with tempfile.TemporaryDirectory() as directory:
            self.runtime["unreal"] = types.SimpleNamespace(Paths=types.SimpleNamespace(project_content_dir=lambda: directory))
            result = self.runtime["_move_filename"]("/Game/Folder/Asset")
            self.assertEqual(Path(result), (Path(directory) / "Folder/Asset.uasset").resolve())
            with self.assertRaises(RuntimeError):
                self.runtime["_move_filename"]("/Game/../../Outside")

    def test_move_and_verify_use_canonical_classes(self):
        """/** @return 原生对象与注册表类型检查均使用稳定类型辅助函数 */"""
        source = (ROOT / "Scripts/BBBAssetMaintenanceToolset.py").read_text(encoding="utf-8-sig")
        self.assertNotIn("str(asset_data.asset_class_path)", source)
        self.assertNotIn("str(target_data[0].asset_class_path)", source)
        self.assertNotIn("str(asset.get_class().get_class_path_name())", source)
        tree = ast.parse(source)
        names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
