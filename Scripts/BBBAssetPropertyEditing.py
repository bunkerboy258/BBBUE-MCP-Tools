import json
import math

import unreal

from BBBAssetWritePolicy import require_write_access


def _verify(target, requested, materialize, path):
    """/** @param target 已写入对象或结构 @param requested 明确字段 @param materialize 类型转换 @param path 报错路径 @return 核验通过时无返回值 */"""
    for name, expected in requested.items():
        actual = target.get_editor_property(name)
        field = path + '.' + name
        structured = isinstance(expected, dict) and not any(
            key in expected for key in ('structType', 'enumType', 'classPath', 'mapValues', 'refPath'))
        if structured:
            _verify(actual, expected, materialize, field)
            continue
        if isinstance(expected, dict) and 'enumType' in expected and isinstance(actual, unreal.EnumBase):
            if type(actual).__name__ != expected['enumType']:
                raise RuntimeError('目标字段枚举类型不匹配: ' + field)
            converted = getattr(type(actual), expected['value'])
        else:
            converted = materialize(expected)
        if isinstance(actual, unreal.StructBase) and isinstance(converted, unreal.StructBase):
            if actual.export_text() == converted.export_text():
                continue
        if isinstance(actual, unreal.Object) and isinstance(expected, str):
            converted = unreal.load_asset(expected) if expected else None
        if isinstance(actual, float) and isinstance(converted, (float, int)):
            if math.isclose(actual, converted, rel_tol=1e-6, abs_tol=1e-6):
                continue
        if actual != converted:
            raise RuntimeError('资产属性回读不符: ' + field)


def configure(asset_path, properties_json, apply_property, materialize, serialize):
    """/** @param asset_path 自有资产或其明确子对象 @param properties_json 嵌套字段 @param apply_property 精确写入 @param materialize 类型转换 @param serialize 回读序列化 @return 保存与字段核验结果 */"""
    if not asset_path.startswith('/Game/_Project/'):
        raise RuntimeError('目标必须为已有自有资产')
    owner_path = asset_path.split(':', 1)[0]
    owner = unreal.load_asset(owner_path)
    target = unreal.load_object(None, asset_path)
    if owner is None or target is None:
        raise RuntimeError('资产或明确子对象不存在: ' + asset_path)
    forbidden = (unreal.World, unreal.Actor, unreal.ActorComponent)
    if isinstance(owner, forbidden) or isinstance(target, forbidden):
        raise RuntimeError('不允许通过资产属性接口编辑世界或演员')
    if target.get_outermost() != owner.get_outermost():
        raise RuntimeError('子对象不属于目标资产包')
    current = target
    while current != owner and current is not None:
        current = current.get_outer()
    if current != owner:
        raise RuntimeError('子对象不属于目标资产')
    requested = json.loads(properties_json)
    if not isinstance(requested, dict) or not requested:
        raise RuntimeError('必须指定非空属性对象')
    require_write_access(owner)
    with unreal.ScopedEditorTransaction('配置资产属性'):
        owner.modify()
        if target != owner:
            target.modify()
        for name, value in requested.items():
            apply_property(target, name, value)
        _verify(target, requested, materialize, asset_path)
    if not unreal.EditorAssetLibrary.save_loaded_asset(owner, False):
        raise RuntimeError('资产属性保存失败: ' + owner_path)
    _verify(target, requested, materialize, asset_path)
    unreal.log('[BBBAssetProperties] 已保存并核验 ' + asset_path)
    return json.dumps({'asset': owner.get_path_name(), 'object': target.get_path_name(),
        'saved': True, 'properties': {name: serialize(target.get_editor_property(name))
        for name in requested}, 'structTexts': {name: target.get_editor_property(name).export_text()
        for name in requested if isinstance(target.get_editor_property(name), unreal.StructBase)}}, ensure_ascii=False)
