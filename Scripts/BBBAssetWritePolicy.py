import unreal


def _package_path(value):
    """
    /**
     * @param value	资产包路径 对象路径或对象
     * @return Game 下规范包路径
     */
    """
    if not isinstance(value, str):
        if value is None:
            raise RuntimeError("写入目标不能为空")
        value = value.get_outermost().get_path_name()
    package = value.split(".", 1)[0]
    if not package.startswith("/Game/") or any(part in {"", ".", ".."} for part in package[1:].split("/")):
        raise RuntimeError("写入目标必须为 Game 下的明确资产包: " + value)
    if any(character in package for character in "\\: ' \t\r\n"):
        raise RuntimeError("资产包路径无效: " + value)
    return package


def require_asset_write(assets, destinations=()):
    """
    /**
     * 批量刷新 Perforce 状态 不办理签出 添加或保存 不缓存资产状态
     * @param assets	已存在的源资产与受影响资产
     * @param destinations	尚未创建的新目标包
     * @return 已核实的源包状态字典
     */
    """
    sources = sorted({_package_path(value) for value in assets})
    targets = sorted({_package_path(value) for value in destinations})
    if not sources and not targets:
        raise RuntimeError("写入预检必须提供目标资产")
    if set(sources) & set(targets):
        raise RuntimeError("现有资产与新目标不能重叠")
    commandlet = any(argument.lower().startswith("-run=") for argument in unreal.SystemLibrary.get_command_line().split())
    if not commandlet and unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
        raise RuntimeError("PIE 期间禁止写入项目资产")
    control = unreal.SourceControl
    if not control.is_enabled() or not control.is_available() or control.current_provider() != "Perforce":
        raise RuntimeError("写入前必须启用并连接 Perforce")
    paths = sources + targets
    states = list(control.query_file_states(paths, silent=True, use_source_control_state_cache=False))
    if len(states) != len(paths):
        raise RuntimeError("无法获得完整 Perforce 状态 不执行写入")
    report = dict(zip(paths, states))
    for path, state in report.items():
        if not state.is_valid or state.is_unknown or state.is_checked_out_other or state.is_conflicted or state.is_deleted:
            raise RuntimeError("Perforce 状态无效或存在冲突: " + path)
        if path in targets:
            if state.is_source_controlled or state.is_added or not state.can_add:
                raise RuntimeError("新目标存在仓库冲突或不在可添加映射内: " + path)
            continue
        if not state.can_edit or not (state.is_checked_out or state.is_added):
            raise RuntimeError("目标必须已独占签出或已打开添加且可编辑: " + path)
        if state.is_source_controlled and not state.is_added and not state.is_current:
            raise RuntimeError("目标不是仓库最新版本 请由用户处理: " + path)
    return report


def require_write_access(obj):
    """
    /**
     * 资产和子对象检查所属包 演员保留官方关卡实例编辑规则
     * @param obj	待修改对象
     * @return 检查通过时无返回值
     */
    """
    if isinstance(obj, (unreal.Actor, unreal.ActorComponent)):
        from toolset_registry.helpers import require_editable

        require_editable(obj)
        return
    require_asset_write([obj])
