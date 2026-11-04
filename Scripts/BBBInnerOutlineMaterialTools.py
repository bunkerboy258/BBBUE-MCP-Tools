import json
import unreal
from BBBAssetWritePolicy import require_asset_write


def create_inner_outline_material(material_path):
    """/** @param material_path 新建项目材质包 @return 已保存且完成参数回读的内侧描边材质 */"""
    if not material_path.startswith("/Game/_Project/") or unreal.EditorAssetLibrary.does_asset_exist(material_path):
        raise RuntimeError("内侧描边要求不存在的自有材质包")
    require_asset_write([], destinations=[material_path])
    directory, name = material_path.rsplit("/", 1)
    material = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, directory, unreal.Material, unreal.MaterialFactoryNew())
    if not material:
        raise RuntimeError("创建内侧描边材质失败")
    material.set_editor_property("material_domain", unreal.MaterialDomain.MD_POST_PROCESS)
    material.set_editor_property("blendable_location", unreal.BlendableLocation.BL_SCENE_COLOR_AFTER_TONEMAPPING)
    editing = unreal.MaterialEditingLibrary
    scene = editing.create_material_expression(material, unreal.MaterialExpressionSceneTexture, -600, 0)
    scene.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0)
    custom = editing.create_material_expression(material, unreal.MaterialExpressionCustom, -100, 0)
    custom.set_editor_property("description", "可见目标内侧细轮廓 不改变背景像素")
    custom.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    names = ["Scene", "MaskStencil", "OutlineWidth", "OutlineOpacity", "CenterStencil", "CenterDepth", "VisibleDepth"]
    inputs = []
    for name in names:
        entry = unreal.CustomInput()
        entry.set_editor_property("input_name", name)
        inputs.append(entry)
    custom.set_editor_property("inputs", inputs)
    custom.set_editor_property("code", r"""
float2 uv = GetDefaultSceneTextureUV(Parameters, 25);
float stencil = CenterStencil.r;
float marked = 1.0 - step(0.5, abs(stencil - MaskStencil));
[branch] if (marked < 0.5 || OutlineOpacity <= 0.0 || OutlineWidth <= 0.0) return Scene.rgb;
float customDepth = CenterDepth.r;
float sceneDepth = VisibleDepth.r;
float visible = step(customDepth, sceneDepth + 0.5);
float2 pixel = View.BufferSizeAndInvSize.zw * clamp(OutlineWidth, 0.0, 2.0);
float nearMask = 1.0;
float2 offsets[4] = {float2(1,0), float2(-1,0), float2(0,1), float2(0,-1)};
[unroll] for (int i = 0; i < 4; ++i)
{
    float other = SceneTextureLookup(uv + offsets[i] * pixel, 25, false).r;
    nearMask = min(nearMask, 1.0 - step(0.5, abs(other - MaskStencil)));
}
float edge = (1.0 - nearMask) * marked * visible * saturate(OutlineOpacity) * step(0.01, OutlineWidth);
return lerp(Scene.rgb, max(Scene.rgb, float3(0.78, 0.78, 0.78)), edge);
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
    defaults = {"MaskStencil": 251.0, "OutlineWidth": 1.0, "OutlineOpacity": 0.1}
    for index, (name, value) in enumerate(defaults.items()):
        parameter = editing.create_material_expression(material, unreal.MaterialExpressionScalarParameter, -600, 200 + index * 160)
        parameter.set_editor_property("parameter_name", name)
        parameter.set_editor_property("default_value", value)
        if not editing.connect_material_expressions(parameter, "", custom, name):
            raise RuntimeError("描边参数连接失败 " + name)
    if not editing.connect_material_property(custom, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR):
        raise RuntimeError("描边输出连接失败")
    editing.recompile_material(material)
    if not unreal.EditorAssetLibrary.save_loaded_asset(material, False):
        raise RuntimeError("描边材质保存失败")
    readback = {name: editing.get_material_default_scalar_parameter_value(material, name) for name in defaults}
    if any(abs(readback[name] - value) > 0.0001 for name, value in defaults.items()):
        raise RuntimeError("描边材质参数回读不一致")
    return json.dumps({"material": material.get_path_name(), "saved": True, "readback": readback}, ensure_ascii=False)
