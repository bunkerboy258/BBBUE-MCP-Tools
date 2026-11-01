import json
import math

import unreal
from BBBAssetWritePolicy import require_asset_write
from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration


@unreal.uclass()
class BBBMonsterTraversalToolset(unreal.ToolsetDefinition):
    """/** 制作僵尸上台动作 配置并保存静态台沿连接 不运行 PIE */"""

    @mcp_tool
    @staticmethod
    def bake_mantle(source_path: str, retargeter_path: str, idle_path: str,
                    sequence_path: str, montage_path: str) -> str:
        """
        /**
         * 从完整原片制作首尾僵尸站姿的快速上台动作
         * @param source_path	完整上台原片
         * @param retargeter_path	保留原片根高度的重定向器
         * @param idle_path	同骨架僵尸站姿
         * @param sequence_path	明确自有序列输出
         * @param montage_path	明确自有蒙太奇输出
         * @return 制作 保存与骨轨回读结果 不运行游戏
         */
        """
        import importlib
        import BBBTraversalAnimationBaking

        source = unreal.load_asset(source_path)
        if not isinstance(source, unreal.AnimSequence):
            raise RuntimeError('需要上台原片')
        end = source.data_model_interface.get_number_of_keys() - 1
        contacts = (round(end * 0.15), round(end * 0.72), round(end * 0.25), round(end * 0.55))
        return importlib.reload(BBBTraversalAnimationBaking).bake(
            source_path, retargeter_path, idle_path, sequence_path, montage_path,
            0, end, 0.15, 0.15, contact_window=contacts)

    @mcp_tool
    @staticmethod
    def configure_assets(logic_paths: list[str], presentation_paths: list[str], blueprint_paths: list[str],
                         mantle_path: str, climb_path: str) -> str:
        """
        /**
         * 配置同骨架上台资源 逻辑根轨迹与双手接触动画图 编译保存
         * @param logic_paths	明确逻辑配置列表
         * @param presentation_paths	明确同骨架表现配置列表
         * @param blueprint_paths	这些表现配置实际引用的动画蓝图完整列表
         * @param mantle_path	快速上台序列
         * @param climb_path	较高攀爬序列
         * @return 配置数量与保存结果
         */
        """
        paths = logic_paths + presentation_paths + blueprint_paths
        if not paths or not presentation_paths or not blueprint_paths or len(paths) > 64:
            raise RuntimeError('需要明确且有限的配置与动画蓝图范围')
        if any(not path.startswith('/Game/_Project/') for path in paths):
            raise RuntimeError('只允许自有配置与动画蓝图')
        logic = [unreal.load_asset(path) for path in logic_paths]
        presentations = [unreal.load_asset(path) for path in presentation_paths]
        blueprints = [unreal.load_asset(path) for path in blueprint_paths]
        if any(not isinstance(value, unreal.BBBMonsterDefinition) for value in logic):
            raise RuntimeError('逻辑配置类型错误')
        if any(not isinstance(value, unreal.BBBMonsterPresentationDefinition) for value in presentations):
            raise RuntimeError('表现配置类型错误')
        if any(not isinstance(value, unreal.AnimBlueprint) for value in blueprints):
            raise RuntimeError('动画蓝图类型错误')
        expected = {value.get_editor_property('animation_class').get_path_name().removesuffix('_C') for value in presentations}
        if expected != {value.get_path_name() for value in blueprints}:
            raise RuntimeError('实际动画蓝图与明确写入范围不一致')
        targets = logic + presentations + blueprints
        dirty = set(unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages())
        if any(value.get_outermost() in dirty for value in targets):
            raise RuntimeError('目标存在未保存编辑')
        mantle, climb = [unreal.load_asset(path) for path in (mantle_path, climb_path)]
        if any(not isinstance(value, unreal.AnimSequence) for value in (mantle, climb)):
            raise RuntimeError('需要两个完整上台动作序列')
        if any(not path.startswith('/Game/_Project/') for path in (mantle_path, climb_path)):
            raise RuntimeError('只允许自有上台动作')
        targets += [mantle, climb]
        require_asset_write(targets)
        for sequence in (mantle, climb):
            sequence.set_editor_properties({'force_root_lock': True, 'root_motion_root_lock': unreal.RootMotionRootLock.ZERO})
        result = json.loads(unreal.BBBMonsterTraversalEditorLibrary.configure_traversal_assets(
            logic, presentations, mantle, climb))
        if not result.get('success'):
            raise RuntimeError('攀爬配置失败 ' + str(result))
        for blueprint in blueprints:
            unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
            if blueprint.get_editor_property('status') != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError('攀爬动画图编译失败 ' + blueprint.get_path_name())
        for value in targets:
            if not unreal.EditorAssetLibrary.save_loaded_asset(value, False):
                raise RuntimeError('攀爬配置保存失败 ' + value.get_path_name())
        for value in presentations:
            if value.get_editor_property('mantle').get_editor_property('sequence') != mantle or value.get_editor_property('climb').get_editor_property('sequence') != climb:
                raise RuntimeError('攀爬资源保存后回读失败')
        result['saved'] = [value.get_path_name() for value in targets]
        return json.dumps(result, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def build_links(expected_level: str, spacing: float = 120.0, minimum_height: float = 35.0,
                    maximum_height: float = 250.0, dry_run: bool = True) -> str:
        """
        /**
         * 批量制作静态地形上台连接 仅重建工具自有组 保留手工连接
         * @param expected_level	当前唯一目标关卡
         * @param spacing	入口间距 单位厘米
         * @param minimum_height	最低攀爬高度
         * @param maximum_height	最高攀爬高度
         * @param dry_run	仅检查 不修改或保存
         * @return 实际候选与创建数量 应用后保存当前关卡并构建导航
         */
        """
        if not expected_level.startswith('/Game/_Project/') or not all(math.isfinite(v) for v in (spacing, minimum_height, maximum_height)):
            raise RuntimeError('需要明确关卡与有限参数')
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if not world or world.get_outermost().get_name() != expected_level:
            raise RuntimeError('当前关卡与明确范围不一致')
        if not dry_run:
            require_asset_write([world])
        result = json.loads(unreal.BBBMonsterTraversalEditorLibrary.build_climb_links(
            expected_level, spacing, minimum_height, maximum_height, dry_run))
        if not result.get('success'):
            raise RuntimeError('静态攀爬连接制作失败 ' + str(result))
        if not dry_run and not unreal.EditorLevelLibrary.save_current_level():
            raise RuntimeError('攀爬连接关卡保存失败')
        return json.dumps(result, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_links(expected_level: str) -> str:
        """
        /**
         * @param expected_level	明确关卡包路径
         * @return 当前连接数量与导航构建状态 不修改
         */
        """
        return unreal.BBBMonsterTraversalEditorLibrary.inspect_climb_links(expected_level)


_registration = Registration([BBBMonsterTraversalToolset])
