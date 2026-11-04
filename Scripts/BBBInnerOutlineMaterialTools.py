import json
import unreal
from BBBAssetWritePolicy import require_asset_write


def configure_inner_outline_material(material_path):
    """/** @param material_path 自有描边材质包 @return 原位构建并保存回读的双组可见内侧描边材质 */"""
    if not material_path.startswith("/Game/_Project/"):
        raise RuntimeError("内侧描边只允许自有材质包")
    exists = unreal.EditorAssetLibrary.does_asset_exist(material_path)
    require_asset_write([material_path] if exists else [], destinations=[] if exists else [material_path])
    material = unreal.EditorAssetLibrary.load_asset(material_path) if exists else None
    if exists and (not isinstance(material, unreal.Material) or material.get_editor_property("material_domain") != unreal.MaterialDomain.MD_POST_PROCESS):
        raise RuntimeError("原位构建只允许后处理材质")
    if not exists:
        directory, name = material_path.rsplit("/", 1)
        material = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, directory, unreal.Material, unreal.MaterialFactoryNew())
    if not material:
        raise RuntimeError("创建内侧描边材质失败")
    material.set_editor_property("material_domain", unreal.MaterialDomain.MD_POST_PROCESS)
    material.set_editor_property("blendable_location", unreal.BlendableLocation.BL_SCENE_COLOR_AFTER_TONEMAPPING)
    editing = unreal.MaterialEditingLibrary
    editing.delete_all_material_expressions(material)
    scene = editing.create_material_expression(material, unreal.MaterialExpressionSceneTexture, -600, 0)
    scene.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0)
    custom = editing.create_material_expression(material, unreal.MaterialExpressionCustom, -100, 0)
    custom.set_editor_property("description", "可见目标内侧细轮廓 不改变背景像素")
    custom.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    names = ["Scene", "MaskStencil", "OutlineWidth", "OutlineOpacity", "CenterStencil", "CenterDepth", "VisibleDepth",
             "SecondaryStencil", "SecondaryWidth", "SecondaryOpacity", "SecondaryColor"]
    inputs = []
    for name in names:
        entry = unreal.CustomInput()
        entry.set_editor_property("input_name", name)
        inputs.append(entry)
    custom.set_editor_property("inputs", inputs)
    custom.set_editor_property("code", r"""
float2 uv = GetDefaultSceneTextureUV(Parameters, 25);
float stencil = CenterStencil.r;
float primary = 1.0 - step(0.5, abs(stencil - MaskStencil));
float secondary = 1.0 - step(0.5, abs(stencil - SecondaryStencil));
float marked = max(primary, secondary);
float opacity = secondary > 0.5 ? SecondaryOpacity : OutlineOpacity;
float width = secondary > 0.5 ? SecondaryWidth : OutlineWidth;
float selectedStencil = secondary > 0.5 ? SecondaryStencil : MaskStencil;
[branch] if (marked < 0.5 || opacity <= 0.0 || width <= 0.0) return Scene.rgb;
float customDepth = CenterDepth.r;
float sceneDepth = VisibleDepth.r;
float visible = step(customDepth, sceneDepth + 0.5);
float2 pixel = View.BufferSizeAndInvSize.zw * clamp(width, 0.0, 2.0);
float nearMask = 1.0;
float2 offsets[4] = {float2(1,0), float2(-1,0), float2(0,1), float2(0,-1)};
[unroll] for (int i = 0; i < 4; ++i)
{
    float other = SceneTextureLookup(uv + offsets[i] * pixel, 25, false).r;
    nearMask = min(nearMask, 1.0 - step(0.5, abs(other - selectedStencil)));
}
float edge = (1.0 - nearMask) * marked * visible * saturate(opacity) * step(0.01, width);
float3 tint = secondary > 0.5 ? SecondaryColor.rgb : max(Scene.rgb, float3(0.78, 0.78, 0.78));
return lerp(Scene.rgb, tint, edge);
""")
    if not editing.connect_material_expressions(scene, "Color", custom, "Scene"):
        raise RuntimeError("描边场景输入连接失败")
    for index, (name, texture_id) in enumerate([
            ("CenterStencil", unreal.SceneTextureId.PPI_CUSTOM_STENCIL),
            ("CenterDepth", unreal.SceneTextureId.PPI_CUSTOM_DEPTH),
            ("VisibleDepth", unreal.SceneTextureId.PPI_SCENE_DEPTH)]):
        node = editing.create_material_expression(material, unreal.MaterialExpressionSceneTexture, -900, 200 + index * 180)
        node.set_editor_property("scene_texture_id", texture_id)
        if not editing.connect_material_expressions(node, "Color", custom, name):
            raise RuntimeError("描边深度输入连接失败 " + name)
    defaults = {"MaskStencil": 251.0, "OutlineWidth": 1.0, "OutlineOpacity": 0.1,
                "SecondaryStencil": 250.0, "SecondaryWidth": 1.25, "SecondaryOpacity": 0.42}
    for index, (name, value) in enumerate(defaults.items()):
        parameter = editing.create_material_expression(material, unreal.MaterialExpressionScalarParameter, -600, 200 + index * 160)
        parameter.set_editor_property("parameter_name", name)
        parameter.set_editor_property("default_value", value)
        if not editing.connect_material_expressions(parameter, "", custom, name):
            raise RuntimeError("描边参数连接失败 " + name)
    color = unreal.LinearColor(1.0, 0.34, 0.055, 1.0)
    parameter = editing.create_material_expression(material, unreal.MaterialExpressionVectorParameter, -600, 1200)
    parameter.set_editor_property("parameter_name", "SecondaryColor")
    parameter.set_editor_property("default_value", color)
    if not editing.connect_material_expressions(parameter, "", custom, "SecondaryColor"):
        raise RuntimeError("描边颜色连接失败")
    if not editing.connect_material_property(custom, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR):
        raise RuntimeError("描边输出连接失败")
    editing.recompile_material(material)
    if not unreal.EditorAssetLibrary.save_loaded_asset(material, False):
        raise RuntimeError("描边材质保存失败")
    readback = {name: editing.get_material_default_scalar_parameter_value(material, name) for name in defaults}
    if any(abs(readback[name] - value) > 0.0001 for name, value in defaults.items()):
        raise RuntimeError("描边材质参数回读不一致")
    read_color = editing.get_material_default_vector_parameter_value(material, "SecondaryColor")
    color_values = [read_color.r, read_color.g, read_color.b, read_color.a]
    if any(abs(actual - expected) > 0.0001 for actual, expected in zip(color_values, [1.0, 0.34, 0.055, 1.0])):
        raise RuntimeError("描边颜色回读不一致")
    return json.dumps({"material": material.get_path_name(), "saved": True, "readback": readback,
                       "secondary_color": color_values}, ensure_ascii=False)
