import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Scripts'))

import BBBMcpCapabilities as capabilities


class StaticLightingContractTests(unittest.TestCase):
    """/** 验证原生数组默认值不会破坏整个工具目录及独立构建数据的范围 */"""

    def contract(self):
        """/** @return 官方后端字符串参数经过公开数组编解码后的契约 */"""
        return capabilities.tool_contract('BBBLevelEditingToolset', 'build_static_lighting', {
            'type': 'object',
            'properties': {
                'expected_level': {'type': 'string'},
                'build_data_path': {'type': 'string'},
                'action': {'type': 'string', 'default': 'status'},
                'quality': {'type': 'integer', 'default': 0},
                'actor_paths_json': {'type': 'string', 'default': '[]'},
            },
            'required': ['expected_level', 'build_data_path'],
        })

    def test_empty_native_array_default_compiles(self):
        """/** @return 空目标列表具有有效公开默认值 且传回后端为 JSON 字符串 */"""
        contract = self.contract()
        self.assertEqual(contract['parameters']['properties']['actor_paths']['default'], [])
        self.assertEqual(contract['codecs']['actor_paths'], {
            'field': 'actor_paths_json', 'encoding': 'json'})
        self.assertNotIn('actor_paths_json', contract['parameters']['properties'])

    def test_native_lighting_schemas_cover_registered_tools(self):
        """/** @return 新增光照入口均进入原生目录基线 防止注册漏项 */"""
        baseline = json.loads((Path(__file__).parent / 'tool_schema_baseline.json').read_text(encoding='utf-8'))
        source = capabilities.source_index('BBBLevelEditingToolset')['public_tools']
        for name in ('inspect_static_lighting', 'build_static_lighting'):
            self.assertIn(name, baseline['BBBLevelEditingToolset'])
            self.assertIn(name, source)

    def test_map_and_generated_data_are_both_scoped(self):
        """/** @return 构建数据与地图均进入精确范围 不扩大为地图目录 */"""
        packages, scoped = capabilities.write_scope(self.contract(), {
            'expected_level': '/Game/Maps/Example',
            'build_data_path': '/Game/Maps/Example_BuiltData',
        })
        self.assertTrue(scoped)
        self.assertEqual(set(packages), {'/Game/Maps/Example', '/Game/Maps/Example_BuiltData'})


if __name__ == '__main__':
    unittest.main()
