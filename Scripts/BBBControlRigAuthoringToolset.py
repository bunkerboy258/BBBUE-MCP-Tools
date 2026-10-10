import json
import math
import os
import stat
import sys
import traceback

import unreal
from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration
from BBBAssetWritePolicy import require_write_access, require_asset_write


def _asset(path, expected_type):
    value = unreal.load_asset(path)
    if not isinstance(value, expected_type):
        raise RuntimeError("资产类型无效 " + path)

    return value


def _key(name, kind="BONE"):
    return unreal.RigElementKey(name=name, type=getattr(unreal.RigElementType, kind))


def _add_graph_variables(asset, graph, request):
    """/** 为显式图配置建立公开输入变量及读取节点 */"""
    for variable in request.get("variables", []):
        name = variable["name"]
        type_object = None
        if variable.get("typeObject"):
            type_object = unreal.load_object(None, variable["typeObject"])
            if type_object is None:
                raise RuntimeError("变量反射类型不存在 " + variable["typeObject"])

        member_type = variable.get("typeObject", variable["type"])
        if variable["type"].startswith("F") and type_object is None:
            raise RuntimeError("结构体变量必须提供 typeObject " + name)

        created = asset.add_member_variable(name, member_type, True, False, variable.get("default", ""))
        if str(created) != name:
            raise RuntimeError("公开变量创建失败或重名 " + name)

        node = graph.add_variable_node(name, variable["type"], type_object, True, variable.get("default", ""), unreal.Vector2D(*variable.get("position", [0.0, 0.0])), variable.get("node", name), False, False)
        if node is None:
            raise RuntimeError("公开变量读取节点创建失败 " + name)


def _transform(value):
    result = unreal.Transform(
        location=unreal.Vector(*value.get("position", [0.0, 0.0, 0.0])),
        scale=unreal.Vector(*value.get("scale", [1.0, 1.0, 1.0])),
    )
    result.rotation = unreal.Quat(*value.get("rotation", [0.0, 0.0, 0.0, 1.0]))
    return result


def _read_transform(value):
    return {"position": list(value.translation.to_tuple()), "rotation": list(value.rotation.to_tuple()), "scale": list(value.scale3d.to_tuple())}


def _pose(animation, mesh, time):
    options = unreal.AnimPoseEvaluationOptions()
    options.optional_skeletal_mesh = mesh
    options.should_retarget = True
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    return unreal.AnimPoseExtensions.get_anim_pose_at_time(animation, time, options)


def _set_pose(rig, pose):
    hierarchy = rig.get_hierarchy()
    for name in unreal.AnimPoseExtensions.get_bone_names(pose):
        hierarchy.set_local_transform(_key(name), unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.LOCAL))


def _mesh_binding(sequence, mesh):
    matches = []
    for binding in sequence.get_bindings():
        template = binding.get_object_template()
        if isinstance(template, unreal.SkeletalMeshActor):
            if template.skeletal_mesh_component.get_skeletal_mesh_asset() == mesh:
                matches.append(binding)

    if len(matches) != 1:
        raise RuntimeError("序列中目标网格绑定必须唯一")

    return matches[0]


@unreal.uclass()
class BBBControlRigAuthoringToolset(unreal.ToolsetDefinition):
    """
    /**
     * 使用官方控制器和求解节点编辑独立动画资产
     */
    """

    @mcp_tool
    @staticmethod
    def capture_attachment_pose(animation_path: str, mesh_path: str, time_seconds: float, attachments_json: str, camera_offset: list[float], file_name: str) -> str:
        """
        /**
         * 离屏拍摄动画及插槽附件 不修改任何资产
         * @param animation_path\t动画路径
         * @param mesh_path\t\t角色网格
         * @param time_seconds\t采样时刻
         * @param attachments_json\t附件和相对插槽变换
         * @param camera_offset\t相机相对胸部位置
         * @param file_name\t\t输出文件名
         * @return 图像路径
         */
        """
        output_parts = file_name.replace("\\", "/").split("/")
        if (len(camera_offset) != 3 or len(output_parts) != 2
                or any(not part or part in {".", ".."} or ":" in part for part in output_parts)
                or not output_parts[1].endswith(".png")):
            raise RuntimeError("截图参数无效")

        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "temp", output_parts[0]))
        path = os.path.join(directory, output_parts[1])
        if os.path.lexists(directory) and (os.path.islink(directory)
                or getattr(os.lstat(directory), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise RuntimeError("截图目录不得为链接")
        if os.path.lexists(path):
            raise RuntimeError("截图目标已存在 禁止覆盖 " + path)

        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            raise RuntimeError("离屏截图需要渲染 PIE 世界")

        actors = []
        try:
            actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, unreal.SkeletalMeshActor, unreal.Transform(location=unreal.Vector(0.0, 0.0, 10000.0)))
            actors.append(actor)
            component = actor.skeletal_mesh_component
            component.set_skeletal_mesh_asset(_asset(mesh_path, unreal.SkeletalMesh))
            if not unreal.BBBBlueprintEditorLibrary.evaluate_animation_preview_pose(component, _asset(animation_path, unreal.AnimSequence), time_seconds):
                raise RuntimeError("角色动画求值失败")

            visible = [actor]
            for entry in json.loads(attachments_json):
                asset = unreal.load_asset(entry["mesh"])
                actor_class = unreal.StaticMeshActor
                if isinstance(asset, unreal.SkeletalMesh):
                    actor_class = unreal.SkeletalMeshActor

                prop = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, actor_class, unreal.Transform())
                actors.append(prop)
                prop_component = prop.get_component_by_class(unreal.MeshComponent)
                prop_component.set_mobility(unreal.ComponentMobility.MOVABLE)
                if isinstance(asset, unreal.SkeletalMesh):
                    prop_component.set_skeletal_mesh_asset(asset)
                    if entry.get("animation"):
                        if not unreal.BBBBlueprintEditorLibrary.evaluate_animation_preview_pose(prop_component, _asset(entry["animation"], unreal.AnimSequence), entry.get("animation_time_seconds", time_seconds)):
                            raise RuntimeError("附件动画求值失败")

                    for bone in entry.get("hidden_bones", []):
                        prop_component.hide_bone_by_name(bone, unreal.PhysBodyOp.PBO_NONE)

                    if entry.get("hidden_bones"):
                        if not entry.get("animation") or not unreal.BBBBlueprintEditorLibrary.evaluate_animation_preview_pose(prop_component, _asset(entry["animation"], unreal.AnimSequence), entry.get("animation_time_seconds", time_seconds)):
                            raise RuntimeError("附件骨骼显隐需要明确动画并完成重新求值")

                if isinstance(asset, unreal.StaticMesh):
                    prop_component.set_static_mesh(asset)

                parent = component.get_socket_transform(entry["socket"], unreal.RelativeTransformSpace.RTS_WORLD)
                prop.set_actor_transform(unreal.MathLibrary.compose_transforms(_transform(entry["transform"]), parent), False, True)
                visible.append(prop)

            target = component.get_socket_location("hand_l")
            location = target + unreal.Vector(*camera_offset)
            light = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, unreal.PointLight, unreal.Transform(location=location))
            actors.append(light)
            light_component = light.get_component_by_class(unreal.PointLightComponent)
            light_component.set_intensity(2000.0)
            light_component.set_attenuation_radius(2000.0)
            light_component.set_cast_shadows(False)
            camera = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, unreal.SceneCapture2D, unreal.Transform(location=location, rotation=unreal.MathLibrary.find_look_at_rotation(location, target)))
            actors.append(camera)
            capture = camera.capture_component2d
            capture.set_editor_property("capture_every_frame", False)
            capture.set_editor_property("capture_on_movement", False)
            render_target = unreal.RenderingLibrary.create_render_target2d(world, 640, 640, unreal.TextureRenderTargetFormat.RTF_RGBA8)
            capture.set_editor_property("texture_target", render_target)
            capture.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
            capture.set_editor_property("primitive_render_mode", unreal.SceneCapturePrimitiveRenderMode.PRM_USE_SHOW_ONLY_LIST)
            capture.set_editor_property("show_only_actors", visible)
            capture.set_editor_property("fov_angle", 45.0)
            settings = capture.get_editor_property("post_process_settings")
            settings.set_editor_property("override_auto_exposure_method", True)
            settings.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
            settings.set_editor_property("override_auto_exposure_bias", True)
            settings.set_editor_property("auto_exposure_bias", 10.0)
            settings.set_editor_property("override_auto_exposure_apply_physical_camera_exposure", True)
            settings.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
            settings.set_editor_property("auto_exposure_bias", 0.0)
            studio_cube = unreal.load_asset("/Engine/EngineResources/GrayLightTextureCube")
            if studio_cube is None:
                raise RuntimeError("手部观察所需的引擎环境光纹理不存在")
            settings.set_editor_property("ambient_cubemap", studio_cube)
            settings.set_editor_property("override_ambient_cubemap_intensity", True)
            settings.set_editor_property("ambient_cubemap_intensity", 1.0)
            settings.set_editor_property("override_ambient_cubemap_tint", True)
            settings.set_editor_property("ambient_cubemap_tint", unreal.LinearColor.WHITE)
            capture.set_editor_property("post_process_settings", settings)
            capture.capture_scene()
            os.makedirs(directory, exist_ok=True)
            unreal.RenderingLibrary.export_render_target(world, render_target, directory, output_parts[1])
            if not os.path.isfile(path) or os.path.getsize(path) < 1024:
                raise RuntimeError("离屏图像无有效内容")

            unreal.log("[BBBControlRigAuthoring] 离屏截图 " + path)
            return json.dumps({"imagePath": path, "time": time_seconds, "resolution": [640, 640]})
        finally:
            for actor in reversed(actors):
                if actor is not None:
                    actor.destroy_actor()

    @mcp_tool
    @staticmethod
    def convert_component_mesh_grips(mesh_path: str, attachment_bone: str, grips_json: str) -> str:
        """
        /**
         * 将骨骼局部握持变换转换为使用装备组件坐标建模的静态附件变换
         * @param mesh_path\t\t装备骨骼网格
         * @param attachment_bone\t原附件骨骼
         * @param grips_json\t\t命名握持变换
         * @return 静态附件握持变换
         */
        """
        mesh = _asset(mesh_path, unreal.SkeletalMesh)
        reference = unreal.AnimPoseExtensions.get_reference_pose(mesh.get_editor_property("skeleton"))
        attachment = reference.get_ref_bone_pose(attachment_bone, unreal.AnimPoseSpaces.WORLD)
        attachment.translation = unreal.Vector()
        result = {name: _read_transform(attachment.inverse().multiply(_transform(value))) for name, value in json.loads(grips_json).items()}
        return json.dumps(result)

    @mcp_tool
    @staticmethod
    def remap_animation_bone_times(animation_path: str, mesh_path: str, duration_seconds: float, frame_rate: int, time_maps_json: str, source_animation_path: str) -> str:
        """
        /**
         * 通过官方动画姿势和数据控制器重映射独立机构动画的时间轴
         * @param animation_path\t待更新的自有无通知无曲线骨骼动画
         * @param mesh_path\t\t实际装备网格
         * @param duration_seconds\t目标时长 秒 必须为整数帧
         * @param frame_rate\t\t目标帧率
         * @param time_maps_json\t骨骼名到目标秒数与原动画秒数对应点的映射 其它骨骼等比例播放
         * @return 保存后的时长 帧数与重映射骨骼
         */
        """
        animation = _asset(animation_path, unreal.AnimSequence)
        source_animation = _asset(source_animation_path, unreal.AnimSequence)
        mesh = _asset(mesh_path, unreal.SkeletalMesh)
        if animation == source_animation:
            raise RuntimeError("机构重映射必须使用独立源动画 禁止累计重映射")
        if frame_rate <= 0 or not math.isfinite(duration_seconds) or duration_seconds <= 0.0:
            raise RuntimeError("动画时长与帧率无效")
        frames = round(duration_seconds * frame_rate)
        if frames <= 0 or frames > 600 or abs(frames / frame_rate - duration_seconds) > 0.00001:
            raise RuntimeError("机构动画须为整数帧且不超过六百帧")
        if unreal.AnimationLibrary.get_animation_notify_events(animation) or unreal.AnimationLibrary.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_FLOAT):
            raise RuntimeError("机构时间重映射不接受已有通知或曲线")

        source_length = source_animation.get_play_length()
        names = [str(name) for name in source_animation.data_model_interface.get_bone_track_names()]
        target_names = {str(name).casefold() for name in animation.data_model_interface.get_bone_track_names()}
        if {name.casefold() for name in names} != target_names:
            raise RuntimeError("源与目标机构动画的骨骼轨道必须一致")
        transform_curves = unreal.AnimationLibrary.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_TRANSFORM)
        mapping = json.loads(time_maps_json)
        if not isinstance(mapping, dict) or not mapping:
            raise RuntimeError("机构时间映射必须明确骨骼与对应点")
        resolved = {}
        for name, points in mapping.items():
            matched = next((bone for bone in names if bone.casefold() == name.casefold()), None)
            if matched is None or not isinstance(points, list) or len(points) < 2:
                raise RuntimeError("机构骨骼或时间对应点无效 " + name)
            if points[0][0] != 0.0 or abs(points[-1][0] - duration_seconds) > 0.00001:
                raise RuntimeError("机构时间映射须覆盖完整目标范围")
            previous_time = -1.0
            for target_time, source_time in points:
                if (not math.isfinite(target_time) or not math.isfinite(source_time)
                        or target_time <= previous_time or source_time < 0.0 or source_time > source_length):
                    raise RuntimeError("机构时间对应点超出范围或重复")
                previous_time = target_time
            resolved[matched] = points

        tracks = {name: [] for name in names}
        for frame in range(frames + 1):
            time_seconds = frame / frame_rate
            default_pose = _pose(source_animation, mesh, time_seconds / duration_seconds * source_length)
            for name in names:
                pose = default_pose
                if name in resolved:
                    points = resolved[name]
                    index = next((index for index in range(len(points) - 1) if time_seconds <= points[index + 1][0]), len(points) - 2)
                    first, last = points[index:index + 2]
                    alpha = (time_seconds - first[0]) / (last[0] - first[0])
                    source_time = first[1] + (last[1] - first[1]) * alpha
                    pose = _pose(source_animation, mesh, source_time)
                tracks[name].append(unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.LOCAL))

        require_write_access(animation)
        controller = animation.controller
        controller.open_bracket("对齐装备机构与手持物的时间交接", False)
        try:
            # 源姿势已包含骨骼修正曲线 清除目标旧修正 防止播放时重复叠加
            if transform_curves:
                controller.remove_all_curves_of_type(unreal.RawCurveTrackTypes.RCT_TRANSFORM, False)
                if unreal.AnimationLibrary.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_TRANSFORM):
                    raise RuntimeError("已烘焙的机构修正曲线删除失败")
            controller.set_frame_rate(unreal.FrameRate(numerator=frame_rate, denominator=1), False)
            controller.set_number_of_frames(unreal.FrameNumber(value=frames), False)
            for name, values in tracks.items():
                if not controller.set_bone_track_keys(name, [value.translation for value in values], [value.rotation for value in values], [value.scale3d for value in values], False):
                    raise RuntimeError("机构动画轨道写入失败 " + name)
        finally:
            controller.close_bracket(False)

        if abs(animation.get_play_length() - duration_seconds) > 0.00001:
            raise RuntimeError("机构动画时长不一致 禁止保存")
        if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
            raise RuntimeError("机构时间轴保存失败")

        return json.dumps({"animation": animation_path, "source": source_animation_path, "length": animation.get_play_length(), "frames": frames, "bones": list(resolved), "bakedTransformCurves": [str(name) for name in transform_curves]})

    @mcp_tool
    @staticmethod
    def set_sequence_attachment_transform(sequence_path: str, label: str, transform_json: str) -> str:
        """
        /**
         * 更新唯一附件绑定的局部变换轨道默认值
         * @param sequence_path\t编辑序列
         * @param label\t\t附件绑定名
         * @param transform_json\t局部变换
         * @return 更新结果
         */
        """
        sequence = _asset(sequence_path, unreal.LevelSequence)
        require_write_access(sequence)
        bindings = [binding for binding in sequence.get_bindings() if binding.get_name() == label]
        if len(bindings) != 1:
            raise RuntimeError("附件绑定必须唯一")

        transform = _transform(json.loads(transform_json))
        rotation = transform.rotation.rotator()
        values = list(transform.translation.to_tuple()) + [rotation.roll, rotation.pitch, rotation.yaw] + list(transform.scale3d.to_tuple())
        tracks = bindings[0].find_tracks_by_type(unreal.MovieScene3DTransformTrack)
        if len(tracks) != 1 or len(tracks[0].get_sections()) != 1:
            raise RuntimeError("附件变换轨道必须唯一")

        channels = tracks[0].get_sections()[0].get_all_channels()
        for channel, value in zip(channels, values):
            if channel.get_keys():
                raise RuntimeError("拒绝覆盖已有变换关键帧")

            channel.set_default(value)

        unreal.EditorAssetLibrary.save_loaded_asset(sequence)
        return json.dumps({"binding": label, "transform": _read_transform(transform)})

    @mcp_tool
    @staticmethod
    def inspect_mesh_bounds(mesh_path: str) -> str:
        """/** @return 网格组件空间包围盒 */"""
        mesh = unreal.load_asset(mesh_path)
        bounds = mesh.get_bounds()
        return json.dumps({"origin": list(bounds.origin.to_tuple()), "extent": list(bounds.box_extent.to_tuple())})

    @mcp_tool
    @staticmethod
    def build_pose_control_keys(animation_path: str, mesh_path: str, overrides_json: str, first_frame: int, last_frame: int) -> str:
        """
        /**
         * 用原动画的局部姿势生成原姿势控制器关键帧 保持骨长
         * @param animation_path\t原始动画
         * @param mesh_path\t\t目标网格
         * @param overrides_json\t参考帧 骨骼和逐帧混合权重
         * @return 控制器关键帧
         */
        """
        animation = _asset(animation_path, unreal.AnimSequence)
        mesh = _asset(mesh_path, unreal.SkeletalMesh)
        count = animation.data_model_interface.get_number_of_keys()
        rate = animation.data_model_interface.get_frame_rate()
        if first_frame < 0 or last_frame < first_frame or last_frame >= count or last_frame - first_frame >= 120:
            raise RuntimeError("原姿势采样帧区间无效 " + str(first_frame) + " 至 " + str(last_frame))
        requests = json.loads(overrides_json)
        if not requests:
            if count < 1 or count > 600:
                raise RuntimeError("原姿势采样帧数超出单次范围 " + str(count))
            unreal.log("[BBBControlRigAuthoring] 原姿势采样帧数 " + str(count))
            keys = []
            for frame in range(first_frame, last_frame + 1):
                pose = _pose(animation, mesh, frame * rate.denominator / rate.numerator)
                names = unreal.AnimPoseExtensions.get_bone_names(pose)
                for name in names:
                    transform = unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.WORLD)
                    keys.append({"frame": frame, "control": "source_" + str(name), "value": _read_transform(transform)})
            return json.dumps(keys)

        reference_component = unreal.SkeletalMeshComponent()
        reference_component.set_skinned_asset_and_update(mesh)
        bone_names = [str(name) for name in unreal.AnimPoseExtensions.get_bone_names(_pose(animation, mesh, 0.0))]
        names_by_lower = {name.lower(): name for name in bone_names}
        parents = {name: names_by_lower.get(str(reference_component.get_parent_bone(name)).lower()) for name in bone_names}

        def component_transforms(locals_by_bone):
            transforms = {}
            for name in bone_names:
                parent = parents[name]
                if parent is not None and parent not in transforms:
                    raise RuntimeError("骨骼层级顺序无效 " + name)

                transforms[name] = locals_by_bone[name]
                if parent is not None:
                    transforms[name] = unreal.MathLibrary.compose_transforms(locals_by_bone[name], transforms[parent])

            return transforms

        references = []
        for request in requests:
            if len(request["weights"]) != count:
                raise RuntimeError("姿势权重帧数错误")

            reference = _pose(animation, mesh, request["reference_frame"] * rate.denominator / rate.numerator)
            references.append({name: unreal.AnimPoseExtensions.get_bone_pose(reference, name, unreal.AnimPoseSpaces.LOCAL) for name in request["bones"]})

        keys = []
        for frame in range(first_frame, last_frame + 1):
            pose = _pose(animation, mesh, frame * rate.denominator / rate.numerator)
            locals_by_bone = {name: unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.LOCAL) for name in bone_names}
            for request, reference in zip(requests, references):
                weight = request["weights"][frame]
                if weight < 0.0 or weight > 1.0:
                    raise RuntimeError("姿势权重越界")

                for name, target in reference.items():
                    original = locals_by_bone[name]
                    blended = original.lerp(target, weight)
                    blended.translation = original.translation
                    blended.scale3d = original.scale3d
                    locals_by_bone[name] = blended

                # 局部姿势修改后按父子层级重新合成组件姿势 避免缓存的子骨骼变换破坏手指对握
                for aim in request.get("hand_space_aim", []):
                    transforms = component_transforms(locals_by_bone)
                    root = transforms[aim["bone"]]
                    tip = transforms[aim["tip"]]
                    hand = transforms[names_by_lower[aim["space"].lower()]]
                    destination = hand.transform_location(unreal.Vector(*aim["point"]))
                    if (tip.translation - root.translation).length() < 0.001 or (destination - root.translation).length() < 0.001:
                        raise RuntimeError("手指对握方向退化 帧 " + str(frame))

                    delta = unreal.MathLibrary.quat_find_between_vectors(tip.translation - root.translation, destination - root.translation)
                    target = unreal.Transform(location=root.translation, scale=root.scale3d)
                    target.rotation = delta * root.rotation
                    target = root.lerp(target, weight)
                    parent = parents[aim["bone"]]
                    if parent is not None:
                        target = unreal.MathLibrary.make_relative_transform(target, transforms[parent])

                    original = locals_by_bone[aim["bone"]]
                    target.translation = original.translation
                    target.scale3d = original.scale3d
                    locals_by_bone[aim["bone"]] = target

            transforms = component_transforms(locals_by_bone)
            for name in bone_names:
                keys.append({"frame": frame, "control": "source_" + name, "value": _read_transform(transforms[name])})

        return json.dumps(keys)

    @mcp_tool
    @staticmethod
    def normalize_authoring_bindings(sequence_path: str, mesh_path: str, rig_path: str) -> str:
        """
        /**
         * 清理重复生成轨道及绑定到错误网格的指定控制绑定
         * @param sequence_path\t编辑序列
         * @param mesh_path\t\t控制绑定唯一目标网格
         * @param rig_path\t\t指定控制绑定
         * @return 清理轨道数
         */
        """
        sequence = _asset(sequence_path, unreal.LevelSequence)
        mesh = _asset(mesh_path, unreal.SkeletalMesh)
        asset = _asset(rig_path, unreal.ControlRigBlueprint)
        require_write_access(sequence)
        target = _mesh_binding(sequence, mesh)
        removed = 0
        for binding in sequence.get_bindings():
            spawn_tracks = binding.find_tracks_by_type(unreal.MovieSceneSpawnTrack)
            for track in list(spawn_tracks)[:-1]:
                binding.remove_track(track)
                removed += 1

            if binding.get_name() == target.get_name():
                continue

            for proxy in unreal.ControlRigSequencerLibrary.get_control_rigs(sequence):
                if proxy.track not in binding.get_tracks():
                    continue

                if proxy.control_rig.get_class() == asset.get_control_rig_class():
                    binding.remove_track(proxy.track)
                    removed += 1

            for track in binding.find_tracks_by_type(unreal.MovieSceneSkeletalAnimationTrack):
                for section in track.get_sections():
                    section.set_is_active(True)

        unreal.EditorAssetLibrary.save_loaded_asset(sequence)
        return json.dumps({"removedTracks": removed})

    @mcp_tool
    @staticmethod
    def compute_palm_contact(animation_path: str, mesh_path: str, definition_path: str, frame: int, equipment_point: list[float], palm_point: list[float]) -> str:
        """
        /**
         * 保持原掌姿态求掌心与装备组件点接触的腕部位置
         * @param animation_path\t原动画
         * @param mesh_path\t\t角色网格
         * @param definition_path\t装备定义
         * @param frame\t\t接触帧
         * @param equipment_point\t装备组件空间接触点
         * @param palm_point\t\t手骨骼空间掌心点
         * @return 接触腕部变换
         */
        """
        pose = _pose(_asset(animation_path, unreal.AnimSequence), _asset(mesh_path, unreal.SkeletalMesh), frame / 30.0)
        right = unreal.AnimPoseExtensions.get_bone_pose(pose, "hand_r", unreal.AnimPoseSpaces.WORLD)
        left = unreal.AnimPoseExtensions.get_bone_pose(pose, "hand_l", unreal.AnimPoseSpaces.WORLD)
        definition = unreal.load_asset(definition_path)
        equipment = definition.get_editor_property("spawn_offset").multiply(right)
        position = equipment.transform_location(unreal.Vector(*equipment_point))
        target = unreal.Transform()
        target.rotation = left.rotation
        target.translation = position - (left.transform_location(unreal.Vector(*palm_point)) - left.translation)
        return json.dumps({"target": _read_transform(target), "contact": list(position.to_tuple())})

    @mcp_tool
    @staticmethod
    def set_sequence_spawn_range(sequence_path: str, label: str, first_frame: int, last_frame: int) -> str:
        """
        /**
         * 更新附件唯一生成区间
         * @param sequence_path\t编辑序列
         * @param label\t\t附件绑定名
         * @param first_frame\t出现帧
         * @param last_frame\t\t结束帧
         * @return 更新区间
         */
        """
        sequence = _asset(sequence_path, unreal.LevelSequence)
        require_write_access(sequence)
        bindings = [binding for binding in sequence.get_bindings() if binding.get_name() == label]
        if len(bindings) != 1 or first_frame >= last_frame:
            raise RuntimeError("生成区间或绑定无效")

        tracks = bindings[0].find_tracks_by_type(unreal.MovieSceneSpawnTrack)
        if len(tracks) != 1:
            raise RuntimeError("生成轨道必须唯一")

        channel = tracks[0].get_sections()[0].get_all_channels()[0]
        for key in channel.get_keys():
            channel.remove_key(key)

        channel.set_default(False)
        channel.add_key(unreal.FrameNumber(value=first_frame), True)
        channel.add_key(unreal.FrameNumber(value=last_frame), False)
        unreal.EditorAssetLibrary.save_loaded_asset(sequence)
        return json.dumps({"binding": label, "range": [first_frame, last_frame]})

    @mcp_tool
    @staticmethod
    def play_pie_montages(montages_json: str) -> str:
        """
        /**
         * 在运行实例同步播放指定蒙太奇供动画及通知验收 不模拟装备业务输入
         * @param montages_json\t实例路径和蒙太奇路径
         * @return 播放时长
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            raise RuntimeError("蒙太奇验收需要 PIE 世界")

        requests = []
        for request in json.loads(montages_json):
            instance = unreal.find_object(None, request["instance"])
            if not isinstance(instance, unreal.AnimInstance) or world.get_name() not in instance.get_path_name():
                raise RuntimeError("目标必须是当前 PIE 动画实例")

            requests.append((instance, _asset(request["montage"], unreal.AnimMontage)))

        results = []
        for instance, montage in requests:
            instance.get_owning_component().set_editor_property("visibility_based_anim_tick_option", unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES)
            length = instance.montage_play(montage)
            if length <= 0.0:
                raise RuntimeError("蒙太奇播放失败")

            results.append({"instance": instance.get_path_name(), "length": length})

        return json.dumps({"animationOnly": True, "played": results})

    @mcp_tool
    @staticmethod
    def inspect_authoring_api(type_names: list[str], method_names: list[str]) -> str:
        """
        /**
         * 查询当前引擎实际反射接口
         * @param type_names\t反射类型名
         * @param method_names\t方法名 空数组列出接口
         * @return 接口文档
         */
        """
        result = {}
        for name in type_names:
            value = getattr(unreal, name, None)
            if value is None:
                result[name] = {"missing": True}
                continue

            if not method_names:
                result[name] = str(value.__doc__)
                continue

            result[name] = {method: str(getattr(value, method).__doc__) for method in method_names if hasattr(value, method)}

        return json.dumps(result, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def set_background_budget(maximum_fps: float) -> str:
        """
        /**
         * 限制后台编辑器更新频率
         * @param maximum_fps\t每秒最大帧数
         * @return 实际请求的预算
         */
        """
        if maximum_fps < 1.0 or maximum_fps > 30.0:
            raise RuntimeError("后台预算必须在一到三十帧之间")

        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        unreal.SystemLibrary.execute_console_command(world, "t.MaxFPS " + str(maximum_fps))
        return json.dumps({"maximumFps": maximum_fps})

    @mcp_tool
    @staticmethod
    def create_control_rig(asset_path: str, mesh_path: str, controls_json: str, graph_json: str) -> str:
        """
        /**
         * 从网格参考骨架和显式节点配置建立独立绑定
         * @param asset_path\t新绑定路径
         * @param mesh_path\t目标网格路径
         * @param controls_json\t控制器类型和参考骨骼
         * @param graph_json\t官方节点 默认值和连线
         * @return 创建报告
         */
        """
        if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            raise RuntimeError("拒绝覆盖已有绑定 " + asset_path)

        mesh = _asset(mesh_path, unreal.SkeletalMesh)
        asset = unreal.ControlRigBlueprintFactory.create_new_control_rig_asset(asset_path, False)
        hierarchy = asset.hierarchy
        controller = hierarchy.get_controller()
        controller.import_bones_from_asset(mesh_path, "", True, True, False)
        asset.set_preview_mesh(mesh)
        report = []
        for control in json.loads(controls_json):
            settings = unreal.RigControlSettings()
            settings.control_type = getattr(unreal.RigControlType, control["type"])
            settings.display_name = control["name"]
            settings.shape_name = control.get("shape", "Box_Thin")
            settings.shape_visible = control["type"] != "FLOAT"
            value = unreal.RigHierarchy.make_control_value_from_euler_transform(unreal.EulerTransform())
            if control["type"] == "FLOAT":
                value = unreal.RigHierarchy.make_control_value_from_float(control.get("value", 0.0))

            key = controller.add_control(control["name"], unreal.RigElementKey(), settings, value, False, False)
            if "bone" in control:
                offset = hierarchy.get_global_transform(_key(control["bone"]), True)
                hierarchy.set_control_offset_transform(key, offset, True)
                hierarchy.set_control_offset_transform(key, offset, False)
                report.append({"control": str(key.name), "offset": _read_transform(offset)})

            hierarchy.set_control_shape_transform(key, unreal.Transform(scale=unreal.Vector(4.0, 4.0, 4.0)), True)

        graph = asset.get_controller()
        request = json.loads(graph_json)
        for existing_node in list(graph.get_graph().get_nodes()):
            graph.remove_node(existing_node, False, False)

        _add_graph_variables(asset, graph, request)

        for node in request["nodes"]:
            result = graph.add_unit_node_from_struct_path(node["struct"], "Execute", unreal.Vector2D(*node.get("position", [0.0, 0.0])), node["name"], False, False)
            if result is None:
                raise RuntimeError("创建官方节点失败 " + node["name"])

            for pin, default in node.get("defaults", {}).items():
                if not graph.set_pin_default_value(node["name"] + "." + pin, default, True, False, False, False):
                    raise RuntimeError("设置引脚失败 " + node["name"] + "." + pin)

        for source, target in request["links"]:
            if not graph.add_link(source, target, False, False):
                raise RuntimeError("绑定连线失败 " + source + " -> " + target)

        asset.recompile_vm()
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset):
            raise RuntimeError("保存绑定失败")

        unreal.log("[BBBControlRigAuthoring] 独立绑定已建立 " + asset_path)
        return json.dumps({"asset": asset.get_path_name(), "controls": report}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def evaluate_rig_pose(asset_path: str, animation_path: str, mesh_path: str, time_seconds: float, controls_json: str, bone_names: list[str], variables_json: str = "{}") -> str:
        """
        /**
         * 在源姿势上执行官方绑定并返回骨骼变换
         * @param asset_path\t绑定路径
         * @param animation_path\t源动画路径
         * @param mesh_path\t实际角色网格
         * @param time_seconds\t取样时间
         * @param controls_json\t控制器位置 旋转或权重
         * @param bone_names\t返回的骨骼
         * @return 源姿势和求解姿势
         */
        """
        asset = _asset(asset_path, unreal.ControlRigBlueprint)
        animation = _asset(animation_path, unreal.AnimSequence)
        mesh = _asset(mesh_path, unreal.SkeletalMesh)
        rig = asset.create_control_rig()
        rig.request_init()
        rig.execute_event("Forwards Solve")
        pose = _pose(animation, mesh, time_seconds)
        _set_pose(rig, pose)
        hierarchy = rig.get_hierarchy()
        for name, value in json.loads(variables_json).items():
            if not rig.set_variable_from_string(name, value):
                raise RuntimeError("控制绑定公开输入赋值失败 " + name)

        for name, value in json.loads(controls_json).items():
            key = _key(name, "CONTROL")
            if isinstance(value, dict):
                hierarchy.set_global_transform(key, _transform(value))
                continue

            hierarchy.set_control_value(key, unreal.RigHierarchy.make_control_value_from_float(value))

        if not rig.execute_event("Forwards Solve"):
            raise RuntimeError("正向求解失败")

        result = {}
        for name in bone_names:
            result[name] = {
                "source": _read_transform(unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.WORLD)),
                "solved": _read_transform(hierarchy.get_global_transform(_key(name))),
                "local": _read_transform(hierarchy.get_local_transform(_key(name))),
            }

        return json.dumps(result, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def audit_control_rig_round_trip(asset_path: str, animation_path: str, mesh_path: str, sample_times: list[float], control_deltas_json: str, bone_names: list[str]) -> str:
        """
        /**
         * 在瞬态实例中验证源姿势反向求解与控制器调整后的正向求解
         * @param asset_path		绑定路径
         * @param animation_path		源动画路径
         * @param mesh_path			实际角色网格
         * @param sample_times		取样秒数
         * @param control_deltas_json	控制器局部增量变换
         * @param bone_names		详细报告骨骼
         * @return 骨骼误差与控制器求解报告
         */
        """
        asset = _asset(asset_path, unreal.ControlRigBlueprint)
        animation = _asset(animation_path, unreal.AnimSequence)
        mesh = _asset(mesh_path, unreal.SkeletalMesh)
        deltas = json.loads(control_deltas_json)
        samples = []
        for time in sample_times:
            if time < 0.0 or time > animation.sequence_length:
                raise RuntimeError("采样时刻超出动画范围")

            rig = asset.create_control_rig()
            rig.request_init()
            pose = _pose(animation, mesh, time)
            _set_pose(rig, pose)
            if not rig.execute_event("Backwards Solve"):
                raise RuntimeError("反向求解失败 " + asset_path)

            hierarchy = rig.get_hierarchy()
            controls = {}
            for key in hierarchy.get_controls():
                controls[str(key.name)] = _read_transform(hierarchy.get_global_transform(key))

            for name, delta in deltas.items():
                key = _key(name, "CONTROL")
                if hierarchy.get_index(key) < 0:
                    raise RuntimeError("控制器不存在 " + name)

                current = hierarchy.get_global_transform(key)
                changed = unreal.MathLibrary.compose_transforms(_transform(delta), current)
                hierarchy.set_global_transform(key, changed)

            if not rig.execute_event("Forwards Solve"):
                raise RuntimeError("正向求解失败 " + asset_path)

            differences = []
            details = {}
            for name in unreal.AnimPoseExtensions.get_bone_names(pose):
                source = unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.LOCAL)
                solved = hierarchy.get_local_transform(_key(name))
                distance = (source.translation - solved.translation).length()
                dot = abs(source.rotation.x * solved.rotation.x + source.rotation.y * solved.rotation.y + source.rotation.z * solved.rotation.z + source.rotation.w * solved.rotation.w)
                angle = math.degrees(2.0 * math.acos(min(1.0, dot)))
                if distance > 0.001 or angle > 0.01:
                    differences.append({"bone": str(name), "cm": distance, "degrees": angle})

                if str(name) in bone_names:
                    details[str(name)] = {
                        "source": _read_transform(unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.WORLD)),
                        "solved": _read_transform(hierarchy.get_global_transform(_key(name))),
                    }

            samples.append({"time": time, "controls": controls, "differences": differences, "bones": details})

        unreal.log("[BBBControlRigAuthoring] 反向与正向求解审计完成 " + asset_path)
        return json.dumps({"asset": asset_path, "animation": animation_path, "samples": samples}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_control_rig_graph(asset_path: str, request_json: str) -> str:
        """
        /**
         * 显式追加官方节点和连接并编译保存
         * @param asset_path\t绑定路径
         * @param request_json\t节点 引脚默认值及连线
         * @return 编译后的节点数
         */
        """
        asset = _asset(asset_path, unreal.ControlRigBlueprint)
        require_write_access(asset)
        graph = asset.get_controller()
        request = json.loads(request_json)
        hierarchy = asset.hierarchy
        hierarchy_controller = hierarchy.get_controller()
        for control in request.get("controls", []):
            key = _key(control["name"], "CONTROL")
            if hierarchy.contains(key):
                raise RuntimeError("控制器已存在 " + control["name"])

            settings = unreal.RigControlSettings()
            settings.control_type = unreal.RigControlType.EULER_TRANSFORM
            settings.shape_visible = control.get("visible", False)
            initial = unreal.RigHierarchy.make_control_value_from_euler_transform(unreal.EulerTransform())
            created = hierarchy_controller.add_control(control["name"], unreal.RigElementKey(), settings, initial, False, False)
            if str(created.name) != control["name"]:
                raise RuntimeError("控制器创建失败 " + control["name"])

        for source, target in request.get("breakLinks", []):
            if not graph.break_link(source, target, False, False):
                raise RuntimeError("断开绑定连线失败 " + source + " -> " + target)

        for name in request.get("removeNodes", []):
            node = graph.get_graph().find_node_by_name(name)
            if node is not None:
                graph.remove_node(node, False, False)

        _add_graph_variables(asset, graph, request)

        for node in request.get("nodes", []):
            result = graph.add_unit_node_from_struct_path(node["struct"], "Execute", unreal.Vector2D(*node.get("position", [0.0, 0.0])), node["name"], False, False)
            if result is None:
                raise RuntimeError("创建官方节点失败 " + node["name"])

            for pin, default in node.get("defaults", {}).items():
                if not graph.set_pin_default_value(node["name"] + "." + pin, default, True, False, False, False):
                    raise RuntimeError("设置引脚失败 " + node["name"] + "." + pin)

        for source, target in request.get("links", []):
            if not graph.add_link(source, target, False, False):
                raise RuntimeError("绑定连线失败 " + source + " -> " + target)

        asset.recompile_vm()
        unreal.EditorAssetLibrary.save_loaded_asset(asset)
        return json.dumps({"nodes": len(graph.get_graph().get_nodes())})

    @mcp_tool
    @staticmethod
    def prepare_animation_sequence(sequence_path: str, animation_path: str, mesh_path: str) -> str:
        """
        /**
         * 建立独立序列和生成型角色 不写入当前关卡
         * @param sequence_path\t新序列路径
         * @param animation_path\t源动画路径
         * @param mesh_path\t目标角色网格
         * @return 序列绑定和帧范围
         */
        """
        if unreal.EditorAssetLibrary.does_asset_exist(sequence_path):
            raise RuntimeError("拒绝覆盖已有序列 " + sequence_path)

        animation = _asset(animation_path, unreal.AnimSequence)
        mesh = _asset(mesh_path, unreal.SkeletalMesh)
        folder, name = sequence_path.rsplit("/", 1)
        sequence = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
        sequence.set_display_rate(unreal.FrameRate(numerator=30, denominator=1))
        end_frame = round(animation.sequence_length * 30.0) + 1
        sequence.set_playback_start(0)
        sequence.set_playback_end(end_frame)
        actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        actor = actors.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(), transient=True)
        actor.set_actor_label("BBB_Reload_HandEdit")
        actor.skeletal_mesh_component.set_skeletal_mesh_asset(mesh)
        actor.skeletal_mesh_component.set_editor_property("disable_post_process_blueprint", True)
        binding = sequence.add_spawnable_from_instance(actor)
        actors.destroy_actor(actor)
        spawn_tracks = binding.find_tracks_by_type(unreal.MovieSceneSpawnTrack)
        spawn_track = spawn_tracks[0] if spawn_tracks else binding.add_track(unreal.MovieSceneSpawnTrack)
        spawn_sections = spawn_track.get_sections()
        spawn = spawn_sections[0] if spawn_sections else spawn_track.add_section()
        spawn.set_range(0, end_frame)
        spawn.get_all_channels()[0].set_default(True)
        spawn.get_all_channels()[0].add_key(unreal.FrameNumber(value=0), True)
        spawn.get_all_channels()[0].add_key(unreal.FrameNumber(value=end_frame), False)
        track = binding.add_track(unreal.MovieSceneSkeletalAnimationTrack)
        section = track.add_section()
        parameters = section.get_editor_property("params")
        parameters.animation = animation
        section.set_editor_property("params", parameters)
        section.set_range(0, end_frame)
        unreal.EditorAssetLibrary.save_loaded_asset(sequence)
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
        unreal.log("[BBBControlRigAuthoring] 独立编辑序列已建立 " + sequence_path)
        return json.dumps({"sequence": sequence.get_path_name(), "bindingId": str(binding.get_id()), "endFrame": end_frame}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def create_control_rig_sequence(sequence_path: str, mesh_path: str, duration_seconds: float, frame_rate: int) -> str:
        """
        /**
         * 建立仅供控制绑定驱动的独立序列 不保存当前关卡
         * @param sequence_path	新序列路径
         * @param mesh_path	目标网格
         * @param duration_seconds	有限正时长
         * @param frame_rate	每秒采样帧数
         * @return 序列与帧范围
         */
        """
        if not math.isfinite(duration_seconds) or duration_seconds <= 0.0 or frame_rate < 1 or frame_rate > 120:
            raise RuntimeError("序列时长或采样率无效")

        if unreal.EditorAssetLibrary.does_asset_exist(sequence_path):
            raise RuntimeError("拒绝覆盖已有序列 " + sequence_path)

        reservation = unreal.SourceControl.query_file_state(sequence_path, silent=True, use_source_control_state_cache=False)
        if reservation.is_added:
            require_asset_write([sequence_path])
        if not reservation.is_added:
            require_asset_write([], destinations=[sequence_path])
        mesh = _asset(mesh_path, unreal.SkeletalMesh)
        folder, name = sequence_path.rsplit("/", 1)
        sequence = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            name, folder, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
        sequence.set_display_rate(unreal.FrameRate(numerator=frame_rate, denominator=1))
        end_frame = round(duration_seconds * frame_rate) + 1
        sequence.set_playback_start(0)
        sequence.set_playback_end(end_frame)
        actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        actor = actors.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(), transient=True)
        try:
            actor.skeletal_mesh_component.set_skeletal_mesh_asset(mesh)
            actor.skeletal_mesh_component.set_editor_property("disable_post_process_blueprint", True)
            binding = sequence.add_spawnable_from_instance(actor)
        finally:
            actors.destroy_actor(actor)

        tracks = binding.find_tracks_by_type(unreal.MovieSceneSpawnTrack)
        track = tracks[0] if tracks else binding.add_track(unreal.MovieSceneSpawnTrack)
        sections = track.get_sections()
        spawn = sections[0] if sections else track.add_section()
        spawn.set_range(0, end_frame)
        channel = spawn.get_all_channels()[0]
        channel.set_default(True)
        channel.add_key(unreal.FrameNumber(value=0), True)
        channel.add_key(unreal.FrameNumber(value=end_frame), False)
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence):
            raise RuntimeError("保存独立序列失败")

        return json.dumps({"sequence": sequence.get_path_name(), "endFrame": end_frame})

    @mcp_tool
    @staticmethod
    def bake_control_rig_animation(sequence_path: str, animation_path: str, mesh_path: str) -> str:
        """
        /**
         * 将指定控制绑定序列通过官方烘焙器导出到明确的动画路径
         * @param sequence_path	编辑序列
         * @param animation_path	目标动画 必须先取得写入权限
         * @param mesh_path	序列中唯一的目标网格
         * @return 导出资产与采样长度
         */
        """
        sequence = _asset(sequence_path, unreal.LevelSequence)
        mesh = _asset(mesh_path, unreal.SkeletalMesh)
        binding = _mesh_binding(sequence, mesh)
        if not binding.find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack):
            raise RuntimeError("序列缺少控制绑定轨道")

        source_animations = []
        for track in binding.find_tracks_by_type(unreal.MovieSceneSkeletalAnimationTrack):
            for section in track.get_sections():
                source = section.get_editor_property("params").animation
                if isinstance(source, unreal.AnimSequence) and source not in source_animations:
                    source_animations.append(source)
        if len(source_animations) > 1:
            raise RuntimeError("序列包含多个不同源动作 无法确定控制曲线来源")

        if unreal.EditorAssetLibrary.does_asset_exist(animation_path):
            animation = _asset(animation_path, unreal.AnimSequence)
            require_write_access(animation)

        if not unreal.EditorAssetLibrary.does_asset_exist(animation_path):
            require_asset_write([], destinations=[animation_path])
            factory = unreal.AnimSequenceFactory()
            factory.target_skeleton = mesh.get_editor_property("skeleton")
            factory.preview_skeletal_mesh = mesh
            folder, name = animation_path.rsplit("/", 1)
            animation = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                name, folder, unreal.AnimSequence, factory)

        options = unreal.AnimSeqExportOption()
        options.export_transforms = True
        options.export_morph_targets = False
        options.export_attribute_curves = True
        options.export_material_curves = False
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if not unreal.SequencerTools.export_anim_sequence(world, sequence, animation, options, binding, False):
            raise RuntimeError("官方控制绑定动画烘焙失败")

        if animation.sequence_length <= 0.0:
            raise RuntimeError("烘焙结果为空")

        copied_curves = 0
        if source_animations:
            copied_curves = unreal.BBBBlueprintEditorLibrary.copy_animation_float_curves(source_animations[0], animation)
            if copied_curves < 0:
                raise RuntimeError("保留源动作浮点曲线失败 禁止保存烘焙结果")

        animation.set_editor_property("enable_root_motion", False)
        if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
            raise RuntimeError("保存烘焙动画失败")

        return json.dumps({"animation": animation.get_path_name(), "length": animation.sequence_length, "copiedFloatCurves": copied_curves})

    @mcp_tool
    @staticmethod
    def inspect_control_rig_reference(asset_path: str, bone_names: list[str]) -> str:
        """
        /**
         * 读取绑定实际导入的参考骨骼局部与组件姿势
         * @param asset_path	控制绑定
         * @param bone_names	明确骨骼列表
         * @return 原始参考变换
         */
        """
        hierarchy = _asset(asset_path, unreal.ControlRigBlueprint).hierarchy
        result = {}
        for name in bone_names:
            key = _key(name)
            if not hierarchy.contains(key):
                raise RuntimeError("参考骨骼不存在 " + name)
            result[name] = {"local": _read_transform(hierarchy.get_local_transform(key, True)),
                            "component": _read_transform(hierarchy.get_global_transform(key, True))}

        return json.dumps(result)

    @mcp_tool
    @staticmethod
    def inspect_control_rig_controls(asset_path: str) -> str:
        """
        /**
         * 读取控制器实际类型与偏移 避免使用不匹配的 Sequencer 写键接口
         * @param asset_path	控制绑定资产
         * @return 控制器名称 类型 初始偏移和是否允许动画
         */
        """
        hierarchy = _asset(asset_path, unreal.ControlRigBlueprint).hierarchy
        controls = []
        for key in hierarchy.get_controls():
            settings = hierarchy.get_control_settings(key)
            controls.append({"name": str(key.name), "type": str(settings.control_type),
                             "animationType": str(settings.animation_type),
                             "offset": _read_transform(hierarchy.get_global_control_offset_transform(key, True))})
        return json.dumps({"asset": asset_path, "controls": controls}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def sample_animation_poses(animation_path: str, mesh_path: str, times: list[float], bone_names: list[str]) -> str:
        """
        /**
         * 读取实际网格上的动画姿势供控制器编辑
         * @param animation_path\t动画路径
         * @param mesh_path\t网格路径
         * @param times\t取样秒数
         * @param bone_names\t骨骼名称
         * @return 组件空间取样
         */
        """
        animation = _asset(animation_path, unreal.AnimSequence)
        mesh = _asset(mesh_path, unreal.SkeletalMesh)
        length = animation.get_play_length()
        if not times or len(times) > 600 or any(not math.isfinite(time) or time < 0.0 or time > length for time in times):
            raise RuntimeError("姿势采样时间必须位于实际动画范围内 每次至多六百项")
        result = unreal.BBBBlueprintEditorLibrary.sample_animation_component_poses(animation, mesh, times, bone_names)
        if not result:
            raise RuntimeError("引擎批量姿势采样失败 请检查 PoseSample 日志")
        rows = json.loads(result)
        if len(rows) != len(times):
            raise RuntimeError("引擎返回的采样数量不符")
        return result

    @mcp_tool
    @staticmethod
    def sample_sequence_controls(sequence_path: str, frames: list[int], control_names: list[str]) -> str:
        """
        /**
         * 读取序列原姿势控制器的实际关键帧值 供离线姿势修复使用
         * @param sequence_path	编辑序列路径
         * @param frames		明确显示帧 每次至多六百项
         * @param control_names	原姿势欧拉变换控制器名称
         * @return 帧号 控制器与实际组件空间变换数组
         */
        """
        if not frames or len(frames) > 600 or not control_names:
            raise RuntimeError("控制器采样须明确帧和名称 每次至多六百帧")

        sequence = _asset(sequence_path, unreal.LevelSequence)
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
        unreal.LevelSequenceEditorBlueprintLibrary.force_update()
        proxies = unreal.ControlRigSequencerLibrary.get_control_rigs(sequence)
        if len(proxies) != 1:
            raise RuntimeError("采样序列必须只有一个控制绑定轨道")

        rig = proxies[0].control_rig
        hierarchy = rig.get_hierarchy()
        for name in control_names:
            key = _key(name, "CONTROL")
            if not hierarchy.contains(key) or hierarchy.get_control_settings(key).control_type != unreal.RigControlType.EULER_TRANSFORM:
                raise RuntimeError("采样仅支持明确存在的欧拉变换控制器 " + name)

        keys = []
        for frame in frames:
            if frame < sequence.get_playback_start() or frame >= sequence.get_playback_end():
                raise RuntimeError("采样帧超出序列范围 " + str(frame))

            for name in control_names:
                value = unreal.ControlRigSequencerLibrary.get_local_control_rig_euler_transform(sequence, rig, name, unreal.FrameNumber(value=frame))
                keys.append({"frame": frame, "control": name, "value": _read_transform(unreal.Transform(location=value.location, rotation=value.rotation, scale=value.scale))})

        return json.dumps(keys, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_sequence_rig(sequence_path: str, rig_path: str, keys_json: str, is_layered: bool, mesh_path: str) -> str:
        """
        /**
         * 在原动画上创建叠加绑定并使用官方接口设置控制器关键帧
         * @param sequence_path\t独立序列路径
         * @param rig_path\t绑定路径
         * @param keys_json\t帧号 控制器和组件空间变换
         * @return 绑定轨道和关键帧数
         */
        """
        sequence = _asset(sequence_path, unreal.LevelSequence)
        asset = _asset(rig_path, unreal.ControlRigBlueprint)
        require_write_access(sequence)
        binding = _mesh_binding(sequence, _asset(mesh_path, unreal.SkeletalMesh))
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
        track = unreal.ControlRigSequencerLibrary.find_or_create_control_rig_track(world, sequence, asset.get_control_rig_class(), binding, is_layered_control_rig=is_layered)
        for source_track in binding.find_tracks_by_type(unreal.MovieSceneSkeletalAnimationTrack):
            for section in source_track.get_sections():
                section.set_is_active(is_layered)
        if track is None:
            raise RuntimeError("建立叠加绑定轨道失败")

        unreal.LevelSequenceEditorBlueprintLibrary.force_update()
        rigs = [value.control_rig for value in unreal.ControlRigSequencerLibrary.get_control_rigs(sequence) if value.track == track]
        if len(rigs) != 1:
            raise RuntimeError("绑定轨道实例数量异常")

        rig = rigs[0]
        if unreal.ControlRigSequencerLibrary.is_layered_control_rig(rig) != is_layered:
            if not unreal.ControlRigSequencerLibrary.set_control_rig_layered_mode(track, is_layered):
                raise RuntimeError("切换控制绑定叠加模式失败")
            unreal.LevelSequenceEditorBlueprintLibrary.force_update()
            rigs = [value.control_rig for value in unreal.ControlRigSequencerLibrary.get_control_rigs(sequence) if value.track == track]
            if len(rigs) != 1:
                raise RuntimeError("切换模式后绑定实例数量异常")
            rig = rigs[0]

        keys = json.loads(keys_json)
        source_groups = {}
        for key in keys:
            frame = unreal.FrameNumber(value=key["frame"])
            value = key["value"]
            if isinstance(value, dict):
                # 原姿势控制器无父级且无偏移 直接写入组件姿势 避免世界空间接口依赖预览角色绑定而静默漏写
                if key["control"].startswith("source_"):
                    source_groups.setdefault(key["control"], []).append(key)
                    continue

                unreal.ControlRigSequencerLibrary.set_control_rig_world_transform(sequence, rig, key["control"], frame, _transform(value), set_key=True)
                continue

            unreal.ControlRigSequencerLibrary.set_local_control_rig_float(sequence, rig, key["control"], frame, value, set_key=True)

        for control, control_keys in source_groups.items():
            frames = [unreal.FrameNumber(value=key["frame"]) for key in control_keys]
            transforms = [_transform(key["value"]) for key in control_keys]
            values = [unreal.EulerTransform(location=transform.translation, rotation=transform.rotation.rotator(), scale=transform.scale3d) for transform in transforms]
            unreal.ControlRigSequencerLibrary.set_local_control_rig_euler_transforms(sequence, rig, control, frames, values)
            actuals = unreal.ControlRigSequencerLibrary.get_local_control_rig_euler_transforms(sequence, rig, control, frames)
            if len(actuals) != len(control_keys):
                raise RuntimeError("原姿势控制器批量写键数量不一致 " + control)
            for key, transform, actual in zip(control_keys, transforms, actuals):
                difference = actual.rotation.quaternion() * transform.rotation.inversed()
                if (actual.location - transform.translation).length() > 0.01 or abs(difference.w) < 0.99999:
                    raise RuntimeError("原姿势控制器写键不一致 " + control + " 帧 " + str(key["frame"])
                                       + " 目标 " + json.dumps(key["value"]) + " 实际 "
                                       + json.dumps({"position": list(actual.location.to_tuple()),
                                                     "rotation": list(actual.rotation.quaternion().to_tuple())}))

        keyed_channels = sum(len(channel.get_keys()) for section in track.get_sections() for channel in section.get_all_channels())
        if keyed_channels < len(keys):
            raise RuntimeError("官方控制器写键未实际产生关键帧 禁止保存")

        unreal.EditorAssetLibrary.save_loaded_asset(sequence)
        unreal.log("[BBBControlRigAuthoring] 控制器关键帧已保存 " + sequence_path)
        return json.dumps({"track": track.get_path_name(), "keys": len(keys), "rig": rig.get_path_name()})

    @mcp_tool
    @staticmethod
    def compute_attachment_contacts(animation_path: str, mesh_path: str, definition_path: str, attachment_bone: str, held_bone: str, contact_frames_json: str, grip_position_json: str) -> str:
        """
        /**
         * 用实际装备挂接变换计算接触目标及手持相对变换
         * @param animation_path\t角色动画
         * @param mesh_path\t角色网格
         * @param definition_path\t装备定义
         * @param attachment_bone\t装备上的接触骨骼
         * @param held_bone\t角色持物骨骼
         * @param contact_frames_json\t接触名称和帧号
         * @param grip_position_json\t物体相对手的局部位置
         * @return 接触目标和手持相对变换
         */
        """
        animation = _asset(animation_path, unreal.AnimSequence)
        mesh = _asset(mesh_path, unreal.SkeletalMesh)
        definition = unreal.load_asset(definition_path)
        equipment_mesh = definition.get_editor_property("equipment_mesh")
        offset = definition.get_editor_property("spawn_offset")
        reference = unreal.AnimPoseExtensions.get_reference_pose(equipment_mesh.get_editor_property("skeleton"))
        attachment = reference.get_ref_bone_pose(attachment_bone, unreal.AnimPoseSpaces.WORLD)
        result = {"contacts": {}, "attachment": _read_transform(attachment), "spawnOffset": _read_transform(offset)}
        for name, frame in json.loads(contact_frames_json).items():
            pose = _pose(animation, mesh, frame / 30.0)
            right_hand = unreal.AnimPoseExtensions.get_bone_pose(pose, "hand_r", unreal.AnimPoseSpaces.WORLD)
            hand = unreal.AnimPoseExtensions.get_bone_pose(pose, held_bone, unreal.AnimPoseSpaces.WORLD)
            world_attachment = attachment.multiply(offset).multiply(right_hand)
            grip = world_attachment.make_relative(hand)
            grip.translation = unreal.Vector(*json.loads(grip_position_json))
            target = grip.inverse().multiply(world_attachment)
            result["contacts"][name] = {"frame": frame, "grip": _read_transform(grip), "target": _read_transform(target), "attachmentWorld": _read_transform(world_attachment)}

        return json.dumps(result, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def create_sequence_attachment(sequence_path: str, label: str, mesh_path: str, socket_name: str, transform_json: str, ranges_json: str, animation_path: str) -> str:
        """
        /**
         * 在独立编辑序列中加入随角色骨骼移动的装备或手持物
         * @param sequence_path\t序列路径
         * @param label\t唯一绑定名称
         * @param mesh_path\t骨骼或静态网格
         * @param socket_name\t角色挂接骨骼
         * @param transform_json\t相对挂接变换
         * @param ranges_json\t显示帧区间
         * @param animation_path\t可选骨骼动画
         * @return 创建的绑定名称
         */
        """
        sequence = _asset(sequence_path, unreal.LevelSequence)
        require_write_access(sequence)
        if any(binding.get_name() == label for binding in sequence.get_bindings()):
            raise RuntimeError("拒绝覆盖已有展示绑定 " + label)

        parents = []
        for candidate in sequence.get_bindings():
            template = candidate.get_object_template()
            if isinstance(template, unreal.SkeletalMeshActor) and template.skeletal_mesh_component.does_socket_exist(socket_name):
                parents.append(candidate)
        if len(parents) != 1:
            raise RuntimeError("附件挂接骨骼必须对应唯一骨骼演员 " + socket_name)
        parent = parents[0]
        mesh = unreal.load_asset(mesh_path)
        actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        if isinstance(mesh, unreal.SkeletalMesh):
            actor = actors.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(), transient=True)
            actor.skeletal_mesh_component.set_skeletal_mesh_asset(mesh)

        if isinstance(mesh, unreal.StaticMesh):
            actor = actors.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(), transient=True)
            actor.static_mesh_component.set_static_mesh(mesh)

        if not isinstance(mesh, (unreal.SkeletalMesh, unreal.StaticMesh)):
            raise RuntimeError("展示网格类型无效")

        actor.set_actor_label(label)
        actor.set_actor_enable_collision(False)
        actor.root_component.set_mobility(unreal.ComponentMobility.MOVABLE)
        binding = sequence.add_spawnable_from_instance(actor)
        binding.set_name(label)
        actors.destroy_actor(actor)
        end = sequence.get_playback_end()
        spawn_tracks = binding.find_tracks_by_type(unreal.MovieSceneSpawnTrack)
        spawn_track = spawn_tracks[0] if spawn_tracks else binding.add_track(unreal.MovieSceneSpawnTrack)
        spawn_sections = spawn_track.get_sections()
        spawn = spawn_sections[0] if spawn_sections else spawn_track.add_section()
        spawn.set_range(0, end + 1)
        channel = spawn.get_all_channels()[0]
        channel.set_default(False)
        ranges = json.loads(ranges_json)
        for first, last in ranges:
            channel.add_key(unreal.FrameNumber(value=first), True)
            channel.add_key(unreal.FrameNumber(value=last), False)

        attachment = binding.add_track(unreal.MovieScene3DAttachTrack).add_section()
        attachment.set_range(0, end)
        identifier = unreal.MovieSceneObjectBindingID()
        identifier.set_editor_property("guid", parent.get_id())
        attachment.set_constraint_binding_id(identifier)
        attachment.set_editor_property("attach_socket_name", socket_name)
        attachment.set_editor_property("attach_component_name", parent.get_object_template().skeletal_mesh_component.get_name())
        attachment.set_editor_property("attachment_location_rule", unreal.AttachmentRule.KEEP_RELATIVE)
        attachment.set_editor_property("attachment_rotation_rule", unreal.AttachmentRule.KEEP_RELATIVE)
        attachment.set_editor_property("attachment_scale_rule", unreal.AttachmentRule.KEEP_RELATIVE)
        transform = _transform(json.loads(transform_json))
        section = binding.add_track(unreal.MovieScene3DTransformTrack).add_section()
        section.set_range(0, end)
        rotator = transform.rotation.rotator()
        values = list(transform.translation.to_tuple()) + [rotator.roll, rotator.pitch, rotator.yaw] + list(transform.scale3d.to_tuple())
        for channel, value in zip(section.get_all_channels(), values):
            channel.set_default(value)

        if animation_path:
            animation = _asset(animation_path, unreal.AnimSequence)
            animation_section = binding.add_track(unreal.MovieSceneSkeletalAnimationTrack).add_section()
            animation_section.set_range(0, end)
            params = animation_section.get_editor_property("params")
            params.animation = animation
            animation_section.set_editor_property("params", params)

        unreal.EditorAssetLibrary.save_loaded_asset(sequence)
        return json.dumps({"binding": label, "socket": socket_name, "ranges": ranges})

    @mcp_tool
    @staticmethod
    def configure_sequence_attachment_animation(sequence_path: str, label: str, animation_path: str, first_frame: int, end_frame: int, play_rate: float) -> str:
        """
        /**
         * 设置唯一骨骼附件动画的显式时间范围与固定速度 拒绝隐式重复播放
         * @param sequence_path\t编辑序列路径
         * @param label\t\t附件绑定名称
         * @param animation_path\t附件动画路径
         * @param first_frame\t包含的起始显示帧
         * @param end_frame\t不包含的结束显示帧
         * @param play_rate\t源动画秒数与序列秒数之比
         * @return 已保存的时间范围与回读速度
         */
        """
        sequence = _asset(sequence_path, unreal.LevelSequence)
        animation = _asset(animation_path, unreal.AnimSequence)
        bindings = [binding for binding in sequence.get_bindings() if binding.get_name() == label]
        if len(bindings) != 1:
            raise RuntimeError("附件绑定必须唯一")

        tracks = bindings[0].find_tracks_by_type(unreal.MovieSceneSkeletalAnimationTrack)
        if len(tracks) > 1 or (tracks and len(tracks[0].get_sections()) != 1):
            raise RuntimeError("附件动画轨道与片段必须唯一")

        rate = sequence.get_display_rate()
        duration = (end_frame - first_frame) * rate.denominator / rate.numerator
        if (first_frame < sequence.get_playback_start() or end_frame > sequence.get_playback_end()
                or duration <= 0.0 or not math.isfinite(play_rate) or play_rate <= 0.0
                or duration * play_rate > animation.get_play_length() + 0.00001):
            raise RuntimeError("附件动画时间无效或会产生重复播放")

        require_write_access(sequence)
        sequence.modify()
        if not tracks:
            tracks = [bindings[0].add_track(unreal.MovieSceneSkeletalAnimationTrack)]
            tracks[0].add_section()
        section = tracks[0].get_sections()[0]
        section.set_range(first_frame, end_frame)
        params = section.get_editor_property("params")
        params.animation = animation
        params.play_rate = unreal.MovieSceneTimeWarpExtensions.make_time_warp(play_rate)
        params.first_loop_start_frame_offset = unreal.FrameNumber(value=0)
        params.start_frame_offset = unreal.FrameNumber(value=0)
        params.end_frame_offset = unreal.FrameNumber(value=0)
        params.reverse = False
        section.set_editor_property("params", params)
        actual = unreal.MovieSceneTimeWarpExtensions.to_fixed_play_rate(section.get_editor_property("params").play_rate)
        if abs(actual - play_rate) > 0.000001:
            raise RuntimeError("附件动画速度回读不一致 禁止保存")

        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError("附件动画时间轴保存失败")

        return json.dumps({"binding": label, "firstFrame": first_frame, "endFrame": end_frame, "playRate": actual})

    @mcp_tool
    @staticmethod
    def create_attachment_preview_animation(source_path: str, destination_path: str, bone_name: str, first_hidden_frame: int, last_hidden_frame: int) -> str:
        """
        /**
         * 创建仅用于编辑预览的弹匣显隐动画 保留运行资产原样
         * @param source_path\t装备原动画
         * @param destination_path\t预览资产路径
         * @param bone_name\t显隐骨骼
         * @param first_hidden_frame\t隐藏起始帧
         * @param last_hidden_frame\t恢复显示帧
         * @return 创建的预览路径
         */
        """
        source = _asset(source_path, unreal.AnimSequence)
        values = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(source, bone_name)
        if unreal.EditorAssetLibrary.does_asset_exist(destination_path):
            animation = _asset(destination_path, unreal.AnimSequence)
            require_write_access(animation)

        if not unreal.EditorAssetLibrary.does_asset_exist(destination_path):
            animation = unreal.EditorAssetLibrary.duplicate_asset(source_path, destination_path)
        scales = [value.scale3d for value in values]
        for index in range(first_hidden_frame, last_hidden_frame):
            scales[index] = unreal.Vector()

        if not animation.controller.set_bone_track_keys(bone_name, [value.translation for value in values], [value.rotation for value in values], scales, False):
            raise RuntimeError("预览显隐轨道写入失败")

        animation.set_editor_property("interpolation", unreal.AnimInterpolationType.STEP)
        unreal.EditorAssetLibrary.save_loaded_asset(animation)
        return json.dumps({"preview": destination_path})

    @mcp_tool
    @staticmethod
    def inject_pie_action(action_path: str, value: float, controller_path: str = "") -> str:
        """
        /**
         * 向当前 PIE 本地玩家注入一次标准增强输入 不发送系统按键
         * @param action_path\t输入动作资产
         * @param value\t第一轴输入值
         * @return 注入的动作和玩家
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            raise RuntimeError("PIE 未运行")

        controller = unreal.GameplayStatics.get_player_controller(world, 0)
        if controller_path:
            controller = unreal.find_object(None, controller_path)
            if not isinstance(controller, unreal.PlayerController):
                raise RuntimeError("指定对象不是 PIE 玩家控制器")
            worlds = unreal.EditorLevelLibrary.get_pie_worlds(False)
            if controller.get_world() not in worlds or not controller.is_local_controller():
                raise RuntimeError("指定控制器不是 PIE 世界的本地玩家")

        action = _asset(action_path, unreal.InputAction)
        library = unreal.get_default_object(unreal.load_class(None, "/Script/Engine.SubsystemBlueprintLibrary"))
        subsystem = library.call_method("GetLocalPlayerSubSystemFromPlayerController", (controller, unreal.EnhancedInputLocalPlayerSubsystem))
        if subsystem is None:
            raise RuntimeError("增强输入子系统不存在")

        input_library = unreal.get_default_object(unreal.EnhancedInputLibrary)
        raw_value = input_library.call_method("MakeInputActionValueOfType", (value, 0.0, 0.0, action.get_editor_property("value_type")))
        subsystem.inject_input_for_action(action, raw_value, [], [])
        return json.dumps({"action": action_path, "value": value, "controller": controller.get_path_name()})

    @mcp_tool
    @staticmethod
    def apply_baked_bone_deltas(source_path: str, baked_path: str, mesh_path: str, targets_json: str, bone_names: list[str]) -> str:
        """
        /**
         * 仅合入官方烘焙的指定骨骼改动 保留目标动画其它数据
         * @param source_path\t原始底稿
         * @param baked_path\t官方烘焙结果
         * @param mesh_path\t评估网格
         * @param targets_json\t目标及各自原始动画路径
         * @param bone_names\t允许调整的骨骼
         * @return 修改数量及最终检查
         */
        """
        source = _asset(source_path, unreal.AnimSequence)
        baked = _asset(baked_path, unreal.AnimSequence)
        mesh = _asset(mesh_path, unreal.SkeletalMesh)
        count = source.data_model_interface.get_number_of_keys()
        if baked.data_model_interface.get_number_of_keys() != count:
            raise RuntimeError("烘焙帧数与底稿不一致")

        allowed = {name.lower() for name in bone_names}
        rate = source.data_model_interface.get_frame_rate()
        samples = []
        for index in range(count):
            before = _pose(source, mesh, index * rate.denominator / rate.numerator)
            after = _pose(baked, mesh, index * rate.denominator / rate.numerator)
            deltas = {}
            for name in unreal.AnimPoseExtensions.get_bone_names(before):
                a = unreal.AnimPoseExtensions.get_bone_pose(before, name, unreal.AnimPoseSpaces.LOCAL)
                b = unreal.AnimPoseExtensions.get_bone_pose(after, name, unreal.AnimPoseSpaces.LOCAL)
                delta = (b.rotation * a.rotation.inversed()).normalized()
                angle = math.degrees(2.0 * math.acos(min(1.0, abs(delta.w))))
                position = b.translation - a.translation
                if str(name).lower() not in allowed:
                    if position.length() > 0.05 or angle > 0.1:
                        raise RuntimeError("烘焙修改了非授权骨骼 " + str(name) + " 帧 " + str(index))

                    continue

                deltas[str(name).lower()] = (position, delta)

            samples.append(deltas)

        results = []
        for request in json.loads(targets_json):
            animation = _asset(request["target"], unreal.AnimSequence)
            original = _asset(request["source"], unreal.AnimSequence)
            require_write_access(animation)
            if original.data_model_interface.get_number_of_keys() != count:
                raise RuntimeError("目标底稿帧数不同")

            tracks = {}
            for name in bone_names:
                values = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(original, name)
                if len(values) != count:
                    raise RuntimeError("目标原始轨道帧数无效 " + name)

                tracks[name] = values

            controller = animation.controller
            controller.open_bracket("合入官方 Control Rig 烘焙手臂轨道", False)
            try:
                for name, values in tracks.items():
                    positions = []
                    rotations = []
                    scales = []
                    for index, value in enumerate(values):
                        shift, delta = samples[index][name.lower()]
                        position = value.translation
                        if name.lower() == "ik_hand_l":
                            position = position + shift

                        positions.append(position)
                        rotations.append(delta * value.rotation)
                        scales.append(value.scale3d)

                    if not controller.set_bone_track_keys(name, positions, rotations, scales, False):
                        raise RuntimeError("合入轨道失败 " + name)

            finally:
                controller.close_bracket(False)

            unreal.EditorAssetLibrary.save_loaded_asset(animation)
            results.append({"asset": animation.get_path_name(), "bones": list(bone_names), "keys": count, "additive": str(animation.get_editor_property("additive_anim_type"))})

        unreal.log("[BBBControlRigAuthoring] 已校验全帧非授权骨骼并合入私有动画")
        return json.dumps(results)

    @mcp_tool
    @staticmethod
    def add_pose_controls(asset_path: str, bone_names: list[str], solve_node_name: str) -> str:
        """
        /**
         * 为烘焙底稿建立隐藏的原姿势控制器和官方整组骨骼赋值节点
         * @param asset_path\t绑定路径
         * @param bone_names\t按层级排序的源骨骼
         * @return 控制器数量
         */
        """
        asset = _asset(asset_path, unreal.ControlRigBlueprint)
        require_write_access(asset)
        hierarchy = asset.hierarchy
        controller = hierarchy.get_controller()
        graph = asset.get_controller()
        solve_pin = solve_node_name + ".ExecutePin"
        if not solve_node_name or graph.get_graph().find_pin(solve_pin) is None:
            raise RuntimeError("手臂求解执行入口不存在 " + solve_node_name)
        names = [str(name) for name in bone_names]
        items = []
        transforms = []
        for element in list(hierarchy.get_all_keys()):
            if element.type == unreal.RigElementType.CONTROL and str(element.name).startswith("source_"):
                controller.remove_element(element, False, False)

        for index, bone in enumerate(names):
            settings = unreal.RigControlSettings()
            settings.control_type = unreal.RigControlType.EULER_TRANSFORM
            settings.shape_visible = False
            key = controller.add_control("source_" + bone, unreal.RigElementKey(), settings, unreal.RigHierarchy.make_control_value_from_euler_transform(unreal.EulerTransform()), False, False)
            if str(key.name) == "None":
                raise RuntimeError("原姿势控制器创建失败 " + bone)

            node = "SourcePose_" + str(index)
            graph.add_unit_node_from_struct_path("/Script/ControlRig.RigUnit_GetTransform", "Execute", unreal.Vector2D(-1000.0, index * 100.0), node, False, False)
            graph.set_pin_default_value(node + ".Item", '(Type=Control,Name="source_' + bone + '")', True, False, False, False)
            items.append('(Type=Bone,Name="' + bone + '")')
            transforms.append("(Rotation=(X=0,Y=0,Z=0,W=1),Translation=(X=0,Y=0,Z=0),Scale3D=(X=1,Y=1,Z=1))")

        graph.add_unit_node_from_struct_path("/Script/ControlRig.RigUnit_SetTransformItemArray", "Execute", unreal.Vector2D(-600.0, 0.0), "OriginalPose", False, False)
        graph.set_pin_default_value("OriginalPose.Items", "(" + ",".join(items) + ")", True, False, False, False)
        graph.set_pin_default_value("OriginalPose.Transforms", "(" + ",".join(transforms) + ")", True, False, False, False)
        graph.set_pin_default_value("OriginalPose.Weight", "1.0", True, False, False, False)
        for index in range(len(names)):
            graph.add_link("SourcePose_" + str(index) + ".Transform", "OriginalPose.Transforms." + str(index), False, False)

        if not graph.break_link("Forward.ExecutePin", solve_pin, False, False):
            raise RuntimeError("原求解执行连线不存在")
        if not graph.add_link("Forward.ExecutePin", "OriginalPose.ExecutePin", False, False):
            raise RuntimeError("原姿势执行入口连接失败")

        if not graph.add_link("OriginalPose.ExecutePin", solve_pin, False, False):
            raise RuntimeError("手臂求解执行入口连接失败")
        asset.recompile_vm()
        unreal.EditorAssetLibrary.save_loaded_asset(asset)
        return json.dumps({"controls": len(names)})

    @mcp_tool
    @staticmethod
    def inspect_sequence_pose(sequence_path: str, frame: int, bone_names: list[str]) -> str:
        """
        /**
         * 使用实际序列播放器检查生成角色姿势
         * @param sequence_path\t序列路径
         * @param frame\t显示帧
         * @param bone_names\t骨骼名称
         * @return 实际组件骨骼与控制器状态
         */
        """
        sequence = _asset(sequence_path, unreal.LevelSequence)
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        player, actor = unreal.LevelSequencePlayer.create_level_sequence_player(world, sequence, unreal.MovieSceneSequencePlaybackSettings())
        params = unreal.MovieSceneSequencePlaybackParams()
        params.time = frame / 30.0
        params.position_type = unreal.MovieScenePositionType.TIME
        params.update_method = unreal.UpdatePositionMethod.PLAY
        result = {"actors": [], "rigs": []}
        try:
            player.set_playback_position(params)
            for binding in sequence.get_bindings():
                identifier = unreal.MovieSceneObjectBindingID()
                identifier.set_editor_property("guid", binding.get_id())
                for bound in player.get_bound_objects(identifier):
                    if isinstance(bound, unreal.SkeletalMeshActor):
                        mesh = bound.skeletal_mesh_component
                        result["actors"].append({"path": bound.get_path_name(), "bones": {name: _read_transform(mesh.get_socket_transform(name, unreal.RelativeTransformSpace.RTS_COMPONENT)) for name in bone_names}})

            for proxy in unreal.ControlRigSequencerLibrary.get_control_rigs(sequence):
                rig = proxy.control_rig
                hierarchy = rig.get_hierarchy()
                result["rigs"].append({"weight": unreal.RigHierarchy.get_float_from_control_value(hierarchy.get_control_value(_key("arm_l_weight", "CONTROL"))), "handControl": _read_transform(hierarchy.get_global_transform(_key("hand_l_ik_ctrl", "CONTROL"))), "bones": {name: _read_transform(hierarchy.get_global_transform(_key(name))) for name in bone_names}})

        except Exception:
            unreal.log_error(traceback.format_exc())
            raise

        finally:
            player.stop()
            unreal.get_editor_subsystem(unreal.EditorActorSubsystem).destroy_actor(actor)

        return json.dumps(result)

    @mcp_tool
    @staticmethod
    def inspect_sequence_bindings(sequence_path: str) -> str:
        """
        /**
         * 检查序列绑定模板及生成轨道
         * @param sequence_path\t序列路径
         * @return 模板网格及轨道信息
         */
        """
        sequence = _asset(sequence_path, unreal.LevelSequence)
        result = []
        for binding in sequence.get_bindings():
            template = binding.get_object_template()
            item = {"name": binding.get_name(), "template": str(template), "tracks": [track.get_class().get_name() for track in binding.get_tracks()]}
            item["sections"] = []
            for track in binding.get_tracks():
                for section in track.get_sections():
                    item["sections"].append({"track": track.get_class().get_name(), "active": section.is_active(), "blend": str(section.get_blend_type()), "channels": [{"name": str(channel.channel_name), "default": str(channel.get_default()), "keys": len(channel.get_keys())} for channel in section.get_all_channels()]})
            if isinstance(template, unreal.SkeletalMeshActor):
                item["mesh"] = str(template.skeletal_mesh_component.get_editor_property("skeletal_mesh_asset"))

            result.append(item)

        return json.dumps(result)

    @mcp_tool
    @staticmethod
    def export_sequence_pose_audit(sequence_path: str, source_path: str, mesh_path: str, sample_times: list[float], report_name: str) -> str:
        """
        /**
         * 使用官方序列烘焙器导出临时动画并检查与源的骨骼差异
         * @param sequence_path\t编辑序列
         * @param source_path\t源动画
         * @param mesh_path\t角色网格
         * @param sample_times\t取样秒数
         * @param report_name\t诊断报告文件名
         * @return 烘焙及差异报告路径
         */
        """
        if os.path.basename(report_name) != report_name:
            raise RuntimeError("诊断报告名无效")

        sequence = _asset(sequence_path, unreal.LevelSequence)
        source = _asset(source_path, unreal.AnimSequence)
        mesh = _asset(mesh_path, unreal.SkeletalMesh)
        bake_path = sequence_path.rsplit("/", 1)[0] + "/ANI_BBB_Rifle_01_ReloadHandBake"
        if unreal.EditorAssetLibrary.does_asset_exist(bake_path):
            baked = _asset(bake_path, unreal.AnimSequence)
            require_write_access(baked)

        if not unreal.EditorAssetLibrary.does_asset_exist(bake_path):
            factory = unreal.AnimSequenceFactory()
            factory.target_skeleton = source.get_editor_property("skeleton")
            factory.preview_skeletal_mesh = mesh
            folder, name = bake_path.rsplit("/", 1)
            baked = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.AnimSequence, factory)
        options = unreal.AnimSeqExportOption()
        options.export_transforms = True
        options.export_morph_targets = True
        options.export_attribute_curves = True
        options.export_material_curves = True
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        binding = _mesh_binding(sequence, mesh)
        spawn_tracks = [track for track in binding.get_tracks() if isinstance(track, unreal.MovieSceneSpawnTrack)]
        if not spawn_tracks:
            require_write_access(sequence)
            spawn = binding.add_track(unreal.MovieSceneSpawnTrack).add_section()
            spawn.set_range(sequence.get_playback_start(), sequence.get_playback_end())
            spawn.get_all_channels()[0].set_default(True)
            unreal.EditorAssetLibrary.save_loaded_asset(sequence)

        spawn_section = binding.find_tracks_by_type(unreal.MovieSceneSpawnTrack)[0].get_sections()[0]
        spawn_channel = spawn_section.get_all_channels()[0]
        spawn_channel.add_key(unreal.FrameNumber(value=sequence.get_playback_start()), True)
        spawn_channel.add_key(unreal.FrameNumber(value=sequence.get_playback_end()), False)
        baked.controller.remove_all_bone_tracks(False)
        if not unreal.SequencerTools.export_anim_sequence(world, sequence, baked, options, binding, False):
            raise RuntimeError("官方序列烘焙失败")

        unreal.EditorAssetLibrary.save_loaded_asset(baked)
        unreal.EditorAssetLibrary.save_loaded_asset(sequence)
        report = {"sequence": sequence_path, "baked": baked.get_path_name(), "length": baked.sequence_length, "samples": []}
        for time in sample_times:
            before = _pose(source, mesh, time)
            after = _pose(baked, mesh, time)
            differences = []
            for name in unreal.AnimPoseExtensions.get_bone_names(before):
                a = unreal.AnimPoseExtensions.get_bone_pose(before, name, unreal.AnimPoseSpaces.LOCAL)
                b = unreal.AnimPoseExtensions.get_bone_pose(after, name, unreal.AnimPoseSpaces.LOCAL)
                distance = (a.translation - b.translation).length()
                dot = abs(a.rotation.x * b.rotation.x + a.rotation.y * b.rotation.y + a.rotation.z * b.rotation.z + a.rotation.w * b.rotation.w)
                angle = math.degrees(2.0 * math.acos(min(1.0, dot)))
                if distance > 0.01 or angle > 0.1:
                    differences.append({"bone": str(name), "cm": distance, "degrees": angle})

            report["samples"].append({"time": time, "differences": differences})

        folder = os.path.join(unreal.Paths.project_saved_dir(), "Diagnostics")
        os.makedirs(folder, exist_ok=True)
        path = os.path.abspath(os.path.join(folder, report_name))
        with open(path, "w", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=4)

        unreal.log("[BBBControlRigAuthoring] 正式烘焙对照报告 " + path)
        return json.dumps({"report": path, "length": baked.sequence_length, "differentBones": sorted({bone["bone"] for sample in report["samples"] for bone in sample["differences"]})})


_official_python = os.path.join(unreal.Paths.engine_plugins_dir(), "Experimental", "Toolsets", "AnimationAssistantToolset", "Content", "Python")
if _official_python not in sys.path:
    sys.path.append(_official_python)

from animation_toolset.toolsets.controlrig import ControlRigTools
from animation_toolset.toolsets.sequencer import SequencerTools
from animation_toolset.toolsets.controlrig_sequencer import SequencerControlRigTools
from animation_toolset.toolsets.import_export import SequencerImportExportTools

_registration = Registration([BBBControlRigAuthoringToolset, ControlRigTools, SequencerTools, SequencerControlRigTools, SequencerImportExportTools])

if __name__ == "__bbb_editor_script__":
    def register_after_reload(delta_seconds):
        _registration.unregister()
        _registration.register()
        unreal.unregister_slate_post_tick_callback(registration_handle)

    registration_handle = unreal.register_slate_post_tick_callback(register_after_reload)
    print("已注册通用 Control Rig 动画编辑工具")
