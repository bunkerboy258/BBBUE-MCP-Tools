import json
import math

import unreal

from BBBAssetWritePolicy import require_asset_write


def create_preset(asset_path, reference_path, object_array_inputs, float_inputs):
    """
    /**
     * @param asset_path	明确的新预设路径
     * @param reference_path	引用的 MetaSound Source
     * @param object_array_inputs	对象数组输入默认值
     * @param float_inputs	浮点输入默认值
     * @return 原生 Builder 创建保存与默认值回读
     */
    """
    if not asset_path.startswith('/Game/_Project/') or unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        raise RuntimeError('要求不存在的自有预设路径')
    reference = unreal.load_asset(reference_path)
    if not isinstance(reference, unreal.MetaSoundSource):
        raise RuntimeError('来源必须是 MetaSound Source')
    objects = {name: [unreal.load_asset(path) for path in paths] for name, paths in object_array_inputs.items()}
    if any(not values or any(value is None for value in values) for values in objects.values()):
        raise RuntimeError('对象数组必须非空且全部可加载')
    if any(not math.isfinite(value) for value in float_inputs.values()):
        raise RuntimeError('浮点默认值必须有限')
    require_asset_write([], [asset_path])
    subsystem = unreal.get_engine_subsystem(unreal.MetaSoundBuilderSubsystem)
    editor = unreal.get_editor_subsystem(unreal.MetaSoundEditorSubsystem)
    builder_name = 'BBB_Author_' + asset_path.rsplit('/', 1)[1]
    builder, result = subsystem.create_source_preset_builder(builder_name, reference)
    if result != unreal.MetaSoundBuilderResult.SUCCEEDED or builder is None:
        raise RuntimeError('原生预设 Builder 创建失败')
    try:
        access = unreal.MetasoundFrontendLiteralBlueprintAccess
        literals = {name: access.create_object_array_meta_sound_literal(values) for name, values in objects.items()}
        literals.update({name: access.create_float_meta_sound_literal(value) for name, value in float_inputs.items()})
        for name, literal in literals.items():
            if builder.set_graph_input_default(name, literal) != unreal.MetaSoundBuilderResult.SUCCEEDED:
                raise RuntimeError('设置 MetaSound 输入失败: ' + name)
            actual, result = builder.get_graph_input_default(name)
            if result != unreal.MetaSoundBuilderResult.SUCCEEDED or actual.export_text() != literal.export_text():
                raise RuntimeError('MetaSound 输入回读不符: ' + name)
        folder, name = asset_path.rsplit('/', 1)
        asset, result = editor.build_to_asset(builder, 'BBB_Evac', name, folder)
        if result != unreal.MetaSoundBuilderResult.SUCCEEDED or asset is None:
            raise RuntimeError('原生 MetaSound 资产构造失败')
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            raise RuntimeError('MetaSound 预设保存失败')
        return {'asset': asset.get_path_name(), 'reference': reference.get_path_name(), 'saved': True,
                'objectArrays': object_array_inputs, 'floats': float_inputs}
    finally:
        subsystem.unregister_builder(builder_name)
