# 骨骼网格原位导入

工具已加入 `BBBMcpCapabilities.TOOLSET_ROUTES` 新宿主启动时自动注册。

通过 `BBBSkeletalMeshImportToolset.reimport_skeletal_mesh(asset_path, source_file, import_uniform_scale=1.0, lod_source_files=[])`
将存在的绝对路径 FBX 原位导入已有 SkeletalMesh 并保存唯一目标。

工具拒绝 PIE 写入、未保存目标以及 Perforce 冲突或他人占用。
受控资产须预先签出，未受控资产按公共写入策略报警。
保留已有骨架，不更新参考姿势，不导入动画、材质、纹理或物理资产。
导入后校验资产身份、骨架身份及骨名列表；原有同名材质槽恢复原材质。
新增材质槽由调用方明确绑定。失败后检查现场，不自动重试或创建兼容副本。

`lod_source_files` 必须显式传入 按 LOD1 起连续提供最多七个明确 FBX 文件。非空时先原位导入基础网格 再通过官方 SkeletalMeshEditorSubsystem.ImportLOD 导入各档 并移除清单之外的多余档位。保存前核对实际档位数量及原骨架身份 返回逐档顶点数。不生成自动减面档位。空数组只执行明确的基础网格重导入。导入开关使用编辑器属性接口开启形态目标 并在保存前检查已有形态目标没有丢失。

每次明确重建目标的 FbxSkeletalMeshImportData 并通过 ScriptedAddFilename 绑定本次基础网格来源 避免原有来源处理器请求失效文件或打开系统选文件窗口。实现集中在 BBBSkeletalMeshImport.py 工具入口每次读取当前实现 不新增第二个编辑入口。正式身体 FBX 须保留原有材质槽名称 工具按明确名称还原绑定。

宿主发现新脚本前，可通过编辑器控制台 `py` 执行
`Scripts/BBBSkeletalMeshImportToolset.py` 注册；随后重新发现实际工具集名称。
