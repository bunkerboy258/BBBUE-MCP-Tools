import json


import os


import unreal




from BBBMcpCapabilities import mcp_tool


from BBBAssetWritePolicy import require_asset_write


from toolset_registry.registration import Registration




MCP_INPUTS = {
    'configure_traversal_contact_points': {
        'points_json': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {'montage': {'type': 'string'}, 'point': {'$ref': '#/$defs/Vector3'}, 'time': {'type': 'number'}},
                'required': ['montage', 'point', 'time'],
                'additionalProperties': False,
            },
            'minItems': 1,
            'maxItems': 8,
        },
    },
    'configure_traversal_montages': {
        'windows_json': {
            'type': 'array',
            'items': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'target': {'type': 'string'},
                        'start': {'type': 'number'},
                        'end': {'type': 'number'},
                        'rotation': {'type': 'boolean'},
                        'bone': {'type': 'string'},
                    },
                    'required': ['target', 'start', 'end'],
                    'additionalProperties': False,
                },
                'minItems': 1,
            },
            'minItems': 0,
        },
    },
}


@unreal.uclass()
class BBBTraversalToolset(unreal.ToolsetDefinition):
    """/** 检查和配置根运动翻越资产以及临时 PIE 验收场景 */"""


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
