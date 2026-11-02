import json
import math
import re

import unreal


def _load(path, asset_type):
    """/** @param path 资产路径 @param asset_type 要求类型 @return 已核验资产 */"""
    asset = unreal.load_asset(path)
    if not isinstance(asset, asset_type):
        raise RuntimeError("资产类型不符: " + path)
    return asset


def _create(path, asset_type):
    """/** @param path 新资产路径 @param asset_type 数据资产类型 @return 新资产 */"""
    from BBBAssetWritePolicy import require_asset_write
    if not path.startswith("/Game/_Project/") or "." in path or path.endswith("/"):
        raise RuntimeError("要求明确的自有资产包路径")
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        raise RuntimeError("目标已存在: " + path)
    require_asset_write([], [path])
    folder, name = path.rsplit("/", 1)
    factory = unreal.DataAssetFactory()
    factory.set_editor_property("data_asset_class", asset_type)
    asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, asset_type, factory)
    if not asset:
        raise RuntimeError("数据资产创建失败: " + path)
    return asset


def _schema_report(schema):
    """/** @param schema 搜索格式 @return 保存后可核验的格式 */"""
    channels = []
    for channel in schema.get_editor_property("channels"):
        item = {"class": channel.get_class().get_path_name()}
        if not isinstance(channel, unreal.PoseSearchFeatureChannel_Group):
            item["weight"] = channel.get_editor_property("weight")
        if isinstance(channel, unreal.PoseSearchFeatureChannel_Trajectory):
            item["samples"] = [{"offset": sample.get_editor_property("offset"), "flags": sample.get_editor_property("flags")} for sample in channel.get_editor_property("samples")]
        if isinstance(channel, unreal.PoseSearchFeatureChannel_Pose):
            item["bones"] = [str(bone.get_editor_property("reference").get_editor_property("bone_name")) for bone in channel.get_editor_property("sampled_bones")]
        channels.append(item)
    return {"path": schema.get_path_name(), "sample_rate": schema.get_editor_property("sample_rate"), "skeletons": [entry.get_editor_property("skeleton").get_path_name() for entry in schema.get_editor_property("skeletons")], "channels": channels}


def create_schema(asset_path: str, skeleton_path: str, bone_names: list[str], trajectory_offsets: list[float], sample_rate: int = 30) -> str:
    """
    /**
     * @param asset_path 新格式路径
     * @param skeleton_path 目标骨架路径
     * @param bone_names 姿态通道采样骨
     * @param trajectory_offsets 轨迹采样秒数
     * @param sample_rate 索引每秒采样数
     * @return 保存后的格式与通道
     */
    """
    skeleton = _load(skeleton_path, unreal.Skeleton)
    if not bone_names or len(set(bone_names)) != len(bone_names):
        raise RuntimeError("采样骨不能为空或重复")
    if any(not math.isfinite(value) for value in trajectory_offsets):
        raise RuntimeError("轨迹采样时间无效")
    if sorted(set(trajectory_offsets)) != trajectory_offsets or sample_rate < 1 or sample_rate > 240:
        raise RuntimeError("轨迹时间必须递增且唯一 采样率须在 1 到 240")
    schema = _create(asset_path, unreal.PoseSearchSchema)
    role = unreal.PoseSearchRoledSkeleton()
    role.set_editor_property("skeleton", skeleton)
    schema.set_editor_property("skeletons", [role])
    schema.set_editor_property("sample_rate", sample_rate)
    trajectory = unreal.new_object(unreal.PoseSearchFeatureChannel_Trajectory, outer=schema)
    samples = []
    for offset in trajectory_offsets:
        sample = unreal.PoseSearchTrajectorySample()
        sample.set_editor_property("offset", offset)
        sample.set_editor_property("flags", 11)
        samples.append(sample)
    trajectory.set_editor_property("samples", samples)
    pose = unreal.new_object(unreal.PoseSearchFeatureChannel_Pose, outer=schema)
    bones = []
    for name in bone_names:
        bone = unreal.PoseSearchBone()
        reference = unreal.BoneReference()
        reference.set_editor_property("bone_name", name)
        bone.set_editor_property("reference", reference)
        bone.set_editor_property("flags", 3)
        bones.append(bone)
    pose.set_editor_property("sampled_bones", bones)
    schema.set_editor_property("channels", [trajectory, pose] if trajectory_offsets else [pose])
    if not unreal.EditorAssetLibrary.save_loaded_asset(schema, only_if_is_dirty=False):
        raise RuntimeError("格式保存失败: " + asset_path)
    return json.dumps(_schema_report(schema), ensure_ascii=False)

def create_database(asset_path: str, schema_path: str, animation_paths: list[str], replace_existing: bool = False) -> str:
    """
    /**
     * @param asset_path 新数据库路径
     * @param schema_path 已有格式路径
     * @param animation_paths 明确动画序列列表
     * @return 保存后的数据库条目 不代表索引构建完成
     */
    """
    schema = _load(schema_path, unreal.PoseSearchSchema)
    skeletons = [entry.get_editor_property("skeleton") for entry in schema.get_editor_property("skeletons")]
    if len(skeletons) != 1 or not animation_paths or len(set(animation_paths)) != len(animation_paths):
        raise RuntimeError("要求单骨架及非空唯一动画列表")
    animations = []
    for path in animation_paths:
        animation = _load(path, unreal.AnimSequence)
        if animation.get_editor_property("skeleton") != skeletons[0]:
            raise RuntimeError("动画骨架与格式不同: " + path)
        animations.append(animation)
    library = unreal.BBBMotionMatchingEditorLibrary
    if not asset_path.startswith("/Game/_Project/"):
        raise RuntimeError("数据库必须属于自有资产")
    database = None
    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        if not replace_existing:
            raise RuntimeError("目标已存在 未明确允许重建: " + asset_path)
        from BBBAssetWritePolicy import require_asset_write
        database = _load(asset_path, unreal.PoseSearchDatabase)
        require_asset_write([database], [])
    if database is None:
        database = _create(asset_path, unreal.PoseSearchDatabase)
    database.set_editor_property("schema", schema)
    if not library.configure_database(database, animations):
        raise RuntimeError("原生数据库配置失败: " + asset_path)
    report = json.loads(library.inspect_database(database, True))
    if report.get("indexStatus") != "ready":
        raise RuntimeError("数据库索引未就绪: " + json.dumps(report, ensure_ascii=False))
    if not unreal.EditorAssetLibrary.save_loaded_asset(database, only_if_is_dirty=False):
        raise RuntimeError("数据库保存失败: " + asset_path)
    return inspect_database(asset_path)

def inspect_database(asset_path: str) -> str:
    """
    /**
     * @param asset_path 数据库路径
     * @return 格式和完整条目 资产保存不等于索引就绪
     */
    """
    database = _load(asset_path, unreal.PoseSearchDatabase)
    report = json.loads(unreal.BBBMotionMatchingEditorLibrary.inspect_database(database, True))
    report["schemaDetails"] = _schema_report(database.get_editor_property("schema"))
    return json.dumps(report, ensure_ascii=False)


def configure_bone_channels(asset_path, group_name, bone_names, origin_bone, position_weight, velocity_weight):
    """
    /**
     * @param asset_path       自有搜索格式
     * @param group_name       独立通道组名称
     * @param bone_names       需要实际姿态连续性的骨骼 空数组移除此组
     * @param origin_bone      相对参考骨骼
     * @param position_weight  位置权重
     * @param velocity_weight  速度权重
     * @return                保存回读后的通道配置
     */
    """
    try:
        from BBBAssetWritePolicy import require_asset_write
        schema = _load(asset_path, unreal.PoseSearchSchema)
        if not asset_path.startswith('/Game/_Project/') or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', group_name):
            raise RuntimeError('要求自有格式和明确的英文通道组名称')
        if len(bone_names) > 8 or len(set(bone_names)) != len(bone_names):
            raise RuntimeError('骨骼名称必须唯一且不超过八个')
        if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name) for name in [origin_bone, *bone_names]):
            raise RuntimeError('骨骼名称无效')
        if any(not math.isfinite(weight) or not 0 < weight <= 1 for weight in [position_weight, velocity_weight]):
            raise RuntimeError('连续性权重必须大于零且不超过一')
        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError('修改搜索通道前必须结束 PIE')
        require_asset_write([schema], [])
        channels = list(schema.get_editor_property('channels'))
        groups = [channel for channel in channels if channel.get_name() == group_name]
        if len(groups) > 1 or any(not isinstance(group, unreal.PoseSearchFeatureChannel_Group) for group in groups):
            raise RuntimeError('指定名称不是唯一的通道组')
        if not bone_names:
            schema.set_editor_property('channels', [channel for channel in channels if channel not in groups])
            if not unreal.EditorAssetLibrary.save_loaded_asset(schema, only_if_is_dirty=False):
                raise RuntimeError('移除通道组后保存失败')
            return json.dumps({'schema': schema.get_path_name(), 'group': group_name, 'channels': [], 'saved': True})

        group = groups[0] if groups else unreal.new_object(unreal.PoseSearchFeatureChannel_Group, outer=schema, name=group_name)
        existing = {channel.get_name(): channel for channel in group.get_editor_property('sub_channels')}
        configured = []
        for bone_name in bone_names:
            for kind, channel_type, weight in [('Position', unreal.PoseSearchFeatureChannel_Position, position_weight),
                                              ('Velocity', unreal.PoseSearchFeatureChannel_Velocity, velocity_weight)]:
                name = kind + '_' + bone_name
                channel = existing.get(name)
                if channel is not None and not isinstance(channel, channel_type):
                    raise RuntimeError('已有通道类型不匹配: ' + name)
                if channel is None:
                    channel = unreal.new_object(channel_type, outer=group, name=name)
                bone = unreal.BoneReference()
                bone.set_editor_property('bone_name', bone_name)
                origin = unreal.BoneReference()
                origin.set_editor_property('bone_name', origin_bone)
                channel.set_editor_property('bone', bone)
                channel.set_editor_property('origin_bone', origin)
                channel.set_editor_property('weight', weight)
                channel.set_editor_property('input_query_pose', unreal.InputQueryPose.USE_CHARACTER_POSE)
                channel.set_editor_property('normalization_group', group_name + '_' + kind)
                configured.append(channel)
        group.set_editor_property('sub_channels', configured)
        if not groups:
            channels.append(group)
        schema.set_editor_property('channels', channels)
        if not unreal.EditorAssetLibrary.save_loaded_asset(schema, only_if_is_dirty=False):
            raise RuntimeError('搜索通道保存失败')
        rows = []
        for channel in group.get_editor_property('sub_channels'):
            rows.append({'path': channel.get_path_name(), 'class': channel.get_class().get_path_name(),
                         'bone': str(channel.get_editor_property('bone').get_editor_property('bone_name')),
                         'originBone': str(channel.get_editor_property('origin_bone').get_editor_property('bone_name')),
                         'weight': float(channel.get_editor_property('weight')),
                         'inputQueryPose': str(channel.get_editor_property('input_query_pose')),
                         'normalizationGroup': str(channel.get_editor_property('normalization_group'))})
        if len(rows) != len(bone_names) * 2:
            raise RuntimeError('保存后的通道数量不匹配')
        for index, row in enumerate(rows):
            expected_weight = position_weight if index % 2 == 0 else velocity_weight
            if row['bone'] != bone_names[index // 2] or row['originBone'] != origin_bone or not math.isclose(row['weight'], expected_weight, rel_tol=1e-6):
                raise RuntimeError('保存后的骨骼或权重不匹配')
            if configured[index].get_editor_property('input_query_pose') != unreal.InputQueryPose.USE_CHARACTER_POSE:
                raise RuntimeError('保存后的查询未使用实际角色姿态')
        return json.dumps({'schema': schema.get_path_name(), 'group': group_name, 'channels': rows, 'saved': True})
    except Exception:
        import traceback
        unreal.log_error(traceback.format_exc())
        raise
