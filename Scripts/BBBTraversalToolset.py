import json
import os
import unreal
import toolset_registry
from BBBMcpCapabilities import mcp_tool
from BBBAssetWritePolicy import require_asset_write, require_write_access
from toolset_registry.registration import Registration
from editor_toolset.toolsets.blueprint import BlueprintTools

_fixtures = {}
_fixture_world = None
_samples = []
_sample_handle = None
_sample_until = 0.0
_play_settings_snapshot = None


def _player_id(character):
    """/** @param character 角色副本 @return 复制的玩家标识 */"""
    return json.loads(unreal.ToolsetLibrary.get_object_properties(character.player_state, ["PlayerId"]))["PlayerId"]


def _blueprint(path):
    """/** @param path 动画蓝图路径 @return 已检查的动画蓝图 */"""
    result = unreal.load_asset(path)
    if not isinstance(result, unreal.AnimBlueprint):
        raise RuntimeError("目标必须是动画蓝图 " + path)
    return result


def _ik_sample(animation, layer_class, montage):
    """/** @param animation 主动画实例 @param layer_class 链接层类 @param montage 当前动作 @return 运行时曲线和按现有图公式计算的输入权重 */"""
    result = {"montagePosition": animation.montage_get_position(montage) if montage else None,
              "mainCurves": {name: animation.get_curve_value(name) for name in ("DisableLHandIK", "DisableAimIK")}}
    layer = animation.get_linked_anim_layer_instance_by_class(layer_class)
    if layer is None:
        result["linkedLayer"] = None
        return result
    curves = {name: layer.get_curve_value(name) for name in ("DisableLHandIK", "DisableAimIK")}
    valid = layer.has_left_hand_ik_target()
    source_alpha = animation.get_editor_property("AimIKAlpha")
    locomotion_alpha = layer.get_editor_property("LocomotionAimIKAlpha")
    result.update({"linkedLayer": layer.get_path_name(), "layerCurves": curves, "validLeftTarget": valid,
                   "sourceAimAlpha": source_alpha, "locomotionAimAlpha": locomotion_alpha,
                   "calculatedLeftInputAlpha": 1 - curves["DisableLHandIK"] if valid else 0,
                   "calculatedAimInputAlpha": source_alpha * locomotion_alpha * (1 - curves["DisableAimIK"])})
    return result


@unreal.uclass()
class BBBTraversalToolset(unreal.ToolsetDefinition):
    """/** 检查和配置根运动翻越资产以及临时 PIE 验收场景 */"""

    @mcp_tool
    @staticmethod
    def configure_character_movement_input(main_path: str) -> str:
        """
        /**
         * 将持续移动状态判断与真实急转加速度分离 不重建移动状态机
         * @param main_path\t独占持有的角色主动画蓝图
         * @return 编译保存结果与事实语义
         */
        """
        dirty = {value.get_path_name() for value in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
        main = _blueprint(main_path)
        require_asset_write([main])
        if main.get_outermost().get_path_name() in dirty:
            raise RuntimeError("目标有未保存改动 不覆盖其它会话")
        if not unreal.BBBAnimationGraphEditorLibrary.configure_character_movement_input(main):
            raise RuntimeError("移动输入构图前置条件不满足或构图失败 不保存")
        unreal.BlueprintEditorLibrary.compile_blueprint(main)
        if main.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("移动输入主图编译包含错误或警告 不保存")
        if not unreal.EditorAssetLibrary.save_loaded_asset(main, False):
            raise RuntimeError("移动输入主图保存失败")
        return json.dumps({"saved": main.get_path_name(), "movementFact": "SourceMovementInput",
                           "predicate": "HasMovementInput", "pivotFact": "SourceAcceleration"}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_character_traversal_state(main_path: str, interface_path: str, base_path: str,
                                            child_paths: list[str], montage_paths: list[str]) -> str:
        """
        /**
         * 将攀爬接入既有移动状态机 由 Base 提供线程安全选择与状态内姿势
         * @param main_path\t\t角色主动画蓝图
         * @param interface_path\t已有移动动画层接口
         * @param base_path\t\t基础继承层
         * @param child_paths\t\t直接继承 Base 的具体装备层
         * @param montage_paths\t翻越 低攀爬 高攀爬三个既有蒙太奇
         * @return 编译与保存清单 不生成备份或兼容入口
         */
        """
        if len(montage_paths) != 3 or len(set(montage_paths)) != 3 or not child_paths:
            raise RuntimeError("需要三个明确攀爬蒙太奇和具体继承层")
        dirty = {value.get_path_name() for value in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
        main, interface, base = [_blueprint(path) for path in [main_path, interface_path, base_path]]
        children = [_blueprint(path) for path in child_paths]
        montages = [unreal.load_asset(path) for path in montage_paths]
        if any(not isinstance(value, unreal.AnimMontage) for value in montages):
            raise RuntimeError("攀爬动画必须为实际蒙太奇")
        skeleton = main.get_editor_property("target_skeleton")
        if skeleton is None or base.get_editor_property("target_skeleton") != skeleton:
            raise RuntimeError("主图和基础层必须使用同一个骨架")
        if any(value.get_blueprint_parent_class() != base.generated_class() for value in children):
            raise RuntimeError("具体层必须直接继承 Base")
        if any(value.get_editor_property("skeleton") != skeleton for value in montages):
            raise RuntimeError("攀爬蒙太奇骨架不匹配")
        targets = [interface, main, base] + children + montages + [skeleton]
        require_asset_write(targets)
        if any(value.get_outermost().get_path_name() in dirty for value in targets):
            raise RuntimeError("目标有未保存改动 不覆盖其它会话")
        if any(len(value.get_editor_property("slot_anim_tracks")) != 1 for value in montages):
            raise RuntimeError("攀爬蒙太奇必须只有一个姿势轨道")
        if unreal.BBBBlueprintEditorLibrary.ensure_animation_layer_interface_function(
                interface, "FullBody_TraversalState", "InputPose", "None") != 1:
            raise RuntimeError("攀爬接口必须是一次新增 不重复构图")
        unreal.BlueprintEditorLibrary.compile_blueprint(interface)
        if not unreal.BBBAnimationGraphEditorLibrary.configure_character_traversal_state(main, base):
            raise RuntimeError("攀爬构图失败 不保存")
        for montage in montages:
            montage.modify()
            tracks = list(montage.get_editor_property("slot_anim_tracks"))
            tracks[0].set_editor_property("slot_name", "Traversal")
            montage.set_editor_property("slot_anim_tracks", tracks)
            for field in ["blend_in", "blend_out"]:
                blend = montage.get_editor_property(field)
                blend.set_editor_property("blend_time", 0.0)
                montage.set_editor_property(field, blend)
            montage.set_editor_property("enable_auto_blend_out", False)
        for value in [base] + children:
            unreal.BlueprintEditorLibrary.compile_blueprint(value)
            default = unreal.get_default_object(value.generated_class())
            default.set_editor_property("use_main_instance_montage_evaluation_data", True)
            if value == base:
                for name, montage in zip(["TraversalVault", "TraversalClimbLow", "TraversalClimbHigh"], montages):
                    default.set_editor_property(name, montage)
        for value in [interface, base, main] + children:
            unreal.BlueprintEditorLibrary.compile_blueprint(value)
            if value.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError("动画蓝图存在编译错误或警告 不保存 " + value.get_path_name())
        saved = []
        for value in targets:
            if not unreal.EditorAssetLibrary.save_loaded_asset(value, False):
                raise RuntimeError("攀爬资产保存失败 已保存清单 " + json.dumps(saved))
            saved.append(value.get_path_name())
        return json.dumps({"state": "Traversal", "layer": "FullBody_TraversalState", "saved": saved}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def remove_pie_traversal_obstacle(world_index: int = -1) -> str:
        """
        /**
         * 删除本工具创建的临时障碍 用于验收目标失效后的动作退出
         * @param world_index 明确 PIE 世界索引 负一同时移除所有副本的障碍
         * @return 是否成功删除临时障碍
         */
        """
        worlds = sorted(unreal.EditorLevelLibrary.get_pie_worlds(False), key=lambda item: item.get_path_name())
        if world_index < -1 or world_index >= len(worlds):
            raise RuntimeError("需要有效 PIE 世界索引或负一")
        targets = worlds if world_index == -1 else [worlds[world_index]]
        fixtures = [(world.get_path_name(), _fixtures.get(world, [])) for world in targets]
        fixtures = [(path, fixture) for path, fixture in fixtures if len(fixture) >= 2]
        if not fixtures or unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is None:
            raise RuntimeError("需要本工具创建的 PIE 障碍")
        removed = []
        for path, fixture in fixtures:
            actor = fixture.pop(1)
            actor.destroy_actor()
            if unreal.SystemLibrary.is_valid(actor):
                raise RuntimeError("临时障碍未完成销毁 " + path)
            removed.append(path)
        return json.dumps({"removed": True, "worlds": removed})

    @mcp_tool
    @staticmethod
    def prepare_pie_traversal_fixture(height: float, depth: float, blocked: bool = False,
                                      world_index: int = 0, place_player: bool = True, lateral_offset: float = 0.0) -> str:
        """
        /**
         * 在当前 PIE 创建临时地板和障碍 并安置本地玩家 不保存关卡
         * @param height 障碍高度 零表示无障碍
         * @param depth 障碍厚度
         * @param blocked 是否在上方增加阻挡以验收失败回退
         * @return 玩家和临时碰撞场景位置
         */
        """
        worlds = sorted(unreal.EditorLevelLibrary.get_pie_worlds(False), key=lambda item: item.get_path_name())
        world = worlds[world_index] if 0 <= world_index < len(worlds) else None
        global _fixture_world
        if world is None or not 0 <= height <= 300 or not 1 <= depth <= 600:
            raise RuntimeError("需要 PIE 世界和有效厘米尺寸")
        player = unreal.GameplayStatics.get_player_character(world, 0)
        if player is None:
            raise RuntimeError("PIE 没有本地角色")
        if len(worlds) > 1 and not player.player_state:
            raise RuntimeError("玩家身份尚未复制 请稍后重试")
        if not -500 <= lateral_offset <= 500:
            raise RuntimeError("侧向观察位置必须仍在验收地板上")
        _fixture_world = world
        fixture = _fixtures.setdefault(world, [])
        for actor in fixture:
            if unreal.SystemLibrary.is_valid(actor):
                actor.destroy_actor()
        fixture.clear()
        cube = unreal.load_asset("/Engine/BasicShapes/Cube")
        origin = unreal.Vector(10000, 10000 + lateral_offset, 30000)
        definitions = [(unreal.Vector(10000, 10000, 29995), unreal.Vector(12, 12, 0.1))]
        if height > 0:
            definitions.append((unreal.Vector(10090 + depth / 2, 10000, 30000 + height / 2), unreal.Vector(depth / 100, 3, height / 100)))
        if blocked:
            definitions.append((unreal.Vector(10140, 10000, 30000 + height + 130), unreal.Vector(3, 3, 0.2)))
        for location, scale in definitions:
            transform = unreal.Transform(location=location, rotation=unreal.Rotator(), scale=scale)
            actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(player, unreal.StaticMeshActor, transform)
            if actor is None:
                raise RuntimeError("临时验收几何创建失败")
            mesh = actor.static_mesh_component
            mesh.set_mobility(unreal.ComponentMobility.MOVABLE)
            mesh.set_static_mesh(cube)
            mesh.set_collision_profile_name("BlockAll")
            mesh.set_mobility(unreal.ComponentMobility.STATIC)
            fixture.append(actor)
        capsule = player.capsule_component
        half = capsule.get_scaled_capsule_half_height()
        if not place_player:
            return json.dumps({"world": world.get_path_name(), "geometryReady": True})
        targets = [player]
        if len(worlds) > 1:
            player_id = _player_id(player)
            targets = [character for active_world in worlds
                       for character in unreal.GameplayStatics.get_all_actors_of_class(active_world, unreal.BBBCharacter)
                       if character.player_state and _player_id(character) == player_id]
        for target in targets:
            movement = target.character_movement
            movement.stop_movement_immediately()
            target.set_actor_location(origin + unreal.Vector(0, 0, half + 2.5), False, True)
            target.set_actor_rotation(unreal.Rotator(), True)
            movement.set_movement_mode(unreal.MovementMode.MOVE_FALLING)
        controller = player.get_controller()
        controller.set_control_rotation(unreal.Rotator())
        return json.dumps({"player": player.get_path_name(), "height": height, "depth": depth, "blocked": blocked, "capsuleHalfHeight": half, "capsuleRadius": capsule.get_scaled_capsule_radius()}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def sample_pie_traversal(seconds: float = 5.0, include_ik_curves: bool = False, world_index: int = 0) -> str:
        """
        /**
         * 异步按游戏时间采集动作 根骨 胶囊 移动模式和动画播放 不修改玩法状态
         * @param seconds 采样游戏秒数
         * @return 采样开始结果
         */
        """
        global _sample_handle, _sample_until
        worlds = sorted(unreal.EditorLevelLibrary.get_pie_worlds(False), key=lambda item: item.get_path_name())
        world = worlds[world_index] if 0 <= world_index < len(worlds) else None
        if world is None or not 0.1 <= seconds <= 15:
            raise RuntimeError("需要 PIE 和有效采样时长")
        if _sample_handle is not None:
            raise RuntimeError("上次采样尚未结束")
        _samples.clear()
        start = unreal.GameplayStatics.get_time_seconds(world)
        _sample_until = start + seconds
        layer_classes = []
        if include_ik_curves:
            for name in ("Rifle", "Unarmed"):
                path = "/Game/_Project/Characters/BBBC_UA/AnimationSystem/Layers/ABP_BBB_LocomotionLayer_" + name
                layer_classes.append(_blueprint(path).generated_class())

        def tick(delta):
            global _sample_handle
            if world not in unreal.EditorLevelLibrary.get_pie_worlds(False):
                unreal.unregister_slate_post_tick_callback(_sample_handle)
                _sample_handle = None
                return
            now = unreal.GameplayStatics.get_time_seconds(world)
            if _samples and now - _samples[-1]["absoluteTime"] < 0.02:
                return
            player = unreal.GameplayStatics.get_player_character(world, 0)
            if player is None:
                return
            mesh = player.mesh
            animation = mesh.get_anim_instance()
            center = player.get_actor_location()
            root = mesh.get_socket_location("root")
            current = animation.get_current_active_montage()
            equipment = player.get_active_equipment()
            sample = {"time": now - start, "absoluteTime": now, "location": [center.x, center.y, center.z], "feetZ": center.z - player.capsule_component.get_scaled_capsule_half_height(), "rootZ": root.z, "yaw": player.get_actor_rotation().yaw, "mode": str(player.character_movement.get_editor_property("movement_mode")), "montage": current.get_path_name() if current else None, "traversing": animation.is_traversing(), "equipment": equipment.get_path_name() if equipment else None}
            velocity = player.get_velocity()
            sample["velocity"] = [velocity.x, velocity.y, velocity.z]
            sample["deltaSeconds"] = unreal.GameplayStatics.get_world_delta_seconds(world)
            sample["animationState"] = json.loads(unreal.BBBAnimationGraphEditorLibrary.inspect_character_traversal_playback(mesh))
            sample["aiming"] = animation.is_aiming()
            sample["equipmentUsable"] = player.is_equipment_usable()
            sample["equipmentHidden"] = json.loads(unreal.ToolsetLibrary.get_object_properties(
                equipment, ["bHidden"]))["bHidden"] if equipment else None
            if len(worlds) > 1:
                sample["network"] = json.loads(BBBTraversalToolset.inspect_pie_traversal_network())
            if isinstance(equipment, unreal.BBBRifleEquipment):
                sample["rifle"] = {"ammo": equipment.get_loaded_ammo(), "reloading": equipment.is_reloading()}
            sample["hands"] = {}
            for bone in ("hand_l", "hand_r"):
                position = mesh.get_socket_location(bone)
                sample["hands"][bone] = [position.x, position.y, position.z]
            if include_ik_curves:
                try:
                    for layer_class in layer_classes:
                        if animation.get_linked_anim_layer_instance_by_class(layer_class) is not None:
                            sample["ik"] = _ik_sample(animation, layer_class, current)
                            break
                except Exception as error:
                    sample["ikError"] = str(error)
            _samples.append(sample)
            if now >= _sample_until:
                unreal.unregister_slate_post_tick_callback(_sample_handle)
                _sample_handle = None

        _sample_handle = unreal.register_slate_post_tick_callback(tick)
        return json.dumps({"sampling": True, "seconds": seconds})

    @mcp_tool
    @staticmethod
    def get_pie_traversal_samples(offset: int = 0, count: int = 80) -> str:
        """
        /**
         * @return 本轮基础验收样本与是否仍在运行
         */
        """
        if offset < 0 or not 1 <= count <= 100:
            raise RuntimeError("需要有效分页区间 每次最多一百条样本")
        return json.dumps({"running": _sample_handle is not None, "total": len(_samples),
                           "samples": _samples[offset:offset + count]}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def summarize_pie_traversal_samples() -> str:
        """
        /**
         * 从完整采样中提取动作与操作限制的验收指标 避免大结果被传输截断
         * @return 帧时范围 移动模式交接 以及攀爬期间的装备操作事实
         */
        """
        active = [sample for sample in _samples if sample["traversing"]]
        changes = [sample for index, sample in enumerate(_samples) if index > 0
                   and sample["mode"] != _samples[index - 1]["mode"]]
        return json.dumps({"running": _sample_handle is not None, "total": len(_samples),
                           "first": _samples[0] if _samples else None, "last": _samples[-1] if _samples else None,
                           "firstTraversal": active[0] if active else None, "lastTraversal": active[-1] if active else None,
                           "modeChanges": changes, "ammoDuringTraversal": sorted({sample["rifle"]["ammo"] for sample in active if "rifle" in sample}),
                           "reloadDuringTraversal": any(sample.get("rifle", {}).get("reloading", False) for sample in active),
                           "equipmentDuringTraversal": list({sample["equipment"] for sample in active}),
                           "equipmentHiddenDuringTraversal": all(sample["equipmentHidden"] for sample in active if sample["equipment"]),
                           "equipmentUsableDuringTraversal": any(sample["equipmentUsable"] for sample in active),
                           "minDeltaSeconds": min((sample["deltaSeconds"] for sample in _samples), default=0),
                           "maxDeltaSeconds": max((sample["deltaSeconds"] for sample in _samples), default=0)}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_pie_traversal_contact_points(montage_paths: list[str]) -> str:
        """
        /**
         * 以完整骨骼容器只读采样接触骨骼 不写资产
         * @param montage_paths	自有攀爬蒙太奇
         * @return 原配置与完整骨骼采样得到的接触点
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        player = unreal.GameplayStatics.get_player_character(world, 0) if world else None
        animation = player.mesh.get_anim_instance() if player else None
        if animation is None or not montage_paths or len(montage_paths) > 8:
            raise RuntimeError("需要已初始化的 PIE 角色与一至八条明确蒙太奇")
        reports = []
        for path in montage_paths:
            montage = unreal.load_asset(path)
            if not path.startswith("/Game/_Project/") or not isinstance(montage, unreal.AnimMontage):
                raise RuntimeError("接触目标必须是自有蒙太奇")
            if montage.get_editor_property("skeleton") != player.mesh.skeletal_mesh_asset.get_editor_property("skeleton"):
                raise RuntimeError("接触动画与角色骨架必须一致")
            matches = []
            for event in unreal.AnimationLibrary.get_animation_notify_events(montage):
                notify = event.get_editor_property("notify_state_class")
                if not isinstance(notify, unreal.AnimNotifyState_MotionWarping):
                    continue
                modifier = notify.get_editor_property("root_motion_modifier")
                if str(modifier.get_editor_property("warp_target_name")) == "TraversalContact":
                    matches.append((event, modifier))
            if len(matches) != 1:
                raise RuntimeError("接触窗口必须唯一 " + path)
            event, modifier = matches[0]
            end = unreal.AnimationLibrary.get_anim_notify_event_trigger_time(event) + unreal.AnimationLibrary.get_anim_notify_event_duration(event)
            bone = str(modifier.get_editor_property("warp_point_anim_bone_name"))
            if bone != "hand_l" or not player.mesh.does_socket_exist(bone):
                raise RuntimeError("需要明确存在的左手接触骨骼")
            pose = unreal.MotionWarpingUtilities.extract_bone_transform_from_animation_at_time(animation, montage, end, False, bone, False)
            reports.append({"montage": path, "time": end, "bone": bone,
                "oldProvider": str(modifier.get_editor_property("warp_point_anim_provider")),
                "point": [pose.translation.x, pose.translation.y, pose.translation.z]})
        return json.dumps({"contacts": reports}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_traversal_contact_points(points_json: str, dry_run: bool = True) -> str:
        """
        /**
         * 在停止 PIE 后配置已核对的动画空间接触点 不修改窗口与源动画
         * @param points_json	只读采样返回的 contacts 数组
         * @param dry_run	只核对签出和接触窗口 不写资产
         * @return 预检或保存的明确接触点
         */
        """
        points = json.loads(points_json)
        if not isinstance(points, list) or not 1 <= len(points) <= 8:
            raise RuntimeError("需要一至八个已核对的接触点")
        require_asset_write([item["montage"] for item in points])
        prepared = []
        for item in points:
            path = item["montage"]
            montage = unreal.load_asset(path)
            if not path.startswith("/Game/_Project/") or not isinstance(montage, unreal.AnimMontage):
                raise RuntimeError("接触目标必须是自有蒙太奇")
            if len(item["point"]) != 3 or not all(abs(value) < 10000 for value in item["point"]):
                raise RuntimeError("接触点必须是有限动画空间厘米坐标")
            matches = []
            for event in unreal.AnimationLibrary.get_animation_notify_events(montage):
                notify = event.get_editor_property("notify_state_class")
                if not isinstance(notify, unreal.AnimNotifyState_MotionWarping):
                    continue
                modifier = notify.get_editor_property("root_motion_modifier")
                end = unreal.AnimationLibrary.get_anim_notify_event_trigger_time(event) + unreal.AnimationLibrary.get_anim_notify_event_duration(event)
                if str(modifier.get_editor_property("warp_target_name")) == "TraversalContact" and abs(end - item["time"]) < 0.0001:
                    matches.append(modifier)
            if len(matches) != 1:
                raise RuntimeError("接触窗口已变动 请重新采样 " + path)
            prepared.append((montage, matches[0], unreal.Transform(location=unreal.Vector(*item["point"]))))
        if not dry_run:
            for montage, modifier, point in prepared:
                modifier.set_editor_properties({"warp_point_anim_provider": unreal.WarpPointAnimProvider.STATIC,
                    "warp_point_anim_transform": point})
                if not unreal.EditorAssetLibrary.save_loaded_asset(montage, False):
                    raise RuntimeError("接触点保存失败 " + montage.get_path_name())
        return json.dumps({"dryRun": dry_run, "contacts": points}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def capture_pie_traversal_side_view(file_name: str, world_index: int = 0) -> str:
        """
        /**
         * 使用临时侧视相机检查全身接触姿势 不移动玩家或修改资产
         * @param file_name	本任务截图的 PNG 文件名
         * @param world_index	同进程 PIE 世界索引
         * @return 截图绝对路径与角色位置
         */
        """
        if not file_name.endswith(".png") or not file_name.replace(".png", "").replace("_", "").isalnum():
            raise RuntimeError("截图文件名只允许字母数字与下划线")
        worlds = sorted(unreal.EditorLevelLibrary.get_pie_worlds(False), key=lambda item: item.get_path_name())
        world = worlds[world_index] if 0 <= world_index < len(worlds) else None
        player = unreal.GameplayStatics.get_player_character(world, 0) if world else None
        if player is None:
            raise RuntimeError("需要有效的 PIE 本地角色")
        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "temp", "TraversalSideView"))
        path = os.path.join(directory, file_name)
        if os.path.exists(path):
            raise RuntimeError("截图已存在 不覆盖已有验收文件")
        center = player.get_actor_location()
        location = center + unreal.Vector(-140, -430, 45)
        rotation = unreal.MathLibrary.find_look_at_rotation(location, center + unreal.Vector(30, 0, 0))
        actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(
            world, unreal.SceneCapture2D, unreal.Transform(location=location, rotation=rotation))
        if actor is None:
            raise RuntimeError("无法创建临时侧视相机")
        try:
            target = unreal.RenderingLibrary.create_render_target2d(world, 1024, 768, unreal.TextureRenderTargetFormat.RTF_RGBA8)
            component = actor.capture_component2d
            component.set_editor_properties({"texture_target": target,
                "capture_source": unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR, "fov_angle": 55.0})
            component.set_editor_property("post_process_settings", unreal.PostProcessSettings(
                override_auto_exposure_bias=True, auto_exposure_bias=3.0))
            component.capture_scene()
            os.makedirs(directory, exist_ok=True)
            unreal.RenderingLibrary.export_render_target(world, target, directory, file_name)
            if not os.path.isfile(path):
                raise RuntimeError("截图失败 需要启用渲染的宿主")
            return json.dumps({"imagePath": path, "playerLocation": [center.x, center.y, center.z]}, ensure_ascii=False)
        finally:
            actor.destroy_actor()

    @mcp_tool
    @staticmethod
    def inspect_traversal_montage_windows(montage_paths: list[str]) -> str:
        """
        /**
         * 核对提前交接所依赖的校正窗口和动画混合参数 不写入资产
         * @param montage_paths	攀爬蒙太奇路径
         * @return 实际播放长度 校正窗口与混合参数
         */
        """
        if not montage_paths or len(montage_paths) > 16:
            raise RuntimeError("需要一至十六条蒙太奇")
        results = []
        for path in montage_paths:
            montage = unreal.load_asset(path)
            if not isinstance(montage, unreal.AnimMontage):
                raise RuntimeError("资产不是蒙太奇 " + path)
            windows = []
            for event in unreal.AnimationLibrary.get_animation_notify_events(montage):
                notify = event.get_editor_property("notify_state_class")
                if not isinstance(notify, unreal.AnimNotifyState_MotionWarping):
                    continue
                modifier = notify.get_editor_property("root_motion_modifier")
                start = unreal.AnimationLibrary.get_anim_notify_event_trigger_time(event)
                duration = unreal.AnimationLibrary.get_anim_notify_event_duration(event)
                windows.append({"start": start, "end": start + duration,
                        "target": str(modifier.get_editor_property("warp_target_name")),
                        "warpPointProvider": str(modifier.get_editor_property("warp_point_anim_provider")),
                        "warpPointBone": str(modifier.get_editor_property("warp_point_anim_bone_name")),
                        "warpToFeet": modifier.get_editor_property("warp_to_feet_location")})
            results.append({"path": montage.get_path_name(), "length": montage.get_play_length(), "windows": windows,
                            "slots": [str(track.get_editor_property("slot_name")) for track in montage.get_editor_property("slot_anim_tracks")],
                            "rateScale": montage.get_editor_property("rate_scale"),
                            "autoBlendOut": montage.get_editor_property("enable_auto_blend_out"),
                            "blendIn": montage.get_editor_property("blend_in").get_editor_property("blend_time"),
                            "blendOut": montage.get_editor_property("blend_out").get_editor_property("blend_time")})
        return json.dumps({"montages": results}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_pie_traversal_network(clients: int = 3, restore: bool = False) -> str:
        """
        /**
         * 临时配置同一宿主中的主机和客机 验收后须先恢复再停止 PIE
         * @param clients	含主机的玩家数量
         * @param restore	恢复调用前的设置
         * @return 生效设置 不主动保存用户配置
         */
        """
        global _play_settings_snapshot
        settings_class = unreal.load_class(None, "/Script/UnrealEd.LevelEditorPlaySettings")
        settings = unreal.get_default_object(settings_class)
        names = ("PlayNetMode", "PlayNumberOfClients", "RunUnderOneProcess")
        if restore:
            if _play_settings_snapshot is None:
                raise RuntimeError("没有待恢复的网络验收设置")
            if not unreal.ToolsetLibrary.set_object_properties(settings, _play_settings_snapshot):
                raise RuntimeError("网络验收设置恢复失败")
            _play_settings_snapshot = None
            return json.dumps({"restored": True})
        if unreal.EditorLevelLibrary.get_pie_worlds(False) or not 2 <= clients <= 4:
            raise RuntimeError("请停止 PIE 并选择二至四名玩家")
        if _play_settings_snapshot is not None:
            raise RuntimeError("网络验收设置尚未恢复")
        previous = unreal.ToolsetLibrary.get_object_properties(settings, list(names))
        try:
            values = json.dumps({"PlayNetMode": "PIE_ListenServer", "PlayNumberOfClients": clients, "RunUnderOneProcess": True})
            if not unreal.ToolsetLibrary.set_object_properties(settings, values):
                raise RuntimeError("网络验收设置应用失败")
            _play_settings_snapshot = previous
        except Exception:
            unreal.ToolsetLibrary.set_object_properties(settings, previous)
            raise
        return unreal.ToolsetLibrary.get_object_properties(settings, list(names))

    @mcp_tool
    @staticmethod
    def inspect_pie_traversal_network() -> str:
        """
        /**
         * 同时只读查看所有 PIE 世界中的角色副本 不推演远端玩法
         * @return 角色网络身份 位置 移动模式与动画事实
         */
        """
        worlds = []
        for world in unreal.EditorLevelLibrary.get_pie_worlds(False):
            actors = []
            for character in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.BBBCharacter):
                center = character.get_actor_location()
                animation = character.mesh.get_anim_instance()
                montage = animation.get_current_active_montage() if animation else None
                equipment = character.get_active_equipment()
                actors.append({"path": character.get_path_name(), "local": character.is_locally_controlled(),
                               "playerId": _player_id(character) if character.player_state else None,
                               "role": str(character.get_local_role()), "location": [center.x, center.y, center.z],
                               "mode": str(character.character_movement.get_editor_property("movement_mode")),
                               "traversing": animation.is_traversing() if animation else None,
                               "montage": montage.get_path_name() if montage else None,
                               "position": animation.montage_get_position(montage) if montage else None,
                               "animationState": json.loads(unreal.BBBAnimationGraphEditorLibrary.inspect_character_traversal_playback(character.mesh)),
                               "equipmentUsable": character.is_equipment_usable(),
                               "velocity": [character.get_velocity().x, character.get_velocity().y, character.get_velocity().z],
                               "facts": json.loads(unreal.ToolsetLibrary.get_object_properties(animation,
                                   ["SourceVelocity", "SourceAcceleration", "SourceMovementInput", "SourceLifePhase"])) if animation else None,
                               "equipmentHidden": json.loads(unreal.ToolsetLibrary.get_object_properties(
                                   equipment, ["bHidden"]))["bHidden"] if equipment else None})
            worlds.append({"world": world.get_path_name(), "time": unreal.GameplayStatics.get_time_seconds(world), "characters": actors})
        return json.dumps({"worlds": worlds}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_traversal_editing_schema(base_path: str, main_path: str) -> str:
        """
        /**
         * 只读返回实际编辑器的翻越图表节点类型和动画编辑接口
         * @param base_path 基础链接动画蓝图
         * @param main_path 主动画蓝图
         * @return 图表路径 节点类型和工具接口
         */
        """
        base = _blueprint(base_path)
        main = _blueprint(main_path)
        event = unreal.BlueprintEditorLibrary.find_event_graph(base)
        report = {"eventGraph": event.get_path_name(), "nodeTypes": {}, "graphs": []}
        with toolset_registry.tool_raising_exceptions():
            for query in ("SubmitInput", "OwningActor", "CastToBBBCharacter", "FullBodyMontageLocalControlPacket", "SwitchonEBBBTraversalAction", "BlendListByBool", "IsTraversing"):
                report["nodeTypes"][query] = list(BlueprintTools.find_node_types(event, query))
            for blueprint in (base, main):
                for graph in BlueprintTools.list_graphs(blueprint):
                    if graph.get_name() in ("FullBody_SkeletalControls", "ShouldEnableControlRig", "EventGraph"):
                        report["graphs"].append(json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph)))
        report["motionWarpingProperties"] = unreal.RootMotionModifier_SkewWarp.__doc__
        report["notifyMethods"] = [name for name in dir(unreal.AnimationLibrary) if "notify" in name]
        report["baseVariables"] = list(unreal.BlueprintEditorLibrary.list_member_variable_names(base, False))
        return json.dumps(report, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_traversal_montages(sequence_paths: list[str], destination_paths: list[str], windows_json: str) -> str:
        """
        /**
         * 从根运动序列创建或配置全身翻越蒙太奇及官方 Skew Warp 窗口
         * @param sequence_paths 已检查的根运动序列
         * @param destination_paths 自有目录下的目标蒙太奇
         * @param windows_json 每条动画的窗口数组 含 start end target 及可选 bone
         * @return 保存的蒙太奇与窗口配置
         */
        """
        windows = json.loads(windows_json)
        if len(sequence_paths) != len(destination_paths) or len(windows) != len(sequence_paths):
            raise RuntimeError("源动画 目标和窗口数量必须一致")
        assets = [unreal.load_asset(path) for path in sequence_paths]
        for animation in assets:
            if not isinstance(animation, unreal.AnimSequence) or not animation.get_editor_property("enable_root_motion"):
                raise RuntimeError("源动画必须是有效根运动序列")
        if len(set(destination_paths)) != len(destination_paths):
            raise RuntimeError("目标蒙太奇路径必须唯一")
        for sequence, definitions in zip(assets, windows):
            if not isinstance(definitions, list) or not definitions:
                raise RuntimeError("每条动画必须配置 Warp 窗口数组")
            for window in definitions:
                if not isinstance(window, dict) or not window.get("target"):
                    raise RuntimeError("Warp 窗口必须明确目标名称")
                start = float(window["start"])
                end = float(window["end"])
                if not 0 <= start < end <= sequence.get_play_length():
                    raise RuntimeError("Warp 窗口超出动画时间")
        if any(not path.startswith("/Game/_Project/") for path in destination_paths):
            raise RuntimeError("蒙太奇目标必须位于自有资产目录")
        existing = [path for path in destination_paths if os.path.isfile(os.path.join(unreal.Paths.project_content_dir(), path[len("/Game/"):] + ".uasset"))]
        new = [path for path in destination_paths if path not in existing]
        require_asset_write(existing, new)
        report = []
        for sequence, path, definitions in zip(assets, destination_paths, windows):
            montage = unreal.load_asset(path)
            if montage is None:
                factory = unreal.AnimMontageFactory()
                factory.set_editor_property("source_animation", sequence)
                folder, name = path.rsplit("/", 1)
                montage = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.AnimMontage, factory)
            if not isinstance(montage, unreal.AnimMontage):
                raise RuntimeError("创建蒙太奇失败 " + path)
            tracks = list(montage.get_editor_property("slot_anim_tracks"))
            if len(tracks) != 1:
                raise RuntimeError("翻越蒙太奇必须只有一个 Traversal 轨道")
            tracks[0].set_editor_property("slot_name", unreal.Name("Traversal"))
            montage.set_editor_property("slot_anim_tracks", tracks)
            for field in ["blend_in", "blend_out"]:
                blend = montage.get_editor_property(field)
                blend.set_editor_property("blend_time", 0.0)
                montage.set_editor_property(field, blend)
            montage.set_editor_property("enable_auto_blend_out", False)
            library = unreal.AnimationLibrary
            track = "TraversalWarp"
            if library.is_valid_anim_notify_track_name(montage, track):
                library.remove_animation_notify_events_by_track(montage, track)
            if not library.is_valid_anim_notify_track_name(montage, track):
                library.add_animation_notify_track(montage, track)
            for window in definitions:
                start = float(window["start"])
                end = float(window["end"])
                notify = library.add_animation_notify_state_event(montage, track, start, end - start, unreal.AnimNotifyState_MotionWarping)
                modifier = unreal.new_object(unreal.RootMotionModifier_SkewWarp, outer=notify)
                modifier.set_editor_properties({"warp_target_name": unreal.Name(window["target"]), "warp_translation": True, "ignore_z_axis": False, "warp_rotation": bool(window.get("rotation", True)), "warp_to_feet_location": True, "subtract_remaining_root_motion": bool(window.get("subtract_remaining", False))})
                if window.get("bone"):
                    modifier.set_editor_properties({"warp_point_anim_provider": unreal.WarpPointAnimProvider.BONE, "warp_point_anim_bone_name": unreal.Name(window["bone"])})
                notify.set_editor_property("root_motion_modifier", modifier)
            if not unreal.EditorAssetLibrary.save_loaded_asset(montage, False):
                raise RuntimeError("蒙太奇保存失败 " + path)
            if path in new and not unreal.SourceControl.mark_file_for_add(path, silent=True):
                unreal.log_warning("新蒙太奇已保存但尚未纳入版本控制 " + path)
            report.append({"montage": path, "sequence": sequence.get_path_name(), "windows": definitions})
        return json.dumps(report, ensure_ascii=False)


_registration = Registration([BBBTraversalToolset])

if __name__ == "__bbb_editor_script__":
    def register_after_reload(delta_seconds):
        _registration.unregister()
        _registration.register()
        unreal.unregister_slate_post_tick_callback(registration_handle)

    registration_handle = unreal.register_slate_post_tick_callback(register_after_reload)
