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
