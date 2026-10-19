import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class FixedArray:
    """/** 独立于列表元组的原生定长数组替身，用于检出类型分支遗漏 */"""

    def __init__(self, values):
        """/** @param values 按原生索引排列的内容 @return 独立定长数组替身 */"""
        self.values = values

    def __iter__(self):
        """/** @return 按原索引排列的迭代器 */"""
        return iter(self.values)


class Struct:
    """/** 仅提供官方编辑器属性读取接口的结构体替身 */"""

    def __init__(self, **properties):
        """/** @param properties 真实字段值夹具 @return 只读字段容器 */"""
        self.properties = properties

    def get_editor_property(self, name):
        """/** @param name 明确字段名 @return 原始字段值，缺失保持异常 */"""
        return self.properties[name]


def property_functions():
    """/** @return 不启动编辑器的真实序列化及点路径函数 */"""
    source = Path(__file__).resolve().parents[1] / 'Scripts/BBBGenericEditorToolset.py'
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ['_serialize_value', '_read_asset_property_path']]
    unreal = SimpleNamespace(Object=type('Object', (), {}), Guid=type('Guid', (), {}),
                             Array=type('Array', (list,), {}), Set=type('Set', (set,), {}), FixedArray=FixedArray)
    namespace = {'unreal': unreal}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), namespace)
    return namespace['_read_asset_property_path'], namespace['_serialize_value']


class AssetPropertyFixedArrayTests(unittest.TestCase):
    def test_fixed_blend_axes_preserve_values_and_original_order(self):
        """/** @return 实际定长轴结构字段不会丢失为三个空对象 */"""
        read, serialize = property_functions()
        asset = Struct(blend_parameters=FixedArray([
            Struct(display_name='Lean', min=-20.0, max=20.0, grid_num=4),
            Struct(display_name='UnusedY', min=0.0, max=100.0, grid_num=1),
            Struct(display_name='UnusedZ', min=-1.0, max=1.0, grid_num=2),
        ]))
        self.assertEqual(read(asset, 'blend_parameters.min'), [-20.0, 0.0, -1.0])
        self.assertEqual(read(asset, 'blend_parameters.grid_num'), [4, 1, 2])
        self.assertEqual(read(asset, 'blend_parameters.display_name'), ['Lean', 'UnusedY', 'UnusedZ'])

    def test_leaf_fixed_array_serializes_as_a_json_container(self):
        """/** @return 叶节点定长数组不被降为不可检查的字符串 */"""
        read, serialize = property_functions()
        value = FixedArray([3, 0, -7])
        self.assertEqual(serialize(value), [3, 0, -7])
        self.assertEqual(read(value, ''), [3, 0, -7])

    def test_dynamic_and_fixed_nested_arrays_keep_field_shape(self):
        """/** @return 动态数组嵌套定长数组保留二维索引关系 */"""
        read, serialize = property_functions()
        asset = Struct(groups=[Struct(parameters=FixedArray([Struct(value=5), Struct(value=2)])),
                               Struct(parameters=FixedArray([Struct(value=9)]))])
        self.assertEqual(read(asset, 'groups.parameters.value'), [[5, 2], [9]])

    def test_missing_struct_property_is_not_fabricated(self):
        """/** @return 真实字段缺失仍明确失败而不是补空值通过 */"""
        read, serialize = property_functions()
        with self.assertRaises(KeyError):
            read(Struct(parameters=FixedArray([Struct(value=1)])), 'parameters.absent')


if __name__ == '__main__':
    unittest.main()
