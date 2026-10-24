import json
import re

import unreal
from BBBMcpCapabilities import mcp_tool
from BBBAssetWritePolicy import require_asset_write
from toolset_registry.registration import Registration


@unreal.uclass()
class BBBMonsterGoreToolset(unreal.ToolsetDefinition):
    """/** 统一血腥资源制作及原生预览 不承担伤害逻辑 */"""

    @mcp_tool
    @staticmethod
    def inspect_monster_presentation(definition_path: str) -> str:
        """/** @param definition_path 唯一表现配置资产 @return 分区所有权及有效性 不保存 */"""
        definition = unreal.load_asset(definition_path)
        if not isinstance(definition, unreal.BBBMonsterPresentationDefinition):
            raise RuntimeError("需要僵尸表现配置")
        return str(unreal.BBBMonsterPresentationEditorLibrary.inspect_configuration(definition))

    @mcp_tool
    @staticmethod
    def save_monster_presentation(definition_path: str) -> str:
        """/** @param definition_path 明确的自有表现配置 @return 完整验证后保存全部内联分区 */"""
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间等待配置保存")
        definition = unreal.load_asset(definition_path)
        if not isinstance(definition, unreal.BBBMonsterPresentationDefinition) or not definition_path.startswith("/Game/_Project/"):
            raise RuntimeError("需要明确的自有僵尸表现配置")
        require_asset_write([definition_path])
        result = str(unreal.BBBMonsterPresentationEditorLibrary.save_configuration(definition))
        if result.startswith("失败"):
            raise RuntimeError(result)
        return result

    @mcp_tool
    @staticmethod
    def import_monster_hit_profile(definition_path: str, region: int, source_path: str) -> str:
        """/** @param definition_path 目标表现配置 @param region 躯干 头 臂 腿四分区编号 @param source_path 参数模板 @return 内联参数导入结果 不保留模板引用 */"""
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间等待参数导入")
        definition = unreal.load_asset(definition_path)
        source = unreal.load_asset(source_path)
        if not isinstance(definition, unreal.BBBMonsterPresentationDefinition) or not isinstance(source, unreal.HitReactProfile) or region not in range(4):
            raise RuntimeError("需要表现配置 四分区编号和受击参数模板")
        require_asset_write([definition_path])
        result = str(unreal.BBBMonsterPresentationEditorLibrary.import_hit_profile(definition, region, source))
        if result.startswith("失败"):
            raise RuntimeError(result)
        return result

    @mcp_tool
    @staticmethod
    def configure_monster_wound_materials(definition_path: str) -> str:
        """
        /**
         * @param definition_path\t当前僵尸唯一表现配置
         * @return 保存并回读的共享投影材质 不生成身体或组织网格
         */
        """
        if not re.fullmatch(r"/Game/_Project/(?:Mass/Monster/Zombie|Debug/ZombieHitReaction)/[A-Za-z0-9_/]*DA_[A-Za-z0-9]+Presentation", definition_path):
            raise RuntimeError("需要明确的自有表现配置路径")
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止适配共享材质")
        if unreal.SourceControl.is_enabled() and unreal.SourceControl.current_provider() == "Perforce":
            raise RuntimeError("本项目不使用 Perforce")
        presentation = unreal.load_asset(definition_path)
        if not isinstance(presentation, unreal.BBBMonsterPresentationDefinition):
            raise RuntimeError("需要僵尸表现配置")
        definition = presentation.get_editor_property("gore")
        folder = definition_path.rsplit("/", 1)[0]
        material_folder = "/Game/_Project/Mass/Monster/Zombie/Shared/Injury/Materials"
        existing = list(unreal.EditorAssetLibrary.list_assets(folder, recursive=True, include_folder=False))
        existing.extend(unreal.EditorAssetLibrary.list_assets(material_folder, recursive=True, include_folder=False))
        destinations = [folder, material_folder]
        for wound in definition.get_editor_property("wounds"):
            for field in ("tissue", "detached_skin", "detached_mesh"):
                resource = wound.get_editor_property(field)
                if resource is not None:
                    if not resource.get_path_name().startswith("/Game/_Project/Mass/Monster/Zombie/Shared/Injury/"):
                        raise RuntimeError("预制资源必须位于本轮自有路径")
                    existing.append(resource.get_path_name())
        require_asset_write(existing, destinations=destinations)
        result = str(unreal.BBBMonsterGoreEditorLibrary.configure_wound_materials(definition))
        if result.startswith("失败"):
            raise RuntimeError(result)
        saved = str(unreal.BBBMonsterGoreEditorLibrary.save_gore_configuration(definition))
        if saved.startswith("失败"):
            raise RuntimeError(saved)
        report = json.loads(str(unreal.BBBMonsterGoreEditorLibrary.inspect_gore_assets(definition)))
        report["saved"] = True
        report["bodyTopologyModified"] = False
        return json.dumps(report, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_monster_gore_assets(definition_path: str) -> str:
        """
        /**
         * @param definition_path\t当前统一血腥配置包路径
         * @return 资源状态 不运行世界 不保存
         */
        """
        definition = unreal.load_asset(definition_path)
        if not isinstance(definition, unreal.BBBMonsterPresentationDefinition):
            raise RuntimeError("需要僵尸表现配置")
        return str(unreal.BBBMonsterGoreEditorLibrary.inspect_gore_assets(definition.get_editor_property("gore")))


_registration = Registration([BBBMonsterGoreToolset])
