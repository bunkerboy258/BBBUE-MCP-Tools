# Mass 部位受击与共享血效

伤口与断肢统一采用 [伤口表现工具](BBBMonsterGoreMCP.md) 中的预制资源与投影内核。该模块不维护独立调试伤口渲染器 不改写部位生命规则。

`inspect_zombie_gib_presentation()` 在当前真实 PIE 查询世界碎片池的模拟数 静止数与已分配槽位数 以及伤口蒙皮的分配数 可见数和对应身体 LOD 不生成碎片 不推进寿命 不改变状态. 用于实际武器链验收 32 个模拟与 128 个静止残留预算. 演员复用后再次查询可确认残留不依赖原演员生命周期. 伤口蒙皮只在身体 LOD0 至 LOD2 显示 更远距离保留身体血污与缺肢轮廓 未显示过近距伤口的远处演员不预分配蒙皮载体.

`gibMeshes` 提供当前一次捕获蒙皮部件的组件路径 资产 物理父组件 可见性 包围范围. 同时返回刚体 location linearVelocity angularVelocity simulating gravity massKg. 近距部件从最终组件空间姿态生成父骨骼相对变换 包含当前物理混合 不使用未混合的动画局部姿态. 全部骨骼只在生成时处理一次 后续由独立刚体驱动 不逐帧复制来源.

`start_player_weapon_hit_capture.capture_gibs` 默认关闭. 开启后同帧保存 gibPresentation 用真实位置与速度区分抛飞 重力下落 碰撞滚动和稳定残留. 不推进物理 不生成部件 不延迟回放. 开启该诊断的耗时不作为关闭诊断时的游戏性能证据.

玩家跨帧采样注册为只读且不等待的观察活动. 后续正式输入可以立即开始 不在采样结束后才开火. 必须通过 inspect_skeletal_hit_reaction_capture 确认完成并核对同帧弹量变化后才能结束 PIE.

PIE 意外结束时玩家采样立即标记失败并注销采样回调 不访问已随世界销毁的相机。相机清理或报告落盘失败同样结束进行中状态并保留明确错误 防止旧采样持续占用共享宿主。

碎肢池的 landed 为活动槽位中已发生真实地面碰撞回调的数量. 回调依赖全池共用的无 Tick 无网络复制载体 不为每块部件创建 Actor. 首次接触即可触发落地声 稳定冻结不再延后补播.

`spawn_mass_hit_acceptance_population` 使用正式实体配置的 LOD、生命、动画预算与行为，每种配置生成一个实体。同一 PIE 只允许一次；与强制全骨骼的检查展示用途不同。正式玩家验收不调用 `create_actor_stress_config`。

`inspect_player_weapon_hit_state` 只读返回玩家生命、镜像权限、步枪弹量及枪口和相机方向。玩家采样报告每帧保留这些事实，可区分空枪、镜像子弹、未命中与反馈链路故障。

`start_player_weapon_hit_capture` 在真实 PIE 玩家相机上按最多 60 Hz 采集画面与 Mass 实体状态，不注入命中或修改生命。使用 ImageWriteQueue 异步导出 PNG，完成前验证全部文件。`duration_seconds` 为游戏时间，`imageSeconds` 保存实际采样时间；视频必须依据时间戳播放，不能将不足 60 Hz 的采样标成真实 60 fps。调用方通过正式 Enhanced Input 驱动步枪并用 `inspect_skeletal_hit_reaction_capture` 查询结果。相机和渲染目标仅用于采样，完成与失败都会释放相机。

`normalize_hit_reaction_arm_bodies(asset_path, mesh_path)` 将自有男性物理资产的 clavicle 手臂刚体统一绑定到 upperarm，保持参考姿势下碰撞形状和关节位置。修改前检查两侧绑定及支持的形状，负一拒绝转换，返回实际改绑数量，不保存。目标必须独占持有。

`rebuild_monster_blood_system` 接收通道与系统路径 方向血滴 单张喷溅与八乘八血雾材质五项参数 原位重建并保存自有通道及 Niagara 系统。两个目标必须已存在并独占持有。系统包含方向血滴 短促喷溅与低透明度血雾 运行时按空间岛批量发布 不生成逐命中 Niagara 组件。原始第三方材质与网格只读。

新建系统包含十六个方向血滴 两张喷溅与一张血雾 已有血液层参数保留。命中 断离及创口首次打开分别使用通道 Surface 二 三 四及对应喷射倍率。碎肉改由共享残肢池的静态网格刚体负责 重建不再接收碎肉材质和网格参数 并移除旧碎肉发射器及其公开参数。普通命中通常一个 偶尔两个 同目标间隔零点二二秒 重大毁伤三至五个 并扣除该间隔内同目标已飞出的普通碎肉 严重毁伤间隔为普通间隔的三倍 避免一轮连射重复叠加。十五米内分配 真实落地后保留二十秒再淡出两秒 静止后停止物理。碎肉最多六十四个 且至少预留八个模拟名额供完整断肢使用。构建返回成功只代表系统编译与保存 实际外观与听感需按本轮授权另行判断。

`BBBHitReactionToolset` 配置局部物理受击资产并跨真实游戏帧采样 六部位通过 `BBBMonsterHitReactionComponent` 消费原始命中事实 受力方向 冲量 混合与恢复全部归属于表现层 普通命中保持追击和当前攻击 血效仍由独立共享表现管线处理

`BBBAssetMaintenanceToolset.configure_monster_blood_residue` 接收 settings_path channel_path splatter_material_paths droplet_material_paths pool_material_paths。三类材质各一至十六个不同资产。已有血通道与材质只读。配置必须独占持有。保存后回读全部参数与材质组。保留现有 Definition 绑定与共享 Niagara。旧地面材质数组和旧工具名称已删除 不提供兼容入口。

运行时镜像弹丸只提交表现事实 不增加伤害倍率或命中历史。短时血滴按重力推进并查询静态环境。主飞溅与细滴沿表面投影方向放置。边缘支撑不足先缩小复查 再失败则放弃。血迹池上限 192 主痕迹保留 120 秒 细滴 50 秒 再淡出 4 秒。65 厘米局部邻域最多五个主痕迹和十个细滴 超额主命中增加已有不规则积血覆盖。飞行表现最多 64 每帧环境查询最多 96。

当前飞行血滴碰撞后立即释放 最长两秒 超时或预算耗尽直接丢弃 不延后排队。方向血滴粒子保留约 1.2 至 1.8 秒 使用相同的喷射速度范围与重力 低透明度血雾仍为短促反馈。池内动态材质按共享父材质复用 切换形状只修改纹理参数。视觉淡出后组件隐藏复用 不让引擎淡出计时器销毁组件。

`BBBHitReactionToolset.create_blood_residue_material` 创建不存在的自有父材质。初始形状与噪声纹理只读 新目标执行源控预检。父材质提供 BloodMask NoiseTexture Coverage SpawnTime MirrorU 并使用贴花生命周期淡出。材质使用非发光表面色彩与逐渐干燥的粗糙度 不修改第三方包。

`preview_blood_residue` 仅带渲染 PIE 可用 接受正式配置和一至六十四个有限三维接触。只测试表现 不造成伤害。`inspect_blood_residue` 只读返回当前飞行数 已分配贴花数 每帧查询与 CPU 耗时 以及有效血迹位置 法线 长轴 尺寸 类型 覆盖 寿命与年龄。正式伤害链仍须使用玩家武器或正式 Mass 弹丸验收。

`start_blood_residue_capture` 使用 floor wall slope edge accumulation 场景在高空建立短时隔离平台。duration_seconds 默认四秒 允许四至一百三十秒实际游戏时间。前四秒每零点二秒采图 后续每十秒与结束时采图。每帧记录最大查询数与 CPU 耗时 连续命中场景分批重复发布表现。近景对准弹道落点。图像仅写入 Saved/temp/<file_prefix>/<captureId>。通过 inspect_skeletal_hit_reaction_capture 查询。成功或失败均销毁平台 补光和相机 不保存关卡。各场景独立 PIE 防止上次血迹混入画面。它是材质和环境接收诊断 不替代正式 Mass 武器链验证。

aging_time_scale 默认一 允许一至二十。只在六秒后且飞行血滴已经全部结束时加速寿命采样 不加速弹道。完成或失败时还原原游戏时间倍率。该选项仅用于隔离验收场景 不应在正式玩法 PIE 中使用。加速后的帧不能作为正常帧率性能验收证据。

`BBBAnimationPreviewToolset.submit_monster_hit_ray` 仅在当前 PIE 用逻辑碰撞查找真实命中部位 经公开输入槽位提交命中与玩家累计伤害。`damage=0` 验证镜像表现 不直接改写实体 Fragment。`capture_monster_animation_transition` 必须明确给出 `hit_region` 和三维 `hit_direction` 在临时表现演员上写入快照 并通过真实动画蓝图采样方向与惯性过渡。

`BBBAnimationPreviewToolset.capture_monster_hit_scene` 接收命中射线 相机位置和唯一文件前缀 在真实 Mass 实体上提交零伤害输入 等待约 0.12 秒后渲染命中场景。截图附加临时补光与固定曝光便于检查材质 不代表关卡最终照明。调用 `inspect_animation_transition_capture` 查询返回的截图编号。相机和补光在完成或失败时销毁 图像仅写入 `Saved/temp/<file_prefix>` 任务结束后由调用方清理。

`start_player_weapon_hit_capture.blood_system_path` 为可选血效路径。传空字符串关闭粒子诊断，传明确系统路径则同步读取共享 Niagara 的粒子数量。性能对照必须关闭该诊断。

`start_skeletal_hit_reaction_capture` 的临时演员持续刷新骨骼姿态。静止单演员且无中断的诊断在预热后暂停基础动画 以固定姿势测量物理偏转 报告记录 animationPausedForMeasurement。移动或群体诊断的姿态变化包含基础动画 不能直接当作受击幅度。该检查强制近景 LOD 仅用于部位与方向诊断 最终玩家画面须使用正式实体配置及完整动画另行验收。

`start_skeletal_hit_reaction_capture.preview_version_path` 选择正式 Mass 模板后使用独立固定靶模式. 此时 `actor_blueprint_path` 传空字符串. `preview_distance_cm` 为机位水平距离 250 至 2500 厘米. `preview_view_yaw` 为绕靶机位角度. 工具在当前模拟世界创建短时灰白平台 背景及白色主灯 补灯 轮廓灯与灰色环境光 使用固定曝光与 80 度视野. 暂停原世界灯光只限当前模拟副本 完成或失败恢复. 机位不绑定角色 输入不依赖角色开火.

固定靶公开 `PreviewHit(Region Direction WoundStrength)` 通过标准点伤害入口驱动正式局部物理 伤口 血液及音效. `shots=0` 为相同场景的无命中基线. 定时命中按真实游戏时钟触发 报告保存 `shotSeconds` 与各靶实际 `consumedHits`. 图像采样同时记录粒子状态 性能对照须传 `capture_images=false` 避免截图和粒子探针开销. 平台 靶 灯光与机位仅存在本次 PIE 不保存测试地图.

固定靶模式在采样前预热一次命中并清理本靶伤口 物理状态与环境残留. 报告以实际命中数的增量核对请求 并记录实际部位是否匹配. 图像诊断同时采集实际相机位置与局部物理状态. `preview_projectile_path` 传正式子弹配置时 改由正式弹丸出生及碰撞触发点伤害 仍无需角色输入. 空字符串使用固定靶 PreviewHit 指令.

环境血迹采样通过已解析的内嵌 Blood 对象路径调用原生血迹入口 避免将表现定义资产误当作血效对象.

图像采样在命中段之后切换至当前最大落地血迹的近景 保持同一中性照明和固定曝光. `imagePhases` 标记 impact 与 ground. 报告同时保留游戏时间与真实墙钟时间 避免变速导出. 无图像性能采样仍由独立 SceneCapture 连续渲染 960×540 目标 不导出画面 不读取粒子或骨骼诊断 也不切换地面机位.

固定靶 `preview_animation_path` 可指定与模板兼容的待机 行走 跑步或攻击序列. 留空使用正式动画蓝图. `preview_wound_strength` 控制大于零且不超过十的创口累计强度 不放大物理冲量. `preview_allow_severing` 明确允许断离 默认关闭. 正式弹丸模式仍使用子弹自身毁伤配置.

固定靶重复应用版本时保留或重建有效动画实例. 轨迹采样在物理后比较目标与同相位参考骨架 初始姿态不一致或单段实例缺失立即失败. 冻结试验停止单段播放进度 仍允许组件正常求值. 约束诊断读取实际运行时约束框架 不以资产模板代替运行时状态.

`configure_hit_reaction_physics_asset` 可传 `mesh_path` 和结构化 `tuning` 原位应用已验证的物理驱动 阻尼 求解次数 投影范围及关节角度. 骨骼轨迹试验与正式资产使用同一个原生应用函数 不再手工抄写近似参数. PIE 期间拒绝修改正式物理资产. 输入先完整检查字段 类型与边界. 临时试验中的组件求解覆盖在结束后恢复.

固定靶视觉场景使用最高感染度 与既有测试样例一致. 普通受击轨迹会临时关闭固定靶的自动断肢和周期重置 完成或失败恢复原值 防止将断头消失后的骨架跳变计作受击尖峰. 断肢视觉联检仍由场景工具的明确开关触发.

同部位连射保留当前混合权重并刷新后续保持 新命中不会再次从零淡入. 恢复阶段再次命中从当前权重重新接入. 同骨骼仍只保留一个活动状态 不增加逐实例系统或新 Tick.

`editor.prepare_temporary_test_level(asset_path=原项目地图包路径 action=begin)` 在没有 PIE 和未保存资产时切换到空白临时编辑关卡 并将关卡包标为 transient. 之后启动 PIE 再创建命中场景 可排除正式地图生成器和 AI 的更新开销. 退出 PIE 后用 `action=restore` 恢复原项目关卡. 不支持嵌套和覆盖外部另行切换的世界. 场景关卡与灯光靶相机均不落入项目资产目录.

`hit.configure_hit_reaction_profile(asset_path, tuning)` 支持项目内独立或内嵌的 HitReactProfile 使用与轨迹诊断相同的原生应用函数配置 `weight rate in hold out cleanOverrides boneWeights` 其中 boneWeights 为骨骼到零至一权重的映射 覆盖包含该骨骼及下级 骨骼映射和混合阶段都先校验再写入 禁止 PIE 修改正式资产 批次保存后返回实际参数

`start_skeletal_hit_reaction_capture` 的 `preview_residue_seconds` 默认零 允许零至三十五秒。非零时延长固定靶采样 每帧读取共享池肉块位置 速度 静止状态和淡出值。初段维持六十帧采图 后段每半秒采图 跟随落地点观察 并在尾段六秒转开视线 九秒转回。使用实际游戏时钟验证落地后残留与回收。

独立场景同时同步可视编辑器的 SIE 机位并在结束时恢复原机位 使正式可见性门槛仍由真实视口驱动。报告记录 editorViewportControlled 不将仅离屏渲染误判为完整断肢已显示。fleshPieces 返回真实网格最低顶点 meshMinimumZ 用于地面穿透检查 不能以松散轴向包围盒代替。
