# 动作匹配运行时探针

适用于当前 PIE 的标准 Motion Matching 与 Pose History。默认选择本地玩家 也支持明确的参考角色路径。单次快照入口 `BBBMotionMatchingEditorLibrary.ProbeMotionMatchingRuntime` 等待已有求值完成。有界连续采集使用原生骨骼完成回调 不主动推进或强制重算动画 不修改角色或资产。

调用 `motion_matching.start_runtime_probe` 并明确本任务 `file_prefix`。`duration_seconds` 为 1 到 120 游戏秒 默认 20 秒。`target_actor_path` 空值使用本地玩家。采集每个实际完成的骨骼姿态 同一引擎帧多次回调保留最后结果。报告仅写入 `Saved/temp/<file_prefix>/MMRuntime_<时间>.jsonl`。拒绝路径穿越 重复启动和超过帧数或墙钟上限的采集。

`motion_matching.inspect_runtime_probe` 返回状态 样本数 世界更新数 缺失姿态帧及最新快照。`motion_matching.stop_runtime_probe` 注销原生回调并关闭文件。时限到达 PIE 结束或原生采样失败时自动收尾。暂停期间不重复记录同一游戏时间。缺帧不补成上一帧 不计为完整覆盖。

快照增加 MM 实际混合播放器及权重 双腿与骨盆的世界和组件空间变换 参考骨架位置 活跃曲线 槽权重和脚部地面查询。脚底接触点按参考骨架根平面标定 属于虚拟骨骼接触点 不表示服装网格逐顶点接触。

`motion_matching.analyze_runtime_probe` 接收 `file_path` 与结构化 `phases` `limits` 以及可选 `baseline_path`。输入用例区间包含唯一 `name` 和闭区间 `start_frame` `end_frame`。检查有限姿态 缺帧 植足滑动 穿地 悬空 膝平面突变 腿部伸展 骨盆突跳和根骨角度突跳。只有稳态区间使用根轨迹方向辅助判定。来源基线必须独立建立并覆盖相同用例。`qualityPassed` `coverageValid` `baselineMatched` 和最终 `acceptancePassed` 分开返回。无来源或无用例覆盖不产生最终验收通过。

无渲染测试要求目标网格实际启用持续骨骼求值 并核对采样覆盖。采集不会替测试目标开启求值或关闭优化。无渲染证据不包含画面 材质和服装穿插验收。

快照包含角色 网格和根骨朝向 世界与角色及网格空间速度 当前输入 加速度 主蓝图生成轨迹 Pose History 实际轨迹 MM 命中数据库与序列 命中时间 代价 镜像 播放速率和权重。命中序列额外采样原始根轨迹 计算根局部与世界空间速度。两侧速度均超过 50 cm/s 时给出方向夹角。

方向误差用于定位查询与动画坐标是否一致。起停 转身和过渡姿态可能暂时产生较大误差 须结合输入阶段 轨迹和实际姿态判断。不能仅凭一个总均值判定视觉验收通过。

使用 `animation.run_pie_input_sequence` 的 `schemaVersion:2` 在游戏帧中注入明确四向输入。先采集修复前报告 再在相同配置下采集修复后报告。完成后仅清理本任务目录 不删除并行采样。

2026-10-25 工程复现: 目标动画前进根轨迹为网格 +Y 左移为网格 +X。错误实现把角色世界旋转写入 `FPoseSearchTrajectoryData::FDerived::Facing`。角色 yaw 为 0 且网格 yaw 为 -90 时 生成和历史轨迹 yaw 错误地成为 0 导致前进命中左移动画 后退命中右移动画。修复为使用本帧网格世界旋转 不写固定角度补偿。

空手四向中速度大于 100 cm/s 的样本平均方向误差: 前进 88.44 到 1.11 度 后退 90 到 0 度 左移 90 到 0 度 右移 90.30 到 0 度。步枪四向 连续反向和视角转动共 750 个注入游戏帧 无跳过 输入释放确认成功。步枪探针共 349 个样本 符合速度阈值的平均方向误差 0.633 度 P95 为 0.220 度。转动后的角色 yaw 为 15 网格和查询轨迹 yaw 均为 -75。

验证: UE5.8 Development Editor 编译成功。原生 `BBB.Animation.MotionMatching.TrajectoryCoordinateSpace` 测试通过 覆盖三个角色朝向各四个移动方向。23 项 Python 探针及相关 MM 工具测试通过。以上证据验证坐标和方向匹配 起停转身细节及整体观感仍由实际游戏画面验收。
# 来源回放与曲线恢复

`motion_matching.prepare_reference_runtime` 在非 PIE 环境只读载入明确来源动画蓝图与骨骼网格 仅在内存中清空明确的无参数角色事实入口 由回放注入原始事实 直接使用原始叶类 保留原有 CVar 配置更新 工作线程逻辑 标准姿态图 属性存取和 Chooser 上下文类型 不保存来源资产或测试夹具。标准 GASP CMC 使用 `Update_PropertiesFromCharacter` 作为该桥接。

随后在 PIE 中通过 `motion_matching.start_reference_replay` 回放 Saved/temp 下已采集的角色位置 速度 加速度 CMC 限制 姿态和普通跳落事实。输入必须包含格式 8 的 `deltaSeconds` 回放临时按每帧原始步长设置固定时钟 并逐帧校验实际 Delta Time 相等 不把可变帧率采样当作固定 60 Hz 数据。结束 失败或 PIE 退出后恢复原固定时钟状态和步长。临时普通 Character 不运行项目玩法及 CMC 积分 只承载来源动画蓝图的独立求值。`inspect_reference_replay` 返回覆盖 时钟状态与失败原因 `stop_reference_replay` 销毁角色与控制器并移除回调。对该角色使用现有逐帧探针 可通过 `referenceReplayFrame` 对齐原始输入帧 不能用资产名称相同替代姿态验收。

`editor.copy_animation_float_curves` 支持 `source_content_directory` 只读来源 Content 目录。先载入自有目标 再作用域挂载外部来源 返回前解除挂载。只允许不同的同长 AnimSequence 复制全部浮点曲线及标记 颜色 说明和外推方式 校验键 插值和有效切线 并对目标全部骨轨道计算前后摘要。引擎会重新生成线性键不参与插值的切线缓存 此缓存不构成语义差异 三次曲线的切线和权重仍严格核对。

`motion_matching.cleanup_animation_blueprints` 的 `flattenStateMachines` 通过节点 GUID 与保留状态名 原位迁移姿态节点及其子图至状态机所在图 删除整个旧状态机。先预检唯一结果与边界 再统一编译保存 不创建兼容分支或历史副本。

格式 5 快照的槽权重固定为 SlotMontageGlobalWeight 并记录 `slotWeightSemantic=montage_global`。不把 SlotNodeGlobalWeight 当成动作贡献。逐帧读取 Foot Placement 的实际绑定 PlantSettings 和 Alpha 写入 footPlacements。植足判定使用该帧 speedThreshold 普通接地帧缺少明确有效参数时直接失败。GASP 实际绑定阈值为 1 不能使用未绑定节点的默认 60。滑步速度及持续时间仍采用固定质量限制。检查器也拒绝缺少槽语义或接触曲线覆盖的数据。原始未扭曲的序列方向只作诊断 最终根骨朝向转换后的方向用于稳态检查。跨骨架滑步对照使用腿长归一化速度。

快照还记录 CMC 地面命中 法线 距离 瞬移标记 上次速度 网格与胶囊组件速度。来源夹具同步还原这些状态 不能只设置 Walking 模式而留下空 CurrentFloor。来源回放拒绝缺少这些事实的旧采集。Pose History 中额外读取骨盆和双脚世界位置 可用脚与骨盆的相对位置核对后置处理是否影响基础脚姿。蹲站几何检查以网格原点位移扣除整体运动 不用会随胶囊半高跳变的角色中心。

`migrate_configuration` 的 blueprint.graphEdits 支持明确图名 节点类 成员或完整函数对象路径 节点属性 可选公开引脚 默认值和连接。现有节点用本图 GUID 或完整对象路径定位 创建节点用请求内 id 定位。函数对象路径使用 `/Script/Engine.KismetMathLibrary:FunctionName`。newVariables 只声明本次需要的明确成员 不创建运行时原生派生逻辑。

`motion_matching.configure_in_place_root_velocities` 按 asset_paths 与 velocities 一一对应 为根轨道恒定或线性的原地序列配置动画局部索引速度。预检全部目标 正式写入仅修改根轨道 并开启提取和强制首帧锁根。全部非根骨轨道前后摘要必须一致后才保存。运行时仍要求主实例使用 RootMotionFromMontagesOnly。

`editor.invoke_pie_object_function` 的参数支持显式 `{"$vector":[x,y,z]}` 和 `{"$rotator":[pitch,yaw,roll]}` 标记 用于瞬态测试角色位置与朝向 不修改关卡资产。

配置重映射支持 existingAssets 明确已有自有 DataAsset 列表。只对列出的对象及其子对象应用 objectRemaps 并回读保存 不接受蓝图 动画或关卡。该列表和新建目标一起构成 target_paths 的完整范围。

参考函数图复制时 自身变量节点由目标图重新创建 不能保留来源字段上下文。保留原连线 数据引脚默认值 拆分结构体和读取节点形式。编译成功后还须检查运行日志及生成轨迹和 Pose History 的样本数。动态检查器将普通帧的空生成轨迹或空历史轨迹直接判为失败 即使 MM 当前仍在播放动画。

来源数据是否可以比较与来源是否达到产品质量分开报告。baselineValid 要求同阶段完整采集 无硬数据失败 并逐帧核对事实 baselineQualityPassed 独立显示来源质量。项目 acceptancePassed 仍要求自身全部固定质量约束通过以及来源逐阶段比较通过 来源警告不能放宽项目阈值。

来源 GASP 的旧序列化 MM 节点在 UE5.8 中出现默认 OnStateExit 绑定时 参考夹具仅在内存中恢复来源已有的 Update_MotionMatching_PostSelection 函数绑定 然后重新编译。源文件不保存。该适配让数据库标签和后续 Steering 与脚部参数读取实际选择结果。

来源回放原样设置 CMC AnalogInputModifier 必须使用包含 analogInputModifier facingYaw 和 gaitRunning 的新采集。来源动画蓝图仅在内存中编译 仅替换原叶类的事实更新函数体 不保存外部包。analyze_runtime_probe 可用 reference_facts_path 和 reference_offset_y 对齐每个 referenceReplayFrame 检查位置 速度 加速度 输入 CMC 限制 胶囊 蹲姿与步态。只有 referenceFactsVerified 成立的独立来源报告可供最终对照。

来源对照逐帧核对网格世界位置与旋转 不再从胶囊半高推算网格位置。原地转身用例必须实际选中过转身动画 普通跳跃用例必须实际离地并选中跳落动画。夹具停留在 Idle 不能通过行为覆盖。

`prepare_reference_runtime.turn_in_strafe=true` 显式将来源 ShouldTurnInPlace 的瞄准限制改为允许当前 Strafe 控制策略 仅在内存改动并在状态中回报 turnInStrafe 以便与非瞄准视角转身的项目比较。未启用时保持来源原有策略。该选项不修改来源动画 数据库或脚部求解。植足滑动按实际 LockType 测量约束点 PivotAroundBall 使用脚掌接触点 不将脚踝绕脚掌旋转视为锁脚滑动。速度和持续时间限制保持不变。

格式 7 额外采集 Foot Placement 每腿的实际 PlantType LastPlantType WantsToPlant 可达标记 输入速度 锁定权重 距离 原始与对齐后的脚变换及脚与脚掌的相对向量。腿状态在骨骼完成后只读取得 使用 UE5.8 编译器检查的成员指针 不修改引擎源码或依赖内存偏移。输入姿态来自引擎已有 ForwardedPose 按 Skeleton 到 CompactPose 映射读取 不将合并网格骨骼索引当作 Skeleton 索引。

格式 8 增加实际 `deltaSeconds` 和双侧锁骨 上臂 前臂 手部的最终变换 同时扩充 `footPlacements.inputBonesWorld` 中脚部修正前的骨骼集合 用于区分基础动作回顿与后置处理。每个 MM 节点通过引擎公开的 `GetMotionMatchingBlendSettings` 读取实际混合时间 Blend Profile 和惯性混合标记 每个活动序列播放器增加时长和未经 Remap Curves 处理的接触与 Phase 曲线。动作时间跳转本身不代表倒放 必须结合播放器身份 权重 原始曲线和前后骨骼运动判断。

接触曲线只表达期望植足。滑动判定要求前后两帧实际处于 Planted 或 Replanted 并且都在同一地面窗口中。PivotAroundBall 比较球关节位置 PivotAroundAnkle 比较脚关节位置 虚拟鞋底点只用于高度检查 避免将脚跟或脚趾围绕约束点的转动当作滑步。原有速度 持续时间与基线容差保持不变。缺少真实腿状态的旧采集不能通过。实际后置 FullBody 和 Traversal 蒙太奇属于动作帧 与基础姿态质量单独计算。
