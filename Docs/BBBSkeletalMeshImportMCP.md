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

离线制作源的正反面校准使用 `Scripts/BBBFbxMeshWinding.py`。通过 Blender 后台运行并在 `--` 后传入 `--files` 和明确的三角化 FBX 路径；默认只读检查 `outwardAreaRatio`，显式 `--apply` 才原位修正大面积反向网格。工具按逐角点法线与几何面的面积关系判断方向，不翻转整份法线，也不改为双面材质。交换面顶点顺序时同步重排四套 UV 等逐角点索引，保留顶点位置、法线数据、材质分组、骨架和蒙皮；正反面大面积混杂时拒绝整体修正。原位写入先验证同目录制作暂存，再替换正式源，已正确的文件不再修改。

制作源校准后通过同一 `skeletal_import.reimport_skeletal_mesh` 入口导入明确的基础与附加档位。随后回读 UE 实际渲染索引方向，并用同视角材质预览检查面部、口腔与手部。骨骼权重、UV 或各档最近表面距离正常，均不能单独证明面的正反朝向正确。

基础网格和全部附加档位共用原生 FBX 导入器；待完整清单导入结束才恢复 Interchange 开关。不得在基础导入后提前恢复，使附加档位切换导入器并产生不同坐标轴。
