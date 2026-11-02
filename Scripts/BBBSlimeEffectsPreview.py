"""正式黏液四段表现的短时离屏打磨。"""
import json
import math
import os
import re
import time
import unreal

_report = {'status':'idle'}
_handle = None

def capture(definition_path, file_prefix):
    """/** @param definition_path 正式黏液配置 @param file_prefix 自有临时目录 @return 仅驱动表现载体的短时拍摄 */"""
    global _report, _handle
    if _handle is not None or not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_-]+', file_prefix):
        raise RuntimeError('拍摄仍在运行或前缀无效')
    definition = unreal.load_asset(definition_path)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    if not isinstance(definition, unreal.BBBSlimeDefinition) or not definition.is_presentation_ready() or world is None:
        raise RuntimeError('需要已保存的完整配置与独立渲染 PIE')
    directory, stem = file_prefix.split('/')
    directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(),'temp',directory))
    if os.path.islink(directory) or os.path.exists(os.path.join(directory,stem+'_mouth.png')):
        raise RuntimeError('拍摄目录不得为链接且不能覆盖输出')
    settings = definition.get_editor_property('presentation')
    for key in ('mouth_system','flight_system','impact_system','ground_system'):
        if not unreal.BBBNiagaraEditorLibrary.prepare_system_for_preview(settings.get_editor_property(key).get_path_name()):
            raise RuntimeError('粒子尚未就绪 '+key)
    origin = unreal.Vector(0,0,50000)
    actors = []
    controller = None
    previous = None
    def spawn(kind, location, rotation=unreal.Rotator()):
        actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, kind, unreal.Transform(location=location+origin,rotation=rotation))
        actors.append(actor)
        return actor
    try:
        floor = spawn(unreal.StaticMeshActor,unreal.Vector(0,0,-2))
        floor.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
        floor.static_mesh_component.set_static_mesh(unreal.load_asset('/Engine/BasicShapes/Plane'))
        floor.set_actor_scale3d(unreal.Vector(25,25,1))
        light = spawn(unreal.DirectionalLight,unreal.Vector(0,0,500),unreal.Rotator(pitch=-55,yaw=-30,roll=0))
        light.light_component.set_editor_property('intensity',6.0)
        slime = spawn(unreal.BBBSlimePresentationActor,unreal.Vector(-450,0,180))
        camera_location = unreal.Vector(-250,-1150,780)
        camera = spawn(unreal.SceneCapture2D,camera_location,unreal.MathLibrary.find_look_at_rotation(camera_location,unreal.Vector(0,0,70)))
        controller=unreal.GameplayStatics.get_player_controller(world,0)
        previous=controller.get_view_target() if controller else None
        if controller:
            controller.set_view_target_with_blend(camera,0.0)
        view = camera.capture_component2d
        view.set_editor_property('capture_every_frame',False)
        view.set_editor_property('capture_on_movement',False)
        view.set_editor_property('fov_angle',57.0)
        target = unreal.RenderingLibrary.create_render_target2d(world,960,640,unreal.TextureRenderTargetFormat.RTF_RGBA8)
        camera_location=camera_location+origin
        view.set_editor_property('texture_target',target)
        view.set_editor_property('capture_source',unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
        view.set_editor_property('hidden_actors',list(unreal.GameplayStatics.get_all_actors_of_class(world,unreal.Pawn)))
        post = view.get_editor_property('post_process_settings')
        for key,value in [('override_auto_exposure_method',True),('auto_exposure_method',unreal.AutoExposureMethod.AEM_MANUAL),
                          ('override_auto_exposure_apply_physical_camera_exposure',True),('auto_exposure_apply_physical_camera_exposure',False),
                          ('override_auto_exposure_bias',True),('auto_exposure_bias',1.2)]:
            post.set_editor_property(key,value)
        view.set_editor_property('post_process_settings',post)
        started = unreal.GameplayStatics.get_time_seconds(world)
        gravity = 980.0*definition.get_editor_property('gravity_scale')
        land = (200+math.sqrt(200*200+2*gravity*180))/gravity
        fact = unreal.BBBSlimeFact()
        instance,valid = unreal.GuidLibrary.parse_string_to_guid('9B81EBB44AB54B2A870BC01ABED76B03')
        source,valid = unreal.GuidLibrary.parse_string_to_guid('A389BB2B4FA74ABD98175E1B4923BBFA')
        for key,value in [('instance_id',instance),('source_id',source),('revision',1),('definition',definition),('normal',unreal.Vector(0,0,1))]:
            fact.set_editor_property(key,value)
        _report = {'status':'running','definition':definition_path,'flightSeconds':land,'images':[],'particleSnapshots':[],'error':None}
        moments = [(0.10,'mouth'),(.55,'flight'),(land+.12,'impact'),(land+1.1,'ground'),(land+definition.get_editor_property('lifetime')+.15,'fade')]
        state = {'index':0,'pending':None,'start':started+.5,'wallStart':time.monotonic()}
        def finish(status,error=None):
            global _handle
            _report['status'] = status
            _report['error'] = error
            if _handle is not None:
                unreal.unregister_slate_post_tick_callback(_handle)
                _handle = None
            if controller and previous and unreal.SystemLibrary.is_valid(previous):
                controller.set_view_target_with_blend(previous,0.0)
            for actor in reversed(actors):
                if unreal.SystemLibrary.is_valid(actor):
                    actor.destroy_actor()
        def tick(delta):
            try:
                if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() != world:
                    raise RuntimeError('拍摄世界已经结束')
                if time.monotonic()-state['wallStart'] > 90:
                    raise RuntimeError('拍摄超时')
                now = unreal.GameplayStatics.get_time_seconds(world)
                age = now-state['start']
                if age < 0:
                    return
                if age < land:
                    fact.set_editor_property('phase',0)
                    fact.set_editor_property('location',origin+unreal.Vector(-450+650*age,0,180+200*age-.5*gravity*age*age))
                    fact.set_editor_property('velocity',unreal.Vector(650,0,200-gravity*age))
                    fact.set_editor_property('ends_at',state['start']+definition.get_editor_property('flight_lifetime'))
                else:
                    fact.set_editor_property('phase',1)
                    fact.set_editor_property('location',origin+unreal.Vector(-450+650*land,0,0))
                    fact.set_editor_property('velocity',unreal.Vector())
                    fact.set_editor_property('ends_at',state['start']+land+definition.get_editor_property('lifetime'))
                fact.set_editor_property('revision',fact.get_editor_property('revision')+1)
                slime.apply_fact(fact)
                if state['pending'] is not None:
                    label,at = state['pending']
                    os.makedirs(directory,exist_ok=True)
                    name = stem+'_'+label+'.png'
                    unreal.RenderingLibrary.export_render_target(world,target,directory,name)
                    path = os.path.join(directory,name)
                    if not os.path.isfile(path):
                        raise RuntimeError('图像未保存')
                    _report['images'].append({'phase':label,'seconds':at,'path':path})
                    _report['particleSnapshots'].append({key:str(unreal.BBBNiagaraEditorLibrary.inspect_pie_system(settings.get_editor_property(key).get_path_name())) for key in ('mouth_system','flight_system','impact_system','ground_system')})
                    state['pending'] = None
                    state['index'] += 1
                    if state['index'] == len(moments):
                        finish('completed')
                        return
                if state['index'] < len(moments) and age >= moments[state['index']][0]:
                    focus=fact.get_editor_property('location')
                    position=focus+unreal.Vector(0,-600,400)
                    camera.set_actor_location(position,False,False)
                    camera.set_actor_rotation(unreal.MathLibrary.find_look_at_rotation(position,focus),False)
                    view.capture_scene()
                    state['pending'] = (moments[state['index']][1],age)
            except Exception as error:
                finish('failed',str(error))
        _handle = unreal.register_slate_post_tick_callback(tick)
        from BBBMcpCapabilities import register_activity
        register_activity('slime:capture',lambda:_handle is not None)
        return json.dumps(_report)
    except Exception:
        if controller and previous and unreal.SystemLibrary.is_valid(previous):
            controller.set_view_target_with_blend(previous,0.0)
        for actor in reversed(actors):
            if unreal.SystemLibrary.is_valid(actor):
                actor.destroy_actor()
        raise

def status():
    """/** @return 最近一次真实拍摄结果 */"""
    return json.dumps(_report)
