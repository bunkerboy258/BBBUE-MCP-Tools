import json

import unreal
from BBBAssetWritePolicy import require_asset_write
from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration


@unreal.uclass()
class BBBMonsterDirectorToolset(unreal.ToolsetDefinition):
    """/** 关卡导演检查 区域自动收集 出生预览与 PIE 调试工具 */"""

    @mcp_tool
    @staticmethod
    def inspect_directors(expected_level: str = '') -> str:
        """
        /**
         * 只读检查当前关卡中的导演实例 区域角色统计与预制波次列表
         * @param expected_level	明确的目标关卡包路径 留空使用当前打开关卡
         * @return 导演与区域检查结果 JSON
         */
        """
        return unreal.BBBMonsterDirectorEditorLibrary.inspect_level_directors(expected_level)

    @mcp_tool
    @staticmethod
    def collect_regions(expected_level: str = '', director_name: str = '', save_level: bool = False) -> str:
        """
        /**
         * 将当前关卡全部小怪生成区域自动收集并绑定到指定导演
         * @param expected_level	明确的目标关卡包路径 留空使用当前打开关卡
         * @param director_name	导演 Actor 名称或标签 留空且关卡仅一个导演时自动选择
         * @param save_level	收集完成后是否立即保存当前关卡
         * @return 收集数量与配置校验结果 JSON
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if not world:
            raise RuntimeError('当前没有打开的编辑关卡')
        if expected_level and world.get_outermost().get_name() != expected_level:
            raise RuntimeError('当前关卡与明确范围不一致')
        require_asset_write([world])
        result = json.loads(unreal.BBBMonsterDirectorEditorLibrary.collect_level_regions(expected_level, director_name))
        if not result.get('success'):
            raise RuntimeError('收集导演区域失败 ' + str(result))
        if save_level and not unreal.EditorLevelLibrary.save_current_level():
            raise RuntimeError('收集导演区域后保存关卡失败')
        result['saved'] = bool(save_level)
        return json.dumps(result, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def validate_director(expected_level: str = '', director_name: str = '') -> str:
        """
        /**
         * 只读校验指定导演的配置资产与地图区域绑定完整性
         * @param expected_level	明确的目标关卡包路径 留空使用当前打开关卡
         * @param director_name	导演 Actor 名称或标签 留空且关卡仅一个导演时自动选择
         * @return 校验结果 JSON
         */
        """
        return unreal.BBBMonsterDirectorEditorLibrary.validate_level_director(expected_level, director_name)

    @mcp_tool
    @staticmethod
    def preview_spawn(expected_level: str = '', director_name: str = '',
                      mode: str = 'DynamicHorde', target_id: str = '') -> str:
        """
        /**
         * 在编辑视口预览固有区 动态波次或预制波次的出生点筛选结果
         * @param expected_level	明确的目标关卡包路径 留空使用当前打开关卡
         * @param director_name	导演 Actor 名称或标签 留空且关卡仅一个导演时自动选择
         * @param mode	预览模式 Population / DynamicHorde / EventWave
         * @param target_id	Population 为区域标识(空表全部) EventWave 为事件标识
         * @return 合格点数 排除点数与原因统计 JSON
         */
        """
        return unreal.BBBMonsterDirectorEditorLibrary.preview_spawn(
            expected_level, director_name, mode, unreal.Name(target_id) if target_id else unreal.Name())

    @mcp_tool
    @staticmethod
    def read_pie_status(director_name: str = '') -> str:
        """
        /**
         * 只读查询 PIE 主机世界中导演的实时运行状态
         * @param director_name	导演 Actor 名称或标签 留空时选首个主机导演
         * @return 实时存活数 固有区激活进度 动态波次冷却与活跃事件 JSON
         */
        """
        return unreal.BBBMonsterDirectorEditorLibrary.read_pie_director_status(director_name)

    @mcp_tool
    @staticmethod
    def control_pie(action: str, director_name: str = '', event_id: str = '') -> str:
        """
        /**
         * 在 PIE 主机世界中控制导演启停 动态波次暂停或触发预制波次
         * @param action	控制动作 Start / Stop / PauseDynamicHorde / ResumeDynamicHorde / TriggerEventWave / StopEventWave
         * @param director_name	导演 Actor 名称或标签 留空时选首个主机导演
         * @param event_id	TriggerEventWave 或 StopEventWave 对应的事件标识
         * @return 投递结果与当前状态 JSON
         */
        """
        return unreal.BBBMonsterDirectorEditorLibrary.control_pie_director(
            director_name, action, unreal.Name(event_id) if event_id else unreal.Name())


_registration = Registration([BBBMonsterDirectorToolset])
