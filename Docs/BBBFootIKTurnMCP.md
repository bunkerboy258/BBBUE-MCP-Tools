# 原地转身脚部 IK 诊断工具

工具集为 Game.Scripts.BBBGenericEditorToolset.BBBGenericEditorToolset

inspect_control_rig_graphs 参数 asset_path
只读返回 Control Rig 模型和本地函数图中的节点 引脚 默认值与连线

inspect_animation_float_curves 参数 asset_paths curve_names
只读返回动画序列浮点曲线的原始时间和值 缺少曲线时返回 exists false

工具注册与重新加载遵循 Docs/UnrealMcpCanonical.md
先 list_toolsets 再 describe_toolset 最后 call_tool
本轮证据位于 Saved/Diagnostics/IKTurnAcceptance_20260928

## 2026 09 30 检测链诊断

inspect_control_rig_graphs 直接读取官方 RigVM 模型 包含子引脚和完整模型路径 不依赖临时导出脚本

追踪通道的枚举列表不能代替运行时命中核对 本次实际绑定的左右追踪均命中 保持原追踪通道不变

probe_pie_character_ground_contacts 无参数 只读返回本地角色的 pelvis ik_foot foot ball 世界位置 与 Visibility 地面命中及脚球骨高度差

同时返回唯一运行中 CR_BBB_MannequinFootPlant 的左右命中标记 目标脚高 当前脚补偿与骨盆补偿 缺少角色 骨骼 绑定或命中结构接口时直接报错

脚球骨高度不等于鞋底高度 必须与同一角色的平地基准对照 跳跃时绑定变量可能保留上一次有效地面采样 必须结合移动模式和最终骨骼位置判断

踏步边缘已确认的问题是半径五厘米的球形检测命中相邻高一级 把本可落在低一级的脚抬高十五厘米 左右 ProcessFootTrace 的 Sphere Radius 已统一改为零点一厘米

最终图表差异只有两处半径默认值 主动画蓝图与 Base 层未改动 验收报告为 Docs/IKReachAcceptance_20260930.md

## 连续曲线恢复贴地权重

BBBBlueprintGraphToolset.configure_control_rig_curve_alpha 将唯一布尔开关替换为线程安全浮点函数

参数为 blueprint_path node_path previous_function alpha_function enable_variable curve_name expected_snapshot dry_run

先读取旧函数逻辑快照 使用其中的 snapshot 预检 新函数名称必须不存在 目标须无未保存改动且允许独占写入

现有函数必须只有曲线读取 总开关 布尔 AND 与小于等于判断 且唯一消费者为指定 Control Rig 的布尔输入 不接受其它结构

写入原位改名旧函数 移除布尔比较 使用总开关选择 Clamp(1 - curve 0 1) 或 0 将 Control Rig 改为 Float 模式 同时移除节点上重复的反转 不保留旧函数或兼容入口

主动画图只替换一个函数调用 保留姿态链与其它节点布局 严格编译通过且回读核对后仅保存目标蓝图 不改状态机过渡 CMC 或蒙太奇

工具会同步更新该函数内两处既有蓝图说明 若项目禁止更新既有注释 须先得到用户针对此次改动的明确例外

提前退出暂停源蒙太奇后恢复权重仍由状态混合带动 不依赖暂停之后的源动画曲线关键帧

BBBTraversalToolset.sample_pie_traversal 的 include_ik_curves 为 true 时额外采样主实例 DisableLegIK 曲线 真实 GetFootPlacementAlpha 返回值 总开关与骨盆 脚 脚球骨世界位置 不主动推进动画 不保存采样文件
