import json
import math
from pathlib import Path
import unreal
from BBBAssetWritePolicy import require_asset_write


def _inputs(asset_path, mesh_path, chains_json):
    """/** @param asset_path 绑定路径 @param mesh_path 网格 @param chains_json 明确链 @return 已校验的网格与链 */"""
    mesh = unreal.load_asset(mesh_path)
    if not isinstance(mesh, unreal.SkeletalMesh) or not asset_path.startswith('/Game/_Project/'):
        raise RuntimeError('需要自有绑定路径和实际骨骼网格')
    chains = json.loads(chains_json)
    if not chains or len(chains) > 8:
        raise RuntimeError('需要明确的一到八条驱动链')
    outputs = set()
    variables = set()
    for chain in chains:
        if set(chain) != {'parent', 'driver', 'twist', 'variable', 'fraction'}:
            raise RuntimeError('驱动链字段不完整')
        if chain['twist'] in outputs or chain['variable'] in variables or not 0 <= chain['fraction'] <= 1:
            raise RuntimeError('目标骨骼 公开变量或分配比例无效')
        outputs.add(chain['twist'])
        variables.add(chain['variable'])
    return mesh, chains


def create(asset_path, mesh_path, chains_json):
    """/** @param asset_path 新绑定 @param mesh_path 导入骨架 @param chains_json 显式扭转链 @return 官方RigVM节点创建结果 */"""
    from BBBControlRigAuthoringToolset import BBBControlRigAuthoringToolset as author
    mesh, chains = _inputs(asset_path, mesh_path, chains_json)
    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        raise RuntimeError('绑定已存在 拒绝覆盖')
    require_asset_write([], [asset_path])
    subsystem = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
    reference = json.loads(unreal.BBBGripGeometryEditorLibrary.sample_skeletal_mesh_surface(mesh, [], [], 1.0, []))
    bones = {bone['name']: bone for bone in reference['bones']}
    nodes = [{'name': 'Begin', 'struct': '/Script/ControlRig.RigUnit_BeginExecution'}]
    links = []
    variables = []
    previous = 'Begin.ExecutePin'
    report = []
    for index, chain in enumerate(chains):
        parent, driver, twist = (chain[k] for k in ['parent', 'driver', 'twist'])
        if not {parent, driver, twist} <= bones.keys():
            raise RuntimeError('骨架缺少驱动骨骼')
        if str(subsystem.get_bone_parent(mesh, driver)) != parent or str(subsystem.get_bone_parent(mesh, twist)) != parent or subsystem.get_bone_children(mesh, twist):
            raise RuntimeError('驱动骨与无子骨的twist必须同属明确父骨')
        axis = bones[driver]['referenceLocal'][:3]
        length = math.sqrt(sum(v*v for v in axis))
        if length < .01:
            raise RuntimeError('驱动轴长度退化')
        axis = [v/length for v in axis]
        fraction = sum(a*b for a,b in zip(bones[twist]['referenceLocal'][:3], axis))/length
        if not .01 < fraction < .99:
            raise RuntimeError('twist骨不在父骨和驱动骨之间')
        prefix = 'Chain'+str(index)+'_'
        def unit(name, struct, defaults=None, x=0):
            nodes.append({'name':prefix+name,'struct':struct,'defaults':defaults or {},'position':[x,index*950]})
        def link(source, target):
            links.append([prefix+source,prefix+target])
        for name, bone, initial in [('Hand', driver, False),('HandRef',driver,True),('TwistRef',twist,True)]:
            unit(name,'/Script/ControlRig.RigUnit_GetTransform',{'Item':'(Type=Bone,Name="'+bone+'")','Space':'LocalSpace','bInitial':str(initial)})
        unit('RefInverse','/Script/RigVM.RigVMFunction_MathQuaternionInverse',x=240)
        unit('Delta','/Script/RigVM.RigVMFunction_MathQuaternionMul',x=480)
        unit('Decompose','/Script/RigVM.RigVMFunction_MathQuaternionSwingTwist',{'TwistAxis':'(X='+str(axis[0])+',Y='+str(axis[1])+',Z='+str(axis[2])+')'},x=720)
        unit('Fraction','/Script/RigVM.RigVMFunction_MathQuaternionSlerp',x=960)
        unit('Target','/Script/RigVM.RigVMFunction_MathQuaternionMul',x=1200)
        unit('Apply','/Script/ControlRig.RigUnit_SetRotation',{'Item':'(Type=Bone,Name="'+twist+'")','Space':'LocalSpace','bInitial':'False','Weight':'1.0','bPropagateToChildren':'False'},x=1440)
        links.append([previous,prefix+'Apply.ExecutePin'])
        previous=prefix+'Apply.ExecutePin'
        link('Hand.Transform.Rotation','Delta.A')
        link('HandRef.Transform.Rotation','RefInverse.Value')
        link('RefInverse.Result','Delta.B')
        link('Delta.Result','Decompose.Input')
        link('Decompose.Twist','Fraction.B')
        link('Fraction.Result','Target.A')
        link('TwistRef.Transform.Rotation','Target.B')
        link('Target.Result','Apply.Value')
        variables.append({'name':chain['variable'],'type':'float','default':str(chain['fraction']),'node':prefix+'Weight','position':[720,index*950+220]})
        links.append([prefix+'Weight.Value',prefix+'Fraction.T'])
        report.append({**chain,'reference_axis':axis,'geometric_fraction':fraction})
    result=json.loads(author.create_control_rig(asset_path,mesh_path,'[]',json.dumps({'nodes':nodes,'links':links,'variables':variables})))
    from BBBControlRigAuthoringToolset import _key
    asset=unreal.load_asset(asset_path)
    for bone in reference['bones']:
        v=bone['referenceLocal'];t=unreal.Transform(location=unreal.Vector(*v[:3]),scale=unreal.Vector(*v[7:10]));t.rotation=unreal.Quat(*v[3:7])
        asset.hierarchy.set_local_transform(_key(bone['name']),t,True,False)
    asset.recompile_vm()
    if not unreal.EditorAssetLibrary.save_loaded_asset(asset,False):raise RuntimeError('网格参考姿势保存失败')
    return {**result,'chains':report,'graphNodes':len(nodes)+len(variables),'method':'reference_relative_swing_twist_absolute_rotation'}


def _qerror(a,b):
    na=math.sqrt(sum(float(x)**2 for x in a));nb=math.sqrt(sum(float(x)**2 for x in b))
    d=abs(sum(float(x)*float(y)for x,y in zip(a,b)))/(na*nb)
    return math.degrees(2*math.acos(min(1,d)))


def _metrics(surface, side):
    """/** @param surface 原生蒙皮 @param side 目标链 @return 实际面片边长应变和面积比 */"""
    vertices={v['id']:v for v in surface['vertices']}
    bones={b['name']:i for i,b in enumerate(surface['bones'])}
    selected={bones[side['parent']],bones[side['twist']]}
    def active(vertex):
        return sum(w for bone,w in vertex['weights'] if bone in selected)>.1
    edges=set()
    areas=[]
    def distance(a,b):return math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))
    def area(a,b,c):
        u=[b[i]-a[i] for i in range(3)];v=[c[i]-a[i]for i in range(3)]
        return .5*math.sqrt(sum(z*z for z in [u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]))
    for triangle in surface['triangles']:
        ids=triangle['vertices']
        if not all(active(vertices[i])for i in ids):continue
        p=[vertices[i]for i in ids]
        rest=area(*(v['bindPosition']for v in p))
        if rest>1e-6:areas.append(area(*(v['position']for v in p))/rest)
        for a,b in [(ids[0],ids[1]),(ids[1],ids[2]),(ids[2],ids[0])]:edges.add(tuple(sorted((a,b))))
    strain=[]
    for a,b in edges:
        rest=distance(vertices[a]['bindPosition'],vertices[b]['bindPosition'])
        if rest>1e-4:strain.append(abs(math.log(max(1e-8,distance(vertices[a]['position'],vertices[b]['position'])/rest))))
    if not strain or not areas:raise RuntimeError('目标前臂没有可比较的实际三角面')
    strain.sort();areas.sort()
    return {'edgeCount':len(strain),'rmsLogEdgeStrain':math.sqrt(sum(x*x for x in strain)/len(strain)),'p95LogEdgeStrain':strain[int((len(strain)-1)*.95)],'p05AreaRatio':areas[int((len(areas)-1)*.05)],'minimumAreaRatio':areas[0]}


def audit(asset_path, mesh_path, chains_json, cases_json, fractions, output_name):
    """/** @param asset_path 正式绑定 @param mesh_path 网格 @param chains_json 驱动链 @param cases_json 真实动作与明确测试旋转 @param fractions 比例候选 @param output_name 临时报告路径 @return 原生Rig实际姿势与蒙皮参数比较 */"""
    from BBBControlRigAuthoringToolset import _pose,_set_pose,_key,_read_transform
    from BBBGripGeometryTools import _output_path
    mesh,chains=_inputs(asset_path,mesh_path,chains_json)
    asset=unreal.load_asset(asset_path)
    if not isinstance(asset,unreal.ControlRigBlueprint) or not fractions or any(not math.isfinite(v)or not 0<=v<=1 for v in fractions):raise RuntimeError('绑定或候选比例无效')
    cases=json.loads(cases_json)
    if not cases or len(cases)>128:raise RuntimeError('明确测试场景数量无效')
    destination=_output_path(output_name)
    rig=asset.create_control_rig();rig.request_init();rig.execute_event('Forwards Solve');hierarchy=rig.get_hierarchy()
    reference=json.loads(unreal.BBBGripGeometryEditorLibrary.sample_skeletal_mesh_surface(mesh,[],[],1.0,[]))
    names=[b['name']for b in reference['bones']];available={str(k.name).lower()for k in hierarchy.get_bones()}
    if not {n.lower() for n in names}<=available:raise RuntimeError('Rig缺少网格原生骨骼 '+str({n for n in names if n.lower() not in available}))
    targets={c['twist']for c in chains}
    rows=[];max_position=0.;max_rotation=0.;max_scale=0.;max_repeat=0.
    for case_index,case in enumerate(cases):
        animation=unreal.load_asset(case['animation'])
        if not isinstance(animation,unreal.AnimSequence) or animation.get_editor_property('additive_anim_type')!=unreal.AdditiveAnimationType.AAT_NONE:raise RuntimeError('测试必须使用绝对动画')
        if not 0<=case['time']<=animation.sequence_length:raise RuntimeError('测试时间越界')
        pose=_pose(animation,mesh,case['time'])
        _set_pose(rig,pose)
        for name,rotation in case.get('driver_rotations',{}).items():
            if name not in {c['driver']for c in chains} or len(rotation)!=4 or abs(sum(q*q for q in rotation)-1)>.0001:raise RuntimeError('测试驱动骨旋转无效')
            transform=hierarchy.get_local_transform(_key(name));transform.rotation=unreal.Quat(*rotation);hierarchy.set_local_transform(_key(name),transform,False,True)
        source_local={n:hierarchy.get_local_transform(_key(n))for n in names}
        source_component={n:hierarchy.get_global_transform(_key(n))for n in names}
        source_surface=json.loads(unreal.BBBGripGeometryEditorLibrary.sample_skeletal_mesh_surface(mesh,list(source_component.values()),[c['parent']for c in chains],.25,[]))
        if [b['name'] for b in source_surface['bones']] != names:raise RuntimeError('Rig骨数组与网格原生骨序不一致')
        baseline={c['twist']:_metrics(source_surface,c)for c in chains}
        source_file=destination.parent/(destination.stem+'_case'+str(case_index)+'_source.json')
        source_file.parent.mkdir(parents=True,exist_ok=True);source_file.write_text(json.dumps(source_surface),encoding='utf-8')
        for fraction in fractions:
            for n in names:hierarchy.set_local_transform(_key(n),source_local[n],False,False)
            for c in chains:
                if not rig.set_variable_from_string(c['variable'],str(fraction)):raise RuntimeError('扭转比例公开变量赋值失败')
            if not rig.execute_event('Forwards Solve'):raise RuntimeError('正式Rig正向执行失败')
            local={n:hierarchy.get_local_transform(_key(n))for n in names};component=[hierarchy.get_global_transform(_key(n))for n in names]
            for n in names:
                before=_read_transform(source_local[n]);after=_read_transform(local[n]);pe=math.dist(before['position'],after['position']);se=math.dist(before['scale'],after['scale']);re=_qerror(before['rotation'],after['rotation']) if n not in targets else 0.
                max_position=max(max_position,pe);max_scale=max(max_scale,se);max_rotation=max(max_rotation,re)
            if not rig.execute_event('Forwards Solve'):raise RuntimeError('正式Rig重复执行失败')
            for n in targets:max_repeat=max(max_repeat,_qerror(_read_transform(local[n])['rotation'],_read_transform(hierarchy.get_local_transform(_key(n)))['rotation']))
            surface=json.loads(unreal.BBBGripGeometryEditorLibrary.sample_skeletal_mesh_surface(mesh,component,[c['parent']for c in chains],.25,[]))
            file=destination.parent/(destination.stem+'_case'+str(case_index)+'_'+str(fraction).replace('.','_')+'.json')
            file.parent.mkdir(parents=True,exist_ok=True);file.write_text(json.dumps(surface))
            rows.append({'case':case.get('name',str(case_index)),'animation':case['animation'],'time':case['time'],'fraction':fraction,'surface':str(file),'sourceSurface':str(source_file),'baseline':baseline,'metrics':{c['twist']:_metrics(surface,c)for c in chains},'twistRotations':{n:_read_transform(local[n])['rotation']for n in targets}})
    result={'asset':asset_path,'mesh':mesh_path,'cases':len(cases),'candidateCount':len(fractions),'rows':rows,'maximumNonTargetRotationDegrees':max_rotation,'maximumPositionCm':max_position,'maximumScaleError':max_scale,'maximumRepeatRotationDegrees':max_repeat,'nativeRigVMExecuted':True,'nativeCPUSkinning':True,'morphClothDeformerEvaluated':False,'mainGameplayEvaluated':False,'passed':max_position<.001 and max_rotation<.02 and max_scale<.0001 and max_repeat<.02}
    destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(result));return {k:v for k,v in result.items()if k!='rows'}|{'report':str(destination)}


def insert(main_path,asset_path,after_node_guid,before_node_guid,output_bones,input_values_json):
    """/** @param main_path 主图 @param asset_path 绑定 @param after_node_guid 上游 @param before_node_guid 下游 @param output_bones 回写骨骼 @param input_values_json 明确浮点输入 @return 编译保存结果 */"""
    main=unreal.load_asset(main_path);rig=unreal.load_asset(asset_path)
    if not isinstance(main,unreal.AnimBlueprint)or not isinstance(rig,unreal.ControlRigBlueprint):raise RuntimeError('需要已保存动画蓝图与绑定')
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:raise RuntimeError('PIE期间禁止插入绑定')
    dirty={p.get_path_name()for p in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    if main.get_outermost().get_path_name() in dirty:raise RuntimeError('主图仍有未交接的修改')
    require_asset_write([main])
    values=json.loads(input_values_json)
    report=json.loads(unreal.BBBHandPoseLayerEditorLibrary.insert_post_process_control_rig(main,rig,after_node_guid,before_node_guid,output_bones,values))
    if report.get('status')!='ok' or not report.get('compiled'):raise RuntimeError(json.dumps(report,ensure_ascii=False))
    if not unreal.EditorAssetLibrary.save_loaded_asset(main,False):raise RuntimeError('主图保存失败')
    return report|{'saved':[main.get_path_name()]}


def sample_node(main_path,mesh_path,node_guid,animation_path,time_seconds,output_name):
    """/** @param main_path 主图 @param mesh_path 网格 @param node_guid 节点 @param animation_path 动作 @param time_seconds 秒数 @param output_name 临时输出 @return 正式节点隔离执行和非目标骨骼误差 */"""
    from BBBGripGeometryTools import _output_path
    destination=_output_path(output_name)
    report=json.loads(unreal.BBBHandPoseLayerEditorLibrary.sample_post_process_control_rig(unreal.load_asset(mesh_path),unreal.load_asset(main_path),node_guid,unreal.load_asset(animation_path),time_seconds))
    if report.get('status')!='ok':raise RuntimeError(json.dumps(report,ensure_ascii=False))
    before=report['sourceLocal'];after=report['solvedLocal'];changed=[];position=0.;scale=0.;other=0.
    for n in before:
        rotation=_qerror(before[n][3:7],after[n][3:7]);position=max(position,math.dist(before[n][:3],after[n][:3]));scale=max(scale,math.dist(before[n][7:],after[n][7:]))
        if rotation>.02:changed.append(n)
        if n.lower()not in {'lowerarm_twist_01_l','lowerarm_twist_01_r'}:other=max(other,rotation)
    summary={'changedBones':changed,'maximumPositionCm':position,'maximumScaleError':scale,'maximumNonTargetRotationDegrees':other,'nativeAnimNodeExecuted':True,'mainGameplayEvaluated':False,'passed':position<.001 and scale<.0001 and other<.02}
    destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(report|summary),encoding='utf-8')
    return summary|{'report':str(destination)}
