# 骨骼网格原位导入

通过 `BBBSkeletalMeshImportToolset.reimport_skeletal_mesh(asset_path, source_file)`
将存在的绝对路径 FBX 原位导入已有 SkeletalMesh 并保存唯一目标。

工具拒绝 PIE 写入、未保存目标以及 Perforce 冲突或他人占用。
受控资产须预先签出，未受控资产按公共写入策略报警。
保留已有骨架，不更新参考姿势，不导入动画、材质、纹理或物理资产。
导入后校验资产身份、骨架身份及骨名列表；原有同名材质槽恢复原材质。
新增材质槽由调用方明确绑定。失败后检查现场，不自动重试或创建兼容副本。

宿主发现新脚本前，可通过编辑器控制台 `py` 执行
`Scripts/BBBSkeletalMeshImportToolset.py` 注册；随后重新发现实际工具集名称。
