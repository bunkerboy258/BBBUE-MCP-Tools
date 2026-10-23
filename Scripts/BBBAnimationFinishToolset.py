import json
import math

import unreal
from BBBAssetWritePolicy import require_asset_write
from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration


MCP_INPUTS = {
    'start_pie_fact_motion_capture': {
        'segments_json': {
            'type': 'array',
            'minItems': 1,
            'maxItems': 24,
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['duration'],
                'properties': {
                    'duration': {'type': 'number', 'exclusiveMinimum': 0, 'maximum': 10},
                    'behavior': {'type': 'integer', 'minimum': 0, 'maximum': 5},
                    'speed': {'type': 'number', 'minimum': 0, 'maximum': 650},
                    'end_speed': {'type': 'number', 'minimum': 0, 'maximum': 650},
                    'cycle_seconds': {'type': 'number', 'minimum': 0.01, 'maximum': 20},
                    'style': {'type': 'integer', 'minimum': 0, 'maximum': 2},
                    'crawling': {'type': 'boolean'},
                    'crawl_start': {'type': 'number', 'minimum': 0, 'maximum': 1},
                    'crawl_end': {'type': 'number', 'minimum': 0, 'maximum': 1},
                    'action_start': {'type': 'number', 'minimum': 0, 'maximum': 1},
                    'action_end': {'type': 'number', 'minimum': 0, 'maximum': 1},
                    'yaw_rate': {'type': 'number', 'minimum': -360, 'maximum': 360},
                    'stagger_region': {'type': 'integer', 'minimum': -1, 'maximum': 5},
                },
            },
        },
    },
}


@unreal.uclass()
class BBBAnimationFinishToolset(unreal.ToolsetDefinition):
    """/** 配置事实动画的移动采样与完整死亡表现并提供逐帧复查 */"""

    @mcp_tool
    @staticmethod
    def configure_speed_blend(asset_path: str, sequence_paths: list[str], speeds: list[float], smoothing_time: float = 0.1) -> str:
        """
        /**
         * @param asset_path\t现有一维速度混合资产
         * @param sequence_paths\t同骨架循环序列
         * @param speeds\t严格递增的厘米每秒采样点 首项为零
         * @param smoothing_time\t速度轴平滑秒数
         * @return 原位重建并保存后的真实采样数据
         */
        """
        asset = unreal.load_asset(asset_path)
        sequences = [unreal.load_asset(path) for path in sequence_paths]
        if not isinstance(asset, unreal.BlendSpace1D) or len(sequences) != len(speeds) or len(sequences) < 2:
            raise RuntimeError("速度混合目标或样本数量无效")
        if any(not isinstance(value, unreal.AnimSequence) or value.get_editor_property('skeleton') != asset.get_editor_property('skeleton') for value in sequences):
            raise RuntimeError("速度样本类型或骨架不匹配")
        if speeds[0] != 0 or any(not math.isfinite(value) for value in speeds) or speeds != sorted(set(speeds)):
            raise RuntimeError("采样速度必须有限且严格递增")
        if not math.isfinite(smoothing_time) or not 0 <= smoothing_time <= 0.3:
            raise RuntimeError("速度轴平滑时间无效")
        require_asset_write([asset])
        dirty = set(unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages())
        if asset.get_outermost() in dirty:
            raise RuntimeError("目标有未保存编辑")
        if not unreal.BBBAnimationGraphEditorLibrary.configure_speed_blend_space(asset, sequences, speeds, smoothing_time):
            raise RuntimeError("速度混合重建失败 不保存")
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            raise RuntimeError("速度混合保存失败")
        return json.dumps({'asset': asset_path, 'saved': True,
                           'samples': [{'sequence': path, 'speed': speed} for path, speed in zip(sequence_paths, speeds)]})

    @mcp_tool
    @staticmethod
    def configure_fact_animation_finish(asset_path: str, turn_sequence_paths: list[str], crawl_death_sequence_path: str,
                                        crawl_attack_sequence_paths: list[str], crawl_attack_sample_pivots: list[float],
                                        crawl_reference_speed: float = 39.7054) -> str:
        """
        /**
         * @param asset_path\t完整事实动画蓝图
         * @param turn_sequence_paths\t左转和右转原地九十度片段
         * @param crawl_death_sequence_path\t完整爬行死亡过渡序列
         * @param crawl_attack_sequence_paths\t爬行攻击变体路径
         * @param crawl_attack_sample_pivots\t各变体实际接触帧的归一化位置
         * @param crawl_reference_speed	原速爬行素材对应的移动速度
         * @return 编译保存结果 实际转向不改变 Mass 移动
         */
        """
        blueprint = unreal.load_asset(asset_path)
        turns = [unreal.load_asset(path) for path in turn_sequence_paths]
        death = unreal.load_asset(crawl_death_sequence_path)
        attacks = [unreal.load_asset(path) for path in crawl_attack_sequence_paths]
        if not math.isfinite(crawl_reference_speed) or crawl_reference_speed <= 0:
            raise RuntimeError('爬行参考速度无效')
        if not 1 <= len(attacks) <= 8 or len(attacks) != len(crawl_attack_sample_pivots) or any(not math.isfinite(value) or not 0 < value < 1 for value in crawl_attack_sample_pivots):
            raise RuntimeError('爬行攻击接触锚点无效')
        if not isinstance(blueprint, unreal.AnimBlueprint) or len(turns) != 2:
            raise RuntimeError("事实动画蓝图或转身样本数量无效")
        if any(not isinstance(value, unreal.AnimSequence) or value.get_editor_property('skeleton') != blueprint.get_editor_property('target_skeleton') for value in turns + [death] + attacks):
            raise RuntimeError("转身或死亡样本的类型与骨架不匹配")
        require_asset_write([blueprint])
        if blueprint.get_outermost() in set(unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()):
            raise RuntimeError("目标有未保存编辑")
        if not unreal.BBBAnimationGraphEditorLibrary.configure_fact_animation_finish(blueprint, turns, death, attacks, crawl_attack_sample_pivots, crawl_reference_speed):
            raise RuntimeError("转身与爬行死亡构图失败 不保存")
        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property('status') != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("最终表现图未无警告编译通过 不保存")
        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("最终表现图保存失败")
        return json.dumps({'asset': asset_path, 'turns': list(turn_sequence_paths), 'crawlDeath': crawl_death_sequence_path,
                           'crawlAttacks': list(crawl_attack_sequence_paths), 'saved': True})

    @mcp_tool
    @staticmethod
    def bake_pose_transition(source_sequence_path: str, target_sequence_path: str, asset_path: str,
                            ground_bone_names: list[str], seconds: float = 1.7) -> str:
        """
        /**
         * 从同骨架两端姿态烘焙完整过渡 保持肢体长度并约束接触点高度
         * @param source_sequence_path	起始姿态序列 取首帧
         * @param target_sequence_path	结束姿态序列 取末帧
         * @param asset_path	原位新建或重建的自有动画序列
         * @param ground_bone_names	不得低于地面的骨骼名称
         * @param seconds	过渡秒数
         * @return 全骨骼烘焙与地面高度回读结果
         */
        """
        import importlib
        import BBBAnimationPoseBaking
        importlib.reload(BBBAnimationPoseBaking)
        return BBBAnimationPoseBaking.bake_pose_transition(source_sequence_path, target_sequence_path, asset_path, ground_bone_names, seconds)

    @mcp_tool
    @staticmethod
    def start_pie_fact_motion_capture(actor_blueprint_path: str, segments_json: str, file_prefix: str,
                                     fps: int = 60, variation_seed: int = 123) -> str:
        """
        /**
         * @param actor_blueprint_path\t明确的表现蓝图 不创建 Mass 实体
         * @param segments_json\t持续秒数 行为 速度 循环秒数和姿态事实的分段数组
         * @param file_prefix\t不存在的本任务临时目录
         * @param fps\t固定姿势采样频率 不作为实测游戏帧率
         * @param variation_seed\t明确的出生种子
         * @return 骨骼数值采样活动 不生成图像 结束后销毁临时演员
         */
        """
        import importlib
        import BBBFactAnimationCaptureTools
        if json.loads(BBBFactAnimationCaptureTools.capture_status()).get('status') == 'running':
            raise RuntimeError('已有逐帧采样活动 禁止重载')
        importlib.reload(BBBFactAnimationCaptureTools)
        from BBBFactAnimationCaptureTools import start_capture
        return start_capture(actor_blueprint_path, segments_json, file_prefix, fps, variation_seed)

    @mcp_tool
    @staticmethod
    def inspect_pie_fact_motion_capture() -> str:
        """/** @return 当前逐帧事实动画采样状态与报告路径 */"""
        from BBBFactAnimationCaptureTools import capture_status
        return capture_status()


_registration = Registration([BBBAnimationFinishToolset])
