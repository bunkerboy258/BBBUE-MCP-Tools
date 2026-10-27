import ast
import math
from pathlib import Path
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class WeaponLocomotionWeightBoundaryTests(unittest.TestCase):
    """/** 承重构图的数值和目标写入边界 */"""

    def setUp(self):
        """/** @return 在无编辑器环境提取输入预检并隔离资产写入 */"""
        source = ROOT / "Scripts/BBBWeaponLocomotionWeight.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        methods = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name in {"validate_weight_settings", "configure_weapon_locomotion_weight"}]
        self.engine = Mock()
        self.access = Mock()
        namespace = {"math": math, "unreal": self.engine, "require_asset_write": self.access}
        exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), "exec"), namespace)
        self.validate = namespace["validate_weight_settings"]
        self.configure = namespace["configure_weapon_locomotion_weight"]
        self.values = (["Rifle", "Pistol"], [0.24, 0.12], [1.1, 0.5], [0.8, 0.4], 0.18, 0.28)

    def test_recommended_rifle_pistol_values_are_accepted(self):
        """/** @return 步枪与手枪参数符合保守幅度约束 */"""
        self.validate(*self.values)

    def test_incomplete_and_duplicate_columns_are_rejected(self):
        """/** @return 映射缺项或重复子层不能进入编辑器写入 */"""
        for layers, support in [([], []), (["Rifle", "Rifle"], [0.24, 0.12]), (["Rifle", "Pistol"], [0.24])]:
            with self.assertRaises(RuntimeError):
                self.validate(layers, support, [1.1, 0.5], [0.8, 0.4], 0.18, 0.28)

    def test_nonfinite_negative_and_excessive_amplitudes_are_rejected(self):
        """/** @return 无效数值和超限响应不会生成资产编辑 */"""
        for column, invalid in [(1, 0.41), (2, 2.01), (3, 1.51), (1, -0.1), (2, math.nan), (3, math.inf)]:
            values = list(self.values)
            values[column] = [invalid, values[column][1]]
            with self.assertRaises(RuntimeError):
                self.validate(*values)

    def test_invalid_blend_order_and_duration_are_rejected(self):
        """/** @return 起停混合不长于匀速且拒绝极短或非有限值 */"""
        for transition, cruise in [(0.3, 0.2), (0.1, 0.28), (0.18, 0.41), (math.nan, 0.28)]:
            with self.assertRaises(RuntimeError):
                self.validate(*self.values[:4], transition, cruise)

    def test_duplicate_or_nonproject_write_scope_rejected_before_load(self):
        """/** @return 重复包和非自有包在加载目标前拒绝 */"""
        for main in ["/Game/_Project/Base", "/Game/_ThirdParty/Main"]:
            with self.assertRaises(RuntimeError):
                self.configure(main, "/Game/_Project/Base", ["/Game/_Project/Rifle"], [0.24], [1.1], [0.8], [], 0.18, 0.28)
        self.engine.load_asset.assert_not_called()

    def test_permission_failure_prevents_any_graph_or_variable_mutation(self):
        """/** @return 写入拒绝时不创建字段 不更改图表也不保存 */"""
        self.engine.AnimBlueprint = Mock
        main, base, child = Mock(), Mock(), Mock()
        base.generated_class.return_value = "BaseClass"
        child.get_blueprint_parent_class.return_value = "BaseClass"
        self.engine.load_asset.side_effect = [main, base, child]
        self.access.side_effect = RuntimeError("write denied")
        with self.assertRaises(RuntimeError):
            self.configure("/Game/_Project/Main", "/Game/_Project/Base", ["/Game/_Project/Rifle"],
                [0.24], [1.1], [0.8], [], 0.18, 0.28)
        self.engine.BlueprintEditorLibrary.assert_not_called()
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
