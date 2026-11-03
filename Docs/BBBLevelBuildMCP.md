# 普通关卡构建

`level.inspect_level_build` 读取当前编辑器关卡的光照有效性 体积光照 非空 HLOD 和不透明静态网格候选对象 不触发构建

`level.build_hlod_cluster` 接收 expected_level actor_paths cluster_label draw_distance source_lod 创建一个原生 HLOD 簇 使用源网格已有 LOD1 或 LOD2 保留原材质 不新增材质烘焙图集 仅接收同一持久关卡中的 2 至 32 个未入簇不透明静态对象 透明和镂空对象会被拒绝 距离范围 10000 至 50000 厘米 代理光照分辨率 256 不生成碰撞 光追几何和距离场 不修改共享源网格或材质

生成的代理包由引擎在当前自有关卡的 HLOD 目录管理 构建后保存代理和关卡 仍需核对代理实际显示 切换距离和后续最终光照 本工具不转换 World Partition 地图 不提供全图无差别合并

`level.build_texture_streaming_data` 重建当前关卡组件流送数据 使用引擎组件构建入口 不重存共享材质 返回实际未构建组件数量

`level.build_reflection_captures` 在最终光照后更新当前关卡静态反射 捕获构建数据由批次按 expected_level 和 build_data_path 保存

实现依赖项目编辑器模块 BBBLevelBuildEditorLibrary 编译成功和宿主加载完成后才能调用 启动成功不代表代理或光照验收成功

2026-11-04 原生编辑器模块编译通过 当前引擎材质烘焙在 DX11 和 DX12 均触发 SharedPointer 断言 因此正式接口采用保留源材质的 HLOD 几何合并 DeadCity 项目拷贝已生成并保存 17 个原生簇 全部 IsBuilt 为真 纹理流送未构建组件为 0 代理包约 40 MB 官方 Slate 远景截图已核对 最终 Production 光照进行中

专项静态光照契约检查通过 全库完整性检查因并行 BBBAnimationMigrationToolset 的源码与目录基线不同而失败 本次不修改该并行模块

纹理流送构建会让引擎补全缺失的纹理标识 本次构建批次额外保存了 T_DustMaskGlass01 第三方纹理包 未主动修改纹理像素和导入设置 不能据此宣称第三方包字节完全未变
