# Copyright (c) 2025 GenOrca. All Rights Reserved.

"""
IK Rig / IK Retargeter authoring and batch animation retargeting.

All actions require the IKRig plugin (a built-in engine plugin, usually enabled
by default). The dependency is soft: each action guards at call time and returns
an actionable error when the plugin is disabled.
"""
import unreal
import json
import traceback


def _plugin_missing():
    if not hasattr(unreal, "IKRigController"):
        return json.dumps({"success": False,
                           "message": "Requires the IKRig plugin. Enable it in Edit > Plugins and restart."})
    return None


def _load_typed(asset_path, cls, label):
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        raise FileNotFoundError(f"{label} not found at path: {asset_path}")
    if not isinstance(asset, cls):
        raise TypeError(f"Asset at {asset_path} is not a {label}, but {type(asset).__name__}")
    return asset


def _split_asset_path(asset_path: str):
    asset_path = asset_path.rstrip("/")
    idx = asset_path.rfind("/")
    return asset_path[idx + 1:], asset_path[:idx]


def ue_create_ik_rig(asset_path: str = None, skeletal_mesh_path: str = None,
                     retarget_root: str = None) -> str:
    """Creates an IK Rig for a skeletal mesh, optionally setting the retarget root bone (requires the IKRig plugin)."""
    guard = _plugin_missing()
    if guard:
        return guard
    if asset_path is None or skeletal_mesh_path is None:
        return json.dumps({"success": False, "message": "Required parameters: asset_path, skeletal_mesh_path."})
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            return json.dumps({"success": False, "message": f"Asset already exists: {asset_path}"})
        mesh = _load_typed(skeletal_mesh_path, unreal.SkeletalMesh, "SkeletalMesh")
        name, package = _split_asset_path(asset_path)
        rig = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            name, package, unreal.IKRigDefinition, unreal.IKRigDefinitionFactory())
        if not rig:
            return json.dumps({"success": False, "message": f"Failed to create IK Rig at {asset_path}."})
        rc = unreal.IKRigController.get_controller(rig)
        if not rc.set_skeletal_mesh(mesh):
            return json.dumps({"success": False, "message": "set_skeletal_mesh failed (incompatible mesh?)."})
        root_set = None
        if retarget_root:
            root_set = bool(rc.set_retarget_root(retarget_root))
        unreal.EditorAssetLibrary.save_loaded_asset(rig)
        return json.dumps({"success": True, "asset_path": asset_path,
                           "skeletal_mesh": skeletal_mesh_path, "retarget_root_set": root_set})
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


def ue_add_retarget_chain(ik_rig_path: str = None, chain_name: str = None,
                          start_bone: str = None, end_bone: str = None, goal_name: str = "") -> str:
    """Adds a retarget chain (e.g. 'Spine': spine_01..spine_03) to an IK Rig (requires the IKRig plugin)."""
    guard = _plugin_missing()
    if guard:
        return guard
    if ik_rig_path is None or chain_name is None or start_bone is None or end_bone is None:
        return json.dumps({"success": False, "message": "Required: ik_rig_path, chain_name, start_bone, end_bone."})
    try:
        rig = _load_typed(ik_rig_path, unreal.IKRigDefinition, "IKRigDefinition")
        rc = unreal.IKRigController.get_controller(rig)
        created = rc.add_retarget_chain(chain_name, start_bone, end_bone, goal_name or "")
        if not str(created):
            return json.dumps({"success": False, "message": "add_retarget_chain returned an empty name (check bone names)."})
        unreal.EditorAssetLibrary.save_loaded_asset(rig)
        return json.dumps({"success": True, "ik_rig_path": ik_rig_path, "chain_name": str(created),
                           "chain_count": len(rc.get_retarget_chains())})
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


def ue_set_retarget_chain_bones(ik_rig_path: str = None, chain_name: str = None,
                                start_bone: str = None, end_bone: str = None) -> str:
    """设置 IK 链起止骨骼并保存资产

    @param ik_rig_path		IK Rig 资产路径
    @param chain_name			IK 链名称
    @param start_bone			起始骨骼名称
    @param end_bone			结束骨骼名称
    @return					JSON 操作结果
    """
    guard = _plugin_missing()
    if guard:
        return guard
    if ik_rig_path is None or chain_name is None or start_bone is None or end_bone is None:
        return json.dumps({"success": False, "message": "需要 ik_rig_path chain_name start_bone 和 end_bone"}, ensure_ascii=False)

    rig = None
    rc = None
    old_start = None
    old_end = None
    try:
        rig = _load_typed(ik_rig_path, unreal.IKRigDefinition, "IKRigDefinition")
        rc = unreal.IKRigController.get_controller(rig)
        chain_names = {str(chain.chain_name) for chain in rc.get_retarget_chains()}
        if chain_name not in chain_names:
            message = "IK 链不存在 {} {}".format(ik_rig_path, chain_name)
            unreal.log_error("[BBBExternal] " + message)
            return json.dumps({"success": False, "message": message}, ensure_ascii=False)

        old_start = str(rc.get_retarget_chain_start_bone(chain_name))
        old_end = str(rc.get_retarget_chain_end_bone(chain_name))
        rc.set_retarget_chain_start_bone(chain_name, start_bone)
        rc.set_retarget_chain_end_bone(chain_name, end_bone)
        actual_start = str(rc.get_retarget_chain_start_bone(chain_name))
        actual_end = str(rc.get_retarget_chain_end_bone(chain_name))
        if actual_start != start_bone or actual_end != end_bone:
            rc.set_retarget_chain_start_bone(chain_name, old_start)
            rc.set_retarget_chain_end_bone(chain_name, old_end)
            message = "IK 链起止骨骼回读不匹配 {} {}".format(actual_start, actual_end)
            unreal.log_error("[BBBExternal] " + message)
            return json.dumps({"success": False, "message": message}, ensure_ascii=False)

        if not unreal.EditorAssetLibrary.save_loaded_asset(rig):
            rc.set_retarget_chain_start_bone(chain_name, old_start)
            rc.set_retarget_chain_end_bone(chain_name, old_end)
            message = "IK Rig 保存失败 {}".format(ik_rig_path)
            unreal.log_error("[BBBExternal] " + message)
            return json.dumps({"success": False, "message": message}, ensure_ascii=False)

        return json.dumps({
            "success": True,
            "ik_rig_path": ik_rig_path,
            "chain_name": chain_name,
            "start_bone": actual_start,
            "end_bone": actual_end,
        }, ensure_ascii=False)
    except Exception as e:
        if rc is not None and old_start is not None and old_end is not None:
            try:
                rc.set_retarget_chain_start_bone(chain_name, old_start)
                rc.set_retarget_chain_end_bone(chain_name, old_end)
            except Exception as rollback_error:
                unreal.log_error("[BBBExternal] IK 链回滚失败 {}".format(rollback_error))

        unreal.log_error("[BBBExternal] IK 链设置失败 {}".format(e))
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()}, ensure_ascii=False)


def ue_get_ik_rig_info(ik_rig_path: str = None) -> str:
    """Returns the skeletal mesh, retarget root, and chains of an IK Rig (requires the IKRig plugin)."""
    guard = _plugin_missing()
    if guard:
        return guard
    if ik_rig_path is None:
        return json.dumps({"success": False, "message": "Required parameter 'ik_rig_path' is missing."})
    try:
        rig = _load_typed(ik_rig_path, unreal.IKRigDefinition, "IKRigDefinition")
        rc = unreal.IKRigController.get_controller(rig)
        mesh = rc.get_skeletal_mesh()
        chains = []
        for ch in rc.get_retarget_chains():
            cname = str(getattr(ch, "chain_name", ""))
            chains.append({
                "name": cname,
                "start_bone": str(rc.get_retarget_chain_start_bone(cname)),
                "end_bone": str(rc.get_retarget_chain_end_bone(cname)),
            })
        return json.dumps({
            "success": True,
            "ik_rig_path": ik_rig_path,
            "skeletal_mesh": mesh.get_path_name() if mesh else None,
            "retarget_root": str(rc.get_retarget_root()),
            "chains": chains,
        })
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


def ue_create_retargeter(asset_path: str = None, source_ik_rig_path: str = None,
                         target_ik_rig_path: str = None, auto_map: bool = True) -> str:
    """Creates an IK Retargeter wired to source/target IK Rigs, with optional fuzzy chain auto-mapping (requires the IKRig plugin)."""
    guard = _plugin_missing()
    if guard:
        return guard
    if asset_path is None or source_ik_rig_path is None or target_ik_rig_path is None:
        return json.dumps({"success": False, "message": "Required: asset_path, source_ik_rig_path, target_ik_rig_path."})
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            return json.dumps({"success": False, "message": f"Asset already exists: {asset_path}"})
        src = _load_typed(source_ik_rig_path, unreal.IKRigDefinition, "IKRigDefinition")
        tgt = _load_typed(target_ik_rig_path, unreal.IKRigDefinition, "IKRigDefinition")
        name, package = _split_asset_path(asset_path)
        rtg = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            name, package, unreal.IKRetargeter, unreal.IKRetargetFactory())
        if not rtg:
            return json.dumps({"success": False, "message": f"Failed to create IK Retargeter at {asset_path}."})
        tc = unreal.IKRetargeterController.get_controller(rtg)
        tc.set_ik_rig(unreal.RetargetSourceOrTarget.SOURCE, src)
        tc.set_ik_rig(unreal.RetargetSourceOrTarget.TARGET, tgt)
        tc.add_default_ops()
        tc.assign_ik_rig_to_all_ops(unreal.RetargetSourceOrTarget.SOURCE, src)
        tc.assign_ik_rig_to_all_ops(unreal.RetargetSourceOrTarget.TARGET, tgt)
        if tc.get_num_retarget_ops() == 0:
            raise RuntimeError("重定向器没有求解操作，禁止保存无效资产")
        if auto_map:
            tc.auto_map_chains(unreal.AutoMapChainType.FUZZY, True)
        unreal.EditorAssetLibrary.save_loaded_asset(rtg)
        return json.dumps({"success": True, "asset_path": asset_path,
                           "source_ik_rig": source_ik_rig_path, "target_ik_rig": target_ik_rig_path,
                           "auto_mapped": bool(auto_map)})
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


def ue_set_retargeter_source_ik_rig(retargeter_path: str = None, source_ik_rig_path: str = None,
                                   chain_mappings: dict = None) -> str:
    """设置重定向器源 IK Rig 并保留其它有效链映射

    @param retargeter_path		重定向器资产路径
    @param source_ik_rig_path	源 IK Rig 资产路径
    @param chain_mappings		目标链名称到源链名称的映射
    @return					JSON 操作结果
    """
    guard = _plugin_missing()
    if guard:
        return guard
    if retargeter_path is None or source_ik_rig_path is None:
        return json.dumps({"success": False, "message": "需要 retargeter_path 和 source_ik_rig_path"}, ensure_ascii=False)
    if chain_mappings is None:
        chain_mappings = {}
    if not isinstance(chain_mappings, dict):
        return json.dumps({"success": False, "message": "chain_mappings 必须是对象"}, ensure_ascii=False)

    retargeter = None
    controller = None
    previous_source_rig = None
    source_rig_change_started = False
    try:
        retargeter = _load_typed(retargeter_path, unreal.IKRetargeter, "IKRetargeter")
        source_rig = _load_typed(source_ik_rig_path, unreal.IKRigDefinition, "IKRigDefinition")
        controller = unreal.IKRetargeterController.get_controller(retargeter)
        source_side = unreal.RetargetSourceOrTarget.SOURCE
        target_side = unreal.RetargetSourceOrTarget.TARGET
        previous_source_rig = controller.get_ik_rig(source_side)
        target_rig = controller.get_ik_rig(target_side)
        if target_rig is None:
            message = "重定向器没有目标 IK Rig {}".format(retargeter_path)
            unreal.log_error("[BBBExternal] " + message)
            return json.dumps({"success": False, "message": message}, ensure_ascii=False)

        source_controller = unreal.IKRigController.get_controller(source_rig)
        target_controller = unreal.IKRigController.get_controller(target_rig)
        source_chain_names = {str(chain.chain_name) for chain in source_controller.get_retarget_chains()}
        target_chain_names = {str(chain.chain_name) for chain in target_controller.get_retarget_chains()}

        explicit_mappings = {}
        for target_chain, source_chain in chain_mappings.items():
            target_name = str(target_chain)
            source_name = str(source_chain)
            if target_name not in target_chain_names:
                message = "目标 IK 链不存在 {}".format(target_name)
                unreal.log_error("[BBBExternal] " + message)
                return json.dumps({"success": False, "message": message}, ensure_ascii=False)
            if source_name not in source_chain_names:
                message = "源 IK 链不存在 {}".format(source_name)
                unreal.log_error("[BBBExternal] " + message)
                return json.dumps({"success": False, "message": message}, ensure_ascii=False)
            explicit_mappings[target_name] = source_name

        if previous_source_rig is None:
            message = "重定向器当前没有源 IK Rig {}".format(retargeter_path)
            unreal.log_error("[BBBExternal] " + message)
            return json.dumps({"success": False, "message": message}, ensure_ascii=False)

        source_rig_change_started = True

        # 控制器重建链映射时会保留仍有效的既有映射
        controller.set_ik_rig(source_side, source_rig)
        current_source_rig = controller.get_ik_rig(source_side)
        if current_source_rig is None or current_source_rig.get_path_name() != source_rig.get_path_name():
            raise RuntimeError("源 IK Rig 设置后回读不匹配")

        for target_name, source_name in explicit_mappings.items():
            if not controller.set_source_chain(source_name, target_name):
                raise RuntimeError("链映射设置失败 {} {}".format(target_name, source_name))
            actual_source_name = str(controller.get_source_chain(target_name))
            if actual_source_name != source_name:
                raise RuntimeError("链映射回读不匹配 {} {}".format(target_name, actual_source_name))

        for target_name, source_name in explicit_mappings.items():
            if str(controller.get_source_chain(target_name)) != source_name:
                raise RuntimeError("指定链映射未生效 {} {}".format(target_name, source_name))

        if not unreal.EditorAssetLibrary.save_loaded_asset(retargeter):
            raise RuntimeError("重定向器保存失败 {}".format(retargeter_path))

        final_mappings = {
            target_name: str(controller.get_source_chain(target_name))
            for target_name in sorted(target_chain_names)
        }
        return json.dumps({
            "success": True,
            "retargeter_path": retargeter_path,
            "source_ik_rig": current_source_rig.get_path_name(),
            "target_ik_rig": target_rig.get_path_name(),
            "chain_mappings": final_mappings,
        }, ensure_ascii=False)
    except Exception as e:
        if controller is not None and previous_source_rig is not None and source_rig_change_started:
            try:
                controller.set_ik_rig(unreal.RetargetSourceOrTarget.SOURCE, previous_source_rig)
                unreal.EditorAssetLibrary.save_loaded_asset(retargeter)
            except Exception as rollback_error:
                unreal.log_error("[BBBExternal] 重定向器回滚失败 {}".format(rollback_error))

        unreal.log_error("[BBBExternal] 重定向器源 IK Rig 设置失败 {}".format(e))
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()}, ensure_ascii=False)


def ue_auto_map_chains(retargeter_path: str = None, mode: str = "FUZZY", force: bool = True) -> str:
    """Re-runs chain mapping on an IK Retargeter. mode: FUZZY, EXACT, or CLEAR (requires the IKRig plugin)."""
    guard = _plugin_missing()
    if guard:
        return guard
    if retargeter_path is None:
        return json.dumps({"success": False, "message": "Required parameter 'retargeter_path' is missing."})
    key = (mode or "FUZZY").upper()
    map_type = getattr(unreal.AutoMapChainType, key, None)
    if map_type is None:
        return json.dumps({"success": False, "message": f"Unknown mode '{mode}'.", "valid_modes": ["FUZZY", "EXACT", "CLEAR"]})
    try:
        rtg = _load_typed(retargeter_path, unreal.IKRetargeter, "IKRetargeter")
        tc = unreal.IKRetargeterController.get_controller(rtg)
        tc.auto_map_chains(map_type, bool(force))
        unreal.EditorAssetLibrary.save_loaded_asset(rtg)
        return json.dumps({"success": True, "retargeter_path": retargeter_path, "mode": key})
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


def ue_batch_retarget(retargeter_path: str = None, anim_paths: list = None,
                      source_mesh_path: str = None, target_mesh_path: str = None,
                      search: str = "", replace: str = "", prefix: str = "",
                      suffix: str = "_Retargeted", target_path: str = None,
                      overwrite_existing: bool = False) -> str:
    """Duplicates and retargets animations through an IK Retargeter; returns the new asset paths (requires the IKRig plugin)."""
    guard = _plugin_missing()
    if guard:
        return guard
    if retargeter_path is None or not anim_paths or source_mesh_path is None or target_mesh_path is None:
        return json.dumps({"success": False,
                           "message": "Required: retargeter_path, anim_paths (non-empty), source_mesh_path, target_mesh_path."})
    try:
        if not target_path or not target_path.startswith("/Game/"):
            raise ValueError("必须指定 Game 内的目标目录，禁止导出到内容根目录")
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("其他会话正在运行 PIE，禁止重定向写入")
        rtg = _load_typed(retargeter_path, unreal.IKRetargeter, "IKRetargeter")
        controller = unreal.IKRetargeterController.get_controller(rtg)
        if controller.get_num_retarget_ops() == 0:
            raise RuntimeError("重定向器求解操作栈为空，禁止生成静止动画")
        src_mesh = _load_typed(source_mesh_path, unreal.SkeletalMesh, "SkeletalMesh")
        tgt_mesh = _load_typed(target_mesh_path, unreal.SkeletalMesh, "SkeletalMesh")
        asset_data = []
        missing = []
        for p in anim_paths:
            ad = unreal.EditorAssetLibrary.find_asset_data(p)
            (asset_data.append(ad) if ad and ad.is_valid() else missing.append(p))
        if missing:
            return json.dumps({"success": False, "message": f"Animations not found: {missing}"})
        for source_path in anim_paths:
            name = source_path.rsplit("/", 1)[-1]
            target_name = prefix + name.replace(search, replace) + suffix
            destination = target_path.rstrip("/") + "/" + target_name
            if not unreal.EditorAssetLibrary.does_asset_exist(destination):
                continue
            if not overwrite_existing:
                raise RuntimeError("目标已经存在，拒绝生成编号副本: " + destination)
            state = unreal.SourceControl.query_file_state(destination)
            if not state.is_valid or not state.can_edit or state.is_checked_out_other:
                raise RuntimeError("覆盖前必须独占签出目标: " + destination)
            if not state.is_added and not state.is_checked_out:
                raise RuntimeError("覆盖目标没有签出: " + destination)
        inputs = unreal.IKRetargetBatchOperationInputs()
        inputs.assets_to_retarget = asset_data
        inputs.source_mesh = src_mesh
        inputs.target_mesh = tgt_mesh
        inputs.ik_retarget_asset = rtg
        inputs.target_path = target_path
        inputs.search = search
        inputs.replace = replace
        inputs.prefix = prefix
        inputs.suffix = suffix
        inputs.include_referenced_assets = False
        inputs.overwrite_existing_files = overwrite_existing
        inputs.retain_additive_flags = True
        out = unreal.IKRetargetBatchOperation.run_batch_retarget(inputs)
        paths = [str(a.package_name) for a in (out or [])]
        if len(paths) != len(anim_paths):
            raise RuntimeError("重定向结果数量与请求不一致")
        for path in paths:
            if not path.startswith(target_path.rstrip("/") + "/"):
                raise RuntimeError("重定向导出路径越界: " + path)
            if not unreal.EditorAssetLibrary.save_asset(path):
                raise RuntimeError("重定向动画保存失败: " + path)
        return json.dumps({"success": True, "retargeter_path": retargeter_path,
                           "count": len(paths), "retargeted_assets": paths})
    except Exception as e:
        unreal.log_error("[BBBExternal] 重定向导出失败 " + str(e))
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


def ue_initialize_retarget_ops(retargeter_path: str, dry_run: bool = True) -> str:
    """
    /**
     * 检查求解操作栈，仅允许初始化空栈，不修改已有求解配置
     * @param retargeter_path	目标重定向器路径
     * @param dry_run		仅检查，不写入资产
     * @return 操作栈与链映射检查结果
     */
    """
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError("其他会话正在运行 PIE，请等待空闲窗口")
    asset = _load_typed(retargeter_path, unreal.IKRetargeter, "IKRetargeter")
    controller = unreal.IKRetargeterController.get_controller(asset)
    before = controller.get_num_retarget_ops()
    if not dry_run:
        state = unreal.SourceControl.query_file_state(retargeter_path)
        if not state.is_valid or not state.can_edit or state.is_checked_out_other:
            raise RuntimeError("初始化前必须独占签出目标重定向器")
        if not state.is_added and not state.is_checked_out:
            raise RuntimeError("重定向器没有签出")
        if before != 0:
            raise RuntimeError("已有求解操作栈，拒绝重复初始化")
        source = controller.get_ik_rig(unreal.RetargetSourceOrTarget.SOURCE)
        target = controller.get_ik_rig(unreal.RetargetSourceOrTarget.TARGET)
        if source is None or target is None:
            raise RuntimeError("源或目标 IK Rig 缺失")
        controller.add_default_ops()
        controller.assign_ik_rig_to_all_ops(unreal.RetargetSourceOrTarget.SOURCE, source)
        controller.assign_ik_rig_to_all_ops(unreal.RetargetSourceOrTarget.TARGET, target)
        controller.auto_map_chains(unreal.AutoMapChainType.EXACT, True)
        if controller.get_num_retarget_ops() == 0:
            raise RuntimeError("初始化没有产生求解操作")
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset):
            raise RuntimeError("重定向器保存失败")
    count = controller.get_num_retarget_ops()
    operations = [str(controller.get_op_name(index)) for index in range(count)]
    target = controller.get_ik_rig(unreal.RetargetSourceOrTarget.TARGET)
    chains = unreal.IKRigController.get_controller(target).get_retarget_chains()
    mappings = {str(chain.chain_name): str(controller.get_source_chain(chain.chain_name)) for chain in chains}
    return json.dumps({"success": True, "before": before, "count": count, "operations": operations, "mappings": mappings, "dryRun": dry_run})
