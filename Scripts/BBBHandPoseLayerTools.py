import json

import unreal
from BBBAssetWritePolicy import require_asset_write


def configure_hand_pose_layer(main_path, base_path, interface_path, child_layer_paths,
                              old_layer_name, layer_name, before_layer_name, grip_getter_name,
                              left_disable_curve, right_disable_curve,
                              left_finger_roots, right_finger_roots):
    """
    /**
     * 定向替换已有单手层 全部编译通过后才保存明确的目标
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
