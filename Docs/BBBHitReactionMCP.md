# Mass 部位受击与共享血效

`spawn_mass_hit_acceptance_population` 使用正式实体配置的 LOD、生命、动画预算与行为，每种配置生成一个实体。同一 PIE 只允许一次；与强制全骨骼的检查展示用途不同。正式玩家验收不调用 `create_actor_stress_config`。

`inspect_player_weapon_hit_state` 只读返回玩家生命、镜像权限、步枪弹量及枪口和相机方向。玩家采样报告每帧保留这些事实，可区分空枪、镜像子弹、未命中与反馈链路故障。

`start_player_weapon_hit_capture` 在真实 PIE 玩家相机上按最多 60 Hz 采集画面与 Mass 实体状态，不注入命中或修改生命。使用 ImageWriteQueue 异步导出 PNG，完成前验证全部文件。`duration_seconds` 为游戏时间，`imageSeconds` 保存实际采样时间；视频必须依据时间戳播放，不能将不足 60 Hz 的采样标成真实 60 fps。调用方通过正式 Enhanced Input 驱动步枪并用 `inspect_skeletal_hit_reaction_capture` 查询结果。相机和渲染目标仅用于采样，完成与失败都会释放相机。

`normalize_hit_reaction_arm_bodies(asset_path, mesh_path)` 将自有男性物理资产的 clavicle 手臂刚体统一绑定到 upperarm，保持参考姿势下碰撞形状和关节位置。修改前检查两侧绑定及支持的形状，负一拒绝转换，返回实际改绑数量，不保存。目标必须独占持有。

`rebuild_monster_blood_system` 用现有方向血滴、单张喷溅与八乘八血雾材质重建自有通道及 Niagara 系统并保存。两个目标必须已存在并独占持有。系统包含方向血滴、短促喷溅和低透明度血雾，运行时按空间岛批量发布，不生成逐命中 Niagara 组件。原始第三方材质只读。

`BBBHitReactionToolset` 配置局部物理受击资产并跨真实游戏帧采样 六部位通过 `BBBMonsterHitReactionComponent` 消费原始命中事实 受力方向 冲量 混合与恢复全部归属于表现层 普通命中保持追击和当前攻击 血效仍由独立共享表现管线处理

`BBBAssetMaintenanceToolset.configure_monster_blood_presentation` 接收 settings_path channel_path ground_material_paths definition_paths。已有血通道和材质只读。血效配置与小怪定义必须独占持有 新配置必须允许添加。全部类型和权限验证通过后保存并回读每个定义的 BloodPresentation。不绑定表现蓝图 不重建已打磨的血滴或血雾系统。旧 configure_monster_blood_impact_system MCP 入口已删除 不保留参数或名称兼容。

运行时镜像弹丸只提交表现事实。该工具不增加伤害倍率或命中历史。地面血迹按真实静态几何查询 池上限默认 96 保留 24 秒后淡出 4 秒 并合并距离 24 厘米以内的连射血迹。

`BBBAnimationPreviewToolset.submit_monster_hit_ray` 仅在当前 PIE 用逻辑碰撞查找真实命中部位 经公开输入槽位提交命中与玩家累计伤害。`damage=0` 验证镜像表现 不直接改写实体 Fragment。`capture_monster_animation_transition` 必须明确给出 `hit_region` 和三维 `hit_direction` 在临时表现演员上写入快照 并通过真实动画蓝图采样方向与惯性过渡。

`BBBAnimationPreviewToolset.capture_monster_hit_scene` 接收命中射线 相机位置和唯一文件前缀 在真实 Mass 实体上提交零伤害输入 等待约 0.12 秒后渲染命中场景。截图附加临时补光与固定曝光便于检查材质 不代表关卡最终照明。调用 `inspect_animation_transition_capture` 查询返回的截图编号。相机和补光在完成或失败时销毁 图像仅写入 `Saved/temp/<file_prefix>` 任务结束后由调用方清理。

`start_player_weapon_hit_capture.blood_system_path` 为可选血效路径。传空字符串关闭粒子诊断，传明确系统路径则同步读取共享 Niagara 的粒子数量。性能对照必须关闭该诊断。

`start_skeletal_hit_reaction_capture` 的临时演员持续刷新骨骼姿态。静止单演员且无中断的诊断在预热后暂停基础动画 以固定姿势测量物理偏转 报告记录 animationPausedForMeasurement。移动或群体诊断的姿态变化包含基础动画 不能直接当作受击幅度。该检查强制近景 LOD 仅用于部位与方向诊断 最终玩家画面须使用正式实体配置及完整动画另行验收。
