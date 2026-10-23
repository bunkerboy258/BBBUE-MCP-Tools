# 事实动画变体与骨骼数值验收

工具域为 animation_finish 原生依赖为 BBBAnimationGraphEditorLibrary
资产编辑在共享可视编辑宿主进行 数值采样演员不属于 Mass 实体

## 配置

configure_speed_blend 原位重建现有一维速度混合
asset_path 指向已有 BlendSpace1D sequence_paths 与 speeds 一一对应
首项速度为零 后续严格递增 全部样本骨架一致 smoothing_time 为 0 至 0.3 秒
循环相位时长应与实际采样速度一致 模型步幅比例只缩放移动循环

configure_fact_animation_finish 接收下列参数

- asset_path 正式事实动画蓝图
- turn_sequence_paths 左右原地九十度片段 共两项
- crawl_death_sequence_path 完整爬行死亡过渡序列
- crawl_attack_sequence_paths 一至八条同骨架攻击序列
- crawl_attack_sample_pivots 各变体实际接触帧的归一化位置
- crawl_reference_speed 素材原速对应的厘米每秒 默认 39.7054

爬行攻击沿用出生种子 动作编号和既有 ActionEpoch 两组姿态槽支持同状态重播
逻辑进度 0.4 映射到接触锚点 单调三次 Hermite 映射在锚点保持一阶连续
映射只影响动画时间 不改变 Mass 伤害 前摇或动作完成时刻
爬行死亡使用单条完整过渡序列按动作进度采样 到终态后保持
姿态选择和混合属于表现层 不维护第二套玩法状态
重复配置原位重建所负责节点 不保留旧图分支
编译无警告后保存 正式目标的未保存修改会阻止构图

## 离线姿态过渡烘焙

bake_pose_transition 使用同骨架源序列首帧和目标序列末帧
参数为 source_sequence_path target_sequence_path asset_path ground_bone_names seconds
asset_path 是新建或原位重建的自有序列 默认持续 1.7 秒 按 60 Hz 烘焙
使用四元数最短路径和平滑进度 保持非骨盆骨骼的源局部平移及缩放
逐帧抬升骨盆 使指定接触骨骼至少高于地面 0.5 cm
输出回读全部骨轨与接触最低高度 源序列保持只读
这是固定端点姿态烘焙 不包含运行时地形探测或脚掌锁定

## 数值采样

start_pie_fact_motion_capture 的公共参数为 actor_blueprint_path segments file_prefix fps variation_seed
segments 是结构化分段数组 内部注册参数 segments_json 由公共契约转换
每段支持以下字段 不接受其它字段

| 字段 | 范围及含义 |
| --- | --- |
| duration | 大于零且不超过 10 秒 必填 |
| behavior | 0 Idle 1 Alert 2 Patrol 3 Chase 4 Attack 5 Dead |
| speed / end_speed | 0 至 650 cm/s 分段起止速度 |
| cycle_seconds | 0.01 至 20 秒 显式循环周期 |
| style | 0 至 2 同一个体的出生风格 |
| crawling | 是否处于爬行表现 |
| crawl_start / crawl_end | 0 至 1 进爬过渡进度 |
| action_start / action_end | 0 至 1 当前动作进度 |
| yaw_rate | 每秒实际演员转向角度 绝对值不超过 360 |
| stagger_region | -1 无踉跄 或 0 至 5 对应部位 |

每次一至二十四段 总长不超过二十四秒 同次采样只能有一种出生风格
动作身份在行为变化或攻击进度重新开始时推进 死亡保持段延续同一身份
不支持显式 action_id phase_start 或 end_cycle_seconds

需要已经启动 PIE 固定 30 或 60 Hz 在正式动画蓝图求值 每次求值跨越引擎帧
只创建一个隐藏临时表现演员 不创建相机 地面 灯光 渲染目标 图片或视频
输出 Saved/temp/<file_prefix>/motion.json 要求目标目录不存在
每帧记录 21 个骨骼的世界与组件空间位置及四元数
同时记录演员位置 动作编号 进度 循环相位 分段索引和实际姿态选择字段
分段首尾及接触进度附近记录状态机和播放器 非活跃播放器缓存不能用作变体已播放的证明
输出 scope 为 fixed_step_animation_blueprint_kinematics 且 imagesGenerated 为 false
成功 失败或 PIE 结束均回收临时演员
inspect_pie_fact_motion_capture 只查询进度 不返回逐帧大数组

固定采样频率不代表游戏实测帧率
数值可检查姿态跳变 关节角度 支撑点轨迹 接触时序和尸体回弹
骨骼质心在脚跟至脚尖滚动时仍会移动 其速度不能直接等同于鞋底打滑速度
采样不覆盖真实射击伤害 群体性能 网络正确性或视觉观感
调用方完成分析后删除本任务临时文件

## 2026-10-23 项目验证

UE5.8 编辑器目标编译成功 男女正式动画蓝图无警告保存
两性别各三种风格已经采样 最后针对两组跑步与冲刺组合再采样 2037 帧
全部最终采样根骨组件位移为零 死亡保持段位移为零
另两组进爬采样最低接触骨骼高度为 2.9173 cm 与 2.4372 cm
完整爬行死亡最低接触高度约 0.476 cm 与 0.473 cm 末态保持不回弹
UBBB.Mass.ZombieVariation / ZombieAnimationFacts / ZombieAnimationFinish 均通过
本轮没有使用截图 视频或视觉分析作为验收手段
