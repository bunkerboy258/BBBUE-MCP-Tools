import json

import unreal
from BBBAssetWritePolicy import require_asset_write


def sample_hand_handling_surface(mesh_path, main_path, base_path, interface_path, animation_path, grip_path,
                                 time_seconds, right_hand_offset, equipment_enabled, left_grip_alpha,
                                 right_grip_alpha, selected_bones, minimum_selected_weight, material_indices):
    """/** @param mesh_path 网格 @param main_path 主图类型 @param base_path 正式层 @param interface_path 正式接口 @param animation_path 源动作 @param grip_path 静态握姿 @param time_seconds 动作秒数 @param right_hand_offset 俯仰偏航滚转度数 @param equipment_enabled 装备事实 @param left_grip_alpha 左指权重 @param right_grip_alpha 右指权重 @param selected_bones 表面骨骼 @param minimum_selected_weight 最低权重 @param material_indices 材质筛选 @return 实际正式层姿势和原生线性蒙皮表面 */"""
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError("离线动作表面采样禁止 PIE")
    if len(right_hand_offset) != 3:
        raise RuntimeError("右腕快照必须是俯仰 偏航 滚转三个度数")
    mesh, main, base, interface, animation, grip = [unreal.load_asset(path) for path in
        [mesh_path, main_path, base_path, interface_path, animation_path, grip_path]]
    dirty_before = {package.get_path_name() for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    offset = unreal.Rotator(pitch=right_hand_offset[0], yaw=right_hand_offset[1], roll=right_hand_offset[2])
    report = json.loads(unreal.BBBHandPoseLayerEditorLibrary.sample_hand_handling_surface(
        mesh, main, base, interface, animation, grip, time_seconds,
        offset,
        equipment_enabled, left_grip_alpha, right_grip_alpha, selected_bones, minimum_selected_weight, material_indices))
    dirty_after = {package.get_path_name() for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    if dirty_after != dirty_before:
        raise RuntimeError("正式层动作表面采样意外改变项目脏包")
    if report.get("status") != "ok":
        raise RuntimeError("正式层动作表面采样失败: " + json.dumps(report, ensure_ascii=False))
    report["projectDirtyPackagesUnchanged"] = True
    report["readOnly"] = True
    report["animation"] = animation.get_path_name()
    report["gripAnimation"] = grip.get_path_name()
    report["inputSnapshot"] = {"rightHandOffsetPitchYawRoll": list(right_hand_offset),
                               "rightHandOffsetQuaternion": list(offset.quaternion().to_tuple()),
                               "animation": animation.get_path_name(), "grip": grip.get_path_name(),
                               "main": main.get_path_name(), "base": base.get_path_name(),
                               "interface": interface.get_path_name(), "mesh": mesh.get_path_name(),
                               "timeSeconds": time_seconds,
                               "equipmentEnabled": equipment_enabled,
                               "leftGripAlpha": left_grip_alpha, "rightGripAlpha": right_grip_alpha,
                               "animationTimeSeconds": time_seconds}
    return report


def configure_right_hand_grip_rotation(base_path, child_layer_paths, main_path, graph_name, before_node_guid):
    """/** @param base_path 基础层 @param child_layer_paths 明确继承层 @param main_path 主图 @param graph_name 骨骼控制图 @param before_node_guid 已有瞄准节点 @return 编译保存与原生连线证据 */"""
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError("PIE 期间禁止修改共享右腕校准")
    paths = [base_path] + list(child_layer_paths) + [main_path]
    if not child_layer_paths or len(paths) != len(set(paths)) or any(not path.startswith("/Game/") for path in paths):
        raise RuntimeError("必须明确唯一基础层 继承层及主图包路径")
    targets = [unreal.load_asset(path) for path in paths]
    if any(not isinstance(target, unreal.AnimBlueprint) for target in targets):
        raise RuntimeError("右腕校准目标必须是动画蓝图")
    base = targets[0]
    parents = [base.generated_class()]
    for child in targets[1:-1]:
        if child.get_blueprint_parent_class() not in parents:
            raise RuntimeError("必须按父层在前列出指定基础层的继承层")
        parents.append(child.generated_class())
    dirty = {package.get_path_name() for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    if any(target.get_outermost().get_path_name() in dirty for target in targets):
        raise RuntimeError("共享蓝图仍有未保存修改 请先交接")
    require_asset_write(targets)
    report = json.loads(unreal.BBBHandPoseLayerEditorLibrary.configure_right_hand_grip_rotation(base, graph_name, before_node_guid))
    if report.get("status") != "ok" or not report.get("compiled"):
        raise RuntimeError("右腕校准配置失败 未保存: " + json.dumps(report, ensure_ascii=False))
    for target in targets:
        unreal.BlueprintEditorLibrary.compile_blueprint(target)
        if target.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("共享右腕校准蓝图编译失败 未保存: " + target.get_path_name())
    saved = []
    for target in targets:
        if not unreal.EditorAssetLibrary.save_loaded_asset(target, False):
            raise RuntimeError("右腕校准保存失败 已保存: " + json.dumps(saved))
        saved.append(target.get_path_name())
    report["saved"] = saved
    return report


def configure_hand_pose_layer(main_path, base_path, interface_path, child_layer_paths,
                              old_layer_name, layer_name, before_layer_name, grip_getter_name,
                              left_disable_curve, right_disable_curve,
                              left_finger_roots, right_finger_roots):
    """
    /**
     * 将手部数据与权重封装到基础层 主图仅保留姿势调用 全部编译通过才保存明确目标
     * @param main_path\t\t主动画蓝图包路径
     * @param base_path\t\t共享基础动画层包路径
     * @param interface_path\t\t已有动画层接口包路径
     * @param child_layer_paths\t\t完整的明确继承层 按父层在前排列
     * @param old_layer_name\t\t本次替换的已有层函数名
     * @param layer_name\t\t正式双手层函数名
     * @param before_layer_name\t\t双手层的直接下游骨骼控制层
     * @param grip_getter_name\t\t主实例的线程安全握姿序列查询函数
     * @param left_disable_curve\t\t左手握姿抑制曲线名
     * @param right_disable_curve\t右手握姿抑制曲线名
     * @param left_finger_roots\t\t左手指分支起点 排除腕骨
     * @param right_finger_roots\t右手指分支起点 排除腕骨
     * @return 原生连线回读 编译和保存清单 运行时验收仍需执行
     */
    """
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError("PIE 期间禁止修改共享握姿层")

    paths = [main_path, base_path, interface_path] + list(child_layer_paths)
    if any(not isinstance(path, str) or not path.startswith("/Game/") for path in paths):
        raise RuntimeError("必须明确全部项目蓝图包路径")
    if len(set(paths)) != len(paths) or not child_layer_paths:
        raise RuntimeError("目标必须唯一 且必须明确共享基础层的继承层")

    names = [old_layer_name, layer_name, before_layer_name, grip_getter_name,
             left_disable_curve, right_disable_curve]
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise RuntimeError("层 查询函数或抑制曲线名称为空")
    if left_disable_curve == right_disable_curve:
        raise RuntimeError("左右抑制曲线必须分别唯一")
    if not left_finger_roots or not right_finger_roots:
        raise RuntimeError("必须明确左右手指分支")

    main, base, interface = [unreal.load_asset(path) for path in paths[:3]]
    children = [unreal.load_asset(path) for path in child_layer_paths]
    targets = [interface, base] + children + [main]
    if any(not isinstance(value, unreal.AnimBlueprint) for value in targets):
        raise RuntimeError("目标包含非动画蓝图资产")

    parents = [base.generated_class()]
    for child in children:
        if child.get_blueprint_parent_class() not in parents:
            raise RuntimeError("继承层必须来自指定基础层且按父层在前排列")
        parents.append(child.generated_class())

    dirty = {package.get_path_name() for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    if any(value.get_outermost().get_path_name() in dirty for value in targets):
        raise RuntimeError("目标包含未保存修改 请先完成并行资产交接")

    require_asset_write(targets)
    report = json.loads(unreal.BBBHandPoseLayerEditorLibrary.configure_hand_pose_layer(
        main, base, interface, old_layer_name, layer_name, before_layer_name,
        grip_getter_name, left_disable_curve, right_disable_curve,
        left_finger_roots, right_finger_roots))
    if report.get("status") != "ok" or not report.get("compiled"):
        raise RuntimeError("双手握姿层配置未通过 未保存: " + json.dumps(report, ensure_ascii=False))

    for target in targets:
        unreal.BlueprintEditorLibrary.compile_blueprint(target)
        if target.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("双手握姿层或继承层编译未通过 未保存: " + target.get_path_name())

    saved = []
    for target in targets:
        if not unreal.EditorAssetLibrary.save_loaded_asset(target, False):
            raise RuntimeError("握姿层保存失败 已保存清单: " + json.dumps(saved, ensure_ascii=False))
        saved.append(target.get_path_name())

    report.update({"saved": saved, "runtimeAcceptance": "pending",
                   "staticSequenceFrame": 0, "independentHandWeights": True})
    return report


def audit_hand_pose_layer(mesh_path, base_animation_path, grip_animation_path,
                         base_path, interface_path, layer_name, alphas):
    """
    /**
     * 在瞬态预览世界真实执行正式基础层 保留逐骨验收证据
     * @param mesh_path\t\t实际角色骨架网格
     * @param base_animation_path\t基准绝对动画序列
     * @param grip_animation_path\t双手静态绝对姿势序列
     * @param base_path\t\t正式基础动画层
     * @param interface_path\t\t正式动画层接口
     * @param layer_name\t\t双手握姿层函数
     * @param alphas\t\t零到一的有限常规取样权重
     * @return 正式层真实求值误差和逐骨变换 不保存 不代表主图玩法验收
     */
    """
    import math

    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError("离线握姿验收不得在 PIE 期间执行")
    if not alphas or len(alphas) > 9 or any(not math.isfinite(value) or not 0 <= value <= 1 for value in alphas):
        raise RuntimeError("取样权重必须为一到九个零到一之间的有限值")
    if not isinstance(layer_name, str) or not layer_name.strip():
        raise RuntimeError("必须明确正式握姿层名称")

    mesh = unreal.load_asset(mesh_path)
    base_animation = unreal.load_asset(base_animation_path)
    grip_animation = unreal.load_asset(grip_animation_path)
    base = unreal.load_asset(base_path)
    interface = unreal.load_asset(interface_path)
    if not isinstance(mesh, unreal.SkeletalMesh) or not isinstance(base_animation, unreal.AnimSequence) or not isinstance(grip_animation, unreal.AnimSequence):
        raise RuntimeError("角色网格或绝对动画序列类型无效")
    if not isinstance(base, unreal.AnimBlueprint) or not isinstance(interface, unreal.AnimBlueprint):
        raise RuntimeError("正式基础层或接口类型无效")

    dirty_before = {package.get_path_name() for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    report = json.loads(unreal.BBBHandPoseLayerEditorLibrary.sample_hand_pose_layer(
        mesh, base_animation, grip_animation, base, interface, layer_name, alphas))
    dirty_after = {package.get_path_name() for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    if dirty_after != dirty_before:
        raise RuntimeError("离线握姿验收意外改变项目脏包状态: " + json.dumps(sorted(dirty_after - dirty_before), ensure_ascii=False))
    if report.get("status") != "ok":
        raise RuntimeError("正式握姿层求值失败: " + json.dumps(report, ensure_ascii=False))

    report["projectDirtyPackagesUnchanged"] = True
    return report
