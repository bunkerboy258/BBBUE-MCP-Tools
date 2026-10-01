import json
import math
import os
import time

import unreal


_capture = None
_capture_handle = None


def _transform(value):
    return {"position": [value.translation.x, value.translation.y, value.translation.z],
            "rotation": [value.rotation.x, value.rotation.y, value.rotation.z, value.rotation.w],
            "scale": [value.scale3d.x, value.scale3d.y, value.scale3d.z]}


def _capture_image(world, mesh, offset, path, exposure_compensation, fill_light_intensity, focus_bone):
    target = mesh.get_socket_location(focus_bone)
    location = target + unreal.Vector(*offset)
    rotation = unreal.MathLibrary.find_look_at_rotation(location, target)
    camera = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(
        world, unreal.SceneCapture2D, unreal.Transform(location=location, rotation=rotation))
    light = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(
        world, unreal.PointLight, unreal.Transform(location=location))
    try:
        light.light_component.set_intensity(fill_light_intensity)
        light.light_component.set_attenuation_radius(600.0)
        light.light_component.set_cast_shadows(False)
        component = camera.capture_component2d
        target_texture = unreal.RenderingLibrary.create_render_target2d(
            world, 768, 768, unreal.TextureRenderTargetFormat.RTF_RGBA8)
        component.set_editor_property("texture_target", target_texture)
        component.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
        component.set_editor_property("fov_angle", 45.0)
        # 固定曝光并关闭运动模糊 保证不同阶段的暗部与腕部轮廓可以直接比较
        settings = component.get_editor_property("post_process_settings")
        settings.set_editor_property("override_auto_exposure_method", True)
        settings.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
        settings.set_editor_property("override_auto_exposure_apply_physical_camera_exposure", True)
        settings.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
        settings.set_editor_property("b_override_exposure_offset", True)
        settings.set_editor_property("exposure_offset", exposure_compensation)
        settings.set_editor_property("override_motion_blur_amount", True)
        settings.set_editor_property("motion_blur_amount", 0.0)
        component.set_editor_property("post_process_settings", settings)
        component.set_editor_property("post_process_blend_weight", 1.0)
        component.capture_scene()
        unreal.RenderingLibrary.export_render_target(world, target_texture, os.path.dirname(path), os.path.basename(path))
    finally:
        camera.destroy_actor()
        light.destroy_actor()


def start_capture(montage_path, times, prefix, interrupt_time=-1.0, capture_images=True, post_roll_seconds=0.6,
        exposure_compensation=1.0, fill_light_intensity=5000.0, focus_bone="spine_03"):
    global _capture, _capture_handle
    if _capture_handle is not None:
        raise RuntimeError("动画采样仍在运行")
    times = [float(value) for value in times]
    if not times or sorted(times) != times or os.path.basename(prefix) != prefix:
        raise RuntimeError("采样时间或文件前缀无效")
    if not math.isfinite(exposure_compensation) or not -4.0 <= exposure_compensation <= 4.0:
        raise RuntimeError("截图曝光补偿必须在负四到正四之间")
    if not math.isfinite(fill_light_intensity) or not 0.0 <= fill_light_intensity <= 50000.0:
        raise RuntimeError("截图补光强度必须在零到五万之间")
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    montage = unreal.load_asset(montage_path)
    pawn = unreal.GameplayStatics.get_player_pawn(world, 0) if world else None
    if pawn is None or not isinstance(montage, unreal.AnimMontage):
        raise RuntimeError("需要有效本地角色和蒙太奇")
    directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "Diagnostics", "AnimationMotion", prefix))
    os.makedirs(directory, exist_ok=False)
    _capture = {"state": "waiting", "directory": directory, "times": times, "next": 0,
                "rows": [], "images": [], "started": time.monotonic(), "error": None}
    mesh = pawn.get_editor_property("mesh")
    if mesh.get_bone_index(focus_bone) < 0:
        raise RuntimeError("截图关注骨骼不存在 " + focus_bone)
    animation = mesh.get_anim_instance()
    if post_roll_seconds < 0.0 or post_roll_seconds > 5.0:
        raise RuntimeError("结束后采样时长必须在零到五秒之间")
    slots = list(montage.get_editor_property("slot_anim_tracks"))
    sequence = slots[0].get_editor_property("anim_track").get_editor_property("anim_segments")[0].get_editor_property("anim_reference")
    options = unreal.AnimPoseEvaluationOptions()
    options.optional_skeletal_mesh = mesh.get_skinned_asset()
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    options.should_retarget = True
    _capture["animation"] = sequence.get_path_name()
    _capture["postRollSeconds"] = post_roll_seconds
    _capture["imageSettings"] = {"exposureCompensation": exposure_compensation,
        "fillLightIntensity": fill_light_intensity, "focusBone": focus_bone}
    performance = unreal.get_default_object(unreal.load_class(None, "/Script/UnrealEd.EditorPerformanceSettings"))
    previous_throttle = performance.get_editor_property("bThrottleCPUWhenNotForeground")
    performance.set_editor_property("bThrottleCPUWhenNotForeground", False)
    previous_dilation = unreal.GameplayStatics.get_global_time_dilation(world)
    unreal.GameplayStatics.set_global_time_dilation(world, 0.1)
    bones = ["clavicle_l", "upperarm_l", "lowerarm_l", "hand_l", "hand_r", "spine_03",
        "lowerarm_twist_01_l", "index_01_l", "middle_01_l", "pinky_01_l"]
    _capture["referenceBones"] = {
        name: {"parent": str(mesh.get_parent_bone(name)),
            "local": _transform(mesh.get_ref_pose_transform(mesh.get_bone_index(name)))}
        for name in bones
    }
    rifle_class = unreal.load_class(None, "/Script/ABBB_Evac.BBBRifleEquipment")
    initial_mesh_actors = {
        actor.get_path_name()
        for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.StaticMeshActor)
    }

    def finish(state):
        global _capture_handle
        _capture["state"] = state
        if _capture_handle is not None:
            unreal.unregister_slate_post_tick_callback(_capture_handle)
        _capture_handle = None
        performance.set_editor_property("bThrottleCPUWhenNotForeground", previous_throttle)
        unreal.GameplayStatics.set_global_time_dilation(world, previous_dilation)
        with open(os.path.join(directory, "motion.json"), "w", encoding="utf-8") as output:
            json.dump(_capture, output, ensure_ascii=False, indent=2)

    def tick(delta_seconds):
        try:
            # 离屏渲染宿主的实时帧率可能不足每秒两帧 超时需要覆盖整个慢速蒙太奇与后滚采样
            if time.monotonic() - _capture["started"] > 300.0:
                raise RuntimeError("等待蒙太奇采样超时")
            active = animation.montage_is_active(montage)
            world_time = unreal.GameplayStatics.get_time_seconds(world)
            if not active and _capture["state"] == "waiting":
                return
            if active and _capture["state"] == "waiting":
                _capture["firstWorldTime"] = world_time - animation.montage_get_position(montage)
                _capture["state"] = "recording"
            if not active and _capture["state"] == "recording":
                _capture["state"] = "postRoll"
                _capture["endedWorldTime"] = world_time
            if _capture["state"] == "postRoll" and world_time - _capture["endedWorldTime"] >= post_roll_seconds:
                finish("completed")
                return
            position = world_time - _capture["firstWorldTime"]
            montage_position = animation.montage_get_position(montage) if active else None
            raw_pose = sequence.get_anim_pose_at_time(min(position, sequence.get_play_length()), options)
            row = {"time": position, "worldTime": world_time,
                   "montagePosition": montage_position, "phase": _capture["state"],
                   "meshAsset": mesh.get_skinned_asset().get_path_name(),
                   "meshTransform": _transform(mesh.get_socket_transform("None")),
                   "bones": {name: _transform(mesh.get_socket_transform(name)) for name in bones},
                   "rawBones": {name: _transform(raw_pose.get_bone_pose(name, unreal.AnimPoseSpaces.WORLD)) for name in bones},
                   "curves": {name: animation.get_curve_value(name) for name in ["DisableLHandIK", "DisableAimIK"]},
                   "equipment": [], "magazines": [], "spawnedMeshes": []}
            for actor in unreal.GameplayStatics.get_all_actors_of_class(world, rifle_class):
                if actor.get_owner() != pawn:
                    continue
                for weapon in actor.get_components_by_class(unreal.SkeletalMeshComponent):
                    row["equipment"].append({"actor": actor.get_path_name(), "asset": weapon.get_skinned_asset().get_path_name(),
                        "transform": _transform(weapon.get_socket_transform("None")),
                        "magazine": _transform(weapon.get_socket_transform("Magazine_joint")),
                        "leftHand": _transform(weapon.get_socket_transform("LeftHand")) if weapon.does_socket_exist("LeftHand") else None,
                        "relativeHandR": _transform(unreal.MathLibrary.make_relative_transform(weapon.get_socket_transform("None"), mesh.get_socket_transform("hand_r")))})
            for child in mesh.get_children_components(True):
                if isinstance(child, unreal.StaticMeshComponent):
                    row["magazines"].append({"name": child.get_name(), "transform": _transform(child.get_socket_transform("None"))})
            for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.StaticMeshActor):
                if actor.get_path_name() in initial_mesh_actors:
                    continue
                component = actor.static_mesh_component
                linear = component.get_physics_linear_velocity()
                angular = component.get_physics_angular_velocity_in_radians()
                row["spawnedMeshes"].append({
                    "actor": actor.get_path_name(),
                    "transform": _transform(component.get_socket_transform("None")),
                    "linearVelocity": [linear.x, linear.y, linear.z],
                    "angularVelocity": [angular.x, angular.y, angular.z],
                })
            _capture["rows"].append(row)
            if active and interrupt_time >= 0.0 and position >= interrupt_time:
                animation.montage_stop(0.0, montage)
                _capture["interruptedAt"] = position
                return
            index = _capture["next"]
            if capture_images and index < len(times) and position >= times[index]:
                distance_scale = 0.55 if focus_bone == "hand_l" else 1.0
                for view, offset in [("front", [150, 70, 15]), ("side", [30, 180, 15])]:
                    offset = [value * distance_scale for value in offset]
                    path = os.path.join(directory, "{:02d}_{:.3f}_{}.png".format(index, position, view))
                    _capture_image(world, mesh, offset, path, exposure_compensation, fill_light_intensity, focus_bone)
                    _capture["images"].append({"time": position, "path": path})
                _capture["next"] += 1
        except Exception as error:
            _capture["error"] = str(error)
            unreal.log_error("动画运动采样失败 " + str(error))
            finish("failed")

    _capture_handle = unreal.register_slate_post_tick_callback(tick)
    return json.dumps({"state": "waiting", "directory": directory})


def capture_status():
    if _capture is None:
        return json.dumps({"state": "idle"})
    return json.dumps({key: value for key, value in _capture.items() if key != "rows"}, ensure_ascii=False)


def export_context(animation_paths, mesh_paths, file_name):
    if os.path.basename(file_name) != file_name:
        raise RuntimeError("报告文件名无效")
    result = {"animations": [], "meshes": []}
    for path in animation_paths:
        animation = unreal.load_asset(path)
        if not isinstance(animation, unreal.AnimSequence):
            raise RuntimeError("动画不存在 " + path)
        result["animations"].append({"path": path, "length": animation.get_play_length(),
            "tracks": {str(name): [_transform(value) for value in unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name)]
                for name in animation.data_model_interface.get_bone_track_names()}})
    subsystem = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
    for path in mesh_paths:
        mesh = unreal.load_asset(path)
        reference = unreal.AnimPoseExtensions.get_reference_pose(mesh.get_editor_property("skeleton"))
        result["meshes"].append({"path": path, "bones": {str(name): {
            "parent": str(subsystem.get_bone_parent(mesh, name)),
            "local": _transform(reference.get_ref_bone_pose(name, unreal.AnimPoseSpaces.LOCAL)),
            "component": _transform(reference.get_ref_bone_pose(name, unreal.AnimPoseSpaces.WORLD))}
            for name in reference.get_bone_names()}})
    path = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "Diagnostics", file_name))
    with open(path, "w", encoding="utf-8") as output:
        json.dump(result, output)
    return json.dumps({"report": path})


if __name__ == "__bbb_editor_script__":
    import importlib
    import sys

    if "BBBAnimationMotionTools" in sys.modules:
        importlib.reload(sys.modules["BBBAnimationMotionTools"] )
