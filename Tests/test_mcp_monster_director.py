from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))
import BBBMcpCapabilities as capabilities


class MonsterDirectorContractTests(unittest.TestCase):
    """/** 验证导演创建只能写明确目标 测试宿主校验保持只读 */"""

    def test_creation_has_explicit_scope_and_native_dependency(self):
        """/** @return 完整路径数组属于明确写入范围 原生创建函数必须存在 */"""
        contract = capabilities.tool_contract("BBBGenericEditorToolset", "create_monster_director_assets", {"type": "object"})
        paths = ["/Game/_Project/Mass/Monster/Director/MEC_BBBMonsterDirector"]
        targets, scoped = capabilities.write_scope(contract, {"asset_paths": paths})
        self.assertEqual((contract["access"], contract["world"]), ("write", "editor"))
        self.assertTrue(scoped)
        self.assertEqual(targets, [paths])
        requirements = capabilities.native_requirements("BBBGenericEditorToolset", "create_monster_director_assets")
        self.assertEqual(requirements["BBBMonsterDirectorEditorLibrary"], {"create_basic_assets"})

    def test_validation_is_read_only(self):
        """/** @return 校验不会被调度为资产写入 原生校验函数必须存在 */"""
        contract = capabilities.tool_contract("BBBGenericEditorToolset", "validate_monster_director_assets", {"type": "object"})
        self.assertEqual(contract["access"], "read")
        requirements = capabilities.native_requirements("BBBGenericEditorToolset", "validate_monster_director_assets")
        self.assertEqual(requirements["BBBMonsterDirectorEditorLibrary"], {"validate_basic_assets"})

    def test_automation_can_run_in_registered_test_host(self):
        """/** @return 自动化属于运行控制 可以进入独立测试宿主 资产写入仍受宿主只读限制 */"""
        contract = capabilities.tool_contract("BBBGenericEditorToolset", "run_automation_tests", {"type": "object"})
        self.assertEqual((contract["access"], contract["world"]), ("pie", "any"))


if __name__ == "__main__":
    unittest.main()
