# 僵尸踉跄构图

`BBBAnimationGraphToolset.configure_fact_body_stagger_state` 重建项目僵尸动画蓝图现有 `Stagger` 状态的五部位姿态分支 不改变六种 AI 行为 不修改 `FactDrivenCrawl` 不保留旧三分支入口。

参数:

- `asset_path`: `/Game/_Project/` 下已独占签出的动画蓝图
- `sequence_paths`: 头部 左臂 右臂 左腿 右腿五个不同的同骨架动画序列 躯干共用头部
- `blend_duration`: 大于零且不超过 0.3 秒 默认 0.12 秒

调用前必须完成原生编辑器模块编译并重新启动唯一 MCP 宿主。PIE 期间拒绝构图。要求现有完整七状态站立图 删除踉跄姿态图旧节点后构造五分支 原有状态转换链保留。不创建兼容分支 不保存编译失败的资产。

动画只读 `StaggeringFact` `StaggerProgressFact` `StaggerVariantFact`。各序列显式时间由 Mass 进度映射 不触发动画通知。死亡无出口 爬行不踉跄 子弹来源成立的踉跄结果取消未结算攻击 不回滚已结算伤害。

Ramster 序列顺序: `Zombie_HitReact_Head` `Zombie_HitReact_LeftArm` `Zombie_HitReact_RightArm` `Zombie_HitReact_LeftLeg` `Zombie_HitReact_RightLeg`。头部和躯干完整播放 2.333333 秒 四肢完整播放 3 秒 踉跄全程停止主动水平移动 重力持续 动作完成后保留 0.35 秒重触发间隔。程序化受击不因踉跄减弱。

`BBBProjectileDefinition.StaggerValue` 是 0 到 1 的基础踉跄能力 乘 `BBBMonsterBodyPartDefinition.StaggerMultiplier` 后夹到 0 到 1。头部默认 1.5 腿部 1.25 躯干 1 手臂 0.75。与普通伤害 耐久伤害和穿透衰减独立 同次开火每个目标只用一个随机样本 同轮命中选择有效伤害乘部位系数最高的候选 已处理的同发后续弹丸不重启动作。不处理近战 不新增历史事件队列。当前贡献快照保留尚有效的踉跄结果 后续未触发命中不会覆盖它 远端还原不重新抽取概率。

来源本机的候选身份 排序时间 随机样本与当前攻击部位汇总不参与反射传输 网络只传当前已成立动作的身份 起止服务器时间和锁定部位 本机去重缓存不会被房主镜像快照清空。候选分组仅在当轮碰撞处理的栈上整理 不跨帧保存事件集合。

验证边界: `Tests/test_zombie_stagger_graph.py`。实际资产仍需编译 事实测试与渲染验收。

`configure_fact_combat_transition_blends` 要求已含完整七状态站立图与爬行图。它补齐重击的 `Attack -> Stagger` 转换 不产生旧状态或兼容分支。全部转换使用惯性混合 死亡优先。

| 参数 | 默认秒数 | 用途 |
|---|---:|---|
| movement_duration | 0.22 | 普通移动转换 |
| attack_enter_duration | 0.08 | 攻击入场 |
| attack_exit_duration | 0.16 | 攻击退出 |
| hit_enter_duration | 0.07 | 重击踉跄入场 |
| hit_exit_duration | 0.18 | 踉跄恢复 |
| crawl_duration | 0.28 | 爬行姿态入场 |
| death_duration | 0.04 | 死亡入场 |

每项必须有限且大于零 不超过半秒。工具只修改已独占签出的目标蓝图 禁止 PIE 编译存在警告或错误时不保存。边界测试位于 `Tests/test_combat_transition_blends.py`。

`capture_monster_stagger_samples(actor_blueprint_paths, hit_region, sample_progress, file_prefix)` 使用渲染 PIE 在高空生成无 Mass 实体的临时表现载体。每批最多十种外观和三个进度。小于一采样正式 `Stagger` 状态 一采样退出后的移动状态。输出实际运行图和骨骼位置 并在异常和成功时均销毁临时演员。不保存资产 不修改现有场景 不作为真实武器伤害链的验收替代。
