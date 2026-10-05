import json
import os

import unreal
from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration
from BBBAssetWritePolicy import require_write_access
from editor_toolset.toolsets.blueprint import BlueprintTools


def _link(source, target):
    """/** @param source 输出引脚 @param target 输入引脚 @return 无 连线失败时报警 */"""
    if not source.is_valid() or not target.is_valid() or not source.try_create_connection(target):
        raise RuntimeError("刚性部件图表连线失败")


def _value(pin, value):
    """/** @param pin 目标引脚 @param value 默认值 @return 无 赋值失败时报警 */"""
    if not pin.set_pin_value(str(value)):
        raise RuntimeError("刚性部件引脚赋值失败 " + str(pin.get_pin_name()))


def _reference(mesh_path, bone_name):
    """/** @param mesh_path 网格路径 @param bone_name 骨骼名称 @return 骨架组件空间参考变换 */"""
    mesh = unreal.load_asset(mesh_path)
    if not isinstance(mesh, unreal.SkeletalMesh):
        raise RuntimeError("目标不是骨骼网格 " + mesh_path)
    pose = unreal.AnimPoseExtensions.get_reference_pose(mesh.get_editor_property("skeleton"))
    if bone_name not in [str(name) for name in pose.get_bone_names()]:
        raise RuntimeError("参考骨架缺少附着骨骼 " + bone_name)
    return pose.get_ref_bone_pose(bone_name, unreal.AnimPoseSpaces.WORLD)


def _transform_text(transform):
    """/** @param transform 待记录的变换 @return 用于诊断报告的变换文本 */"""
    position = transform.translation
    rotation = transform.rotation
    scale = transform.scale3d
    return "(Rotation=(X={},Y={},Z={},W={}),Translation=(X={},Y={},Z={}),Scale3D=(X={},Y={},Z={}))".format(
        rotation.x, rotation.y, rotation.z, rotation.w,
        position.x, position.y, position.z,
        scale.x, scale.y, scale.z,
    )


@unreal.uclass()
class BBBRigidPartToolset(unreal.ToolsetDefinition):
    """/** 提供骨骼部件的参考姿势检查和蓝图刚性附着编辑工具 */"""

    @mcp_tool
    @staticmethod
    def inspect_reference_attachment(mesh_paths: list[str], bone_name: str) -> str:
        """
        /**
         * 只读核对部件附着骨骼的参考姿势
         * @param mesh_paths	待核对的骨骼网格路径
         * @param bone_name	附着骨骼名称
         * @return 参考姿势和保持原始位置所需的相对变换
         */
        """
        rows = []
        for path in mesh_paths:
            reference = _reference(path, bone_name)
            offset = unreal.MathLibrary.invert_transform(reference)
            rows.append({"mesh": path, "bone": bone_name, "reference": _transform_text(reference), "offset": _transform_text(offset)})
        return json.dumps(rows, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_rigid_blueprint_part(leader_node_path: str, slot_node_path: str, slot_pin_name: str, slot_name: str, function_name: str, reference_mesh_path: str, bone_name: str) -> str:
        """
        /**
         * 在指定姿势跟随节点前分流单个部位并创建刚性附着函数 不自动保存
         * @param leader_node_path	现有姿势跟随节点完整路径
         * @param slot_node_path	提供部位名称的节点完整路径
         * @param slot_pin_name	提供部位名称的输出引脚
         * @param slot_name	需要刚性附着的部位名称
         * @param function_name	新增蓝图函数名称
         * @param reference_mesh_path	提供参考骨架的网格路径
         * @param bone_name	附着骨骼名称
         * @return 编译状态与参考姿势偏移
         */
        """
        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("PIE 期间禁止修改刚性部件图表")
        leader = unreal.load_object(None, leader_node_path)
        slot_node = unreal.load_object(None, slot_node_path)
        if not isinstance(leader, unreal.K2Node_CallFunction) or slot_node is None:
            raise RuntimeError("目标图表节点无效")
        graph = leader.get_outer()
        blueprint = graph.get_outer()
        require_write_access(blueprint)
        if slot_node.get_outer() != graph:
            raise RuntimeError("部位引脚与姿势节点必须属于同一图表")
        if function_name in [str(item.get_name()) for item in BlueprintTools.list_graphs(blueprint)]:
            raise RuntimeError("目标函数已存在 拒绝覆盖")
        execute = leader.find_execute_pin()
        previous = list(execute.list_connected_pins())
        following = list(leader.find_then_pin().list_connected_pins())
        part_sources = list(leader.find_input_pin("self").list_connected_pins())
        body_sources = list(leader.find_input_pin("NewLeaderBoneComponent").list_connected_pins())
        if any(len(items) != 1 for items in (previous, following, part_sources, body_sources)):
            raise RuntimeError("姿势节点必须有唯一执行前后节点和部件来源")
        offset = unreal.MathLibrary.invert_transform(_reference(reference_mesh_path, bone_name))

        with unreal.ScopedEditorTransaction("BBB Rigid Part Attachment"):
            blueprint.modify()
            function_graph = BlueprintTools.add_function_graph(blueprint, function_name)
            if str(function_graph.get_name()) != function_name:
                raise RuntimeError("函数名称被占用 请重新加载已保存蓝图后再执行")
            BlueprintTools.add_object_function_param(function_graph, "PartMesh", unreal.SkeletalMeshComponent.static_class(), True)
            BlueprintTools.add_object_function_param(function_graph, "BodyMesh", unreal.SkeletalMeshComponent.static_class(), True)
            editor = unreal.BlueprintGraphEditor.get_graph_editor(function_graph)
            entry = next(node for node in editor.list_all_nodes() if isinstance(node, unreal.K2Node_FunctionEntry))
            part = entry.find_output_pin("PartMesh")
            body = entry.find_output_pin("BodyMesh")

            clear = editor.add_call_function_node("/Script/Engine.SkinnedMeshComponent.SetLeaderPoseComponent")
            _link(part, clear.find_input_pin("self"))
            _value(clear.find_input_pin("bForceUpdate"), "true")
            _link(editor.find_graph_entry_pin(), clear.find_execute_pin())

            mode = editor.add_call_function_node("/Script/Engine.SkeletalMeshComponent.SetAnimationMode")
            _link(part, mode.find_input_pin("self"))
            _value(mode.find_input_pin("InAnimationMode"), "AnimationSingleNode")
            _link(clear.find_then_pin(), mode.find_execute_pin())

            animation = editor.add_call_function_node("/Script/Engine.SkeletalMeshComponent.SetAnimation")
            _link(part, animation.find_input_pin("self"))
            _link(mode.find_then_pin(), animation.find_execute_pin())

            attach = editor.add_call_function_node("/Script/Engine.SceneComponent.K2_AttachToComponent")
            _link(part, attach.find_input_pin("self"))
            _link(body, attach.find_input_pin("Parent"))
            _value(attach.find_input_pin("SocketName"), bone_name)
            for name in ("LocationRule", "RotationRule", "ScaleRule"):
                _value(attach.find_input_pin(name), "KeepRelative")
            _value(attach.find_input_pin("bWeldSimulatedBodies"), "false")
            _link(animation.find_then_pin(), attach.find_execute_pin())

            relative = editor.add_call_function_node("/Script/Engine.SceneComponent.K2_SetRelativeTransform")
            _link(part, relative.find_input_pin("self"))
            make_transform = editor.add_call_function_node("/Script/Engine.KismetMathLibrary.MakeTransform")
            location = offset.translation
            rotation = offset.rotation.rotator()
            scale = offset.scale3d
            _value(make_transform.find_input_pin("Location"), "{}, {}, {}".format(location.x, location.y, location.z))
            _value(make_transform.find_input_pin("Rotation"), "{}, {}, {}".format(rotation.pitch, rotation.yaw, rotation.roll))
            _value(make_transform.find_input_pin("Scale"), "{}, {}, {}".format(scale.x, scale.y, scale.z))
            _link(make_transform.find_output_pin("ReturnValue"), relative.find_input_pin("NewTransform"))
            make_transform.set_node_pos(unreal.IntPoint(1280, 300))
            _link(attach.find_then_pin(), relative.find_execute_pin())
            result = editor.add_return_node()
            _link(relative.find_then_pin(), result.find_execute_pin())
            for index, node in enumerate([entry, clear, mode, animation, attach, relative, result]):
                node.set_node_pos(unreal.IntPoint(index * 320, 0))
            BlueprintTools.compile_blueprint(blueprint)
            if blueprint.get_editor_property("status") == unreal.BlueprintStatus.BS_ERROR:
                raise RuntimeError("刚性附着函数编译失败 尚未保存")

            leader = unreal.load_object(None, leader_node_path)
            slot_node = unreal.load_object(None, slot_node_path)
            graph = leader.get_outer()
            execute = leader.find_execute_pin()
            previous = list(execute.list_connected_pins())
            following = list(leader.find_then_pin().list_connected_pins())
            part_sources = list(leader.find_input_pin("self").list_connected_pins())
            body_sources = list(leader.find_input_pin("NewLeaderBoneComponent").list_connected_pins())
            main_editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
            equal = main_editor.add_call_function_node("/Script/Engine.KismetMathLibrary.EqualEqual_NameName")
            _link(slot_node.find_output_pin(slot_pin_name), equal.find_input_pin("A"))
            _value(equal.find_input_pin("B"), slot_name)
            branch = main_editor.add_branch_node()
            _link(equal.find_output_pin("ReturnValue"), branch.find_input_pin("Condition"))
            call = main_editor.add_call_function_node(blueprint.generated_class().get_path_name() + "." + function_name)
            if call is None:
                raise RuntimeError("已编译的刚性附着函数无法创建调用节点")
            _link(part_sources[0], call.find_input_pin("PartMesh"))
            _link(body_sources[0], call.find_input_pin("BodyMesh"))
            previous[0].break_single_pin_link(execute)
            _link(previous[0], branch.find_execute_pin())
            _link(branch.find_output_pin("then"), call.find_execute_pin())
            _link(branch.find_output_pin("else"), execute)
            _link(call.find_then_pin(), following[0])
            position = leader.get_node_pos()
            equal.set_node_pos(unreal.IntPoint(position.x - 600, position.y - 450))
            branch.set_node_pos(unreal.IntPoint(position.x - 300, position.y - 250))
            call.set_node_pos(unreal.IntPoint(position.x, position.y - 350))
            BlueprintTools.compile_blueprint(blueprint)
            if blueprint.get_editor_property("status") == unreal.BlueprintStatus.BS_ERROR:
                raise RuntimeError("部件分流编译失败 尚未保存")

        unreal.log("[BBBRigidPart]刚性附着图表已编译 部位={} 骨骼={}".format(slot_name, bone_name))
        return json.dumps({"blueprint": blueprint.get_path_name(), "function": function_name, "bone": bone_name, "offset": _transform_text(offset), "saved": False}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def validate_rigid_part_selection(actor_blueprint_paths: list[str], assembly_class_path: str, selection_property: str, apply_function: str, slot_name: str, item_names: list[str], body_tag: str, animation_paths: list[str], bone_name: str, report_name: str) -> str:
        """
        /**
         * 在临时人物上验证选装后的刚性骨骼附着并输出实际渲染截图 不修改资产
         * @param actor_blueprint_paths	真实人物和预览人物蓝图路径
         * @param assembly_class_path	组装组件类路径
         * @param selection_property	默认选装结构属性名称
         * @param apply_function	蓝图组装函数名称
         * @param slot_name	刚性部件的部位名称
         * @param item_names	按顺序切换的目录条目名称 可重复
         * @param body_tag	动画主网格组件标签
         * @param animation_paths	用于动作采样的动画序列
         * @param bone_name	预期附着骨骼名称
         * @param report_name	报告文件名称 不含路径
         * @return 验证结果 报告和截图路径
         */
        """
        pie_worlds = unreal.EditorLevelLibrary.get_pie_worlds(False)
        if len(pie_worlds) != 1:
            raise RuntimeError("验证需要唯一单人 PIE 世界")
        if os.path.basename(report_name) != report_name or not report_name.endswith(".json"):
            raise RuntimeError("报告名称无效")
        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "Diagnostics", "RigidParts"))
        os.makedirs(directory, exist_ok=True)
        report_path = os.path.join(directory, report_name)
        if os.path.exists(report_path):
            raise RuntimeError("报告已存在 拒绝覆盖")
        assembly_class = unreal.load_class(None, assembly_class_path)
        animations = [unreal.load_asset(path) for path in animation_paths]
        if assembly_class is None or any(not isinstance(item, unreal.AnimSequence) for item in animations):
            raise RuntimeError("验证组件或动画资产无效")
        fixtures = []
        results = []
        screenshots = []
        try:
            origin = unreal.Vector(0, 0, 1000)
            for position in (unreal.Vector(220, 180, 1250), unreal.Vector(-200, 100, 1200), unreal.Vector(100, -240, 1200)):
                light = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(pie_worlds[0], unreal.PointLight.static_class(), unreal.Transform(location=position))
                fixtures.append(light)
                light.point_light_component.set_editor_property("intensity", 80000.0)
                light.point_light_component.set_editor_property("attenuation_radius", 1500.0)
            for actor_index, blueprint_path in enumerate(actor_blueprint_paths):
                blueprint = unreal.load_asset(blueprint_path)
                actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(pie_worlds[0], blueprint.generated_class(), unreal.Transform(location=origin))
                fixtures.append(actor)
                actor.set_replicates(False)
                assembly = actor.get_component_by_class(assembly_class)
                body_components = actor.get_components_by_tag(unreal.SkeletalMeshComponent, body_tag)
                parts = actor.get_components_by_tag(unreal.SkeletalMeshComponent, slot_name)
                if assembly is None or len(body_components) != 1 or len(parts) != 1:
                    raise RuntimeError("验证人物必须有唯一组装组件 主网格和目标部件")
                body = body_components[0]
                part = parts[0]
                for item_index, item_name in enumerate(item_names):
                    assembly = actor.get_component_by_class(assembly_class)
                    body = actor.get_components_by_tag(unreal.SkeletalMeshComponent, body_tag)[0]
                    part = actor.get_components_by_tag(unreal.SkeletalMeshComponent, slot_name)[0]
                    selection = assembly.get_editor_property(selection_property).copy()
                    choices = [choice.copy() for choice in selection.get_editor_property("parts")]
                    matches = [choice for choice in choices if str(choice.get_editor_property("slot")) == slot_name]
                    if len(matches) != 1:
                        raise RuntimeError("默认选装中目标部位不唯一")
                    matches[0].set_editor_property("item", unreal.Name(item_name))
                    selection.set_editor_property("parts", choices)
                    if not getattr(assembly, apply_function)(selection):
                        raise RuntimeError("蓝图组装返回失败 " + item_name)
                    if part.get_editor_property("leader_pose_component") is not None:
                        raise RuntimeError("刚性部件仍在复制人体骨骼 " + item_name)
                    if part.get_attach_parent() != body or str(part.get_attach_socket_name()) != bone_name:
                        raise RuntimeError("刚性部件附着对象或骨骼不符 " + item_name)
                    if part.get_anim_instance() is not None and part.get_anim_instance().get_class() != unreal.AnimSingleNodeInstance.static_class():
                        raise RuntimeError("刚性部件残留动画蓝图实例")
                    reference_points = {}
                    if part.get_editor_property("skeletal_mesh_asset") is not None:
                        for name in ("spine_01", "spine_02", "spine_03", "clavicle_l", "clavicle_r"):
                            reference_points[name] = part.get_socket_transform(name, unreal.RelativeTransformSpace.RTS_COMPONENT).translation
                    for animation_index, animation in enumerate(animations):
                        for fraction in (0.0, 0.5, 0.95):
                            if not unreal.BBBBlueprintEditorLibrary.evaluate_animation_preview_pose(body, animation, fraction * animation.get_play_length()):
                                raise RuntimeError("动作姿势求值失败")
                            expected = part.get_relative_transform() * body.get_socket_transform(bone_name, unreal.RelativeTransformSpace.RTS_WORLD)
                            actual = part.get_world_transform()
                            error = actual.translation.distance(expected.translation)
                            if error > 0.01:
                                raise RuntimeError("刚性部件未跟随附着骨骼 位置误差=" + str(error))
                            shape_error = 0.0
                            for name, point in reference_points.items():
                                current = part.get_socket_transform(name, unreal.RelativeTransformSpace.RTS_COMPONENT).translation
                                shape_error = max(shape_error, point.distance(current))
                            if shape_error > 0.01:
                                raise RuntimeError("刚性部件内部骨骼仍在变形 " + str(shape_error))
                            results.append({"actor": blueprint_path, "item": item_name, "mesh": str(part.get_editor_property("skeletal_mesh_asset")), "animation": animation.get_path_name(), "fraction": fraction, "positionErrorCm": error, "internalBoneMotionCm": shape_error, "leader": None, "socket": str(part.get_attach_socket_name())})
                            if actor_index == 1 and item_index < 2 and animation_index in (0, 3) and fraction == 0.5:
                                center, extent = actor.get_actor_bounds(False)
                                camera = center + unreal.Vector(220, 280, 80)
                                rotation = unreal.MathLibrary.find_look_at_rotation(camera, center)
                                name = report_name[:-5] + "-{}-{}.png".format(item_index, animation_index)
                                path = os.path.join(directory, name)
                                if os.path.exists(path):
                                    raise RuntimeError("验收截图已存在 拒绝覆盖 " + path)
                                capture_actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(actor, unreal.SceneCapture2D.static_class(), unreal.Transform(location=camera, rotation=rotation))
                                try:
                                    target = unreal.RenderingLibrary.create_render_target2d(actor, 960, 960, unreal.TextureRenderTargetFormat.RTF_RGBA8)
                                    capture = capture_actor.capture_component2d
                                    capture.set_editor_property("texture_target", target)
                                    capture.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
                                    capture.set_editor_property("fov_angle", 45.0)
                                    capture.capture_scene()
                                    unreal.RenderingLibrary.export_render_target(actor, target, directory, name)
                                finally:
                                    capture_actor.destroy_actor()
                                screenshots.append(path)
                actor.destroy_actor()
                fixtures.remove(actor)
        finally:
            for fixture in reversed(fixtures):
                fixture.destroy_actor()
        with open(report_path, "w", encoding="utf-8") as output:
            json.dump({"samples": results, "screenshots": screenshots}, output, ensure_ascii=False, indent=4)
        unreal.log("[BBBRigidPart]选装与姿势验证通过 样本={}".format(len(results)))
        return json.dumps({"passed": True, "samples": len(results), "report": report_path, "screenshots": screenshots}, ensure_ascii=False)


_registration = Registration([BBBRigidPartToolset])

if __name__ == "__bbb_editor_script__":
    def register_after_reload(delta_seconds):
        """/** @param delta_seconds 编辑器帧间隔 @return 无 下一帧刷新工具注册 */"""
        _registration.unregister()
        _registration.register()
        unreal.unregister_slate_post_tick_callback(registration_handle)

    registration_handle = unreal.register_slate_post_tick_callback(register_after_reload)
