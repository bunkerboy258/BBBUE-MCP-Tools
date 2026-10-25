import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class MotionMatchingTests(unittest.TestCase):
    """/** 检查数据库输入在写资产前拒绝 */"""

    def setUp(self):
        """/** @return 独立假引擎及真实工具实现 */"""
        self.unreal = types.SimpleNamespace(Skeleton=type("Skeleton", (), {}), PoseSearchSchema=type("Schema", (), {}), AnimSequence=type("Sequence", (), {}))
        path = Path(__file__).resolve().parents[1] / "Scripts/BBBMotionMatchingAssets.py"
        spec = importlib.util.spec_from_file_location("motion_matching_test_subject", path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"unreal": self.unreal}):
            spec.loader.exec_module(self.module)
        self.create = Mock(side_effect=AssertionError("不得开始写入"))
        self.module._create = self.create

    def test_schema_rejects_invalid_sampling(self):
        """/** @return 非有限 重复 乱序及越界采样拒绝 */"""
        self.module._load = Mock()
        for offsets, rate in [([float("nan")], 30), ([0, 0], 30), ([1, 0], 30), ([0], 0), ([0], 241)]:
            with self.subTest(offsets=offsets, rate=rate), self.assertRaises(RuntimeError):
                self.module.create_schema("/Game/_Project/PSS", "/Skeleton", ["pelvis"], offsets, rate)
        self.create.assert_not_called()

    def test_schema_rejects_duplicate_bones(self):
        """/** @return 重复采样骨在创建前拒绝 */"""
        self.module._load = Mock()
        with self.assertRaises(RuntimeError):
            self.module.create_schema("/Game/_Project/PSS", "/Skeleton", ["pelvis", "pelvis"], [0])
        self.create.assert_not_called()

    def test_database_rejects_empty_and_duplicate_lists(self):
        """/** @return 空数据库及重复动画在创建前拒绝 */"""
        skeleton = object()
        role = Mock()
        role.get_editor_property.return_value = skeleton
        schema = Mock()
        schema.get_editor_property.return_value = [role]
        self.module._load = Mock(return_value=schema)
        for paths in [[], ["/A", "/A"]]:
            with self.subTest(paths=paths), self.assertRaises(RuntimeError):
                self.module.create_database("/Game/_Project/PSD", "/Schema", paths)
        self.create.assert_not_called()

    def test_database_rejects_different_skeleton(self):
        """/** @return 不同骨架不能进入数据库 */"""
        role = Mock()
        role.get_editor_property.return_value = object()
        schema = Mock()
        schema.get_editor_property.return_value = [role]
        animation = Mock()
        animation.get_editor_property.return_value = object()
        self.module._load = Mock(side_effect=[schema, animation])
        with self.assertRaisesRegex(RuntimeError, "骨架"):
            self.module.create_database("/Game/_Project/PSD", "/Schema", ["/Animation"])
        self.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
