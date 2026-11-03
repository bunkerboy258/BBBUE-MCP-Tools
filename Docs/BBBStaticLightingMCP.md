# 原生静态光照构建

`level.inspect_static_lighting` 与 `level.build_static_lighting` 使用项目原生 `BBBStaticLightingEditorLibrary` 读取和构建当前编辑器世界的静态光照 不执行临时编辑器脚本

## 检查

`inspect_static_lighting(expected_level, center, extent)` 要求当前关卡与明确包路径一致 包围盒单位为厘米 `extent` 是非负半尺寸 全零读取整个世界

返回静态网格组件的演员路径 网格路径 移动性 阴影开关 实际光照贴图尺寸和包围盒 唯一网格清单返回 Nanite 状态 渲染 LOD 数量 UV 通道数 光照 UV 索引与备用 LOD0 三角数 同时返回关卡强制禁用预计算光照开关 未构建对象数与构建数据路径

`channel_present` 仅表示光照 UV 索引对应已有通道 不代表 UV 无重叠 重叠与接缝由实际局部构建日志和画面检查确认 不在全图只读审计内执行无界的逐三角 UV 深度扫描 检查不会修改网格或关卡

## 构建

`build_static_lighting(expected_level, build_data_path, action, quality, actor_paths)` 的 `build_data_path` 必须为目标地图包路径加 `_BuiltData` `action` 为 `start` `status` 或 `cancel` 质量零至三分别为 Preview Medium High Production 空演员列表构建当前整个持久关卡 显式演员列表只生成目标演员的映射 其他演员仍参与遮挡和反弹计算

公开 `actor_paths` 是数组 原生 Python 注册参数使用 `actor_paths_json` 字符串和 JSON 编解码 避免反射空数组默认值破坏整个工具目录

启动要求退出 PIE 项目允许静态光照 关卡没有禁用预计算光照 且没有其他光照构建在运行 每个演员路径都必须属于当前持久关卡 构建期间登记阻塞活动 防止编辑器变更世界 启动时临时开启自动采用构建结果 完成后恢复原偏好 不保存用户配置

状态分别报告引擎构建启动 完成成功 结果采用和当前是否仍运行 只有构建不再运行且收到成功与采用事件时才返回 `completed` 无成功证据不得将静止状态视为构建完成 查询完成状态后显式保存目标地图与构建数据 再回读结果

`cancel` 仅请求取消本工具持有的构建 须继续查询直到引擎结束 不取消其他调用者持有的构建

局部映射只用于小样 无法当作整图构建完成证明 正式交付需要整图构建与实际角色场景复测

## 验证

2026-11-03 UE5.8 原生完整编译与工具 Python 语法检查通过 实际场景构建与画面验证执行中

## GPU 整图烘焙

`level.build_gpu_lightmass(expected_level, build_data_path, action, gi_samples, shadow_samples, tile_pool_size, workload_factor)` 使用引擎 GPULightmassSubsystem 的 FullBake 不调用 CPU BuildLighting 要求启用 GPULightmass 插件 DX12 与硬件光追 编辑器不能以 r.RayTracing=0 启动

默认 GI 512 阴影 128 瓦片池 32 工作倍率 2 关闭实时视口 户外关闭辐照缓存 完成后降噪 压缩贴图 体积光照格 200cm 质量倍率 2 不修改进程优先级 不修改源美术

活动按原生 IsRunning 与 GetPercentage 回读 进程停止不单独证明烘焙成功 交付必须核对引擎完成及结果导入日志 并保存地图与独立 BuiltData 不自动回退 CPU

2026-11-03 GPU 工具配置完成 实际整图烘焙待完成
