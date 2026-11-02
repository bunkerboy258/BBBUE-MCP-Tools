"""黏液四段表现的离线素材装配。"""
import importlib
import json
import re
import unreal
from BBBAssetWritePolicy import require_asset_write

PREFIX = '/Game/_Project/Mass/Monster/SpecialInfected/Shared/Slime'
BLOOD = '/Game/_ThirdParty/VFX/RealisticBloodVFX/BloodPack/'
WATER = '/Game/_ThirdParty/FX/ArrowTrail/'
VERSION = 'SpiderLiquid20261102L'

def _load(path, kind):
    """/** @param path 明确资源 @param kind 真实类型 @return 已核验资源 */"""
    value = unreal.load_asset(path)
    if not isinstance(value, kind):
        raise RuntimeError('资源类型不符 '+path)
    return value

def _check(value):
    """/** @param value 原生制作结果 @return 拒绝原生失败 */"""
    text = str(value)
    if text.startswith('失败'):
        raise RuntimeError(text)
    return text

def _save(value):
    """/** @param value 明确自有输出 @return 保存已完成资产 */"""
    if not unreal.EditorAssetLibrary.save_loaded_asset(value, False):
        raise RuntimeError('资源保存失败 '+value.get_path_name())

def _clone(source, name):
    """/** @param source 原包资源 @param name 自有输出名 @return 同源的独立制作副本 */"""
    path = PREFIX+'/Effects/'+name
    value = unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
    if value and unreal.EditorAssetLibrary.get_metadata_tag(value, 'BBB.SlimeSource') != source:
        raise RuntimeError('拒绝覆盖其它来源 '+path)
    if value is None:
        value = unreal.EditorAssetLibrary.duplicate_asset(source, path)
        if value is None:
            raise RuntimeError('资源复制失败 '+path)
        unreal.EditorAssetLibrary.set_metadata_tag(value, 'BBB.SlimeSource', source)
    return value

def _material(parent, name, neutral=False):
    """/** @param parent 原材质 @param name 自有实例 @param neutral 粒子负责配色 @return 已保存实例 */"""
    path = PREFIX+'/Effects/'+name
    value = unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
    if value is None:
        factory = unreal.MaterialInstanceConstantFactoryNew()
        value = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, PREFIX+'/Effects', unreal.MaterialInstanceConstant, factory)
    if not isinstance(value, unreal.MaterialInstanceConstant):
        raise RuntimeError('材质实例类型不符 '+path)
    color = unreal.LinearColor(1, 1, 1, 1) if neutral else unreal.LinearColor(.025, .11, .006, 1)
    edit = unreal.MaterialEditingLibrary
    edit.set_material_instance_parent(value, _load(parent, unreal.MaterialInterface))
    names = [str(x) for x in edit.get_vector_parameter_names(value)]
    for key, tint in [('MainColor', color), ('SecondaryColor', color if neutral else unreal.LinearColor(.14, .27, .025, 1)), ('SpecularTint', unreal.LinearColor(.4, .5, .25, 1))]:
        if key in names:
            edit.set_material_instance_vector_parameter_value(value, key, tint)
    for key, number in [('Darkness', .6), ('SpecularValue', .35), ('Roughness', .22), ('Alpha', 1.0), ('DistortIntensity', .12)]:
        if key in [str(x) for x in edit.get_scalar_parameter_names(value)]:
            edit.set_material_instance_scalar_parameter_value(value, key, number)
    _save(value)
    return value

def _resident_textures(instance):
    """/** @param instance 自有液体实例 @return 共享的有限尺寸常驻遮罩 减少首次流送波动 */"""
    edit=unreal.MaterialEditingLibrary
    for key in edit.get_texture_parameter_names(instance):
        source=edit.get_material_instance_texture_parameter_value(instance,key)
        if not isinstance(source,unreal.Texture2D):
            continue
        if source.get_path_name().startswith(PREFIX+'/Effects/T_Slime_'):
            source=_load(unreal.EditorAssetLibrary.get_metadata_tag(source,'BBB.SlimeSource'),unreal.Texture2D)
        texture=_clone(source.get_path_name(),'T_Slime_'+source.get_name())
        texture.set_editor_property('never_stream',True)
        texture.set_editor_property('max_texture_size',1024)
        texture.set_editor_property('virtual_texture_streaming',False)
        _save(texture)
        edit.set_material_instance_texture_parameter_value(instance,key,texture)
    _save(instance)


def _ground_fade(instance):
    """/** @param instance 自有水洼实例 @return 保留原包细节并使生命周期淡出生效 */"""
    edit=unreal.MaterialEditingLibrary
    original=instance.get_editor_property('parent')
    while isinstance(original,unreal.MaterialInstanceConstant):
        original=original.get_editor_property('parent')
    path=PREFIX+'/Effects/M_SlimePuddle'
    material=unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else unreal.EditorAssetLibrary.duplicate_asset(original.get_path_name(),path)
    if not isinstance(material,unreal.Material):
        raise RuntimeError('水洼母材质类型无效')
    if unreal.EditorAssetLibrary.get_metadata_tag(material,'BBB.DecalFade') != '1':
        opacity=edit.get_material_property_input_node(material,unreal.MaterialProperty.MP_OPACITY)
        output=edit.get_material_property_input_node_output_name(material,unreal.MaterialProperty.MP_OPACITY)
        if opacity is None:
            raise RuntimeError('源水洼缺少透明度输入')
        fade=edit.create_material_expression(material,unreal.MaterialExpressionDecalLifetimeOpacity,400,300)
        multiply=edit.create_material_expression(material,unreal.MaterialExpressionMultiply,600,300)
        for a,out,b,pin in [(opacity,output,multiply,'A'),(fade,'',multiply,'B')]:
            if not edit.connect_material_expressions(a,out,b,pin):
                raise RuntimeError('水洼消退连接失败')
        if not edit.connect_material_property(multiply,'',unreal.MaterialProperty.MP_OPACITY):
            raise RuntimeError('水洼透明度连接失败')
        unreal.EditorAssetLibrary.set_metadata_tag(material,'BBB.DecalFade','1')
        edit.recompile_material(material)
        _save(material)
    values=[]
    for kind in ['scalar','vector','texture']:
        names=getattr(edit,'get_'+kind+'_parameter_names')(instance)
        for name in names:
            values.append((kind,name,getattr(edit,'get_material_instance_'+kind+'_parameter_value')(instance,name)))
    edit.set_material_instance_parent(instance,material)
    for kind,name,value in values:
        if value is not None:
            getattr(edit,'set_material_instance_'+kind+'_parameter_value')(instance,name,value)
    _save(instance)


def _body():
    """/** @return 共享颜色数据驱动的湿润形变液团材质 */"""
    path = PREFIX+'/Effects/M_SlimeFlight'
    material = unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
    if material and unreal.EditorAssetLibrary.get_metadata_tag(material, 'BBB.SlimeVersion') == VERSION:
        return material
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    if material is None:
        material = tools.create_asset('M_SlimeFlight', PREFIX+'/Effects', unreal.Material, unreal.MaterialFactoryNew())
    edit = unreal.MaterialEditingLibrary
    edit.delete_all_material_expressions(material)
    def node(kind, **properties):
        value = edit.create_material_expression(material, getattr(unreal, kind), -300, 0)
        for key, item in properties.items():
            value.set_editor_property(key, item)
        return value
    def link(a, b, pin, output=''):
        if not edit.connect_material_expressions(a, output, b, pin):
            raise RuntimeError('材质连接失败 '+pin)
    dark = node('MaterialExpressionVectorParameter', parameter_name='MainColor', default_value=unreal.LinearColor(.025, .11, .006, 1), use_custom_primitive_data=True, primitive_data_index=0)
    bright = node('MaterialExpressionVectorParameter', parameter_name='SecondaryColor', default_value=unreal.LinearColor(.14, .27, .025, 1), use_custom_primitive_data=True, primitive_data_index=3)
    noise = node('MaterialExpressionTextureSample', texture=_load(WATER+'Texture/T_Noise_01', unreal.Texture2D))
    color = node('MaterialExpressionLinearInterpolate')
    link(dark, color, 'A')
    link(bright, color, 'B')
    link(noise, color, 'Alpha', 'R')
    edit.connect_material_property(color, '', unreal.MaterialProperty.MP_BASE_COLOR)
    rough = node('MaterialExpressionConstant', r=.22)
    edit.connect_material_property(rough, '', unreal.MaterialProperty.MP_ROUGHNESS)
    spec = node('MaterialExpressionConstant', r=.45)
    edit.connect_material_property(spec, '', unreal.MaterialProperty.MP_SPECULAR)
    time = node('MaterialExpressionTime')
    speed = node('MaterialExpressionMultiply', const_b=.8)
    link(time, speed, 'A')
    uv = node('MaterialExpressionTextureCoordinate')
    wave = node('MaterialExpressionDotProduct')
    axis = node('MaterialExpressionConstant2Vector', r=3, g=5)
    link(uv, wave, 'A')
    link(axis, wave, 'B')
    phase = node('MaterialExpressionAdd')
    link(speed, phase, 'A')
    link(wave, phase, 'B')
    sine = node('MaterialExpressionSine')
    link(phase, sine, '')
    amount = node('MaterialExpressionMultiply', const_b=1.25)
    link(sine, amount, 'A')
    normals = node('MaterialExpressionVertexNormalWS')
    displacement = node('MaterialExpressionMultiply')
    link(normals, displacement, 'A')
    link(amount, displacement, 'B')
    edit.connect_material_property(displacement, '', unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
    edit.recompile_material(material)
    unreal.EditorAssetLibrary.set_metadata_tag(material, 'BBB.SlimeVersion', VERSION)
    _save(material)
    return material

def _parameters(system, replacements):
    """/** @param system 自有粒子系统 @param replacements 精确快速迭代输入 @return 保存显式参数 */"""
    library = unreal.BBBNiagaraEditorLibrary
    inspection = str(library.inspect_parameters(system.get_path_name()))
    changes = []
    for line in inspection.splitlines():
        fields = line.split(' | ')
        if len(fields) != 4 or fields[0] == 'User' or fields[0].startswith('Node='):
            continue
        for suffix, value in replacements.items():
            if fields[1].endswith(suffix):
                changes.append({'store': fields[0], 'name': fields[1], 'value': '(Value='+str(value)+')'})
    unique = {(v['store'], v['name']): v for v in changes}
    if unique:
        _check(library.configure_parameters(system.get_path_name(), json.dumps(list(unique.values()))))

def _burst(system, emitter, speed, lifetime, size, spread, bubbles=False, streak=False, flight=False):
    """/** @param system 自有系统 @param emitter 明确粒子层 @param speed 初速 @param lifetime 寿命 @param size 尺寸 @param spread 散布 @param bubbles 地面小泡 @param streak 连续黏液拖滴 @param flight 水体散滴 @return 同一预算下的液滴运动 */"""
    library = unreal.BBBNiagaraEditorLibrary
    def fields(items):
        return [{'name': n, 'type': t} for n, t in items]
    parameters = [
        {'name': 'User.Color', 'type': 'color', 'value': '(R=.025,G=.11,B=.006,A=1)'},
        {'name': 'User.SecondaryColor', 'type': 'color', 'value': '(R=.14,G=.27,B=.025,A=1)'},
        {'name': 'User.SpawnRate', 'type': 'float', 'value': '(Value=1)'},
        {'name': 'User.Direction', 'type': 'vec3', 'value': '(X=0,Y=0,Z=1)'},
        {'name': 'User.Size', 'type': 'float', 'value': '(Value=1)'},
        {'name': 'User.Seed', 'type': 'float', 'value': '(Value=1)'},
        {'name': 'User.TrailLifetime', 'type': 'float', 'value': '(Value=.2)'}]
    inputs = fields([('Engine.Owner.Position','position'), ('Engine.Owner.Velocity','vec3'), ('Engine.ExecutionIndex','int'), ('Emitter.Age','float'), ('User.Seed','float'), ('User.TrailLifetime','float'),
                     ('User.Color','color'), ('User.SecondaryColor','color'), ('User.Direction','vec3'), ('User.Size','float'), ('User.SpawnRate','float')])
    outputs = fields([('Particles.Position','position'), ('Particles.Velocity','vec3'), ('Particles.SpriteSize','vec2'),
                      ('Particles.Color','color'), ('Particles.BurstColor','color'), ('Particles.Lifetime','float'),
                      ('Particles.Age','float'), ('Particles.SpriteRotation','float'), ('Particles.SubImageIndex','float'),
                      ('Particles.SpriteAlignment','vec3'), ('Particles.NormalizedAge','float'), ('DataInstance.Alive','bool'), ('Particles.DynamicMaterialParameter','vec4')])
    if bubbles:
        outputs += fields([('Particles.Scale','vec3')])
    code = """float R=frac(sin(InExecutionIndex*12.9898+InAge*131.0+InSeed)*43758.5453);
float Q=frac(sin(InExecutionIndex*39.346+InAge*47.0+InSeed)*47453.5453);
float3 N=normalize(InDirection+float3(0,0,0.0001));
float3 U=normalize(cross(N,abs(N.z)>.9?float3(0,1,0):float3(0,0,1)));
float3 V=cross(U,N);
float3 Side=U*cos(Q*6.283185)+V*sin(Q*6.283185);
OutPosition=InPosition+N*2;
OutVelocity=normalize(N+Side*SPREAD)*(SPEED*(.6+.4*R));
OutSpriteSize=float2(SIZEX,SIZEY)*(.7+.6*Q);
OutColor=lerp(InColor,InSecondaryColor,R); OutColor.rgb*=3; OutBurstColor=OutColor;
OutAlive=Q<saturate(InSpawnRate);
OutLifetime=LIFETIME*(.8+.4*R); OutAge=0; OutNormalizedAge=0;
OutDynamicMaterialParameter=float4(0,1,1,1);
OutSpriteRotation=Q*360; OutSubImageIndex=0; OutSpriteAlignment=normalize(OutVelocity+N*.001);
"""
    for key, value in [('SPREAD', spread), ('SPEED', speed), ('SIZEX', size[0]), ('SIZEY', size[1]), ('LIFETIME', lifetime)]:
        code = code.replace(key, str(float(value)))
    if flight:
        code += 'OutDynamicMaterialParameter=float4(4,.344,1,1);\n'
    if streak:
        code += 'OutVelocity=-InVelocity*.18; OutSpriteAlignment=normalize(OutVelocity+float3(.001,0,0)); OutSpriteSize*=InSize; OutLifetime=InTrailLifetime; OutBurstColor=OutColor;\n'
    if flight:
        code += 'OutLifetime=InTrailLifetime*1.3; OutBurstColor=OutColor;\n'
    if bubbles:
        code += 'OutScale=float3(.025,.025,.025)*(1+R*.5);\n'
    if bubbles:
        code += 'OutPosition=InPosition+Side*sqrt(R)*160*InSize;\nOutVelocity=N*(12+R*8);\n'
    _check(library.configure_particle_stage(system.get_path_name(), emitter, json.dumps({'stage':'spawn','name':emitter+'SlimeSpawn','inputs':inputs,'outputs':outputs,'code':code,'parameters':parameters})))
    inputs = fields([('Particles.Position','position'), ('Particles.Velocity','vec3'), ('Particles.SpriteSize','vec2'),
                     ('Particles.BurstColor','color'), ('Particles.Lifetime','float'), ('Particles.Age','float'), ('Engine.DeltaTime','float')])
    outputs = fields([('Particles.Position','position'), ('Particles.Velocity','vec3'), ('Particles.SpriteSize','vec2'),
                      ('Particles.Color','color'), ('Particles.Age','float'), ('Particles.NormalizedAge','float'),
                      ('Particles.SubImageIndex','float'), ('DataInstance.Alive','bool'), ('Particles.DynamicMaterialParameter','vec4'), ('Particles.SpriteAlignment','vec3')])
    code = """OutAge=InAge+InDeltaTime; OutNormalizedAge=saturate(OutAge/InLifetime);
OutVelocity=InVelocity*exp(-2.8*InDeltaTime)-float3(0,0,GRAVITY*InDeltaTime);
OutPosition=InPosition+OutVelocity*InDeltaTime;
OutSpriteAlignment=normalize(OutVelocity+float3(0,0,.001));
OutSpriteSize=InSpriteSize;
OutColor=float4(InBurstColor.rgb,InBurstColor.a*pow(1-OutNormalizedAge,1.5));
OutDynamicMaterialParameter=float4(OutNormalizedAge,1,1,1);
OutSubImageIndex=OutNormalizedAge*15; OutAlive=OutAge<InLifetime;
""".replace('GRAVITY','0' if bubbles or streak else '550')
    if flight:
        code += 'OutDynamicMaterialParameter=float4(4,.344,1,1);\n'
    update={'stage':'update','name':emitter+'SlimeUpdate','inputs':inputs,'outputs':outputs,'code':code}
    if streak:
        update['render']={'kind':'sprite','material':PREFIX+'/Effects/MI_SlimeDrop','aligned':True}
    if bubbles:
        update['render']={'kind':'mesh','mesh':'/Engine/BasicShapes/Sphere','material':PREFIX+'/Effects/MI_SlimeBubble'}
    _check(library.configure_particle_stage(system.get_path_name(), emitter, json.dumps(update)))

def _material_inputs():
    """/** @return 所复用粒子材质实际连接的动态输入 用于制作核对 */"""
    edit=unreal.MaterialEditingLibrary
    result={}
    for path in [WATER+'Material/MI_Instance/MI_WaterRibbon',WATER+'Material/MI_Instance/MI_WaterParticle',PREFIX+'/Effects/MI_SlimeDrop',PREFIX+'/Effects/MI_SlimeSplash']:
        material=_load(path,unreal.MaterialInterface)
        while isinstance(material,unreal.MaterialInstanceConstant):
            material=material.get_editor_property('parent')
        pending=[edit.get_material_property_input_node(material,prop) for prop in [unreal.MaterialProperty.MP_OPACITY,unreal.MaterialProperty.MP_EMISSIVE_COLOR,unreal.MaterialProperty.MP_BASE_COLOR]]
        seen=set();values=[]
        while pending and len(seen)<256:
            node=pending.pop()
            if node is None or node.get_path_name() in seen:
                continue
            seen.add(node.get_path_name())
            if isinstance(node,unreal.MaterialExpressionDynamicParameter):
                values.append({'names':[str(x) for x in node.get_editor_property('param_names')],'default':str(node.get_editor_property('default_value'))})
            pending+=list(edit.get_inputs_for_material_expression(material,node))
        result[path]=values
    return result


def build(destination_root):
    """/** @param destination_root 唯一正式黏液目录 @return 四段表现与已保存配置 */"""
    if destination_root != PREFIX or unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError('需要正式黏液目录且已经退出 PIE')
    definition = _load(PREFIX+'/DA_Slime', unreal.BBBSlimeDefinition)
    require_asset_write([definition], destinations=[PREFIX])
    if unreal.EditorAssetLibrary.get_metadata_tag(definition, 'BBB.SlimeVersion') == VERSION and definition.is_presentation_ready():
        return json.dumps({'readOnly':True,'definition':definition.get_path_name(),'presentationReady':True,'materialInputs':_material_inputs()})
    body = _body()
    ground = _material(BLOOD+'_Commons/Materials/Decals/Puddles/MI_BloodPuddle_01', 'MI_SlimePuddle')
    _ground_fade(ground)
    drops = _material(BLOOD+'_Commons/Materials/MI_BloodSplash_07', 'MI_SlimeSplash', True)
    sheet = _material(BLOOD+'_Commons/Materials/MI_BloodSplash_06', 'MI_SlimeDrop', True)
    bubble = _material('/Game/_ThirdParty/FX/Realistic_Starter_VFX_Pack_Vol2/Materials/M_Bubble', 'MI_SlimeBubble', True)
    for material in (ground,drops,sheet):
        _resident_textures(material)
    trail = _clone(WATER+'FX/NS_ArrowTrail_Water', 'NS_SlimeFlight')
    mouth = _clone(BLOOD+'Dripping/Niagara/NS_Dripping_Low', 'NS_SlimeMouth')
    impact = _clone(BLOOD+'Splash/Niagara/NS_BloodSplash_Low', 'NS_SlimeImpact')
    bubbles = _clone(BLOOD+'Dripping/Niagara/NS_Dripping_Low', 'NS_SlimeGround')
    library = unreal.BBBNiagaraEditorLibrary
    _check(library.configure_emitter_layers(trail.get_path_name(), json.dumps([
        {'name':'Trail','material':sheet.get_path_name(),'local_space':False},
        {'name':'Particle001','material':WATER+'Material/MI_Instance/MI_WaterParticle','local_space':False}]), True))
    _parameters(trail, {'.Trail.Multiply_Float.A':28, '.Particle001.Multiply_Float.A':16, '.SpawnBurst_Instantaneous.Spawn Count':2})
    _check(library.configure_burst_sprite_layer(mouth.get_path_name(),json.dumps({'name':'Mouth','material':sheet.get_path_name(),'count':10,'lifetime':.38,'speed':420,'drag':2.8,'gravity':550,'growth':0,'size':[5,13],'color':[.065,.14,.012,1],'aligned':True})))
    for system, layers, looping in [
        (mouth,[('Mouth',sheet)],False),
        (impact,[('DirectionalBurst001',drops),('Drip',sheet)],False),
        (bubbles,[('Flow',bubble)],True)]:
        _check(library.configure_emitter_layers(system.get_path_name(), json.dumps([{'name':n,'material':m.get_path_name(),'local_space':False} for n,m in layers]),looping))
        _parameters(system,{'.SpawnRate.SpawnRate':4 if looping else 0,'.SpawnBurst_Instantaneous.Spawn Count':1 if looping else (10 if system == mouth else 6),'.SystemState.Loop Duration':1 if looping else .12})
    _burst(trail,'Trail',0,.2,(6,20),0,streak=True)
    _burst(trail,'Particle001',45,.3,(6,12),.6,flight=True)
    _burst(mouth,'Mouth',420,.38,(9,22),.28)
    _burst(impact,'DirectionalBurst001',160,.4,(65,65),1.2)
    _burst(impact,'Drip',280,.65,(6,16),2.4)
    _burst(bubbles,'Flow',15,.65,(7,7),.2,True)
    presentation = definition.get_editor_property('presentation')
    for name, value in [('trail_width',1.2),('main_color',unreal.LinearColor(.018,.065,.004,1)),('secondary_color',unreal.LinearColor(.065,.14,.012,1)),('flight_material',body),('ground_material',ground),('mouth_system',mouth),('flight_system',trail),('impact_system',impact),('ground_system',bubbles)]:
        presentation.set_editor_property(name,value)
    definition.set_editor_property('presentation',presentation)
    if not definition.is_presentation_ready():
        raise RuntimeError('四段黏液表现配置未就绪')
    unreal.EditorAssetLibrary.set_metadata_tag(definition,'BBB.SlimeVersion',VERSION)
    _save(definition)
    return json.dumps({'definition':definition.get_path_name(),'presentationReady':True,'systems':[v.get_path_name() for v in (mouth,trail,impact,bubbles)],
                       'budgets':{'mouthBurst':10,'impactBurst':12,'groundPerSecond':4,'maximumAreas':definition.get_editor_property('world_limit')},'saved':True})
