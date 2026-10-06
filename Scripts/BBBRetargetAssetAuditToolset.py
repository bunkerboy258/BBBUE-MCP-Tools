import json
import math

import unreal
from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration


def _asset(path, expected_type):
    """/** @param path 资产路径 @param expected_type 类型 @return 已核对的资产 */"""
    value = unreal.load_asset(path)
    if not isinstance(value, expected_type):
        raise RuntimeError("资产类型无效: " + path)
    return value


def _distance(first, second):
    """/** @param first 位置 @param second 位置 @return 厘米距离 */"""
    return (first - second).length()


@unreal.uclass()
class BBBRetargetAssetAuditToolset(unreal.ToolsetDefinition):
    """/** 核验动画姿势并准备独立根运动重定向资产 */"""

    @mcp_tool
    @staticmethod
    def retarget_sequences(source_paths: list[str], retargeter_path: str, target_folder: str, overwrite: bool = False) -> str:
        """
        /**
         * @param source_paths 源动画序列
         * @param retargeter_path 已核验的重定向器
         * @param target_folder 自有资产目标目录
         * @param overwrite 是否重建同名目标 现有目标必须已签出或打开添加
         * @return 官方批量重定向创建并保存的资产
         */
        """
        from BBBAssetWritePolicy import require_asset_write
        if not source_paths or len(set(source_paths)) != len(source_paths):
            raise RuntimeError("源动画不能为空或重复")
        if not target_folder.startswith("/Game/_Project/") or target_folder.endswith("/"):
            raise RuntimeError("目标必须为自有资产目录")
        retargeter = _asset(retargeter_path, unreal.IKRetargeter)
        controller = unreal.IKRetargeterController.get_controller(retargeter)
        source_mesh = controller.get_preview_mesh(unreal.RetargetSourceOrTarget.SOURCE)
        target_mesh = controller.get_preview_mesh(unreal.RetargetSourceOrTarget.TARGET)
        if not source_mesh or not target_mesh:
            raise RuntimeError("重定向器缺少源或目标网格")
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        sources = []
        existing = []
        destinations = []
        expected = []
        for path in source_paths:
            animation = _asset(path, unreal.AnimSequence)
            if animation.get_editor_property("skeleton") != source_mesh.get_editor_property("skeleton"):
                raise RuntimeError("源动画与源网格骨架不同: " + path)
            target = target_folder + "/" + animation.get_name()
            if target == path or target in expected:
                raise RuntimeError("目标存在命名冲突: " + target)
            expected.append(target)
            if unreal.EditorAssetLibrary.does_asset_exist(target):
                if not overwrite:
                    raise RuntimeError("目标已存在 未授权覆盖: " + target)
                existing.append(_asset(target, unreal.AnimSequence))
            else:
                destinations.append(target)
            data = registry.get_asset_by_object_path(unreal.Name(animation.get_path_name()))
            if not data.is_valid():
                raise RuntimeError("源动画注册信息无效: " + path)
            sources.append(data)
        require_asset_write(existing, destinations)
        inputs = unreal.IKRetargetBatchOperationInputs()
        inputs.assets_to_retarget = sources
        inputs.source_mesh = source_mesh
        inputs.target_mesh = target_mesh
        inputs.ik_retarget_asset = retargeter
        inputs.target_path = target_folder
        inputs.include_referenced_assets = False
        inputs.overwrite_existing_files = overwrite
        inputs.retain_additive_flags = True
        results = unreal.IKRetargetBatchOperation.run_batch_retarget(inputs)
        created = [str(result.package_name) for result in results]
        if sorted(created) != sorted(expected):
            raise RuntimeError("重定向输出与明确目标不一致: " + str(created))
        for path in created:
            asset = _asset(path, unreal.AnimSequence)
            asset.set_preview_skeletal_mesh(target_mesh)
            if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
                raise RuntimeError("重定向动画保存失败: " + path)
        for path in destinations:
            if not unreal.SourceControl.mark_file_for_add(path, silent=True):
                raise RuntimeError("目标未打开添加: " + path)
        return json.dumps({"saved": created, "mesh": target_mesh.get_path_name()}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_root_motion_retargeter(asset_path: str, source_mesh_path: str) -> str:
        """
        /**
         * @param asset_path 已独占签出或打开添加的独立重定向器
         * @param source_mesh_path 与本批源动画骨架一致的预览网格
         * @return 根骨设置与辅助骨映射的写后核验
         */
        """
        from BBBAssetWritePolicy import require_asset_write
        asset = _asset(asset_path, unreal.IKRetargeter)
        require_asset_write([asset])
        asset.modify()
        controller = unreal.IKRetargeterController.get_controller(asset)
        controller.set_preview_mesh(unreal.RetargetSourceOrTarget.SOURCE, _asset(source_mesh_path, unreal.SkeletalMesh))
        for index in reversed(range(controller.get_num_retarget_ops())):
            op = controller.get_op_controller(index)
            if op.get_class().get_name() in {"IKRetargetRunIKRigController", "IKRetargetPinBoneController"}:
                controller.remove_retarget_op(index)
        roots = []
        for index in range(controller.get_num_retarget_ops()):
            op = controller.get_op_controller(index)
            if op.get_class().get_name() == "IKRetargetRootMotionController":
                op.set_source_root_bone("root")
                op.set_target_root_bone("root")
                settings = op.get_settings()
                settings.root_motion_source = unreal.RootMotionSource.COPY_FROM_SOURCE_ROOT
                settings.root_height_source = unreal.RootMotionHeightSource.COPY_HEIGHT_FROM_SOURCE
                op.set_settings(settings)
                if str(op.get_source_root_bone()).casefold() != "root":
                    raise RuntimeError("源根骨设置未生效")
                roots.append(index)
        if len(roots) != 1:
            raise RuntimeError("独立重定向器需要唯一根运动操作")
        index = controller.add_retarget_op("/Script/IKRig.IKRetargetPinBoneOp")
        if index < 0:
            raise RuntimeError("辅助骨操作创建失败")
        controller.set_op_name("Traversal IK Bones", index)
        pin = controller.get_op_controller(index)
        for source_bone, target_bone in (("root", "ik_foot_root"), ("root", "ik_hand_root"), ("hand_r", "ik_hand_gun"), ("foot_l", "ik_foot_l"), ("foot_r", "ik_foot_r"), ("hand_l", "ik_hand_l"), ("hand_r", "ik_hand_r")):
            pin.set_bone_pair(source_bone, target_bone)
        pairs = {str(key): str(value) for key, value in pin.get_all_bone_pairs().items()}
        if len(pairs) != 7:
            raise RuntimeError("辅助骨映射不完整")
        asset.modify()
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            raise RuntimeError("独立重定向器配置保存失败")
        return json.dumps({"saved": True, "asset": asset_path, "root": "root", "ikPairs": pairs}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def open_new_assets_for_add(asset_paths: list[str]) -> str:
        """
        /**
         * @param asset_paths 已存在但尚未纳入 Perforce 的自有资产包
         * @return 已打开添加的资产 不提交
         */
        """
        if unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("PIE 期间禁止变更资产版本控制")
        if not asset_paths or any(not path.startswith("/Game/_Project/") for path in asset_paths):
            raise RuntimeError("必须明确提供自有资产包")
        control = unreal.SourceControl
        if not control.is_available() or str(control.current_provider()) != "Perforce":
            raise RuntimeError("Perforce 未连接")
        states = list(control.query_file_states(asset_paths, silent=True, use_source_control_state_cache=False))
        if len(states) != len(asset_paths):
            raise RuntimeError("Perforce 状态不完整")
        for path, state in zip(asset_paths, states):
            _asset(path, unreal.Object)
            if state.is_added:
                continue
            if not state.is_valid or not state.can_add or state.is_source_controlled:
                raise RuntimeError("只允许打开添加新资产: " + path)
        for path, state in zip(asset_paths, states):
            if state.is_added:
                continue
            if not control.mark_file_for_add(path, silent=True):
                raise RuntimeError("打开添加失败: " + path)
        return json.dumps({"openedForAdd": list(asset_paths)}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_retargeter(asset_path: str) -> str:
        """
        /**
         * @param asset_path 重定向器路径
         * @return 操作栈设置及版本控制连接状态 不修改资产
         */
        """
        asset = _asset(asset_path, unreal.IKRetargeter)
        controller = unreal.IKRetargeterController.get_controller(asset)
        operations = []
        for index in range(controller.get_num_retarget_ops()):
            op = controller.get_op_controller(index)
            settings = None
            if hasattr(op, "get_settings"):
                settings = str(op.get_settings().export_text())
            operations.append({
                "index": index,
                "name": str(controller.get_op_name(index)),
                "enabled": controller.get_retarget_op_enabled(index),
                "controllerClass": op.get_class().get_path_name(),
                "settings": settings,
            })
        meshes = {}
        for label, side in (("source", unreal.RetargetSourceOrTarget.SOURCE), ("target", unreal.RetargetSourceOrTarget.TARGET)):
            mesh = controller.get_preview_mesh(side)
            rig = controller.get_ik_rig(side)
            meshes[label] = {
                "mesh": mesh.get_path_name() if mesh else None,
                "rig": rig.get_path_name() if rig else None,
            }
        return json.dumps({
            "asset": asset_path,
            "meshes": meshes,
            "operations": operations,
            "sourceControl": {
                "provider": str(unreal.SourceControl.current_provider()),
                "available": unreal.SourceControl.is_available(),
                "lastError": str(unreal.SourceControl.last_error_msg()),
            },
        }, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_animation_poses(asset_paths: list[str], mesh_path: str = "", sample_count: int = 13) -> str:
        """
        /**
         * @param asset_paths 动画序列路径
         * @param mesh_path 明确预览网格 空字符串使用动画骨架
         * @param sample_count 均匀采样数 二至一百零一 零表示所有帧
         * @return 根轨迹与组件空间手脚关系 不保存文件或修改资产
         */
        """
        if (sample_count != 0 and not 2 <= sample_count <= 101) or not asset_paths or len(asset_paths) > 16:
            raise RuntimeError("动画数量或采样数无效")
        mesh = None
        if mesh_path:
            mesh = _asset(mesh_path, unreal.SkeletalMesh)
        options = unreal.AnimPoseEvaluationOptions()
        options.evaluation_type = unreal.AnimDataEvalType.RAW
        options.should_retarget = False
        options.incorporate_root_motion_into_pose = True
        if mesh:
            options.optional_skeletal_mesh = mesh
        reports = []
        pairs = (("foot_l", "ik_foot_l"), ("foot_r", "ik_foot_r"), ("hand_l", "ik_hand_l"), ("hand_r", "ik_hand_r"))
        required = ("root", "pelvis", "ik_foot_root", "ik_hand_root", "ik_hand_gun", "upperarm_l", "lowerarm_l", "upperarm_r", "lowerarm_r")
        required += tuple(name for pair in pairs for name in pair)
        for path in asset_paths:
            animation = _asset(path, unreal.AnimSequence)
            skeleton = animation.get_editor_property("skeleton")
            if mesh and skeleton != mesh.get_editor_property("skeleton"):
                raise RuntimeError("预览骨架不一致: " + path)
            count = animation.data_model_interface.get_number_of_keys()
            track_names = {str(name).casefold() for name in animation.data_model_interface.get_bone_track_names()}
            frames = sorted({round(index * (count - 1) / (sample_count - 1)) for index in range(sample_count)})
            if sample_count == 0:
                frames = list(range(count))
            samples = []
            for frame in frames:
                pose = animation.get_anim_pose_at_frame(frame, options)
                available = {str(name).casefold() for name in pose.get_bone_names()}
                missing = sorted(set(required) - available)
                if missing:
                    raise RuntimeError("姿势缺少骨骼: " + path + " " + str(missing))
                bones = {}
                for name in required:
                    transform = pose.get_bone_pose(name, unreal.AnimPoseSpaces.WORLD)
                    vector = transform.translation
                    quat = transform.rotation
                    values = [vector.x, vector.y, vector.z, quat.x, quat.y, quat.z, quat.w]
                    if not all(math.isfinite(value) for value in values):
                        raise RuntimeError("骨骼数据包含无效数值: " + path + " " + name)
                    bones[name] = values
                errors = {}
                for fk_name, ik_name in pairs:
                    fk = pose.get_bone_pose(fk_name, unreal.AnimPoseSpaces.WORLD)
                    ik = pose.get_bone_pose(ik_name, unreal.AnimPoseSpaces.WORLD)
                    dot = abs(fk.rotation.x * ik.rotation.x + fk.rotation.y * ik.rotation.y + fk.rotation.z * ik.rotation.z + fk.rotation.w * ik.rotation.w)
                    errors[ik_name] = {
                        "positionCm": _distance(fk.translation, ik.translation),
                        "rotationDegrees": math.degrees(2.0 * math.acos(min(1.0, dot))),
                    }
                samples.append({"frame": frame, "bones": bones, "ikErrors": errors})
            reports.append({
                "asset": path,
                "skeleton": skeleton.get_path_name(),
                "keys": count,
                "seconds": animation.get_play_length(),
                "rootMotion": animation.get_editor_property("enable_root_motion"),
                "forceRootLock": animation.get_editor_property("force_root_lock"),
                "missingTracks": sorted(set(required) - track_names),
                "samples": samples,
            })
        return json.dumps({"mesh": mesh_path, "assets": reports}, ensure_ascii=False)


_registration = Registration([BBBRetargetAssetAuditToolset])

if __name__ == "__bbb_editor_script__":
    def register_after_reload(delta_seconds):
        """/** @param delta_seconds 帧间隔 @return 注册只读工具 */"""
        _registration.unregister()
        _registration.register()
        unreal.unregister_slate_post_tick_callback(registration_handle)

    registration_handle = unreal.register_slate_post_tick_callback(register_after_reload)
