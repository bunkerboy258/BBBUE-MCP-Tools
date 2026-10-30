import unreal

from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration


@unreal.uclass()
class BBBSkeletalMeshImportToolset(unreal.ToolsetDefinition):
    """/** 原位导入明确骨骼网格 保持资产身份和原有骨架 */"""

    @mcp_tool
    @staticmethod
    def reimport_skeletal_mesh(asset_path: str, source_file: str, import_uniform_scale: float = 1.0, lod_source_files: list[str] = []) -> str:
        """
        /**
         * 使用原生 FBX 工厂原位重导入 不创建动画 材质 纹理或物理资产
         * @param asset_path\t已有骨骼网格的明确对象路径
         * @param source_file\t已存在的 FBX 绝对路径
         * @param import_uniform_scale\t相对源文件的统一导入缩放
         * @param lod_source_files\t按 LOD1 起顺序导入的明确 FBX 文件 传入时完整替换细节档位
         * @return 原位保存结果 骨架与顶点数量
         */
        """
        import importlib
        import BBBSkeletalMeshImport
        return importlib.reload(BBBSkeletalMeshImport).reimport(asset_path, source_file, import_uniform_scale, lod_source_files)


_registration = Registration([BBBSkeletalMeshImportToolset])
