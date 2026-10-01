# 动画通知通用 MCP 扩展

工具集为 `Game.Scripts.BBBGenericEditorToolset.BBBGenericEditorToolset`

- `inspect_animation_notifies(asset_path)` 只读返回 AnimSequence 或 AnimMontage 的通知轨道 类路径 时间与持续时间
- `replace_animation_notify_track(asset_path, track_name, events_json)` 先校验所有配置 仅替换指定轨道内的通知 保留其它轨道并保存
- `events_json` 为数组 每项包含 `class_path` `time` 可选 `duration` 通知状态必须有正持续时间 单次通知必须为零
- 调用前先检查脏包 确认所选轨道的旧事件可以被替换 并在正式项目独占签出 本次隔离副本不连接版本控制
- 创建事件失败时工具报警且不保存 不声称自动回滚 调用者必须检查脏包
- 工具注册沿用 Scripts/BBBGenericEditorToolset.py 的 Registration 重启副本后通过 list_toolsets 与 describe_toolset 验证
- 合回原项目时只追加新工具及 math 导入 禁止覆盖并行会话已添加的方法
# 蒙太奇运动验收

### 骨骼轨迹编辑

动画迁移工具集提供以下通用入口 实现在 Scripts/BBBAnimationTrajectoryTools.py

- export_animation_motion_context 导出原始轨道和网格参考骨骼层级
- bake_animation_arm_trajectory 复制源动画至专用路径 根据参考骨骼空间轨迹求解三骨骼手臂链 只改变旋转 并检查可达误差 支持显式曲线关键帧和手指握持区间
- replace_montage_animation_references 以明确映射替换等长片段 保留插槽通知和播放设置
- hold_animation_bone_tracks 固定指定骨骼轨道为选定帧 保留其余动画数据

编辑必须在 PIE 停止后进行 目标资产须独占签出 新资产自动标记添加 不执行 Submit 或 Revert
运动采样临时将时间倍率降为 0.1 以避免后台低帧率跳过关键姿势 采样结束恢复原倍率
start_pie_montage_motion_capture 的 interrupt_time 默认为负值 设置非负时间可在该时刻主动停止角色蒙太奇 用于检查 Notify 中断清理 报告记录实际中断时刻

动画迁移工具集新增 start_pie_montage_motion_capture 与 get_pie_montage_motion_capture_status
前者接收 montage_path sample_times file_prefix 等待本地角色实际播放蒙太奇后逐帧记录手臂装备与临时弹匣变换 并在采样时间从正面和侧面截图
输出保存在 Saved/Diagnostics/AnimationMotion 下 临时相机与补光只存在于 PIE 世界 结束后立即销毁 不保存关卡
采样只读运行时状态 不负责触发换弹 需另行通过正常输入触发动作

轨迹关键帧可使用 space 字段的 component 值将弹匣目标固定在角色网格组件空间 未指定时沿用参考骨骼空间 两种空间的端点先转换至同一组件空间再插值
运动报告的 spawnedMeshes 记录采样开始后生成的静态网格 Actor 世界变换与物理线速度和角速度 用于验证脱手后的实际飞行方向

### 手腕姿势约束

bake_animation_arm_trajectory 的关键帧 rotation 使用 XYZW 四元数 默认相对 referenceTransform 设置 rotationSpace 为 component 时使用角色组件空间

wristBendDegrees 指定肘部求解期望的掌轴与前臂夹角 maximumWristBendDegrees 是完整握持区间的保存前硬限制 超限时报告时间与角度并拒绝写入骨轨道

前臂旋转按目标手掌和参考手腕关系分配 烘焙后仍须 rebuild_arm_twist_tracks 并检查运行时正侧面 手持通知的 HandMagazineTransform 必须同步采用 gripTransform

旋转参考在关键帧各自的动画时间求值 再在组件空间插值 不随当前采样时刻重新选择四元数弧线

关键帧 gripRotation 可定义不同握持区间的局部旋转 区间内必须保持一致 区间间只在未持有弹匣时过渡 相应通知分别设置握持变换

fingerPose 的 boneRotations 可提供特定手指骨骼的 XYZW 局部旋转 用于拇指对握校准 保持原骨长

maximumElbowStepDegrees 限制逐帧肘平面转动 maximumBoneStepDegrees 在写入前检查三根手臂骨骼的相邻帧旋转 超限直接拒绝写入

### 全阶段手腕诊断与当前烘焙接口

本节说明当前实现 优先于前文旧手腕姿势约束说明

- audit_arm_motion_trajectory 接收 report_path 读取运动报告 在同目录写入 motion_arm_audit.json 返回分阶段极值
- start_pie_montage_motion_capture 新增 capture_images 默认 true 设为 false 时只采样轨迹 sample_times 仍传入非空数组 例如仅含零
- post_roll_seconds 默认 0.6 可设零至五秒 蒙太奇不再活动后继续采集 观察 IK 恢复与中断后的姿势
- 报告 time 为动作开始后的游戏时间 montagePosition 为活动蒙太奇位置 非活动时为空 phase 区分 recording 与 postRoll
- referenceBones 来自实际角色网格 rawBones 为第一插槽首段原始序列的组件空间骨骼 bones 为运行时世界空间骨骼 当前原始序列对照适用于本项目从零开始且等速播放的单段蒙太奇
- 诊断分开输出 palmFlexDegrees palmDeviationDegrees wristTwistDegrees 以及肩肘腕局部角速度和角加速度 轴向扭转跨越正负一百八十度时连续展开
- 角速度验收使用 capture_images 为 false 的独立采样 截图渲染可能扰动逐帧姿势更新时间 不能混用两次采样的速度峰值

烘焙参考改为实际 mesh 参考变换 关键帧 wristTwistDegrees 指定轴向扭转 maximumPalmFlexDegrees 与 maximumPalmDeviationDegrees 为掌面弯曲和侧偏保存前硬限制 旧 wristBendDegrees 不再使用

forearmTwistBone 指定前臂辅助骨 其轨道在本次烘焙内按实际网格参考姿势与沿骨长度比例生成 不再在烘焙后调用使用 Skeleton 参考姿势的 rebuild_arm_twist_tracks

### 截图亮度参数

- exposure_compensation 默认 1 范围负四至正四 使用固定手动曝光
- fill_light_intensity 默认 5000 范围零至五万
- focus_bone 默认 spine_03 可使用 hand_l 获取腕部近景 必须为角色网格中的有效骨骼
- imageSettings 记录实际曝光 补光与关注骨骼 相机关闭物理曝光和运动模糊
- 参数超限直接报错 临时相机补光在截图结束后销毁 不改变关卡保存内容
