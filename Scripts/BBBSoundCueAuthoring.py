import math

import unreal

from BBBAssetWritePolicy import require_asset_write


_DISTANCE_FIELDS = (
    "fade_in_distance_start",
    "fade_in_distance_end",
    "fade_out_distance_start",
    "fade_out_distance_end",
)


def configure_sound_cue(asset_path, wave_paths, fade_distances, attenuation_path):
    """
    /**
     * 使用原生声音图表创建或更新单波形和距离淡化 Cue
     * @param asset_path	目标声音提示包
     * @param wave_paths	按输入顺序排列的 SoundWave 路径
     * @param fade_distances	逐输入的淡入和淡出厘米区间
     * @param attenuation_path	SoundAttenuation 资产路径
     * @return 已保存的图表节点 波形 淡化区间及衰减引用
     */
    """
    if not asset_path.startswith("/Game/") or "." in asset_path:
        raise RuntimeError("目标需为 Game 下的正式包路径")
    count = len(wave_paths)
    if not 1 <= count <= 8 or len(set(wave_paths)) != count:
        raise RuntimeError("需要一至八个不重复的波形")
    if count == 1 and fade_distances:
        raise RuntimeError("单波形 Cue 的淡化区间应为空")
    if count > 1 and len(fade_distances) != count * 4:
        raise RuntimeError("每层需要淡入起止和淡出起止四个数值")

    fades = [list(fade_distances[index:index + 4]) for index in range(0, len(fade_distances), 4)]
    for row in fades:
        if not all(math.isfinite(value) and value >= 0 for value in row) or sorted(row) != row:
            raise RuntimeError("淡化距离必须有限 非负且按区间递增")
    if fades:
        if fades[0][:2] != [0, 0]:
            raise RuntimeError("首层淡入起止必须为零")
        for near, far in zip(fades, fades[1:]):
            if near[2:] != far[:2] or far[0] >= far[1]:
                raise RuntimeError("相邻输入必须以同一非零区间交叉淡化")

    library = unreal.EditorAssetLibrary
    waves = [library.load_asset(path) for path in wave_paths]
    if not all(isinstance(wave, unreal.SoundWave) for wave in waves):
        raise RuntimeError("波形必须全部能加载为 SoundWave")
    attenuation = library.load_asset(attenuation_path)
    if not isinstance(attenuation, unreal.SoundAttenuation):
        raise RuntimeError("衰减路径必须加载为 SoundAttenuation")

    editor = unreal.get_editor_subsystem(unreal.SoundCueEditorSubsystem)
    player_class = unreal.SoundNodeWavePlayer.static_class()
    crossfade_class = unreal.SoundNodeDistanceCrossFade.static_class()
    classes = list(editor.get_sound_node_classes())
    if player_class not in classes or (fades and crossfade_class not in classes):
        raise RuntimeError("当前编辑器未启用所需的声音节点")

    cue = None
    original = []
    if library.does_asset_exist(asset_path):
        cue = library.load_asset(asset_path)
        if not isinstance(cue, unreal.SoundCue) or cue.get_outermost().get_path_name() != asset_path:
            raise RuntimeError("正式目标必须是原路径的 SoundCue")
        original = list(editor.get_nodes(cue))
        if not all(node.get_class() in (player_class, crossfade_class) for node in original):
            raise RuntimeError("目标 Cue 存在其它类型的节点")
    require_asset_write([cue] if cue else [], [] if cue else [asset_path])

    with unreal.ScopedEditorTransaction("配置声音提示图表"):
        if cue is None:
            directory, name = asset_path.rsplit("/", 1)
            cue = editor.create_sound_cue(directory, name)
            if not isinstance(cue, unreal.SoundCue):
                raise RuntimeError("创建目标 Cue 失败")

        cue.modify()
        players = []
        for wave in waves:
            player = editor.add_node(cue, player_class)
            if player is None:
                raise RuntimeError("创建波形播放器失败")
            player.modify()
            player.set_editor_property("sound_wave_asset_ptr", wave)
            player.set_editor_property("looping", False)
            if player.get_editor_property("sound_wave_asset_ptr") != wave:
                raise RuntimeError("波形播放器引用回读不符")
            players.append(player)

        root = players[0]
        if fades:
            root = editor.add_node(cue, crossfade_class)
            if root is None:
                raise RuntimeError("创建距离淡化节点失败")
            for index, node in enumerate(players):
                editor.connect_nodes(cue, root, node, index)
            if list(root.get_editor_property("child_nodes")) != players:
                raise RuntimeError("距离淡化输入的连接顺序不符")

            inputs = list(root.get_editor_property("cross_fade_input"))
            if len(inputs) != len(fades):
                raise RuntimeError("距离淡化参数数量与输入连接不符")
            root.modify()
            for datum, row in zip(inputs, fades):
                for field, value in zip(_DISTANCE_FIELDS, row):
                    datum.set_editor_property(field, value)
                datum.set_editor_property("volume", 1.0)
            root.set_editor_property("cross_fade_input", inputs)

        cue.set_editor_property("attenuation_settings", attenuation)
        cue.set_editor_property("override_attenuation", False)
        editor.set_root_node(cue, root)
        for node in original:
            editor.remove_node(cue, node)
        editor.layout_sound_cue(cue)

        actual_root = cue.get_editor_property("first_node")
        if actual_root != root or cue.get_editor_property("attenuation_settings") != attenuation:
            raise RuntimeError("声音图表根节点或衰减引用回读不符")
        actual_fades = []
        if fades:
            for datum in root.get_editor_property("cross_fade_input"):
                actual_fades.append([datum.get_editor_property(field) for field in _DISTANCE_FIELDS])
            if actual_fades != fades or list(root.get_editor_property("child_nodes")) != players:
                raise RuntimeError("声音图表距离参数回读不符")

    if not library.save_loaded_asset(cue, False):
        raise RuntimeError("声音提示保存失败")
    return {
        "asset": cue.get_path_name(),
        "wave_paths": [wave.get_path_name() for wave in waves],
        "fade_distances": actual_fades,
        "attenuation": attenuation.get_path_name(),
        "node_count": len(editor.get_nodes(cue)),
    }
