import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Scripts'))
from MCP.mcp_contracts import backend_arguments, compile_contract


class NativeParameterShapeTests(unittest.TestCase):
    """/** 原生参数约束不能改变传输编码 */"""

    def test_native_parameters_keep_values_and_defaults(self):
        """/** @return 字符串 数字与数组的约束保留原生传输 */"""
        item = {'id': 'test.operation', 'name': 'operation', 'definition': 'TestToolset', 'access': 'read', 'world': 'any',
                'parameters': {'type': 'object', 'properties': {
                    'action': {'type': 'string', 'default': 'status'},
                    'quality': {'type': 'integer', 'default': 0},
                    'actor_paths': {'type': 'array', 'items': {'type': 'string'}}}}}
        shapes = {'operation': {'action': {'type': 'string', 'enum': ['start', 'status']},
                                'quality': {'type': 'integer', 'minimum': 0, 'maximum': 3},
                                'actor_paths': {'type': 'array', 'items': {'type': 'string'}, 'default': []}}}
        with patch('MCP.mcp_contracts.source_inputs', return_value=shapes):
            contract = compile_contract(item)
        self.assertEqual(contract['parameters']['properties']['action']['default'], 'status')
        values = {'action': 'start', 'quality': 2, 'actor_paths': ['/Game/Map:Floor']}
        self.assertEqual(backend_arguments(contract, values), values)

    def test_json_string_parameters_still_encode(self):
        """/** @return 明确的 JSON 字符串接口继续按结构化数据编解码 */"""
        item = {'id': 'test.operation', 'name': 'operation', 'definition': 'TestToolset', 'access': 'read', 'world': 'any',
                'parameters': {'type': 'object', 'properties': {
                    'entries_json': {'type': 'string', 'default': '[]'}}}}
        with patch('MCP.mcp_contracts.source_inputs', return_value={'operation': {
                'entries_json': {'type': 'array', 'items': {'type': 'string'}}}}):
            contract = compile_contract(item)
        self.assertEqual(contract['parameters']['properties']['entries']['default'], [])
        encoded = backend_arguments(contract, {'entries': ['one', 'two']})
        self.assertEqual(json.loads(encoded['entries_json']), ['one', 'two'])


if __name__ == '__main__':
    unittest.main()
