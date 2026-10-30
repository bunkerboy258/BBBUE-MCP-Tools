# 双臂握持余量制作与序列验收

公共入口为 `control_rig.process_dual_arm_body_pose`。以 `_GripMargin.json.source` 结尾的正式制作源交给 `BBBGripMarginTools`。操作在编辑器内完成；活动 PIE 期间拒绝修改。不需要启动 PIE。

制作源位于角色 `Source/Animation`，格式为 `BBBGripMargin`、schema 1，明确 `mesh`、`rig`、`template_rig`、`database_root`、`retract_component_cm`、`weapons` 和 `extra_animations`。武器条目指定名称与正式 HandGrip 制作源，FireGrip 读取同目录对应文件。共同身体参考使用已选定的姿势；不把仍被排除武器使用的共用加法参考纳入写入清单。

`extra_animations` 的五项分别为身体中立参考、站立参考、蹲姿参考、站立端枪目标和蹲姿端枪目标。端枪加法的原始完整姿势与其参考必须共同处理。身体求解沿胸骨空间施加明确收枪量，右手保留枪口方向，左手使用 FAL 的既有相对握点。专属预览按正式右前臂空间腕部增量、手指和本武器左握点求解，保持挂接和手动校准值。

## 操作

| action / job_index | 作用 | write_paths |
| --- | --- | --- |
| inspect / -1 | 从正式 PoseSearchDatabase 枚举动作并写入制作清单 | 制作 Rig |
| capture / -1 | 读取模板官方节点和连线，去除静态 BasePose，返回新 Rig 的图配置 | 模板或目标 Rig |
| inspect / 非负起始索引 | 每次预查 30 个动作，各取五个时间点，核对所有武器开火及未开火握姿 | 制作 Rig |
| bake / 非负起始索引 | 每次原位烘焙 10 个明确动画，全帧检查接触和余量，保存后回读全部骨轨与元数据 | 清单对应的 10 个动画，末批取剩余项 |
| capture / 武器索引 | 同步该武器 HandGrip、FireGrip 的身体参考与制作底稿，保留手指、握点和校准 | 两个握姿各自的动画、Rig、LS，共六个包 |
| prepare_action / 武器索引 | 生成或刷新该武器 `Animation/work/LS_GripMargin` | 该 LS 和共同制作 Rig |
| inspect / 武器索引 | write_paths 指向唯一 LS_GripMargin 时，通过官方 Sequencer 瞬态导出后逐帧检查 | 该 LS |
| finalize / 武器索引 | 打开该 LS 第 60 帧，跨编辑器帧渲染第 60、90 帧的正面、俯视和右侧 | 该 LS |
| inspect / -2 | 读取最近一次该宿主渲染活动的结果 | 制作 Rig |

新 Rig 用 `control_rig.create_control_rig` 从捕获的图配置构建，配置两侧 clavicle、hand IK、elbow pole 六个欧拉控制器。不要直接复制模板的已编译 RigVM。预览首次建立隐藏的 source 骨骼控制器，确保 Sequencer 和离线求解使用相同完整源姿势。

## 验收边界

每条 LS 为 30 fps、301 帧。0/60/120 为中立、站立端枪和蹲姿端枪；30/90/150 在对应姿势加 5 厘米向外扰动；180 起播放站立射击加法，210 起播放蹲姿射击加法，240—270 检查抬枪插值。射击叠加从正式 recoil 动画和其实际参考帧计算，不改变后坐力资产。

骨轨烘焙只改上下臂、腕骨和手部 IK 辅助骨，保存原骨长与缩放。整段先计算并检查，再写入；帧数、时长、曲线、通知、标记和非授权轨道回读不符时失败。制作源记录输出摘要；重复执行仅在当前输出摘要一致时跳过，拒绝覆盖后来改动。

序列验收使用官方 `SequencerTools.export_anim_sequence` 输出到瞬态作用域，检查所有 301 帧：左臂伸展率不超过 0.901，左肘离完全伸直至少 35 度，相邻帧胸部空间肘部弯曲平面不得突变超过 45 度。临时导出不保存，结束释放作用域。渲染输出到 `Saved/temp/RifleGripMargin`，活动完成后销毁所属角色、相机和灯光；交付后清除本任务图片。

这些检查证明保存后的关卡序列和烘焙姿势满足余量要求，不等同于完整主动画蓝图、网络、装备切换或 Tick 时序验收。共用参考必须先查引用；排除武器仍引用的参考不得随步枪姿势一起改写。
