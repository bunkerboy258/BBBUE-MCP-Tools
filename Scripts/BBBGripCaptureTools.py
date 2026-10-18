import json
import math
import os
from pathlib import Path
import re
import uuid

import unreal


_CAPTURES = {}


def capture_status(capture_id):
    """/** @param capture_id 本宿主创建的截图编号 @return 完成或失败的实际记录 */"""
    if capture_id not in _CAPTURES:
        raise RuntimeError('GRIP_CAPTURE_UNKNOWN: 请核对宿主和截图编号')
    return dict(_CAPTURES[capture_id])


def start_capture(animation_path, mesh_path, time_seconds, attachments_json, camera_offset, file_name, exposure_bias, target_bone):
    """/** @param animation_path 静态或动作序列 @param mesh_path 实际角色网格 @param time_seconds 取样时刻 @param attachments_json 真实附件配置 @param camera_offset 相对腕骨观察位置 @param file_name 本任务输出名 @param exposure_bias 手动曝光补偿 @param target_bone 观察腕骨 @return 跨帧任务及完整状态查询参数 */"""
    camera_offset = list(camera_offset)
    if not math.isfinite(exposure_bias) or not -6 <= exposure_bias <= 6:
        raise RuntimeError('手部截图曝光补偿必须为负六至六的有限数')
    if not target_bone or not math.isfinite(time_seconds) or time_seconds < 0 or len(camera_offset) != 3 or any(not math.isfinite(value) for value in camera_offset):
        raise RuntimeError('手部截图需要明确目标骨骼及有限采样参数')
    if re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_-]+\.png', file_name) is None:
        raise RuntimeError('截图名称必须为任务目录和png文件名')
    if '-nullrhi' in unreal.SystemLibrary.get_command_line().lower():
        raise RuntimeError('手部截图需要带渲染的宿主')
    if any(record['status'] == 'pending' for record in _CAPTURES.values()):
        raise RuntimeError('已有手部截图预热中 请先等待其批次完成')
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    if world is None:
        raise RuntimeError('手部截图需要先启动PIE或Simulate')
    root = Path(unreal.Paths.project_saved_dir()).resolve() / 'temp'
    path = root / file_name
    for parent in (root, path.parent):
        if parent.is_symlink() or (parent.exists() and getattr(os.path, 'isjunction', lambda item: False)(parent)):
            raise RuntimeError('截图目录不得为链接')
    if path.exists():
        raise RuntimeError('截图拒绝覆盖已有文件')
    mesh = unreal.load_asset(mesh_path)
    animation = unreal.load_asset(animation_path)
    if not isinstance(mesh, unreal.SkeletalMesh) or not isinstance(animation, unreal.AnimSequence) or time_seconds > animation.get_play_length():
        raise RuntimeError('截图网格动画或采样时刻无效')
    attachments = json.loads(attachments_json)
    capture_id = uuid.uuid4().hex
    record = {'status': 'pending', 'captureId': capture_id, 'imagePath': str(path), 'time': time_seconds,
              'resolution': [640, 640], 'targetBone': target_bone, 'exposureBias': exposure_bias,
              'linearExposureMultiplier': 2 ** exposure_bias,
              'temporaryActorsDestroyed': False, 'warmupFrames': 60}
    _CAPTURES[capture_id] = record

    def render_frames():
        """/** @return 逐帧准备真实材质和蒙皮 再捕获并销毁所属演员 */"""
        actors = []
        spawn = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor
        evaluate = unreal.BBBBlueprintEditorLibrary.evaluate_animation_preview_pose
        try:
            actor = spawn(world, unreal.SkeletalMeshActor, unreal.Transform(location=unreal.Vector(0, 0, 10000)))
            actors.append(actor)
            component = actor.skeletal_mesh_component
            component.set_skeletal_mesh_asset(mesh)
            component.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
            if not component.does_socket_exist(target_bone):
                raise RuntimeError('截图目标骨骼不存在: ' + target_bone)
            visible = [actor]
            posed = [(component, animation, time_seconds)]
            attached = []
            for request in attachments:
                asset = unreal.load_asset(request['mesh'])
                if not isinstance(asset, (unreal.SkeletalMesh, unreal.StaticMesh)):
                    raise RuntimeError('截图附件不是明确网格')
                actor_class = unreal.StaticMeshActor
                if isinstance(asset, unreal.SkeletalMesh):
                    actor_class = unreal.SkeletalMeshActor
                prop = spawn(world, actor_class, unreal.Transform())
                actors.append(prop)
                prop_component = prop.get_component_by_class(unreal.MeshComponent)
                prop_component.set_mobility(unreal.ComponentMobility.MOVABLE)
                prop_component.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
                if isinstance(asset, unreal.SkeletalMesh):
                    prop_component.set_skeletal_mesh_asset(asset)
                    if request.get('animation'):
                        prop_animation = unreal.load_asset(request['animation'])
                        if not isinstance(prop_animation, unreal.AnimSequence):
                            raise RuntimeError('截图附件动画类型无效')
                        posed.append((prop_component, prop_animation, request.get('animation_time_seconds', time_seconds)))
                    for bone in request.get('hidden_bones', []):
                        prop_component.hide_bone_by_name(bone, unreal.PhysBodyOp.PBO_NONE)
                if isinstance(asset, unreal.StaticMesh):
                    prop_component.set_static_mesh(asset)
                values = request['transform']
                transform = unreal.Transform(location=unreal.Vector(*values.get('position', [0, 0, 0])), scale=unreal.Vector(*values.get('scale', [1, 1, 1])))
                transform.rotation = unreal.Quat(*values.get('rotation', [0, 0, 0, 1]))
                attached.append((prop, request['socket'], transform))
                visible.append(prop)
            camera = spawn(world, unreal.SceneCapture2D, unreal.Transform())
            actors.append(camera)
            light = spawn(world, unreal.PointLight, unreal.Transform())
            actors.append(light)
            light_component = light.get_component_by_class(unreal.PointLightComponent)
            light_component.set_intensity(2000)
            light_component.set_attenuation_radius(2000)
            light_component.set_cast_shadows(False)
            target = unreal.RenderingLibrary.create_render_target2d(world, 640, 640, unreal.TextureRenderTargetFormat.RTF_RGBA8)
            capture = camera.capture_component2d
            capture.set_editor_property('texture_target', target)
            capture.set_editor_property('capture_source', unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
            capture.set_editor_property('capture_every_frame', False)
            capture.set_editor_property('capture_on_movement', False)
            capture.set_editor_property('always_persist_rendering_state', True)
            capture.set_editor_property('primitive_render_mode', unreal.SceneCapturePrimitiveRenderMode.PRM_USE_SHOW_ONLY_LIST)
            capture.set_editor_property('show_only_actors', visible)
            capture.set_editor_property('fov_angle', 45)
            flags = [unreal.EngineShowFlagsSetting(show_flag_name=name, enabled=True)
                     for name in ('PostProcessing', 'Tonemapper', 'EyeAdaptation')]
            capture.set_editor_property('show_flag_settings', flags)
            settings = unreal.PostProcessSettings()
            for name in ('auto_exposure_method', 'auto_exposure_apply_physical_camera_exposure', 'auto_exposure_bias',
                         'dynamic_global_illumination_method', 'reflection_method', 'motion_blur_amount'):
                settings.set_editor_property('override_' + name, True)
            settings.set_editor_property('auto_exposure_method', unreal.AutoExposureMethod.AEM_MANUAL)
            settings.set_editor_property('auto_exposure_apply_physical_camera_exposure', False)
            settings.set_editor_property('auto_exposure_bias', 0)
            settings.set_editor_property('override_scene_color_tint', True)
            multiplier = 2 ** exposure_bias
            settings.set_editor_property('scene_color_tint', unreal.LinearColor(multiplier, multiplier, multiplier, 1))
            settings.set_editor_property('dynamic_global_illumination_method', unreal.DynamicGlobalIlluminationMethod.NONE)
            settings.set_editor_property('reflection_method', unreal.ReflectionMethod.NONE)
            settings.set_editor_property('motion_blur_amount', 0)
            settings.set_editor_property('ambient_cubemap', unreal.load_asset('/Engine/EngineResources/GrayLightTextureCube'))
            settings.set_editor_property('override_ambient_cubemap_intensity', True)
            settings.set_editor_property('ambient_cubemap_intensity', 1)
            capture.set_editor_property('post_process_settings', settings)
            capture.set_editor_property('post_process_blend_weight', 1)
            for frame in range(60):
                for current_component, current_animation, seconds in posed:
                    if not evaluate(current_component, current_animation, seconds):
                        raise RuntimeError('截图固定姿势求值失败')
                for prop, socket, transform in attached:
                    parent = component.get_socket_transform(socket, unreal.RelativeTransformSpace.RTS_WORLD)
                    prop.set_actor_transform(unreal.MathLibrary.compose_transforms(transform, parent), False, True)
                center = component.get_socket_location(target_bone)
                location = center + unreal.Vector(*camera_offset)
                camera.set_actor_location(location, False, True)
                camera.set_actor_rotation(unreal.MathLibrary.find_look_at_rotation(location, center), True)
                light.set_actor_location(location, False, True)
                if frame >= 56:
                    capture.capture_scene()
                yield
            capture.capture_scene()
            yield
            path.parent.mkdir(parents=True, exist_ok=True)
            unreal.RenderingLibrary.export_render_target(world, target, str(path.parent), path.name)
            if not path.is_file() or path.stat().st_size < 1024:
                raise RuntimeError('截图文件缺失或内容过小')
            yield
        finally:
            for actor in reversed(actors):
                if unreal.SystemLibrary.is_valid(actor):
                    actor.destroy_actor()
            record['temporaryActorsDestroyed'] = True

    iterator = render_frames()
    handle = None

    def advance_frame(delta_seconds):
        """/** @param delta_seconds 编辑器帧间隔 @return 完成一个渲染阶段或清理失败 */"""
        try:
            if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() != world:
                raise RuntimeError('截图期间PIE世界已经结束')
            next(iterator)
        except StopIteration:
            record['status'] = 'completed'
            unreal.unregister_slate_post_tick_callback(handle)
        except Exception as error:
            record['status'] = 'failed'
            record['error'] = str(error)
            try:
                iterator.close()
            except Exception as cleanup_error:
                record['cleanupError'] = str(cleanup_error)
            unreal.unregister_slate_post_tick_callback(handle)
            unreal.log_error('[BBBGripCapture] ' + str(error))

    from BBBMcpCapabilities import register_activity
    register_activity('grip_capture:' + capture_id, lambda: dict(record))
    handle = unreal.register_slate_post_tick_callback(advance_frame)
    result = dict(record)
    result['next'] = {'tool': 'control_rig.capture_attachment_pose', 'arguments': {
        'animation_path': animation_path, 'mesh_path': mesh_path, 'time_seconds': time_seconds,
        'attachments': attachments, 'camera_offset': camera_offset, 'file_name': file_name,
        'exposure_bias': exposure_bias, 'target_bone': target_bone, 'action': 'status', 'capture_id': capture_id}}
    return json.dumps(result, ensure_ascii=False)
