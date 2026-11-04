# GPU 稳定帧捕获

`runtime.apply_scene_quality(quality=0..4)` 在当前 PIE 中调用实际 `GameUserSettings` 的统一档位设置与 `ApplyNonResolutionSettings`。返回设置类和生效的分组 抗锯齿 视距 LOD 阴影及纹理池参数。不保存用户配置或资产。使用项目设置子类时也执行其原生覆盖流程。比较画质档位时先应用再预热 不用直接修改各个 `sg.*` 代替游戏的设置应用流程。

`runtime.profile_scene_gpu` 使用 `prepare → capture → capture → restore`。

`prepare` 保存原值并启用材质及网格绘制标记，不捕获。等待至少 60 个引擎帧，使标记切换引起的渲染状态及阴影缓存重建完成。过早调用 `capture` 返回 `warming`，不会请求 GPU 分析。未准备直接捕获会明确失败。

准备后可以连续调用 `capture`，期间不切换标记。最后调用 `restore` 恢复并回读原设置。请求成功仅代表已请求捕获，结果须从对应宿主日志读取；禁止将父子计时重复相加。

DeadCity 实测：每次切换标记后立刻捕获会记录地形预阴影重建约 7.81–9.84 ms；同一次 PIE 保持标记不变的后续三次捕获不再出现 PreshadowCache 重绘，ShadowDepths 为 1.70、1.14、1.15 ms。这是捕获流程差异，不是游戏帧率优化收益。地形材质同一条目约 0.46 ms，不依据此前单帧异常值削减材质画质。

回归检查 `Tests/test_gpu_profile_warmup.py` 验证准备阶段不捕获、帧数门槛、连续捕获不切换标记、结束恢复原值。
